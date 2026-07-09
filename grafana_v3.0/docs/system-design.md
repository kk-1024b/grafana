# System Design — 数据流与 Flask 功能说明

## 一、整体架构

```
CI 设备
  │  PUT /details/<timestamp>/testResult.json
  ▼
nginx (8080) ── WebDAV ──▶ /data/details/catch2/<timestamp>/testResult.json
                                          │
                            watcher.py 每 2 秒轮询
                                          │
                                          ▼
                              /data/platforms/<platform>.db  (SQLite)
                                          │
                              Flask (3000) 读取 DB
                                          │
                                          ▼
                              浏览器 ─ 仪表板 / 详情 / 平台历史
```

三个进程由 supervisord 管理，运行在同一个 Docker 容器内：

| 进程 | 职责 |
|---|---|
| nginx | 接收 CI 上传的 JSON 文件（WebDAV PUT） |
| watcher | 监听文件目录，解析 JSON，写入 SQLite |
| flask | 查询 SQLite，渲染页面，提供 API |

---

## 二、数据接收

### 2.1 上传协议

CI 设备通过 HTTP PUT 上传 JSON 文件：

```
PUT http://<host>:9698/details/<YYYY-MM-DD_HH-MM-SS>/testResult.json
Authorization: Basic user:pass123
Content-Type: application/json
```

### 2.2 nginx WebDAV

`conf/nginx.conf` 配置：

```nginx
location /details/ {
    alias /data/details/catch2/;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    create_full_put_path on;   # 自动创建子目录
}
```

- nginx 将文件写到宿主机挂载目录 `/data/details/catch2/<timestamp>/testResult.json`
- 不做任何解析，只做文件落盘

### 2.3 JSON 格式

```json
{
  "platform": "tx82",
  "os": "linux",
  "arch": "x86_64",
  "time": "2026-07-09T10:00:00Z",
  "summary": { "pass": 120, "total": 125 },
  "results": [
    { "num": 1, "module": "ModA", "binary": "test_a", "case": "TestFoo::bar", "result": "pass" },
    { "num": 2, "module": "ModA", "binary": "test_a", "case": "TestFoo::baz", "result": "FAILED" }
  ]
}
```

---

## 三、数据解析

### 3.1 watcher（`app_catch2/watch_catch2_files.py`）

每 2 秒扫描 `/data/details/catch2/`，发现新的 `testResult.json` 后：

1. 调用 `resultSum.getTestResultFromJson()` 解析 JSON
2. 调用 `db.run_exists()` 去重（避免重复写入）
3. 调用 `resultSum.insertResult()` 写入 SQLite

### 3.2 JSON 解析（`app_catch2/resultSum.py`）

从 JSON 中提取：

| 字段 | 来源 |
|---|---|
| platform / os / arch | 顶层字段 |
| time | 顶层字段（UTC，附加 `Z` 标记） |
| pass / total | `summary.pass` / `summary.total` |
| 测试用例列表 | `results[]` 数组 |

### 3.3 数据库写入（`app_catch2/db.py`）

每个 platform 对应一个独立的 SQLite 文件：`/data/platforms/<platform>.db`

```sql
-- 每次运行的汇总
CREATE TABLE runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    time     TEXT    NOT NULL,   -- UTC ISO-8601
    platform TEXT    NOT NULL,
    os       TEXT    NOT NULL,
    arch     TEXT    NOT NULL,
    pass     INTEGER NOT NULL,
    total    INTEGER NOT NULL
);

-- 该运行的所有测试用例
CREATE TABLE test_cases (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id),
    num       INTEGER,
    module    TEXT,
    binary    TEXT,
    case_name TEXT,
    result    TEXT     -- 'pass' 或失败原因字符串
);
```

写入顺序：先 `INSERT INTO runs` 获取 `run_id`，再批量 `INSERT INTO test_cases`。

---

## 四、Flask 的职责

Flask（`app_web/web.py`）是唯一的对外展示层，承担以下功能：

### 4.1 时区转换（全局 Filter）

DB 中所有时间存储为 UTC，Flask 在展示前统一转为 CST（UTC+8）：

```python
CST = timezone(timedelta(hours=8))

@app.template_filter('utc_to_cst')
def utc_to_cst(s):
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    return dt.astimezone(CST).strftime('%Y-%m-%d %H:%M:%S')
```

模板中使用：`{{ run.time | utc_to_cst }}`

### 4.2 路由一览

