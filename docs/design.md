# 设计文档

本目录（`grafana/`）是一个 monorepo，包含一个 CI runner 和一个测试结果仪表盘（`grafana_*` 三个演进版本）。本文档按子系统分节记录设计。

> 演进脉络：`grafana_nginx`（三容器）→ `grafana_v2.0`（单容器 Grafana）→ `grafana_v3.0`（自研 Flask），以及独立的 `ci_runner`（CI runner）。

---

## 1. grafana_nginx —— 三容器版本（最早）

### 定位

最早的测试结果仪表盘：**nginx + Python watcher + Grafana 三个独立 Docker 容器**协同工作，CSV 格式，Grafana 用 Infinity 插件读 CSV 画图。

### 架构

三个独立容器，共享同一个宿主机数据目录：

| 容器 | 端口 | 职责 |
|---|---|---|
| `test_nginx1.28`（nginx） | 9699 | WebDAV PUT 接收 CI 上传的 `testResult.csv`；同时提供静态 GET |
| `dt_watcher`（Python） | — | 每 2s 轮询 `/data/details/sources/`，解析 CSV → 追加汇总 + 生成 HTML |
| `dt_dashboards`（Grafana） | 9696 | Infinity 插件通过 nginx GET 读汇总 CSV 画趋势图，链接到 HTML 报告 |

三个容器对同一宿主目录（`/home/kk/catch2_data/data`）使用了**不同的挂载点**：watcher 挂 `/data`，nginx 挂 `/opt/catch2_data` + `/usr/share/nginx/html/data`。

### 数据流

```
CI → PUT testResult.csv → nginx 落盘 /opt/catch2_data/details/sources/<timestamp>/
  → watcher 轮询发现新文件 → resultSum.getTestResult() 统计 pass/total
  → 追加一行到 /data/catch2Result.csv → csv2html 生成 report-<timestamp>.html
  → Grafana 读 catch2Result.csv 画趋势图，链接到 HTML 报告
```

### 数据格式

**testResult.csv**（单次运行，CI 上传）：
```
Num,module,binary,case,result
0,module/device,DeviceTest,txGetDevice_Basic,pass
```
`result` 列取值：`pass` / `failed` / `timeout`；watcher 判断最后一列 == `"pass"` 计入通过数。

**catch2Result.csv**（汇总，watcher 维护）：
```
time,pass,total
2025-09-15 10:14:21,30,40
```

### 关键文件

| 文件 | 职责 |
|---|---|
| `app/watch_new_files.py` | 入口：轮询、协调 `resultSum` 与 `csv2html` |
| `app/resultSum.py` | CSV 解析（`getTestResult`）、汇总追加（`insertOneResult`）、时间戳转换（`switchTime`） |
| `app/csv2html.py` | 把 `testResult.csv` 转成自包含 HTML 报告（排序/分页/高亮） |
| `build_script/build_{nginx1.28,watcher,grafana}.sh` | 三个容器的构建/启动脚本 |
| `test_data/auto.sh` | 模拟 30 次 CI 上传，用于测试数据注入 |

### 痛点（催生 v2.0）

- 三个容器需分别启动、有顺序依赖、维护三套配置
- 三套挂载路径指向同一目录，易混淆
- 数据是 CSV 文件，无查询能力；HTML 报告与 Grafana 面板割裂

---

## 2. grafana_v2.0 —— 单容器 Grafana 版本

### 定位

把 v1 的三个容器**合并为单个容器 `dt_all`**，用 `supervisord` 管理多进程；引入 **SQLite 存储**（替代 CSV 直读）和 **benchmark 支持**。

### 架构

单容器，`supervisord` 管理 4 个进程：

| 进程 | 端口（容器→宿主） | 职责 |
|---|---|---|
| nginx | 8080 → 9698 | WebDAV 接收 CI 上传 |
| grafana-server | 3000 → 9696 | 仪表盘，`frser-sqlite-datasource` 插件直读 SQLite |
| watcher（`app_catch2`） | — | 解析 catch2 CSV/JSON → 写 SQLite |
| bm_watcher（`app_bm`） | — | 解析 benchmark JSON → 写 SQLite |

### 数据流

```
CI → PUT CSV/JSON → nginx 落盘 → watcher 解析 → SQLite → Grafana 直读 SQLite 画图
```

### 上传路径（`conf/nginx.conf`）

| location | 落盘目录 | 用途 |
|---|---|---|
| `/details/sources/` | `/data/details/catch2/` | catch2 结果（CSV） |
| `/details/sources_bm/` | `/data/details/benchmark/` | benchmark 结果（JSON） |
| `/details/tx82/` | `/data/details/tx82/catch2/` | tx82 平台专用上传 |
| `/html/` | `/data/details/html/` | 只读 HTML 报告（免认证） |

