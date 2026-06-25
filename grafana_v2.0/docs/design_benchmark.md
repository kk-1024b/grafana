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
    │ http://host:9698/details/sources_bm/{timestamp}/result.json
    ▼
nginx (9698)
    │ WebDAV PUT → 写入 /data/details/benchmark/{timestamp}/result.json
    ▼
bm_watcher（轮询间隔 2 秒）
    ├── 检测 /data/details/benchmark/ 下新 .json 文件
    ├── bm_parser.py 解析 JSON
    └── db_bm.py 写入 benchmark_results.db
         └── 每个 benchmark name 对应一张独立表（按需自动创建）
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

**职责**：按需动态建表、提供插入接口。

```
init_db(db_path) → conn
ensure_table(conn, name)              # 首次遇到新 name 时建表（幂等）
insert_benchmark(conn, name, date, host_srv, author, bm)
```

**Schema**（每个 benchmark name 对应一张表，表名即 name 字段，消毒后使用）：

```sql
-- 示例：BM_MemcpyD2H_Pageable
CREATE TABLE IF NOT EXISTS "BM_MemcpyD2H_Pageable" (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,   -- RFC3339: 2026-05-22T10:10:32Z
    host_srv   TEXT,
    author     TEXT,
    size       REAL,            -- bytes
    real_time  REAL,            -- 单位 ns
    cpu_time   REAL,            -- 单位 ns
    time_unit  TEXT,
    metrics    REAL,            -- 吞吐量（bytes/s 等）
    iterations INTEGER
);
```

数据库文件路径：`/data/benchmark_results.db`

**表命名规则**：`re.sub(r'[^\w]', '_', name)` 消毒后作为表名，加双引号包裹避免 SQL 关键字冲突。

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
              for bm in benchmarks:
                  db_bm.insert_benchmark(bm['name'], ...)
```

**重启行为**：启动时**不重建历史数据**（`benchmark_results.db` 持久化，数据已在），只记录现有文件集合用于后续 diff。若 DB 丢失或损坏，使用 `rebuild_db_bm.py`（见 4.4）从原始文件重建。

### 4.4 `rebuild_db_bm.py` — 数据库重建工具

**职责**：DB 损坏或丢失时，遍历所有历史 JSON 文件，从零重建 `benchmark_results.db`。原始文件是唯一的真实来源，重建是幂等操作。

**用法**：

```bash
# 容器内（默认路径）
cd /app_bm && python3 rebuild_db_bm.py

# 自定义路径（本地测试）
python3 app_bm/rebuild_db_bm.py \
  --source-dir ./test_data \
  --db-path ./test.db
```

**参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--source-dir` | `/data/details/benchmark` | 存放时间戳子目录的根目录 |
| `--db-path` | `/data/benchmark_results.db` | 输出 DB 路径 |

**执行逻辑**：

```
1. 删除现有 DB 文件（若存在）
2. db_bm.init_db(db_path)     重建表结构
3. glob **/*.json             按目录名排序（保证时间顺序）
4. 逐文件：
     bm_parser.parse_json()
     for bm in benchmarks:
         db_bm.insert_benchmark(bm['name'], ...)
     打印进度 [i/N] OK/SKIP（含 benchmark 条数）
5. 打印汇总：X/N imported
```

解析失败的文件打印 `SKIP` 跳过，不中断整体流程。

**验证**：重建完成后，用 `.tables` 确认各 benchmark 表已创建：

```bash
sqlite3 /data/benchmark_results.db ".tables"
# 预期：列出 BM_MemcpyD2H_Pageable  BM_MemcpyD2H_Pinned 等

sqlite3 /data/benchmark_results.db \
  "SELECT COUNT(*) FROM BM_MemcpyD2H_Pageable;"
```

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
location /details/sources_bm/ {
    alias /data/details/benchmark/;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
}
```

CI 上传命令：

```bash
curl -u user:pass123 -T result.json \
  http://localhost:9698/details/sources_bm/2026-05-22_10-10-32/result.json
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

每个 benchmark name 对应一张表，Time Series 面板直接查对应表，Time column = `date`。

```sql
-- 折线图：某 benchmark 的 metrics 历史趋势
SELECT date, metrics
FROM BM_MemcpyD2H_Pageable
ORDER BY date

-- 多指标对比（同一面板多条线）
SELECT date, real_time, cpu_time, metrics
FROM BM_MemcpyD2H_Pageable
ORDER BY date

-- 最近 N 条记录
SELECT date, metrics
FROM BM_MemcpyD2H_Pageable
ORDER BY date DESC LIMIT 20
```

**面板配置**：Standard options → Unit 设为 `bytes/s`（metrics 为吞吐量时），Min = 0。

---

## 9. 与 catch2 管道对比

| 维度 | app_catch2 | app_bm |
|------|-----------|--------|
| 输入格式 | CSV | JSON |
| 上传路径 | `/details/sources/{ts}/testResult.csv` | `/details/sources_bm/{ts}/result.json` |
| 监听目录 | `/data/details/catch2/` | `/data/details/benchmark/` |
| 数据库 | `test_results.db` | `benchmark_results.db` |
| 进程名 | `watcher` | `bm_watcher` |
| 主要指标 | pass/total（功能正确性） | real_time/metrics（性能） |
