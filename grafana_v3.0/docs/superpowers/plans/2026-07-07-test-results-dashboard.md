# Test Results Dashboard (v3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask-based test results dashboard replacing Grafana, showing a 10-day pivot table of (platform, os, arch) × date with pass/fail badge coloring and click-through to failed test cases.

**Architecture:** Flask serves the pivot table via a Jinja2 template; SQLite (shared with the Python file watcher) stores run summaries and per-case results; supervisord orchestrates nginx (WebDAV upload) + watcher + Flask inside a single Docker container.

**Tech Stack:** Python 3, Flask, SQLite3, Jinja2, supervisord, nginx-extras (WebDAV), Docker (debian:bookworm-slim)

---

## File Map

| Status | Path | Responsibility |
|--------|------|----------------|
| Create | `app_catch2/db.py` | SQLite schema + CRUD for `runs` and `test_cases` |
| Create | `app_catch2/resultSum.py` | Parse JSON → extract platform/os/arch/time/pass/total/rows |
| Create | `app_catch2/watch_catch2_files.py` | Poll `/data/details/catch2/`, process new `.json` files |
| Create | `app_web/web.py` | Flask: `GET /` (pivot table), `GET /api/detail` (failed cases JSON) |
| Create | `app_web/templates/index.html` | Jinja2 table + AJAX modal |
| Create | `conf/nginx.conf` | WebDAV PUT on `/details/` |
| Create | `conf/supervisord.conf` | nginx + watcher + flask processes |
| Create | `Dockerfile` | debian:bookworm-slim + nginx-extras + Flask |
| Create | `tests/conftest.py` | sys.path setup for test imports |
| Create | `tests/test_db.py` | DB layer unit tests |
| Create | `tests/test_result_sum.py` | JSON parser unit tests |
| Create | `tests/test_web.py` | Flask route unit tests |

---

### Task 1: Project scaffold + test infrastructure

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import sys, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'app_catch2'))
sys.path.insert(0, os.path.join(BASE, 'app_web'))
```

- [ ] **Step 2: Verify pytest discovers tests directory**

```bash
pytest tests/ -v
```
Expected: `no tests ran` (zero tests, zero errors)

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: scaffold test infrastructure"
```

---

### Task 2: DB layer

**Files:**
- Create: `app_catch2/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests — create `tests/test_db.py`**

```python
import pytest
import db

@pytest.fixture
def conn(tmp_path):
    return db.init_db(tmp_path / 'test.db')

def test_init_creates_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert 'runs' in tables
    assert 'test_cases' in tables

def test_insert_run_returns_id(conn):
    run_id = db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 93, 100)
    assert run_id == 1

