# app/ 与 app_2.0/ 模块说明

本项目有两个版本的 Python watcher：

| 版本 | 存储方式 | Grafana 插件 | HTML 报告 |
|------|---------|-------------|----------|
| `app/` | CSV 文件 | Infinity | 有 |
| `app_2.0/` | SQLite 数据库 | frser-sqlite-datasource | 无 |

Dockerfile 通过 `COPY app/ /app/` 或 `COPY app_2.0/ /app/` 切换版本。

---

## app/ — CSV 版本

三个文件协同完成：把 CI 上传的测试结果 CSV，转化为 Grafana 可读的汇总 CSV + 可交互的 HTML 报告。

### watch_new_files.py — 主入口

轮询 `/data/details/sources/` 目录，每 2 秒扫描一次，发现新文件就触发处理。

启动时：清空 `/data/details/html/`，扫描已有文件重建汇总 CSV 和 HTML。

### resultSum.py — CSV 解析 + 汇总写入

- `getTestResult(file)`：统计 `result == 'pass'` 的行数，时间戳从父目录名提取
- `insertOneResult(tm, passNum, totalNum)`：追加一行到 `/data/catch2Result.csv`
- `switchTime(tm)`：`2026-06-23_10-00-00` → `2026-06-23 10:00:00`

### csv2html.py — HTML 报告生成器

将 `testResult.csv` 渲染为自包含 HTML，支持列排序、分页、全局搜索、pass/fail 高亮。

```
watch_new_files.py
    ├── resultSum.py   → catch2Result.csv
    └── csv2html.py    → report-{timestamp}.html
```

---

## app_2.0/ — SQLite 版本

废弃 HTML 报告，数据写入 SQLite，Grafana 直接查询数据库。

### db.py — 数据库层

- `init_db(db_path='/data/test_results.db')` — 建表并返回连接
- `insert_run(conn, time, pass_, total) → run_id`
- `insert_test_cases(conn, run_id, rows)` — 批量插入明细

**Schema：**
```sql
runs(id, time, pass, total)
test_cases(id, run_id, num, module, binary, case_name, result)
```

`test_cases.run_id` 外键关联 `runs.id`，通过 JOIN 查询某次运行的明细。

### resultSum.py — CSV 解析 + 写库

- `getTestResult(file)` — 返回 `(time, passNum, totalNum, rows)`，`rows` 为原始行列表
- `insertResult(conn, time, passNum, totalNum, rows)` — 调用 `db.insert_run` + `db.insert_test_cases`

### watch_new_files.py — 主入口

- 启动时创建 `WATCH_DIR`，调用 `db.init_db()` 初始化数据库
- 重启后**不重建历史数据**（SQLite 持久化，数据已在）
- 其余轮询逻辑（每 2 秒 diff）与 CSV 版本相同

```
watch_new_files.py
    ├── db.py          → /data/test_results.db
    └── resultSum.py   → 解析 CSV，写入 runs + test_cases 表
```

---

## Grafana 查询示例（app_2.0 版本）

```sql
-- 趋势图
SELECT time, pass, total FROM runs ORDER BY time

-- 明细表（变量 $run_id）
SELECT num, module, binary, case_name, result
FROM test_cases WHERE run_id = $run_id

-- 变量数据源（下拉选择运行）
SELECT id || ' - ' || time AS label, id AS value
FROM runs ORDER BY time DESC
```
