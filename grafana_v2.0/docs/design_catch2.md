# app_catch2 详细设计文档

## 1. 概述

`app_catch2/` 是 catch2 测试结果处理管道，与 benchmark 管道（`app_bm/`）完全隔离。

**职责**：监听 nginx 上传的 catch2 测试结果 CSV 文件，解析后写入 `test_results.db`，供 Grafana 查询展示测试通过率趋势和用例明细。

---

## 2. 数据流

```
CI/CD 流水线
    │
    │ curl -u user:pass123 -T testResult.csv
    │ http://host:9698/catch2/{timestamp}/testResult.csv
    ▼
nginx (9698)
    │ WebDAV PUT → 写入 /data/details/catch2/{timestamp}/testResult.csv
    ▼
watcher（轮询间隔 2 秒）
    ├── 检测 /data/details/catch2/ 下新文件
    ├── resultSum.py 解析 CSV
    └── db.py 写入 test_results.db
         ├── runs 表（每次 CI 运行一行）
         └── test_cases 表（每条用例一行）
         ▼
Grafana (9696)
    └── frser-sqlite-datasource 查询 /data/test_results.db
```

---

## 3. 输入格式（catch2 CSV）

```
Num,module,binary,case,result
0,module/device,DeviceTest,txGetDevice_Basic,pass
1,module/device,DeviceTest,txGetDevice_Fail,failed
2,module/device,DeviceTest,txGetDevice_Timeout,timeout
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `Num` | int | 用例序号 |
| `module` | string | 模块路径，如 `module/device` |
| `binary` | string | 测试可执行文件名 |
| `case` | string | 测试用例名 |
| `result` | string | 结果：`pass` \| `failed` \| `timeout` |

**时间戳来源**：不在 CSV 内容中，而是从文件的**父目录名**提取，格式 `YYYY-MM-DD_HH-MM-SS`，对应一次 CI 运行。

---

## 4. 模块设计

### 4.1 `db.py` — 数据库层

**职责**：建表、提供 CRUD 接口。

```
init_db(db_path) → conn
insert_run(conn, time, pass_, total) → run_id
insert_test_cases(conn, run_id, rows)
```

**Schema**：

```sql
CREATE TABLE IF NOT EXISTS runs (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    time  TEXT    NOT NULL,   -- 格式：2026-06-23 10:00:00
    pass  INTEGER NOT NULL,
    total INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS test_cases (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id),
    num       INTEGER,
    module    TEXT,
    binary    TEXT,
    case_name TEXT,
    result    TEXT
);
```

数据库文件路径：`/data/test_results.db`

**关联关系**：`test_cases.run_id → runs.id`，通过 JOIN 查询某次运行的所有用例明细。

### 4.2 `resultSum.py` — CSV 解析层

**职责**：读取 CSV 文件，统计 pass/total，返回原始行列表。

```
getTestResult(file) → (time, passNum, totalNum, rows)
switchTime(tm) → str
insertResult(conn, time, passNum, totalNum, rows)
```

**`getTestResult` 逻辑**：

```
1. 从 file.parent.name 提取时间戳目录名
2. csv.DictReader 逐行读取
3. 统计 result == 'pass' 的行数
4. 返回 (目录名, pass数, total数, 所有行列表)
```

**时间戳转换（`switchTime`）**：

```
目录名：  2026-06-23_10-00-00
              ↓ replace('_', ' ') + rsplit('-', 2) + ':' 拼接
写库值：  2026-06-23 10:00:00
```

**`insertResult` 逻辑**：

```
1. db.insert_run(conn, time, passNum, totalNum) → run_id
2. db.insert_test_cases(conn, run_id, rows)
```

### 4.3 `watch_catch2_files.py` — 主入口（文件监听）

**职责**：轮询目录，协调解析和写库。

| 配置 | 值 |
|------|----|
| `WATCH_DIR` | `/data/details/catch2` |
| `SECONDS` | 2 |

**启动逻辑**：

```
main()
  ├── WATCH_DIR.mkdir(parents=True, exist_ok=True)
  ├── db.init_db()           初始化数据库
  ├── 扫描现有文件集合        作为 known 集合
  └── watcher_task()         进入无限循环
        ├── sleep(2)
        ├── rglob('*')       扫描所有文件
        ├── diff（current - known）= 新文件
        └── 对每个新文件：
              resultSum.getTestResult()
              resultSum.switchTime()
              resultSum.insertResult()
```

**重启行为**：启动时**不重建历史数据**（`test_results.db` 持久化，数据已在），只记录现有文件集合用于后续 diff。若 DB 丢失或损坏，使用 `rebuild_db.py`（见 4.4）从原始文件重建。

### 4.4 `rebuild_db.py` — 数据库重建工具

**职责**：DB 损坏或丢失时，遍历所有历史 CSV 文件，从零重建 `test_results.db`。原始文件是唯一的真实来源，重建是幂等操作。

**用法**：

```bash
# 容器内（默认路径）
cd /app && python3 rebuild_db.py