def test_run_exists_true(conn):
    db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 93, 100)
    assert db.run_exists(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64') is True

def test_run_exists_false(conn):
    assert db.run_exists(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64') is False

def test_insert_test_cases(conn):
    run_id = db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 1, 2)
    rows = [
        {'Num': 1, 'module': 'mod', 'binary': 'bin', 'case': 'TestFoo::bar', 'result': 'pass'},
        {'Num': 2, 'module': 'mod', 'binary': 'bin', 'case': 'TestFoo::baz', 'result': 'FAILED'},
    ]
    db.insert_test_cases(conn, run_id, rows)
    cur = conn.execute('SELECT case_name FROM test_cases WHERE run_id=? ORDER BY num', (run_id,))
    names = [r[0] for r in cur.fetchall()]
    assert names == ['TestFoo::bar', 'TestFoo::baz']
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```bash
pytest tests/test_db.py -v
```
Expected: `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Create `app_catch2/db.py`**

```python
#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB_PATH = Path('/data/test_results.db')


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            time     TEXT    NOT NULL,
            platform TEXT    NOT NULL,
            os       TEXT    NOT NULL,
            arch     TEXT    NOT NULL,
            pass     INTEGER NOT NULL,
            total    INTEGER NOT NULL
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
    """)
    conn.commit()
    return conn


def run_exists(conn, time, platform, os_, arch):
    cur = conn.execute(
        'SELECT 1 FROM runs WHERE time=? AND platform=? AND os=? AND arch=? LIMIT 1',
        (time, platform, os_, arch)
    )
    return cur.fetchone() is not None


def insert_run(conn, time, platform, os_, arch, pass_, total):
    cur = conn.execute(
        'INSERT INTO runs (time, platform, os, arch, pass, total) VALUES (?, ?, ?, ?, ?, ?)',
        (time, platform, os_, arch, pass_, total)
    )
    conn.commit()
    return cur.lastrowid


def insert_test_cases(conn, run_id, rows):
    conn.executemany(
        'INSERT INTO test_cases (run_id, num, module, binary, case_name, result) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        [
            (run_id, row.get('Num'), row.get('module'), row.get('binary'),
             row.get('case'), row.get('result'))
            for row in rows
        ]
    )
    conn.commit()
```

- [ ] **Step 4: Run — expect 5 passed**

```bash
pytest tests/test_db.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add app_catch2/db.py tests/test_db.py
git commit -m "feat: DB layer with platform/os/arch in runs table"
```

---

### Task 3: JSON parser

**Files:**
- Create: `app_catch2/resultSum.py`
- Create: `tests/test_result_sum.py`

- [ ] **Step 1: Write failing tests — create `tests/test_result_sum.py`**

```python
import json
import pytest
import db
import resultSum

@pytest.fixture
def json_file(tmp_path):
    data = {
        "platform": "tx8", "os": "kylin", "arch": "amd64",
        "time": "2026-07-07 10:00:00",
        "summary": {"pass": 93, "total": 100},
        "results": [
            {"num": 1, "case": "TestFoo::bar", "result": "pass"},
            {"num": 2, "case": "TestFoo::baz", "result": "FAILED"},
        ]
    }
    f = tmp_path / "testResult.json"
    f.write_text(json.dumps(data))
    return str(f)

def test_parse_fields(json_file):
    platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(json_file)
    assert platform == 'tx8'
    assert os_ == 'kylin'
    assert arch == 'amd64'
    assert passNum == 93
    assert totalNum == 100

def test_parse_time_rfc3339(json_file):
    _, _, _, tm, _, _, _ = resultSum.getTestResultFromJson(json_file)
    assert tm == '2026-07-07T10:00:00Z'

def test_parse_rows(json_file):
    _, _, _, _, _, _, rows = resultSum.getTestResultFromJson(json_file)
    assert len(rows) == 2
    assert rows[0]['case'] == 'TestFoo::bar'

def test_insert_result(json_file, tmp_path):
    conn = db.init_db(tmp_path / 'test.db')
    platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(json_file)
    run_id = resultSum.insertResult(conn, platform, os_, arch, tm, passNum, totalNum, rows)
    assert run_id == 1

def test_insert_result_dedup(json_file, tmp_path):
    conn = db.init_db(tmp_path / 'test.db')
    platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(json_file)
    run_id1 = resultSum.insertResult(conn, platform, os_, arch, tm, passNum, totalNum, rows)
    run_id2 = resultSum.insertResult(conn, platform, os_, arch, tm, passNum, totalNum, rows)
    assert run_id1 == 1
    assert run_id2 is None
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```bash
pytest tests/test_result_sum.py -v
```
Expected: `ModuleNotFoundError: No module named 'resultSum'`

- [ ] **Step 3: Create `app_catch2/resultSum.py`**

```python
#!/usr/bin/env python3
import json
import logging

import db

logger = logging.getLogger(__name__)


def getTestResultFromJson(file):
    with open(file, encoding='utf-8') as f:
        data = json.load(f)
    platform = data['platform']
    os_      = data['os']
    arch     = data['arch']
    tm       = data['time'].replace(' ', 'T') + 'Z'
    passNum  = data['summary']['pass']
    totalNum = data['summary']['total']
    rows = [{**{k: v for k, v in r.items() if k != 'num'}, 'Num': r['num']}
            for r in data['results']]
    return platform, os_, arch, tm, passNum, totalNum, rows


def insertResult(conn, platform, os_, arch, time, passNum, totalNum, rows):
    if db.run_exists(conn, time, platform, os_, arch):
        logger.info(f"Skipping duplicate: {time} {platform}/{os_}/{arch}")
        return None
    run_id = db.insert_run(conn, time, platform, os_, arch, passNum, totalNum)
    db.insert_test_cases(conn, run_id, rows)
    return run_id
```

- [ ] **Step 4: Run — expect 5 passed**

```bash
pytest tests/test_result_sum.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add app_catch2/resultSum.py tests/test_result_sum.py
git commit -m "feat: JSON parser reads platform/os/arch fields"
```

---

### Task 4: File watcher

**Files:**
- Create: `app_catch2/watch_catch2_files.py`

No unit tests — the polling loop integrates filesystem + timing. Verified by the Docker smoke test in Task 8.

- [ ] **Step 1: Create `app_catch2/watch_catch2_files.py`**

```python
#!/usr/bin/env python3
import shutil
import time
import logging
from datetime import datetime
from pathlib import Path

import db
import resultSum

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

WATCH_DIR = Path('/data/details/catch2')
SECONDS = 2


def processNewFile(conn, f):
    f = Path(f)
    if f.suffix != '.json':
        logger.info(f"Skipping non-JSON: {f}")
        return
    logger.info(f"Processing: {f}")
    platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(str(f))
    resultSum.insertResult(conn, platform, os_, arch, tm, passNum, totalNum, rows)


def watcher_task(conn, known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
        new_files = current - known
        for f in sorted(new_files):
            processNewFile(conn, f)
        known = current


def initDir():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    if db.DB_PATH.exists():
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        bak = db.DB_PATH.parent / f"test_results_{ts}.db.bak"
        shutil.copy2(db.DB_PATH, bak)
        logger.info(f"DB backed up to {bak}")
    conn = db.init_db()
    logger.info("Database initialized")
    known = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
    logger.info(f"Processing {len(known)} existing files on startup")
    for f in sorted(known):
        processNewFile(conn, f)
    return conn, known


def main():
    conn, known = initDir()
    logger.info(f"Watching {WATCH_DIR} every {SECONDS}s")
    watcher_task(conn, known)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Commit**

```bash
git add app_catch2/watch_catch2_files.py
git commit -m "feat: file watcher for JSON uploads"
```

---

### Task 5: Flask routes

**Files:**
- Create: `app_web/web.py`
- Create: `tests/test_web.py`

- [ ] **Step 1: Write failing tests — create `tests/test_web.py`**

```python
import json
import pytest
from datetime import date
import db

@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / 'test.db'
    conn = db.init_db(db_path)
    today = date.today().strftime('%Y-%m-%dT12:00:00Z')
    run_id = db.insert_run(conn, today, 'tx8', 'kylin', 'amd64', 93, 100)
    db.insert_test_cases(conn, run_id, [
        {'Num': 1, 'module': 'mod', 'binary': 'bin', 'case': 'TestFoo::fail1', 'result': 'FAILED'},
    ])
    conn.close()
    import web
    web.DB_PATH = str(db_path)
    web.app.config['TESTING'] = True
    return web.app.test_client()

def test_index_ok(client):
    resp = client.get('/')
    assert resp.status_code == 200

def test_index_contains_platform(client):
    resp = client.get('/')
    assert b'tx8' in resp.data

def test_pivot_query_today(tmp_path):
    import web
    db_path = tmp_path / 'test.db'
    conn = db.init_db(db_path)
    today = date.today().strftime('%Y-%m-%dT12:00:00Z')
    db.insert_run(conn, today, 'tx8', 'kylin', 'amd64', 93, 100)
    rows, days = web.pivot_query(conn)
    assert len(rows) == 1
    assert rows[0]['d0'] == '93/100'
    assert rows[0]['d0_id'] == 1
    assert len(days) == 10

def test_detail_returns_failed_cases(client):
    resp = client.get('/api/detail?run_id=1')
    data = json.loads(resp.data)
    assert len(data) == 1
    assert data[0]['case_name'] == 'TestFoo::fail1'

def test_detail_empty_for_unknown(client):
    resp = client.get('/api/detail?run_id=999')
    assert json.loads(resp.data) == []

def test_detail_excludes_passing(tmp_path):
    import web
    db_path = tmp_path / 'test.db'
    conn = db.init_db(db_path)
    today = date.today().strftime('%Y-%m-%dT12:00:00Z')
    run_id = db.insert_run(conn, today, 'tx8', 'kylin', 'arm', 99, 100)
    db.insert_test_cases(conn, run_id, [
        {'Num': 1, 'module': 'm', 'binary': 'b', 'case': 'TestA::pass_case', 'result': 'pass'},
        {'Num': 2, 'module': 'm', 'binary': 'b', 'case': 'TestA::fail_case', 'result': 'FAILED'},
    ])
    conn.close()
    web.DB_PATH = str(db_path)
    web.app.config['TESTING'] = True
    c = web.app.test_client()
    resp = c.get(f'/api/detail?run_id={run_id}')
    data = json.loads(resp.data)
    assert len(data) == 1
    assert data[0]['case_name'] == 'TestA::fail_case'
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```bash
pytest tests/test_web.py -v
```
Expected: `ModuleNotFoundError: No module named 'web'`

- [ ] **Step 3: Create `app_web/` directory**

```bash
mkdir -p app_web/templates
```

- [ ] **Step 4: Create `app_web/web.py`**

```python
#!/usr/bin/env python3
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).parent.parent / 'app_catch2'))

DB_PATH = os.environ.get('DB_PATH', '/data/test_results.db')

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


PIVOT_SQL = """
SELECT r.platform, r.os, r.arch,
  MAX(CASE WHEN date(r.time)=date('now','-9 day') THEN r.id END) AS d9_id,
  MAX(CASE WHEN date(r.time)=date('now','-9 day') THEN r.pass||'/'||r.total END) AS d9,
  MAX(CASE WHEN date(r.time)=date('now','-8 day') THEN r.id END) AS d8_id,
  MAX(CASE WHEN date(r.time)=date('now','-8 day') THEN r.pass||'/'||r.total END) AS d8,
  MAX(CASE WHEN date(r.time)=date('now','-7 day') THEN r.id END) AS d7_id,
  MAX(CASE WHEN date(r.time)=date('now','-7 day') THEN r.pass||'/'||r.total END) AS d7,
  MAX(CASE WHEN date(r.time)=date('now','-6 day') THEN r.id END) AS d6_id,
  MAX(CASE WHEN date(r.time)=date('now','-6 day') THEN r.pass||'/'||r.total END) AS d6,
  MAX(CASE WHEN date(r.time)=date('now','-5 day') THEN r.id END) AS d5_id,
  MAX(CASE WHEN date(r.time)=date('now','-5 day') THEN r.pass||'/'||r.total END) AS d5,
  MAX(CASE WHEN date(r.time)=date('now','-4 day') THEN r.id END) AS d4_id,
  MAX(CASE WHEN date(r.time)=date('now','-4 day') THEN r.pass||'/'||r.total END) AS d4,
  MAX(CASE WHEN date(r.time)=date('now','-3 day') THEN r.id END) AS d3_id,
  MAX(CASE WHEN date(r.time)=date('now','-3 day') THEN r.pass||'/'||r.total END) AS d3,
  MAX(CASE WHEN date(r.time)=date('now','-2 day') THEN r.id END) AS d2_id,
  MAX(CASE WHEN date(r.time)=date('now','-2 day') THEN r.pass||'/'||r.total END) AS d2,
  MAX(CASE WHEN date(r.time)=date('now','-1 day') THEN r.id END) AS d1_id,
  MAX(CASE WHEN date(r.time)=date('now','-1 day') THEN r.pass||'/'||r.total END) AS d1,
  MAX(CASE WHEN date(r.time)=date('now')           THEN r.id END) AS d0_id,
  MAX(CASE WHEN date(r.time)=date('now')           THEN r.pass||'/'||r.total END) AS d0
FROM runs r
JOIN (
    SELECT platform, os, arch, date(time) AS day, MAX(time) AS latest_time
    FROM runs
    GROUP BY platform, os, arch, date(time)
) l ON r.platform=l.platform AND r.os=l.os AND r.arch=l.arch
    AND date(r.time)=l.day AND r.time=l.latest_time
WHERE date(r.time) >= date('now', '-9 day')
GROUP BY r.platform, r.os, r.arch
ORDER BY r.platform, r.os, r.arch
"""


def pivot_query(conn):
    days = [date.today() - timedelta(days=i) for i in range(9, -1, -1)]
    rows = conn.execute(PIVOT_SQL).fetchall()
    return [dict(row) for row in rows], days


@app.route('/')
def index():
    conn = get_db()
    rows, days = pivot_query(conn)
    conn.close()
    return render_template('index.html', rows=rows, days=days)


@app.route('/api/detail')
def detail():
    run_id = request.args.get('run_id', type=int)
    if not run_id:
        return jsonify([])
    conn = get_db()
    cases = conn.execute(
        "SELECT case_name, result FROM test_cases "
        "WHERE run_id=? AND result!='pass' ORDER BY num",
        (run_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(c) for c in cases])


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)
```

- [ ] **Step 5: Run — pivot test passes, index fails on missing template**

```bash
pytest tests/test_web.py::test_pivot_query_today tests/test_web.py::test_detail_returns_failed_cases tests/test_web.py::test_detail_excludes_passing -v
```
Expected: `3 passed`

```bash
pytest tests/test_web.py::test_index_ok -v
```
Expected: FAIL with `TemplateNotFound: index.html` (template added in Task 6)

- [ ] **Step 6: Commit**

```bash
git add app_web/web.py tests/test_web.py
git commit -m "feat: Flask pivot route and detail API"
```

---

### Task 6: HTML template

**Files:**
- Create: `app_web/templates/index.html`

- [ ] **Step 1: Create `app_web/templates/index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Test Results</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fa; padding: 24px; font-size: 14px; color: #333; }
h1 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
.legend { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; font-size: 12px; }
.legend span { padding: 2px 8px; border-radius: 4px; }
.table-wrap { background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.1); overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 900px; }
th { background: #f0f2f5; font-weight: 600; padding: 9px 12px; text-align: center; font-size: 12px; color: #555; border-bottom: 2px solid #dde1e7; white-space: nowrap; }
th.left { text-align: left; }
th.today { color: #1a5fb4; font-weight: 700; }
td { padding: 7px 12px; border-bottom: 1px solid #eaecf0; white-space: nowrap; }
td.label { font-weight: 500; }
td.center { text-align: center; }
tr.g0 td { background: #EAF4FB; }
tr.g1 td { background: #EAF7EF; }
tr.g2 td { background: #FDF4E7; }
tr.g0:hover td, tr.g1:hover td, tr.g2:hover td { filter: brightness(0.96); }
.badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; cursor: pointer; transition: filter .15s; }
.badge:hover { filter: brightness(0.92); }
.badge.green  { background: #D4EDDA; color: #1a6632; }
.badge.yellow { background: #FFF3CD; color: #856404; }
.badge.red    { background: #F8D7DA; color: #842029; }
.badge.empty  { background: #e9ecef; color: #aaa; cursor: default; }
td.today .badge.green, td.today .badge.yellow, td.today .badge.red { box-shadow: 0 0 0 1px #90c4f8; }
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 100; align-items: center; justify-content: center; }
.modal-overlay.open { display: flex; }
.modal { background: #fff; border-radius: 10px; width: 520px; max-width: 95vw; max-height: 80vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,.18); }
.modal-header { padding: 16px 20px 12px; border-bottom: 1px solid #eaecf0; display: flex; justify-content: space-between; align-items: flex-start; }
.modal-title { font-weight: 600; font-size: 15px; }
.modal-meta  { font-size: 12px; color: #888; margin-top: 2px; }
.modal-close { cursor: pointer; font-size: 20px; color: #aaa; line-height: 1; }
.modal-close:hover { color: #333; }
.modal-body  { overflow-y: auto; padding: 14px 20px; }
.fail-list   { list-style: none; }
.fail-list li { padding: 8px 10px; border-radius: 5px; margin-bottom: 6px; background: #fff5f5; border-left: 3px solid #e55; font-size: 13px; font-family: monospace; }
</style>
</head>
<body>
<h1>Test Results</h1>
<p class="subtitle">最近 10 天测试结果 · 点击数字查看失败用例</p>
<div class="legend">
  <strong style="color:#555;">通过率：</strong>
  <span style="background:#D4EDDA;color:#1a6632;">≥ 95%</span>
  <span style="background:#FFF3CD;color:#856404;">90 – 95%</span>
  <span style="background:#F8D7DA;color:#842029;">&lt; 90%</span>
  <span style="background:#e9ecef;color:#aaa;">— 无数据</span>
</div>
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th class="left">platform</th>
      <th class="left">os</th>
      <th class="left">arch</th>
      {% for d in days %}
      <th{% if loop.last %} class="today"{% endif %}>{{ d.month }}月{{ d.day }}日{% if loop.last %} ✦{% endif %}</th>
      {% endfor %}
    </tr>
  </thead>
  <tbody>
    {% set ns = namespace(group_idx=-1, prev_key='') %}
    {% for row in rows %}
      {% set key = row.platform ~ '/' ~ row.os %}
      {% if key != ns.prev_key %}
        {% set ns.group_idx = (ns.group_idx + 1) % 3 %}
        {% set ns.prev_key = key %}
      {% endif %}
      <tr class="g{{ ns.group_idx }}">
        <td class="label">{{ row.platform }}</td>
        <td>{{ row.os }}</td>
        <td>{{ row.arch }}</td>
        {% for i in range(9, -1, -1) %}
          {% set val = row['d' ~ i] %}
          {% set run_id = row['d' ~ i ~ '_id'] %}
          <td class="center{% if loop.last %} today{% endif %}">
            {% if val %}
              {% set parts = val.split('/') %}
              {% set pct = parts[0]|int / parts[1]|int %}
              {% if pct >= 0.95 %}{% set cls = 'green' %}
              {% elif pct >= 0.90 %}{% set cls = 'yellow' %}
              {% else %}{% set cls = 'red' %}{% endif %}
              <span class="badge {{ cls }}" onclick="showDetail({{ run_id }}, '{{ row.platform }}', '{{ row.os }}', '{{ row.arch }}', '{{ val }}')">{{ val }}</span>
            {% else %}
              <span class="badge empty">—</span>
            {% endif %}
          </td>
        {% endfor %}
      </tr>
    {% endfor %}
  </tbody>
</table>
</div>

<div class="modal-overlay" id="modal" onclick="closeModal(event)">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title" id="modal-title"></div>
        <div class="modal-meta" id="modal-meta"></div>
      </div>
      <span class="modal-close" onclick="document.getElementById('modal').classList.remove('open')">×</span>
    </div>
    <div class="modal-body">
      <ul class="fail-list" id="modal-list"></ul>
    </div>
  </div>
</div>

<script>
async function showDetail(runId, platform, os, arch, score) {
  const resp = await fetch('/api/detail?run_id=' + runId);
  const cases = await resp.json();
  const parts = score.split('/').map(Number);
  document.getElementById('modal-title').textContent = platform + ' / ' + os + ' / ' + arch;
  document.getElementById('modal-meta').textContent = parts[0] + '/' + parts[1] + ' passed · ' + (parts[1] - parts[0]) + ' failed';
  const list = document.getElementById('modal-list');
  if (cases.length === 0) {
    list.innerHTML = '<li style="background:#f0fff0;border-left-color:#4caf50;color:#2e7d32;">All tests passed</li>';
  } else {
    list.innerHTML = cases.map(c => '<li>' + c.case_name + '</li>').join('');
  }
  document.getElementById('modal').classList.add('open');
}
function closeModal(e) {
  if (e.target === document.getElementById('modal'))
    document.getElementById('modal').classList.remove('open');
}
</script>
</body>
</html>
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all 16 tests pass

- [ ] **Step 3: Commit**

```bash
git add app_web/templates/index.html
git commit -m "feat: Jinja2 table template with AJAX modal"
```

---

### Task 7: Config files and Dockerfile

**Files:**
- Create: `conf/nginx.conf`
- Create: `conf/supervisord.conf`
- Create: `Dockerfile`

- [ ] **Step 1: Create `conf/nginx.conf`**

```nginx
server {
    listen 8080;

    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location /details/ {
        alias /data/details/catch2/;
        dav_methods PUT DELETE MKCOL COPY MOVE;
        dav_access user:rw group:rw all:r;
        create_full_put_path on;
    }
}
```

- [ ] **Step 2: Create `conf/supervisord.conf`**

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:nginx]
command=nginx -g "daemon off;"
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/nginx.log
stderr_logfile=/var/log/supervisor/nginx_err.log

[program:watcher]
command=python3 /app/watch_catch2_files.py
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/watcher.log
stderr_logfile=/var/log/supervisor/watcher_err.log

[program:flask]
command=python3 /app_web/web.py
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/flask.log
stderr_logfile=/var/log/supervisor/flask_err.log
```

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx-extras \
    supervisor \
    apache2-utils \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install flask --break-system-packages

RUN htpasswd -cb /etc/nginx/.htpasswd user pass123

COPY app_catch2/ /app/
COPY app_web/    /app_web/

COPY conf/nginx.conf        /etc/nginx/sites-available/default
COPY conf/supervisord.conf  /etc/supervisor/conf.d/all.conf

RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

EXPOSE 3000 8080

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/all.conf"]
```

- [ ] **Step 4: Commit**

```bash
git add conf/nginx.conf conf/supervisord.conf Dockerfile
git commit -m "feat: Docker container config (nginx + watcher + Flask)"
```

---

### Task 8: Integration smoke test

- [ ] **Step 1: Run full unit test suite**

```bash
pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 2: Build Docker image**

```bash
docker build -t grafana_v3:latest .
```
Expected: build succeeds with no errors

- [ ] **Step 3: Start container**

```bash
docker run -d --name gv3_test \
  -p 3000:3000 -p 8080:8080 \
  -v /tmp/gv3_data:/data \
  grafana_v3:latest

sleep 3
docker exec gv3_test supervisorctl status
```
Expected:
```
flask     RUNNING   pid ...
nginx     RUNNING   pid ...
watcher   RUNNING   pid ...
```

- [ ] **Step 4: Upload a test JSON and verify dashboard**

```bash
curl -u user:pass123 -X PUT \
  http://localhost:8080/details/2026-07-07_12-00-00/testResult.json \
  -H "Content-Type: application/json" \
  -d '{
    "platform":"tx8","os":"kylin","arch":"amd64",
    "time":"2026-07-07 12:00:00",
    "summary":{"pass":93,"total":100},
    "results":[
      {"num":1,"case":"TestFoo::bar","result":"pass"},
      {"num":2,"case":"TestFoo::baz","result":"FAILED"}
    ]
  }'

sleep 3
curl -s http://localhost:3000/ | grep -c 'tx8'
```
Expected: `1` (platform appears in table)

- [ ] **Step 5: Verify detail API**

```bash
curl -s "http://localhost:3000/api/detail?run_id=1"
```
Expected: `[{"case_name": "TestFoo::baz", "result": "FAILED"}]`

- [ ] **Step 6: Cleanup**

```bash
docker stop gv3_test && docker rm gv3_test
```