### 存储

**catch2**（`/data/test_results.db`，单一 DB）：
```sql
runs(id, time TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result)
```

**benchmark**（`/data/benchmark_results.db`）：按 benchmark 名称**动态建表**（`db_bm.ensure_table`），每张表字段为 `(id, date, host_srv, author, size, real_time, cpu_time, time_unit, metrics, iterations)`。

### watcher 行为

启动时先把旧 DB 复制为带时间戳的 `.bak` 备份，然后重新处理 `WATCH_DIR` 下所有历史文件；`app_catch2/watch_catch2_files.py` 还处理 `.tar.gz`（移动到 logs 目录）和 `.json`（`getTestResultFromJson`），CSV 与 JSON 并存。

### 目录（三个 Python app 并存）

| 目录 | 存储 | 状态 |
|---|---|---|
| `app/` | CSV + HTML（原 v1 逻辑） | 保留备用，未打包进镜像 |
| `app_catch2/` | SQLite | **活跃**（Dockerfile `COPY app_catch2/ /app/`） |
| `app_bm/` | SQLite（benchmark） | **活跃**（Dockerfile `COPY app_bm/ /app_bm/`） |

### 关键文件

`Dockerfile`、`conf/supervisord.conf`（4 进程）、`conf/nginx.conf`、`app_catch2/{watch_catch2_files,resultSum,db,csv2html,rebuild_db}.py`、`app_bm/{watch_bm_files,bm_parser,db_bm,rebuild_db_bm}.py`、`build_script/build_all_in_one.sh`。

### 遗留问题（催生 v3.0）

- **Grafana 配置不持久化**（`/var/lib/grafana` 未挂载，容器删除即丢）
- 镜像 **1–2 GB**，且需外网构建（Grafana apt 源 + 插件）
- 仪表盘改动需**重建镜像**，无法热更新
- 单一 `test_results.db`，无多平台概念，`runs` 表无 `platform/os/arch` 字段

---

## 3. grafana_v3.0 —— Flask 自研仪表盘版本（当前）

### 定位

用**自研 Flask 仪表盘**替换 Grafana，数据格式收敛为**纯 JSON**，引入**多平台支持**（每个 platform 一个独立 SQLite），镜像瘦身到 ~200 MB。

### 架构

单容器，`supervisord` 管理 3 个进程：

| 进程 | 端口（容器→宿主） | 职责 |
|---|---|---|
| nginx | 8080 → 9698 | WebDAV 接收 CI 上传的 JSON |
| watcher（`app_catch2`） | — | 每 2s 轮询，解析 JSON → 写 per-platform SQLite |
| flask（`app_web`） | 3000 → 9696 | 读 SQLite，渲染仪表盘 + API |

### 数据流

```
CI → PUT /details/<timestamp>/testResult.json → nginx WebDAV 落盘 /data/details/catch2/
  → watcher 发现新文件 → resultSum.getTestResultFromJson() 解析
  → db.run_exists() 去重 → 写 /data/platforms/<platform>.db
  → Flask 遍历所有 *.db，执行 PIVOT_SQL → 渲染 10 天 pivot 表
```

### 路由（`app_web/web.py`）

| 路由 | 说明 |
|---|---|
| `GET /` | 10 天 pivot 汇总表（platform/os/arch × 日期，pass/fail 着色） |
| `GET /detail/<platform>/<run_id>` | 单次运行全部测试用例 |
| `GET /platform/<platform>?os=&arch=` | 平台历史趋势 + Chart.js 折线图 |
| `GET /api/detail?run_id=&platform=` | 失败用例 JSON（首页 modal 用） |

### Schema

每个 platform 一个 DB（`/data/platforms/<platform>.db`）：
```sql
runs(id, time TEXT, platform TEXT, os TEXT, arch TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result)
```

### 时区约定

**UTC 存库，CST（UTC+8）展示**，只在渲染层转换：
- SQL：`date(time, '+8 hours')` 做日期分组（`PIVOT_SQL`）
- Python：`datetime.now(CST).date()` 生成列头日期
- Jinja2：`{{ run.time | utc_to_cst }}` filter

CI 上传的 JSON `time` 字段应为 UTC，watcher 无条件追加 `Z` 后缀标记。

### 热更新（无需重建镜像）