# 自定义路径（本地测试）
python3 app_catch2/rebuild_db.py \
  --source-dir ./test_data \
  --db-path ./test.db
```

**参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--source-dir` | `/data/details/catch2` | 存放时间戳子目录的根目录 |
| `--db-path` | `/data/test_results.db` | 输出 DB 路径 |

**执行逻辑**：

```
1. 删除现有 DB 文件（若存在）
2. db.init_db(db_path)        重建表结构
3. glob **/testResult.csv     按目录名排序（保证时间顺序）
4. 逐文件：
     resultSum.getTestResult()
     resultSum.switchTime()
     resultSum.insertResult()
     打印进度 [i/N] OK/SKIP
5. 打印汇总：X/N imported
```

解析失败的文件打印 `SKIP` 跳过，不中断整体流程。

**验证**：重建完成后，`runs` 表行数应等于 `/data/details/catch2/` 下子目录数：

```bash
sqlite3 /data/test_results.db "SELECT COUNT(*) FROM runs;"
ls /data/details/catch2/ | wc -l
```

---

## 5. 目录与路径

| 路径 | 用途 |
|------|------|
| `/data/details/catch2/` | nginx 接收 PUT 上传，watcher 监听 |
| `/data/test_results.db` | SQLite 数据库（挂载目录内，持久化） |
| `/app/` | Python 脚本（Dockerfile `COPY app_catch2/ /app/` 打包进镜像） |

---

## 6. nginx 配置

```nginx
location /catch2/ {
    alias /data/details/catch2/;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
}
```

CI 上传命令：

```bash
# 时间戳格式：YYYY-MM-DD_HH-MM-SS
curl -u user:pass123 -T testResult.csv \
  http://localhost:9698/catch2/2026-06-24_10-00-00/testResult.csv
```

---

## 7. supervisord 配置

```ini
[program:watcher]
command=python3 /app/watch_catch2_files.py
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/watcher.log
stderr_logfile=/var/log/supervisor/watcher_err.log
```

日志查看：

```bash
docker exec dt_all tail -f /var/log/supervisor/watcher_err.log
```

---

## 8. Grafana 查询示例

数据源：`frser-sqlite-datasource`，文件路径 `/data/test_results.db`

```sql
-- 趋势图：历次运行通过率
SELECT time, pass, total,
       ROUND(pass * 100.0 / total, 1) AS pass_rate
FROM runs ORDER BY time

-- 变量数据源（下拉选择运行）
SELECT id || ' - ' || time AS __text, id AS __value
FROM runs ORDER BY time DESC

-- 明细表（变量 $run_id）
SELECT num, module, binary, case_name, result
FROM test_cases WHERE run_id = $run_id ORDER BY num

-- 失败用例筛选
SELECT num, module, binary, case_name, result
FROM test_cases
WHERE run_id = $run_id AND result != 'pass'

-- 单次运行统计
SELECT time, pass, total,
       ROUND(pass * 100.0 / total, 1) || '%' AS pass_rate
FROM runs WHERE id = $run_id
```

---

## 9. 备用版本：app/（CSV 版本）

`app/` 保留了原始 CSV 方案，作为回退备用。与 `app_catch2/` 的主要区别：

| 项目 | app_catch2/（当前） | app/（备用） |
|------|-------------------|------------|
| 存储 | SQLite `test_results.db` | `catch2Result.csv` + per-run HTML |
| Grafana 插件 | frser-sqlite-datasource | yesoreyeram-infinity-datasource |
| 重启行为 | 不重建历史 | 清空 HTML 目录，重扫重建 |

**切换回 CSV 版本**，修改 `Dockerfile` 两行：

```dockerfile
# 替换脚本目录
COPY app/ /app/

# 替换插件
RUN grafana cli ... install yesoreyeram-infinity-datasource
```

并在 `conf/nginx.conf` 的 `/catch2/` location 中额外加回静态 GET 路径：

```nginx
location /data/ {
    alias /data/;
    autoindex on;
}
```

---

## 10. 与 benchmark 管道对比

| 维度 | app_catch2 | app_bm |
|------|-----------|--------|
| 输入格式 | CSV | JSON |
| 上传路径 | `/details/sources/{ts}/testResult.csv` | `/details/sources_bm/{ts}/result.json` |
| 监听目录 | `/data/details/catch2/` | `/data/details/benchmark/` |
| 数据库 | `test_results.db` | `benchmark_results.db` |
| 进程名 | `watcher` | `bm_watcher` |
| 容器内脚本路径 | `/app/` | `/app_bm/` |
| 主要指标 | pass/total（功能正确性） | real_time/metrics（性能） |
