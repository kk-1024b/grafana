# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single Docker container that merges three services (nginx WebDAV + Python file watcher + Grafana) using `supervisord`. CI/CD pipelines PUT test result CSVs to nginx; the Python watcher processes them into a SQLite database; Grafana reads those via the SQLite plugin.

Two watcher versions exist side by side — `app/` (CSV) and `app_2.0/` (SQLite). The Dockerfile's `COPY app_2.0/ /app/` line controls which is active.

## Build & Run

```bash
# Build image, export to dt_all_1.0.tar, and start container
bash build_script/build_all_in_one.sh

# Check all three processes are RUNNING
docker exec dt_all supervisorctl status

# View logs per process
docker exec dt_all tail -f /var/log/supervisor/watcher.log
docker exec dt_all tail -f /var/log/supervisor/nginx_err.log
docker exec dt_all tail -f /var/log/supervisor/grafana.log
```

## Deploying on another machine (offline)

```bash
# Load the exported tar (CMD is lost on docker export — must specify it explicitly)
docker import dt_all_1.0.tar dt_all:1.0
docker run -d --restart=always --name dt_all \
    -p 9696:3000 -p 9698:8080 \
    -v /your/data/path:/data \
    dt_all:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

## Architecture

```
supervisord
├── nginx (8080 → host:9698)   PUT /details/sources/ → /data/details/sources/ (symlink→catch2)
├── grafana-server (3000 → host:9696)  queries /data/test_results.db via SQLite plugin
└── python3 /app/watch_new_files.py    polls /data/details/catch2/ every 2s
```

Single volume mount: `-v /host/catch2_data/data:/data`

## Data Flow

1. CI uploads `testResult.csv` via `PUT /details/sources/<YYYY-MM-DD_HH-MM-SS>/testResult.csv` (port 9698)
2. Watcher detects new file → parses pass/total counts + all rows → writes to SQLite (`runs` + `test_cases` tables)
3. Grafana `frser-sqlite-datasource` plugin queries `/data/test_results.db` directly

## Python App Versions

### app_2.0/ (active — SQLite)
- **`watch_new_files.py`** — entry point; creates `WATCH_DIR` on startup, initializes DB, polls every 2s; no rebuild on restart (SQLite is persistent)
- **`resultSum.py`** — parses CSV returning `(time, passNum, totalNum, rows)`; writes via `db.insertResult()`
- **`db.py`** — SQLite layer: `init_db()`, `insert_run()`, `insert_test_cases()`

### app/ (original — CSV, inactive)
- Writes `catch2Result.csv` and generates per-run HTML reports
- Switch back: change `COPY app_2.0/ /app/` → `COPY app/ /app/` in Dockerfile and restore `/data/` GET in `conf/nginx.conf`

## Key Files

| File | Purpose |
|------|---------|
| `Dockerfile` | debian:bookworm-slim; installs nginx-extras, grafana (apt), frser-sqlite-datasource plugin, python3, supervisord |
| `conf/nginx.conf` | WebDAV PUT on `/details/` only; Basic Auth user:pass123 |
| `conf/supervisord.conf` | Runs nginx, grafana-server, python watcher; all with autorestart=true |

## Database Schema

```sql
runs(id, time TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result TEXT)
```

DB file: `/data/test_results.db` (inside mounted volume — persistent across restarts)

Timestamp format in `runs.time`: `2026-06-23T10:00:00Z` (RFC3339, converted from directory name `2026-06-23_10-00-00`)

## Important Constraints

- **Grafana data not persisted**: `/var/lib/grafana` is inside the container. Add `-v /host/grafana:/var/lib/grafana` to persist dashboard config across container restarts.
- **`docker export` drops CMD**: When loading with `docker import`, always append the supervisord command explicitly to `docker run`.
- **Infinity plugin requires internet at build time**: For offline builds, download the plugin zip separately and modify the Dockerfile to install from a local path.
- **Basic Auth credentials are hardcoded** in the Dockerfile (`htpasswd -cb`); changing them requires a rebuild.
