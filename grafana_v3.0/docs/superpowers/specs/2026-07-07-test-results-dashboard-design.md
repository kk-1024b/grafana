# Test Results Dashboard — Design Spec (v3.0)

Date: 2026-07-07

## Overview

Replace Grafana with a custom Flask web page inside the existing Docker container. The page displays a pivot table: rows are `(platform, os, arch)` combinations; columns are the last 10 days. Each cell shows `pass/total` as a colored badge. Clicking a badge opens a modal with the list of failed test cases for that run.

---

## Architecture

Single Docker container, supervisord manages three processes:

```
supervisord
├── nginx        port 8080  WebDAV PUT — receives CI JSON uploads
├── python       watch_files.py — polls directory, parses JSON → SQLite
└── flask        web.py, port 3000 — serves dashboard + /api/detail
```

Flask replaces Grafana. The Grafana install and frser-sqlite-datasource plugin are removed from the Dockerfile.

---

## DB Schema

```sql
CREATE TABLE runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    time     TEXT    NOT NULL,
    platform TEXT    NOT NULL,
    os       TEXT    NOT NULL,
    arch     TEXT    NOT NULL,
    pass     INTEGER NOT NULL,
    total    INTEGER NOT NULL
);

CREATE TABLE test_cases (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id),
    num       INTEGER,
    module    TEXT,
    binary    TEXT,
    case_name TEXT,
    result    TEXT
);
```

Changes from v2.0: `runs` gains `platform`, `os`, `arch` columns.

---

## Data Flow

### CI Upload

```
PUT /details/<timestamp>/testResult.json
Example: PUT /details/2026-07-07_10-00-00/testResult.json
```

### JSON Format

```json
{
  "platform": "tx8",
  "os": "kylin",
  "arch": "amd64",
  "time": "2026-07-07 10:00:00",
  "summary": { "pass": 93, "total": 100 },
  "results": [
    { "num": 1, "case": "TestFoo::bar", "result": "pass" },
    { "num": 2, "case": "TestFoo::baz", "result": "FAILED" }
  ]
}
```

`platform`, `os`, `arch` are new fields added to the existing v2.0 JSON structure.

### Watcher

`app_catch2/watch_catch2_files.py` detects new `.json` files. `resultSum.getTestResultFromJson` is extended to also read `platform`, `os`, `arch` from the JSON. `db.insert_run` gains these three parameters.

---

## Flask Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Pivot table page (last 10 days) |
| `/api/detail` | GET | `?run_id=<id>` → JSON list of failed cases |

### Pivot SQL

When there are multiple runs per `(platform, os, arch, day)`, the one with the latest `time` is used. A join against the per-group latest-time subquery ensures `run_id` and `pass/total` always come from the same row.

```sql
SELECT r.platform, r.os, r.arch,
  MAX(CASE WHEN date(r.time)=date('now','-9 day') THEN r.id END) AS d9_id,
  MAX(CASE WHEN date(r.time)=date('now','-9 day') THEN r.pass||'/'||r.total END) AS d9,
  -- d8 .. d1 same pattern --
  MAX(CASE WHEN date(r.time)=date('now') THEN r.id END) AS d0_id,
  MAX(CASE WHEN date(r.time)=date('now') THEN r.pass||'/'||r.total END) AS d0
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
```

### Detail SQL

```sql
SELECT case_name, result
FROM test_cases
WHERE run_id = ? AND result != 'pass'
ORDER BY num
```

---

## UI

- **Row grouping**: rows are visually grouped by `(platform, os)`. Each group gets a distinct background color (cycling through a palette). Row background is set per group, not per row.
- **Badge colors**: per-cell pass-rate thresholds:
  - Green: `pass/total >= 0.95`
  - Yellow: `0.90 <= pass/total < 0.95`
  - Red: `pass/total < 0.90`
  - Gray (`—`): no data for that day
- **Today column**: rightmost column, header marked with ✦, badges have a subtle blue outline.
- **Modal**: clicking any badge sends `GET /api/detail?run_id=<id>` via `fetch()`. Response renders a list of failed `case_name` values inside a modal overlay. Clicking outside the modal closes it.
- **No auto-refresh**.

---

## File Changes

| Action | File | Change |
|---|---|---|
| New | `app_web/web.py` | Flask app (pivot route + API route) |
| New | `app_web/templates/index.html` | Jinja2 table template + modal JS |
| Modify | `app_catch2/db.py` | Add `platform/os/arch` to `insert_run()` and `init_db()` |
| Modify | `app_catch2/resultSum.py` | Read `platform/os/arch` from JSON in `getTestResultFromJson` |
| Modify | `conf/supervisord.conf` | Replace `grafana-server` entry with `flask run` |
| Modify | `Dockerfile` | Replace Grafana install + plugin with Flask (`pip install flask`); `COPY app_web/ /app_web/` |
