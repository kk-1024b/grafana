# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a CI/CD test dashboard system that collects Catch2 test results, serves them via nginx, and visualizes them in Grafana. Three Docker containers work together:

1. **nginx** (`test_nginx1.28`) — accepts `PUT` uploads of test result CSVs from CI, serves files via HTTP `GET`
2. **watcher** (`dt_watcher`) — Python daemon that watches for new CSV files and processes them
3. **grafana** (`dt_dashboards`) — visualizes test trends using the Infinity plugin to read CSVs

## Data Flow

```
CI/CD runner
  → PUT testResult.csv to nginx (port 9699)
    → /opt/catch2_data/details/sources/<timestamp>/testResult.csv

Python watcher (watches /data/details/sources/)
  → reads new testResult.csv
  → appends summary row (time,pass,total) to /data/catch2Result.csv
  → generates /data/details/html/report-<timestamp>.html

Grafana (port 9696)
  → reads /data/catch2Result.csv via nginx GET for trend chart
  → links to per-run HTML reports via nginx GET
```

## Shared Volume

Both nginx and watcher mount the same host path (`/home/kk/catch2_data/data`) as `/data` (watcher) and `/opt/catch2_data` + `/usr/share/nginx/html/data` (nginx). The grafana data directory is persisted via `~/grafana-data`.

## Starting the Stack

```bash
# 1. Start nginx (WebDAV PUT + static GET on port 9699)
bash build_script/build_nginx1.28.sh

# 2. Start watcher (Python file watcher + CSV/HTML generator)
bash build_script/build_watcher.sh

# 3. Start Grafana (on port 9696, admin password: admin)
bash build_script/build_grafana.sh
```

## Uploading Test Results (from CI)

```bash
# Upload a testResult.csv for a given run (timestamp becomes the run ID)
curl -u user:pass123 -T testResult.csv \
  http://localhost:9699/details/sources/<YYYY-MM-DD_HH-MM-SS>/testResult.csv
```

The `<YYYY-MM-DD_HH-MM-SS>` directory name is parsed as the test run timestamp by `resultSum.switchTime()`.

## Python App (`app/`)

- **`watch_new_files.py`** — entry point; polls `/data/details/sources/` every 2 seconds for new files, calls `resultSum` and `csv2html` for each
- **`resultSum.py`** — parses `testResult.csv` (counting `pass` in last column), appends to `/data/catch2Result.csv`, generates HTML
- **`csv2html.py`** — converts a `testResult.csv` into a self-contained HTML report with sorting, pagination, and pass/fail highlighting

Run the watcher locally (outside Docker) for development:
```bash
cd app
python3 watch_new_files.py
```

## CSV Formats

**`testResult.csv`** (per-run, uploaded by CI):
```
Num,module,binary,case,result
0,module/device,DeviceTest,txGetDevice_Basic,pass
```
`result` column values: `pass`, `failed`, `timeout`

**`catch2Result.csv`** (aggregated summary, read by Grafana):
```
time,pass,total
2025-09-15 10:14:21,30,40
```

## Grafana Plugin

The **Infinity** datasource plugin is required (supports CSV/JSON). For offline/VDI installs:
```bash
# Download and install offline
unzip yesoreyeram-infinity-datasource-3.3.0.zip -d /var/lib/grafana/plugins
chown -R grafana:grafana /var/lib/grafana/plugins
docker restart dt_dashboards
```

## Testing Data Injection

Use `test_data/auto.sh` to simulate 30 CI uploads:
```bash
bash test_data/auto.sh
```
