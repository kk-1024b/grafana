# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Flask-based CI test results dashboard. Replaces Grafana with a custom web page showing a 10-day pivot table of `(platform, os, arch) × date`, with pass/fail badge coloring and click-through to failed test cases.

## Build & Run

```bash
# Build Docker image
docker build -t dt_v3:1.0 .

# Run (dashboard on :9696, WebDAV upload on :9698)
docker run -d --restart=always --name dt_v3 \
    -p 9696:3000 \
    -p 9698:8080 \
    -v /home/kk/catch2_data/data:/data \
    dt_v3:1.0

# Check process status
docker exec dt_v3 supervisorctl status
```

## Hot-Update (No Rebuild Needed)

```bash
# Templates — no restart needed, Flask reads on every request
docker cp app_web/templates/platform.html dt_v3:/app_web/templates/platform.html
docker cp app_web/templates/index.html    dt_v3:/app_web/templates/index.html
docker cp app_web/templates/detail.html   dt_v3:/app_web/templates/detail.html

# web.py — restart Flask after copy (supervisord auto-restarts it)
docker cp app_web/web.py dt_v3:/app_web/web.py
FLASK_PID=$(for p in $(docker exec dt_v3 ls /proc/ | grep -E '^[0-9]+$'); do \
  docker exec dt_v3 cat /proc/$p/cmdline 2>/dev/null | tr '\0' ' ' | grep -q web.py && echo $p; done)
docker exec dt_v3 python3 -c "import os,signal; os.kill($FLASK_PID, signal.SIGTERM)"
```

## Tests

```bash
# Run all tests
pytest tests/

# Run a single test
pytest tests/test_db.py::test_insert_run_returns_id
```

`tests/conftest.py` adds `app_catch2/` and `app_web/` to `sys.path` — no install required.

## Seed DB from JSON files (local dev)

```bash
# Seed from demo/ into default /data/platforms/
python3 rebuild_db.py demo/

# Seed into a custom directory
python3 rebuild_db.py demo/ --db-dir /home/kk/catch2_data/data/platforms
```

## Architecture

Single Docker container, three processes managed by supervisord:

```
supervisord
├── nginx  (8080)  WebDAV PUT — receives CI JSON uploads to /data/details/catch2/
├── watcher        polls /data/details/catch2/ every 2s → writes to SQLite per platform
└── flask  (3000)  reads SQLite, serves dashboard + API
```

**Volume layout** (`-v <host>:/data`):
```
/data/
  platforms/<platform>.db   — one SQLite DB per platform, auto-created
  details/catch2/           — landing dir for CI uploads (nginx writes here)
```

**Container paths:**
- `app_catch2/` → `/app/` (watcher runs here; `db.py` and `resultSum.py` are siblings)
- `app_web/` → `/app_web/`

## Key Files

| File | Role |
|---|---|
| `app_web/web.py` | Flask app — all routes, `PIVOT_SQL`, timezone filter |
| `app_catch2/watch_catch2_files.py` | Watcher loop — detects new JSON files, calls resultSum/db |
| `app_catch2/resultSum.py` | JSON parser + duplicate-aware insert coordinator |
| `app_catch2/db.py` | SQLite schema (`init_db`) + CRUD (`insert_run`, `insert_test_cases`, `run_exists`) |
| `rebuild_db.py` | CLI tool to seed DBs from a directory of JSON files |
| `conf/supervisord.conf` | Process definitions for nginx, watcher, flask |
| `conf/nginx.conf` | WebDAV PUT config; Basic Auth via `/etc/nginx/.htpasswd` |

## Data Flow

1. CI `PUT /details/<timestamp>/testResult.json` → nginx writes file to `/data/details/catch2/`
2. Watcher detects new file → `resultSum.getTestResultFromJson()` parses it → `db.run_exists()` deduplicates → `db.insert_run()` + `db.insert_test_cases()` write to `<platform>.db`
3. Browser hits Flask → `PIVOT_SQL` reads all `*.db` files → renders 10-day pivot table

## Timezone Convention

- **DB stores UTC** — `time` field in `runs` is ISO-8601 with `Z` suffix
- **Display in CST (UTC+8)** — all conversions happen at render time:
  - SQLite: `date(time, '+8 hours')` in SQL queries
  - Python: `datetime.now(CST).date()` for column headers
  - Jinja2: `{{ run.time | utc_to_cst }}` filter in templates
- CI JSON `time` field must be UTC; the watcher appends `Z` unconditionally

## DB Schema

```sql
runs(id, time TEXT, platform TEXT, os TEXT, arch TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result TEXT)
```

One file per platform: `/data/platforms/<platform>.db`. To reset: `rm /data/platforms/<platform>.db`.

## Flask Routes

| Route | Template | Purpose |
|---|---|---|
| `GET /` | `index.html` | 10-day pivot table (one row per platform/os/arch combo) |
| `GET /detail/<platform>/<run_id>` | `detail.html` | All test cases for one run |
| `GET /platform/<platform>?os=&arch=` | `platform.html` | History table + Chart.js trend (60-day window) |
| `GET /api/detail?run_id=&platform=` | JSON | Failed cases only — used by index.html modal |

## Frontend Notes

- `index.html` — server-rendered Jinja2 table; badge clicks open a modal via `fetch('/api/detail')`
- `detail.html` / `platform.html` — server-rendered rows, client-side JS pagination
- `platform.html` — Chart.js line chart; data embedded as JSON blob in `<script>` tag; Chart.js is locally hosted at `/static/js/chart.umd.min.js`

## Offline / Export

```bash
docker export dt_v3 -o dt_v3_1.0.tar
docker import dt_v3_1.0.tar dt_v3:1.0
# Must specify CMD explicitly after import (export strips it):
docker run -d --restart=always --name dt_v3 \
    -p 9696:3000 -p 9698:8080 \
    -v /your/data:/data \
    dt_v3:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

## Credentials

nginx Basic Auth: `user` / `pass123` (hardcoded in Dockerfile — rebuild to change)
