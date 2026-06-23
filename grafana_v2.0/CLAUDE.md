# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single Docker container that merges three services (nginx WebDAV + Python file watcher + Grafana) using `supervisord`. CI/CD pipelines PUT test result CSVs to nginx; the Python watcher processes them into HTML reports and an aggregated CSV; Grafana reads those files via the Infinity plugin.

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
    -p 9696:3000 -p 9699:8080 \
    -v /your/data/path:/data \
    dt_all:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

## Architecture

```
supervisord
├── nginx (8080 → host:9699)   PUT /details/ → /data/details/sources/
│                               GET /data/    → /data/
├── grafana-server (3000 → host:9696)  reads CSV via nginx GET
└── python3 /app/watch_new_files.py    polls /data/details/sources/ every 2s
```

Single volume mount: `-v /host/catch2_data/data:/data`

## Data Flow

1. CI uploads `testResult.csv` via `PUT /details/sources/<YYYY-MM-DD_HH-MM-SS>/testResult.csv`
2. Watcher detects new file → parses pass/total counts → appends row to `/data/catch2Result.csv` → generates `/data/details/html/report-<timestamp>.html`
3. Grafana Infinity plugin reads `/data/catch2Result.csv` for trend chart

## Python App (`app/`)

- **`watch_new_files.py`** — entry point; on startup clears HTML dir and rebuilds from existing sources, then polls for new files every 2s
- **`resultSum.py`** — parses CSV (counts rows where last column == `"pass"`), appends to `catch2Result.csv`; timestamp is parsed from the **parent directory name** of the uploaded file
- **`csv2html.py`** — generates self-contained HTML with sorting, pagination, global search, pass/fail highlighting; no external dependencies

Timestamp conversion (`resultSum.switchTime`): directory name `2026-06-23_10-00-00` → CSV value `2026-06-23 10:00:00`.

## Key Files

| File | Purpose |
|------|---------|
| `Dockerfile` | debian:bookworm-slim; installs nginx-extras, grafana (apt), Infinity plugin, python3, supervisord |
| `conf/nginx.conf` | WebDAV PUT on `/details/`, static GET on `/data/`, Basic Auth user:pass123 |
| `conf/supervisord.conf` | Runs nginx, grafana-server, python watcher; all with autorestart=true |

## Important Constraints

- **Grafana data not persisted**: `/var/lib/grafana` is inside the container. Add `-v /host/grafana:/var/lib/grafana` to persist dashboard config across container restarts.
- **Watcher resets on restart**: `initHtmlDir()` clears `/data/details/html/` and rebuilds `catch2Result.csv` from all existing files in `sources/` on every startup.
- **`docker export` drops CMD**: When loading with `docker import`, always append the supervisord command explicitly to `docker run`.
- **Infinity plugin requires internet at build time**: For offline builds, download the plugin zip separately and modify the Dockerfile to install from a local path.
- **Basic Auth credentials are hardcoded** in the Dockerfile (`htpasswd -cb`); changing them requires a rebuild.
