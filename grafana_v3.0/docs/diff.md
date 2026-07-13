# v2.0 → v3.0 变更说明

## 一句话总结

v3.0 用自研 Flask 仪表板替换了 Grafana，同时引入多平台支持（每个 platform 独立 SQLite 文件 + pivot 汇总表），并将数据格式收敛为纯 JSON。

---

## 核心变更对比

| 维度 | v2.0 | v3.0 |
|---|---|---|
| **仪表板** | Grafana（`grafana-server` 进程） | 自研 Flask（`web.py`） |
| **进程数** | 4（nginx + grafana + watcher + bm_watcher） | 3（nginx + watcher + flask） |
| **数据格式** | CSV（主）+ JSON（辅） | JSON 唯一格式 |
| **平台支持** | 单平台，单一 `test_results.db` | 多平台，每个 platform 一个 `<platform>.db` |
| **`runs` 表结构** | `(id, time, pass, total)` | `(id, time, platform, os, arch, pass, total)` |
| **时区处理** | 无（由 Grafana 展示层控制） | UTC 存库，CST 展示（SQL `+8 hours` + Jinja2 filter） |
| **HTML 报告生成** | watcher 生成静态 HTML 报告文件 | 无（Flask 动态渲染） |
| **Benchmark 支持** | `app_bm/`（独立 watcher） | 已移除 |
| **镜像体积** | ~1–2 GB（含 Grafana） | ~200 MB（仅 Flask + nginx） |
| **构建依赖** | 需外网（Grafana apt 源 + frser-sqlite-datasource 插件） | 仅需 pip install flask（支持国内镜像） |
| **热更新** | 仪表板改动需重建镜像 | `docker cp *.html` 无需重启；`web.py` 只需 kill Flask（supervisord 自动重启） |
| **watcher 启动行为** | 备份旧 DB → 重建 DB → 重处理所有文件 | 保留已有 DB → 重处理文件（`run_exists()` 去重） |
| **tar.gz 处理** | 移动到 `/data/details/html/logs/` | 已移除 |
| **rebuild_db 工具** | `app_catch2/rebuild_db.py`（内嵌） | `rebuild_db.py`（顶层，支持 `--db-dir` 参数） |

---

## 详细说明

### 1. 仪表板：Grafana → Flask

v2.0 使用 Grafana 作为展示层，需要安装 `frser-sqlite-datasource` 插件并手工配置数据源和 Dashboard。Dashboard 配置不随容器持久化，容器删除后需重建。

v3.0 用 `app_web/web.py`（Flask）替代 Grafana，提供三个页面：

- `/` — 10 天 pivot 汇总表（所有 platform/os/arch × 日期）
- `/detail/<platform>/<run_id>` — 单次运行的全量测试用例
- `/platform/<platform>?os=&arch=` — 历史趋势 + Chart.js 折线图

页面逻辑全部在代码中，随 `docker cp` 即可更新，无需 Grafana 账号或插件管理。

### 2. 多平台支持

v2.0 的 `runs` 表没有 `platform / os / arch` 字段，所有结果写入同一个 `test_results.db`，只能展示单一设备的数据。

v3.0 从 JSON 的 `platform` 字段派生 DB 文件名（`/data/platforms/<platform>.db`），每个平台独立存储。首页 pivot 查询遍历所有 `*.db` 文件，将结果合并为一张跨平台的汇总表，行 = `(platform, os, arch)`，列 = 最近 10 天。

### 3. 数据格式收敛

v2.0 的 watcher 同时支持 CSV（解析列头，通过父目录名提取时间戳）和 JSON，还处理 `.tar.gz` 归档文件。

v3.0 只接受 JSON，格式固定：

```json
{
  "platform": "tx8", "os": "kylin", "arch": "amd64",
  "time": "2026-07-08T10:00:00Z",
  "summary": {"pass": 93, "total": 100},
  "results": [{"num": 1, "case": "TestFoo::bar", "result": "pass"}, ...]
}
```

CSV 解析（`csv2html.py`、`getTestResult()`）和 tar.gz 处理逻辑均已删除。

### 4. 时区处理显式化

v2.0 的 DB 中 `time` 字段存储的是从目录名提取的时间字符串，时区语义不明确，由 Grafana 展示层自行处理。

v3.0 规定：DB 统一存 UTC（ISO-8601 + `Z` 后缀），展示统一用 CST（UTC+8）：

- SQL 查询中用 `date(time, '+8 hours')` 做日期分组
- Flask 列头用 `datetime.now(CST).date()` 生成
- 模板用 `{{ run.time | utc_to_cst }}` filter 格式化

### 5. watcher 启动行为变化

v2.0 watcher 启动时会先备份旧 DB，再重建（空表），然后重处理 WATCH_DIR 下的所有历史文件——每次重启都会全量重建。

v3.0 watcher 启动时保留已有 DB，仅对 WATCH_DIR 中的文件调用 `run_exists()` 去重后按需插入。历史数据不会因重启丢失，重启速度更快。

### 6. Benchmark 模块移除

v2.0 包含 `app_bm/`（`watch_bm_files.py`、`db_bm.py`、`bm_parser.py`）用于处理 benchmark 结果，supervisord 中有独立的 `bm_watcher` 进程。

v3.0 不包含任何 benchmark 相关代码。如需恢复，参照 v2.0 的 `app_bm/` 目录和 supervisord 配置。
