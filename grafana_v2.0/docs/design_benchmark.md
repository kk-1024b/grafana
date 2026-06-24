# app_bm 详细设计文档

## 1. 概述

`app_bm/` 是独立的 benchmark 数据处理管道，与 catch2 测试结果管道（`app_catch2/`）完全隔离。

**职责**：监听 nginx 上传的 benchmark JSON 文件，解析后写入 `benchmark_results.db`，供 Grafana 查询展示性能趋势。

---

## 2. 数据流

```
CI/CD 流水线
    │
    │ curl -u user:pass123 -T result.json
    │ http://host:9699/benchmark/{timestamp}/result.json
    ▼
nginx (9699)
    │ WebDAV PUT → 写入 /data/details/benchmark/{timestamp}/result.json
    ▼
bm_watcher（轮询间隔 2 秒）
    ├── 检测 /data/details/benchmark/ 下新 .json 文件
    ├── bm_parser.py 解析 JSON
    └── db_bm.py 写入 benchmark_results.db
         ├── runs 表（顶层元数据）
         └── benchmarks 表（各条 benchmark 数据）
         ▼
Grafana (9696)
    └── frser-sqlite-datasource 查询 /data/benchmark_results.db
```

---

## 3. 输入格式（Google Benchmark JSON）

```json
{
    "date": "2026-05-22_10-10-32",
    "auther": "wangbing",
    "hostSrv": "qw-sh-8",
    "benchmarks": [
        {
            "name": "BM_MemcpyD2H_Pageable",
            "run_name": "BM_MemcpyD2H_Pageable/1073741824",
            "run_type": "iteration",
            "threads": 1,
            "iterations": 1000,
            "real_time": 115388254.19999921,
            "cpu_time": 115383051.662,
            "time_unit": "ns",
            "Metrics": 9305888590.513191,
            "size": 1073741824.0
        }
    ]
}
```

**顶层字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | string | 运行时间戳，格式 `YYYY-MM-DD_HH-MM-SS` |
| `auther` | string | 执行者（注：原始字段名拼写如此） |
| `hostSrv` | string | 执行机器名 |
| `benchmarks` | array | benchmark 结果列表 |

**benchmark 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | benchmark 名称（不含参数） |
| `run_name` | string | 完整运行名（含参数，如 `/1073741824`） |
| `run_type` | string | 通常为 `iteration` |
| `threads` | int | 线程数 |
| `iterations` | int | 实际执行次数 |
| `real_time` | float | 实际耗时（单位见 `time_unit`） |
| `cpu_time` | float | CPU 耗时 |
| `time_unit` | string | 时间单位，通常为 `ns` |
| `Metrics` | float | 吞吐量等自定义指标（bytes/s 等） |
| `size` | float | 数据量（bytes） |

省略字段：`family_index`、`per_family_instance_index`、`repetitions`、`repetition_index`（辅助调度字段，Grafana 不需要）。

---

## 4. 模块设计

### 4.1 `db_bm.py` — 数据库层

**职责**：建表、提供 CRUD 接口。

```
init_db(db_path) → conn
insert_run(conn, date, author, host_srv) → run_id
insert_benchmarks(conn, run_id, benchmarks)
```

**Schema**：

```sql
CREATE TABLE IF NOT EXISTS runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date     TEXT NOT NULL,   -- 格式：2026-05-22 10:10:32
    author   TEXT,
    host_srv TEXT
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    name       TEXT,          -- BM_MemcpyD2H_Pageable
    run_name   TEXT,          -- BM_MemcpyD2H_Pageable/1073741824
    run_type   TEXT,
    threads    INTEGER,
    iterations INTEGER,
    real_time  REAL,          -- 单位 ns
    cpu_time   REAL,          -- 单位 ns
    time_unit  TEXT,
    metrics    REAL,          -- 吞吐量
    size       REAL           -- bytes
);
```

数据库文件路径：`/data/benchmark_results.db`

**关联关系**：`benchmarks.run_id → runs.id`，一次运行对应多条 benchmark 记录。