| 改动文件 | 动作 |
|---|---|
| `*.html` 模板 | `docker cp` 后无需重启（Flask 每请求读模板） |
| `web.py` | `docker cp` 后 kill Flask 进程，supervisord 自动重启 |

### 关键文件

| 文件 | 职责 |
|---|---|
| `app_web/web.py` | Flask 全部路由 + `PIVOT_SQL` + `utc_to_cst` filter |
| `app_web/templates/{index,detail,platform}.html` | 三个页面（服务端渲染） |
| `app_catch2/watch_catch2_files.py` | watcher 轮询循环 |
| `app_catch2/resultSum.py` | JSON 解析 + 去重插入协调 |
| `app_catch2/db.py` | SQLite schema + CRUD（`run_exists` 去重） |
| `rebuild_db.py` | 顶层 CLI，从 JSON 目录 seed DB（`--db-dir` 可选） |
| `conf/{nginx,supervisord}.conf` | WebDAV + 3 进程定义 |

### 相对 v2.0 的关键变更（详见 `grafana_v3.0/docs/diff.md`）

| 维度 | v2.0 | v3.0 |
|---|---|---|
| 仪表盘 | Grafana | 自研 Flask |
| 数据格式 | CSV + JSON | 纯 JSON |
| 平台 | 单一 `test_results.db` | 每平台一个 `<platform>.db` |
| 时区 | 无显式处理 | UTC 存库 / CST 展示 |
| 镜像体积 | 1–2 GB | ~200 MB |
| 热更新 | 需重建镜像 | `docker cp` 即可 |
| benchmark | `app_bm` 独立 watcher | 已移除 |

---

## 4. ci_runner —— Docker 定时 CI 系统

### 一句话

一个跑在 Docker 里的轻量 CI 系统：每天固定时间从自建 GitLab 拉 C/C++ 项目代码 → 编译 → 跑测试，也支持 HTTP 和 `docker exec` 手动触发。它负责"跑"，不负责"看"测试结果。

### 与 grafana_v3.0 的关系

- `ci_runner/` —— 负责拉代码、编译、执行测试，产出结果
- `grafana_v3.0/` —— 接收测试结果 JSON，渲染 pass/fail 仪表盘

两者目前是**松耦合**的：`ci_runner` 的通知器是 `NoopNotifier`（no-op），跑完测试后不会自动把结果上传到 dashboard——上传这一步尚未在代码里接起来。

### 核心架构

单容器长跑一个 Python 进程，三件事合在同一个进程里：

| 组件 | 职责 |
|---|---|
| FastAPI（`app/main.py`） | HTTP 端点（`/projects`、`/runs`、`POST /projects/{name}/run` 等） |
| APScheduler | 按 `config/config.yaml` 里的 cron 定时触发 |
| CLI（`app/cli.py`） | `docker exec` 手动触发 / 查历史 |

三种触发方式（定时 / HTTP / CLI）**最终都收敛到同一个函数** `Pipeline.run()`（`app/pipeline.py`）。

### 一次运行的流程

1. 拿非阻塞锁 → 拿不到就记一条 `skipped` 返回（HTTP 409）
2. 全新 `git clone --depth=1` 到临时目录
3. 跑 `build_cmd`（cmake + make，超时按进程组 kill）
4. 成功再跑 `test_cmd`（ctest）
5. 最后写 `status.json`、删临时目录、调 notifier、按 `keep_runs` 轮转旧日志

### 数据存储

| 路径 | 内容 |
|---|---|
| `data/db.sqlite` | 运行历史元数据 |
| `data/runs/<id>/` | 每次运行的 clone/build/test 日志 + status.json |
| `cache/ccache/` | ccache 编译缓存（加速重复构建） |
| `config/config.yaml` | 项目、repo、cron、编译/测试命令 |
| `secrets/id_rsa` | 拉 GitLab 用的 SSH 私钥（只读挂载） |

### 快速上手

```bash
cd ci_runner
cp ~/.ssh/id_rsa secrets/id_rsa && chmod 600 secrets/id_rsa   # 放私钥
# 改 config/config.yaml 的 repo_url；改 docker-compose.yml 的 GITLAB_HOST
docker compose up -d                                          # 启动
curl -X POST http://127.0.0.1:8080/projects/my_cpp_project/run  # 手动触发
```

### 测试

分三层（unit / integration / e2e），不用真连 GitLab、不用真编译 C++ 就能测透逻辑：

```bash
source .venv/bin/activate
pytest tests/unit tests/integration tests/e2e -v
```

更完整的用法（问题排查、6 个扩展点）见 `ci_runner/README.md` 和 `ci_runner/ci_runner-ci-usage.md`。