| 路由 | 模板 | 说明 |
|---|---|---|
| `GET /` | `index.html` | 10 天 pivot 汇总表 |
| `GET /detail/<platform>/<run_id>` | `detail.html` | 单次运行全部测试用例 |
| `GET /platform/<platform>?os=&arch=` | `platform.html` | 平台历史趋势 |
| `GET /api/detail?run_id=&platform=` | JSON | 失败用例列表（modal 用） |
| `GET /static/js/chart.umd.min.js` | — | 本地化 Chart.js |

### 4.3 首页 Pivot 查询（`GET /`）

从所有 `*.db` 文件中读取最近 10 天的数据，构建二维表格（platform/os/arch × 日期）：

```sql
SELECT r.platform, r.os, r.arch,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-N day')
       THEN r.pass||'/'||r.total END) AS dN,
  ...
FROM runs r
JOIN (
    -- 每天只取最新一条
    SELECT platform, os, arch, date(time,'+8 hours') AS day, MAX(time) AS latest_time
    FROM runs GROUP BY platform, os, arch, date(time,'+8 hours')
) l ON ... AND r.time=l.latest_time
WHERE date(r.time,'+8 hours') >= date('now', '+8 hours', '-9 day')
GROUP BY r.platform, r.os, r.arch
```

- 日期计算全部在 SQLite 内用 `+8 hours` 偏移，与 Python 侧的 CST 保持一致
- 列头日期由 Python `datetime.now(CST).date()` 生成，与 SQL 结果对齐

渲染：`render_template('index.html', rows=rows, days=days)`

### 4.4 详情页（`GET /detail/<platform>/<run_id>`）

```python
run   = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
cases = conn.execute(
    'SELECT num, module, binary, case_name, result FROM test_cases WHERE run_id=? ORDER BY num',
    (run_id,)
).fetchall()
return render_template('detail.html', run=dict(run), cases=[dict(c) for c in cases])
```

模板中 `{{ run.time | utc_to_cst }}` 显示 CST 时间。

### 4.5 平台历史页（`GET /platform/<platform>?os=&arch=`）

```python
os   = request.args.get('os',   '')
arch = request.args.get('arch', '')
rows = conn.execute(
    'SELECT id, time, pass, total FROM runs WHERE os=? AND arch=? ORDER BY time DESC',
    (os, arch)
).fetchall()
```

Python 侧处理：
- `time_cst = utc_to_cst(d['time'])` — 转为 CST 字符串
- `pass_rate = round(pass/total*100, 1)` — 计算通过率
- `chart_runs = [r for r in reversed(runs) if date >= cutoff]` — 图表只取最近 60 天

传入模板两组数据：
- `runs`（DESC）— 左侧分页表格
- `chart_runs`（ASC，60 天）— 右侧 Chart.js 折线图

### 4.6 失败用例 API（`GET /api/detail`）

```python
cases = conn.execute(
    "SELECT case_name, result FROM test_cases WHERE run_id=? AND result!='pass' ORDER BY num",
    (run_id,)
).fetchall()
return jsonify([dict(c) for c in cases])
```

首页 modal 弹窗通过 `fetch('/api/detail?run_id=X&platform=Y')` 调用，动态展示失败用例。

---

## 五、前端渲染机制

| 页面 | 渲染方式 | 说明 |
|---|---|---|
| index.html | 服务端渲染 | Jinja2 直接输出 HTML 表格 |
| detail.html | 服务端渲染 + 客户端分页 | 全量 `<tr>` 由服务端输出，JS 控制显隐 |
| platform.html | 服务端渲染 + 客户端分页 + Chart.js | 表格同上；图表数据以 JSON blob 嵌入 `<script>`，Chart.js 读取后绘图 |

Chart.js 文件（`/static/js/chart.umd.min.js`）本地托管，无需访问外网。

---

## 六、数据流完整时序

```
CI 上传
  │ PUT /details/2026-07-09_10-00-00/testResult.json
  ▼
nginx 写文件到 /data/details/catch2/
  │
  │ (2 秒内)
  ▼
watcher 发现新文件
  │ resultSum.getTestResultFromJson()
  │ db.run_exists() → 跳过重复
  │ db.insert_run()      → runs 表新增一行
  │ db.insert_test_cases() → test_cases 批量插入
  ▼
/data/platforms/tx82.db 更新
  │
  │ (用户刷新浏览器)
  ▼
Flask GET /
  │ 读所有 *.db，执行 PIVOT_SQL
  │ render_template('index.html', rows, days)
  ▼
浏览器显示最新结果
  │ 点击 badge → GET /detail/tx82/42
  │ 点击 platform → GET /platform/tx82?os=linux&arch=x86_64
  ▼
Flask 查对应 DB，渲染详情页 / 历史页
```