### 4.2 `bm_parser.py` — JSON 解析层

**职责**：读取 JSON 文件，提取字段，做必要的格式转换。

```
parse_json(file) → (date, author, host_srv, benchmarks_list)
```

**时间戳转换**（`_switch_time`）：

```
原始：  2026-05-22_10-10-32
           ↓ replace('_', ' ') + rsplit('-', 2) + ':' 拼接
转换后：2026-05-22 10:10:32
```

与 `app_catch2/resultSum.py` 中 `switchTime` 逻辑相同，但作为模块内部函数独立实现，保持模块隔离。

### 4.3 `watch_bm_files.py` — 主入口（文件监听）

**职责**：轮询目录，协调解析和写库。

| 配置 | 值 |
|------|----|
| `WATCH_DIR` | `/data/details/benchmark` |
| `SECONDS` | 2 |

**启动逻辑**：

```
main()
  ├── WATCH_DIR.mkdir(parents=True, exist_ok=True)
  ├── db_bm.init_db()        初始化数据库
  ├── 扫描现有 .json 文件     作为 known 集合
  └── watcher_task()         进入无限循环
        ├── sleep(2)
        ├── rglob('*.json')  只扫描 JSON 文件
        ├── diff（current - known）= 新文件
        └── 对每个新文件：
              bm_parser.parse_json()
              db_bm.insert_run()
              db_bm.insert_benchmarks()
```

**重启行为**：启动时**不重建历史数据**（`benchmark_results.db` 持久化，数据已在），只记录现有文件集合用于后续 diff。

---

## 5. 目录与路径

| 路径 | 用途 |
|------|------|
| `/data/details/benchmark/` | nginx 接收 PUT 上传，bm_watcher 监听 |
| `/data/benchmark_results.db` | SQLite 数据库（挂载目录内，持久化） |
| `/app_bm/` | Python 脚本（Dockerfile `COPY app_bm/ /app_bm/` 打包进镜像） |

---

## 6. nginx 配置

```nginx
location /benchmark/ {
    alias /data/details/benchmark/;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
}
```

CI 上传命令：

```bash
curl -u user:pass123 -T result.json \
  http://localhost:9699/benchmark/2026-05-22_10-10-32/result.json
```

---

## 7. supervisord 配置

```ini
[program:bm_watcher]
command=python3 /app_bm/watch_bm_files.py
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/bm_watcher.log
stderr_logfile=/var/log/supervisor/bm_watcher_err.log
```

日志查看：

```bash
docker exec dt_all tail -f /var/log/supervisor/bm_watcher_err.log
```

---

## 8. Grafana 查询示例

数据源：`frser-sqlite-datasource`，文件路径 `/data/benchmark_results.db`

```sql
-- 所有运行列表
SELECT id, date, author, host_srv FROM runs ORDER BY date DESC

-- 某次运行的所有 benchmark（变量 $run_id）
SELECT name, run_name, real_time, cpu_time, metrics, size, time_unit
FROM benchmarks WHERE run_id = $run_id

-- 指定 benchmark 的历史趋势（变量 $bm_name）
SELECT r.date, b.real_time, b.metrics, b.size
FROM benchmarks b JOIN runs r ON b.run_id = r.id
WHERE b.name = '$bm_name'
ORDER BY r.date

-- 同一运行内按 size 排序（吞吐量分析）
SELECT size, metrics, real_time
FROM benchmarks
WHERE run_id = $run_id AND name = '$bm_name'
ORDER BY size
```

---

## 9. 与 catch2 管道对比

| 维度 | app_catch2 | app_bm |
|------|-----------|--------|
| 输入格式 | CSV | JSON |
| 上传路径 | `/catch2/{ts}/testResult.csv` | `/benchmark/{ts}/result.json` |
| 监听目录 | `/data/details/catch2/` | `/data/details/benchmark/` |
| 数据库 | `test_results.db` | `benchmark_results.db` |
| 进程名 | `watcher` | `bm_watcher` |
| 主要指标 | pass/total（功能正确性） | real_time/metrics（性能） |
