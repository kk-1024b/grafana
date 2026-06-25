# 设计文档：grafana_v2.0 合并容器架构

## 1. 背景与目标

### 1.1 原有架构问题

原系统由三个独立 Docker 容器组成，部署时需要：
- 分别启动三个容器，顺序有依赖关系
- 维护三套容器配置和生命周期
- 三个容器共享同一宿主机目录，挂载路径不一致（`/data`、`/opt/catch2_data`、`/usr/share/nginx/html/data` 指向同一宿主目录）

### 1.2 目标

将三个容器合并为一个，保留全部功能，降低部署复杂度：
- 单命令启动
- 单一数据卷挂载
- 可整体导出为 tar 包，离线传输部署

---

## 2. 系统架构

### 2.1 整体结构

```
┌─────────────────────────── Docker 容器 dt_all ─────────────────────────────┐
│                                                                              │
│   supervisord（进程守护）                                                    │
│   ├── nginx           监听 8080，对外映射 9698                               │
│   │   ├── PUT /details/  ← CI/CD 上传 CSV                                   │
│   │   └── GET /data/     → Grafana 读取 CSV / HTML                          │
│   │                                                                          │
│   ├── grafana-server  监听 3000，对外映射 9696                               │
│   │   └── Infinity 插件 → 通过 nginx GET 读取 CSV                           │
│   │                                                                          │
│   └── python watcher  后台轮询                                               │
│       ├── 监听 /data/details/sources/ 目录                                  │
│       ├── 新文件到达 → 解析 CSV → 追加 /data/catch2Result.csv               │
│       └── 生成 /data/details/html/report-{timestamp}.html                   │
│                                                                              │
│   /data/  ←──────────────────── 宿主机挂载（唯一数据卷）                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 外部数据流

```
CI/CD 流水线
    │
    │ curl -u user:pass123 -T testResult.csv
    │ http://host:9698/details/sources/{timestamp}/testResult.csv
    ▼
nginx (9698)
    │ WebDAV PUT → 写入 /data/details/sources/{timestamp}/testResult.csv
    ▼
Python watcher（轮询间隔 2 秒）
    ├── 读取 CSV，统计 pass/total
    ├── 追加行到 /data/catch2Result.csv
    └── 生成 /data/details/html/report-{timestamp}.html
         ▲
Grafana (9696)
    ├── Infinity 插件 GET /data/catch2Result.csv  → 趋势图
    └── 链接到 GET /data/details/html/report-*.html → 详情页
```

---

## 3. 组件详细设计

### 3.1 nginx

**角色**：文件上传入口 + 静态文件服务器

**监听端口**：8080（容器内），映射到宿主 9698

**关键配置**：

```nginx
# PUT 上传（WebDAV）
location /details/ {
    alias /data/details/;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    create_full_put_path on;   # 自动创建多级目录
}

# GET 静态文件
location /data/ {
    alias /data/;
    autoindex on;
}
```

**依赖模块**：`ngx_http_dav_module`，由 `nginx-extras` 包提供（Debian）

**认证**：HTTP Basic Auth，账号 `user:pass123`，文件位于 `/etc/nginx/.htpasswd`

**目录约定**：CI 上传时在 `sources/` 下以时间戳命名子目录，子目录名即为该次运行的 run ID：
```
/data/details/sources/
└── 2026-06-23_10-00-00/
    └── testResult.csv
```

---

### 3.2 Python watcher

**角色**：文件变化监听 + 数据聚合 + HTML 报告生成

**入口**：`/app/watch_new_files.py`

**运行逻辑**：

```
启动
  ├── initHtmlDir()        清空 /data/details/html/
  ├── initCatch2Table()    扫描现有 sources/，重建 catch2Result.csv 和所有 HTML
  └── watcher_task()       进入无限循环
        ├── sleep(2)
        ├── 扫描 sources/ 当前文件集合
        ├── diff（当前 - 已知）= 新文件
        └── 对每个新文件：
              ├── getTestResult()      解析 CSV，统计 pass/total
              ├── switchTime()         转换时间戳格式
              ├── insertOneResult()    追加到 catch2Result.csv
              └── switch_csv2html()   生成 HTML 报告
```

**时间戳格式转换**（`resultSum.switchTime`）：

```
目录名：  2026-06-23_10-00-00
          ↓ replace('_', ' ')
          ↓ rsplit('-', 2) 并用 ':' 拼接后两段
