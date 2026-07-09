# grafana_v3.0 — Test Results Dashboard

Flask-based test results dashboard. Replaces Grafana with a custom web page showing a 10-day pivot table of (platform, os, arch) × date, with pass/fail badge coloring and click-through to failed test cases.

## Architecture

Single Docker container managed by supervisord:

```
supervisord
├── nginx     (8080)  WebDAV PUT — receives CI JSON uploads
├── watcher          polls /data/details/catch2/ every 2s → SQLite (per platform)
└── flask     (3000)  serves dashboard + /api/detail
```

Data layout on mounted volume:
```
/data/
  platforms/
    <platform>.db    ← one DB per platform, auto-created on first upload
  details/catch2/    ← CI upload directory
```

## Build & Run

> **Mirror:** The Dockerfile uses `mirrors.tuna.tsinghua.edu.cn` for both apt and pip to speed up builds in China.

```bash
# Build image
docker build -t dt_v3:1.0 .

# Run (dashboard on :9696, upload on :9698)
docker run -d --restart=always --name dt_v3 \
    -p 9696:3000 \
    -p 9698:8080 \
    -v /home/kk/catch2_data/data:/data \
    dt_v3:1.0
```

**Port mapping:** `-p <host_port>:<container_port>` — the container always uses `3000` (Flask) and `8080` (nginx). Only the host-side ports need to be free. Example with custom ports:

```bash
docker run -d --restart=always --name dt_v3 \
    -p 8080:3000 \
    -p 9000:8080 \
    -v /home/kk/catch2_data/data:/data \
    dt_v3:1.0
# Dashboard → http://<host>:8080
# Upload    → http://<host>:9000/details/...
```

**Verify processes:**
```bash
docker exec dt_v3 supervisorctl status
```

## Hot-update Files in Running Container

No rebuild needed for code changes — copy files directly into the running container:

```bash
# templates (no restart needed — Flask reads on every request)
docker cp app_web/templates/platform.html  dt_v3:/app_web/templates/platform.html
docker cp app_web/templates/index.html     dt_v3:/app_web/templates/index.html
docker cp app_web/templates/detail.html    dt_v3:/app_web/templates/detail.html

# web.py (restart Flask after copying)
docker cp app_web/web.py  dt_v3:/app_web/web.py
FLASK_PID=$(for p in $(docker exec dt_v3 ls /proc/ | grep -E '^[0-9]+$'); do \
  docker exec dt_v3 cat /proc/$p/cmdline 2>/dev/null | tr '\0' ' ' | grep -q web.py && echo $p; done)
docker exec dt_v3 python3 -c "import os,signal; os.kill($FLASK_PID, signal.SIGTERM)"
```

| Changed file | Action after `docker cp` |
|---|---|
| `*.html` template | None |
| `web.py` | Restart Flask (supervisord auto-restarts it) |

## Access Dashboard (WSL2)

On WSL2, use the WSL2 IP instead of localhost:

```
http://172.31.147.150:9696
```

To make `localhost` work permanently (Windows 11 22H2+), add to `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then restart WSL: `wsl --shutdown`

## CI Upload Format

Upload path: `PUT /details/<YYYY-MM-DD_HH-MM-SS>/testResult.json`

```bash
curl -u user:pass123 -X PUT \
  http://172.31.147.150:9698/details/2026-07-08_10-00-00/testResult.json \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "tx8",
    "os": "kylin",
    "arch": "amd64",
    "time": "2026-07-08 10:00:00",
    "summary": {"pass": 93, "total": 100},
    "results": [
      {"num": 1, "case": "TestFoo::bar", "result": "pass"},
      {"num": 2, "case": "TestFoo::baz", "result": "FAILED"}
    ]
  }'
```

Or upload a file directly:
```bash
curl -u user:pass123 -X PUT \
  http://172.31.147.150:9698/details/2026-07-08_10-00-00/testResult.json \
  -T result.json
```

Dashboard: **http://172.31.147.150:9696** (wait 2–3s after upload for watcher to process)

## Offline Deployment

```bash
# Export on build machine
docker export dt_v3 -o dt_v3_1.0.tar

# Load and run on target machine
docker import dt_v3_1.0.tar dt_v3:1.0
docker run -d --restart=always --name dt_v3 \
    -p 9696:3000 -p 9698:8080 \
    -v /your/data:/data \
    dt_v3:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

> **Note:** `docker export/import` drops CMD metadata — always specify the supervisord command explicitly on `docker run`.

## Timezone

All timestamps in the DB are stored as **UTC** (RFC3339, e.g. `2026-07-08T10:00:00Z`).

The dashboard converts to **CST (UTC+8)** at display time:
- Dashboard column headers (7月9日, 7月8日 ...) — Python uses `datetime.now(CST).date()`
- Pivot SQL date grouping — SQLite uses `date(time, '+8 hours')`
- Detail page run time — Jinja2 filter `utc_to_cst` converts on render

The JSON `time` field uploaded by CI should be in **local time (CST)** or any format parseable by Python's `datetime.fromisoformat`. The watcher appends `Z` to mark it as UTC when writing to the DB — ensure CI sends UTC time, not local time, to avoid double-offset.

## DB Schema

```sql
runs(id, time TEXT, platform TEXT, os TEXT, arch TEXT, pass INTEGER, total INTEGER)
test_cases(id, run_id → runs.id, num, module, binary, case_name, result TEXT)
```

One DB file per platform: `/data/platforms/<platform>.db` (persistent across restarts).
To reset a platform's history: `rm /data/platforms/<platform>.db`

## Credentials

nginx Basic Auth: `user` / `pass123` (hardcoded in Dockerfile — rebuild to change)