CSV 列值：2026-06-23 10:00:00
```

**三个模块职责**：

| 模块 | 职责 |
|------|------|
| `watch_new_files.py` | 文件轮询、协调调用其他模块 |
| `resultSum.py` | CSV 解析、汇总写入、初始化 |
| `csv2html.py` | 生成可交互 HTML 报告（排序/分页/搜索/高亮） |

---

### 3.3 Grafana

**角色**：数据可视化仪表盘

**监听端口**：3000（容器内），映射到宿主 9696

**关键依赖**：Infinity 数据源插件（支持 CSV/JSON 格式），构建时通过以下命令安装：
```bash
grafana cli --pluginsDir /var/lib/grafana/plugins plugins install yesoreyeram-infinity-datasource
```

**数据读取路径**：
- 汇总趋势：`http://localhost:9698/data/catch2Result.csv`
- 单次报告：`http://localhost:9698/data/details/html/report-{timestamp}.html`

**启动方式**（supervisord 调用）：
```bash
/usr/sbin/grafana-server \
    --homepath=/usr/share/grafana \
    --config=/etc/grafana/grafana.ini
```

**关键环境变量**：

| 变量 | 值 | 说明 |
|------|----|------|
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` | 管理员密码 |
| `GF_PATHS_DATA` | `/var/lib/grafana` | 数据目录（dashboard 配置持久化） |
| `GF_PATHS_PLUGINS` | `/var/lib/grafana/plugins` | 插件目录 |

> **注意**：`/var/lib/grafana` 在容器内，未挂载到宿主机。容器删除后 dashboard 配置会丢失。如需持久化，增加挂载 `-v /host/grafana:/var/lib/grafana`。

---

### 3.4 supervisord

**角色**：容器内多进程守护

**配置文件**：`/etc/supervisor/conf.d/all.conf`

**启动命令**（`CMD`）：
```bash
/usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

`-n`（nodaemon）使 supervisord 在前台运行，保持容器存活。

**各进程配置要点**：

| 进程 | autorestart | 说明 |
|------|-------------|------|
| nginx | true | 崩溃自动重启 |
| grafana | true | 崩溃自动重启 |
| watcher | true | 崩溃自动重启，重启后重新初始化 HTML 和汇总 CSV |

**日志路径**：

```
/var/log/supervisor/
├── supervisord.log
├── nginx.log / nginx_err.log
├── grafana.log / grafana_err.log
└── watcher.log / watcher_err.log
```

---

## 4. 数据文件设计

### 4.1 目录结构（容器内 /data/）

```
/data/
├── catch2Result.csv              # 汇总：每次运行一行，Grafana 趋势图数据源
└── details/
    ├── sources/                  # CI 上传目标，watcher 监听此处
    │   ├── 2026-06-23_10-00-00/
    │   │   └── testResult.csv
    │   └── 2026-06-24_09-30-00/
    │       └── testResult.csv
    └── html/                     # watcher 生成的 HTML 报告
        ├── report-2026-06-23 10:00:00.html
        └── report-2026-06-24 09:30:00.html
```

### 4.2 CSV 格式

**testResult.csv**（单次运行，CI 上传）：
```
Num,module,binary,case,result
0,module/device,DeviceTest,txGetDevice_Basic,pass
1,module/device,DeviceTest,txGetDevice_Fail,failed
```
- `result` 列：`pass` | `failed` | `timeout`
- watcher 判断逻辑：最后一列 == `"pass"` 计入通过数

**catch2Result.csv**（汇总，watcher 维护）：
```
time,pass,total
2026-06-23 10:00:00,38,40
2026-06-24 09:30:00,40,40
```

---

## 5. 镜像构建设计

### 5.1 基础镜像选型

选用 `debian:bookworm-slim` 而非 `alpine`：
- `nginx-extras`（含 WebDAV 模块）在 Debian apt 中原生可用；Alpine 的 nginx 默认不含 WebDAV，需手动编译
- Grafana 官方提供 Debian/Ubuntu apt 源，安装简单可靠
- 三组件均有成熟的 Debian 安装路径，Dockerfile 可维护性更高

### 5.2 Dockerfile 分层设计

```
Layer 1: debian:bookworm-slim
Layer 2: apt 安装基础工具（nginx-extras, supervisor, python3 等）
Layer 3: 添加 Grafana apt 源 + 安装 grafana
Layer 4: 安装 Infinity 插件（grafana cli）
Layer 5: 生成 htpasswd 文件
Layer 6: COPY app/（Python 脚本）
Layer 7: COPY conf/（nginx.conf, supervisord.conf）
Layer 8: 软链 nginx sites-enabled
```

分层原则：变化频率低的层（apt 安装）放在前面，变化频率高的层（Python 脚本、配置文件）放在后面，利用 Docker 构建缓存加速迭代。

### 5.3 导出方式对比

| 方式 | 命令 | 保留 CMD | 文件大小 | 推荐场景 |
|------|------|----------|----------|----------|
| `docker save` | `docker save image -o file.tar` | ✅ 保留 | 较大（含所有层） | 标准镜像分发 |
| `docker export` | `docker export container -o file.tar` | ❌ 丢失 | 较小（扁平文件系统） | 与原系统 `docker import` 流程一致 |

本项目选用 `docker export`，与原有 `build_grafana.sh` 中 `docker import` 的使用习惯保持一致。**import 启动时必须手动指定 CMD**：
```bash
docker run ... dt_all:1.0 /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

---

## 6. 关键设计决策

### 决策 1：为何用 supervisord 而非 shell 脚本

直接用 shell 脚本启动多进程（`nginx & grafana & python3 &`）的问题：
- 任意子进程退出后不会自动重启
- 无统一日志管理
- Docker 信号传递不正确（PID 1 需要处理 SIGTERM）

supervisord 解决了以上全部问题，且配置直观。

### 决策 2：Python 脚本打包进镜像而非挂载

原有 `dt_watcher` 通过 `-v /host/app:/app` 挂载脚本，方便修改但依赖宿主机路径。合并后脚本通过 `COPY app/ /app/` 打包进镜像：
- 镜像自包含，可完整导出到其他机器
- 修改脚本需重新构建镜像（接受此代价）

### 决策 3：挂载路径统一为 /data

原三个容器对同一宿主目录使用了三个不同挂载点，合并后统一为 `/data`，nginx 配置和 Python 脚本均指向此路径，消除路径歧义。

---

## 7. app_2.0：SQLite 版本变更（v2）

在 `app/`（CSV 版本）基础上，新增 `app_2.0/` 目录实现 SQLite 存储，两个版本并存，通过 Dockerfile 的 `COPY` 目标切换。

**主要变化：**

| 项目 | app/（CSV） | app_2.0/（SQLite） |
|------|------------|-------------------|
| 存储 | `catch2Result.csv` + HTML 文件 | `test_results.db`（SQLite） |
| Grafana 插件 | `yesoreyeram-infinity-datasource` | `frser-sqlite-datasource` |
| HTML 报告 | 生成 `/data/details/html/*.html` | 废弃，由 Grafana 面板替代 |
| nginx GET | 需要 `/data/` 静态路径 | 移除，Grafana 直接读文件 |

**新增模块 `db.py`：**

```python
init_db(db_path)          # 建表，返回连接
insert_run(conn, ...)     # 写 runs 表，返回 run_id
insert_test_cases(conn, run_id, rows)  # 批量写明细
```

**Schema：**

```sql
runs(id, time TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result)
```

**切换回 CSV 版本：** 修改 Dockerfile 两行（`COPY app/` + Infinity 插件）并恢复 `nginx.conf` 的 `/data/` GET location。

---

## 8. 限制与已知问题

1. **Grafana dashboard 不持久化**：`/var/lib/grafana` 未挂载，容器删除后 dashboard 配置丢失。首次启动后需手动配置 Infinity 数据源和 dashboard，或额外挂载该目录。

2. **watcher 重启会重置汇总 CSV**：`watch_new_files.py` 启动时调用 `initHtmlDir()` 清空 HTML 目录，并重新扫描 `sources/` 重建 `catch2Result.csv`。已有历史数据不会丢失（只要 `sources/` 目录保持挂载），但 CSV 会重新生成。

3. **Basic Auth 凭据硬编码**：`user:pass123` 写入 Dockerfile，修改需重新构建镜像。

4. **Infinity 插件需构建时联网**：离线环境需提前下载插件 zip 包并修改 Dockerfile 改为离线安装。
