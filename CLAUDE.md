# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Monorepo for a CI test-results pipeline ("001_my_framework") with two roles:

- **CI runner** (`ci_runner/`) — a Docker-scheduled FastAPI service that clones from GitLab, builds, and runs tests.
- **Results dashboard** (`grafana_*`) — receives test-result JSON over HTTP and renders pass/fail trends.

The `grafana_*` directories are successive versions of the *same* dashboard, kept for reference — not three things running at once. Only one is active:

| Directory | Status | Dashboard | Data format |
|---|---|---|---|
| `grafana_v3.0/` | **active** | Self-written Flask (`app_web/web.py`) | JSON only, one SQLite DB per platform |
| `grafana_v2.0/` | previous | Grafana + `frser-sqlite-datasource` | CSV + JSON, single DB, plus benchmark module |
| `grafana_nginx/` | earliest | Grafana + Infinity plugin, 3 containers | CSV + static HTML |

Active development is in **`grafana_v3.0/`**; `ci_runner/` is a separate, self-contained system. They are loosely coupled today — `ci_runner`'s notifier is a `NoopNotifier`, so the upload to the dashboard is not wired in code.

## Where to Start Reading

- `grafana_v3.0/CLAUDE.md` — build, run, hot-update (`docker cp`), tests, timezone, DB schema.
- `grafana_v3.0/docs/diff.md` — v2.0 → v3.0 changes (why Grafana was dropped, JSON-only, multi-platform).
- `grafana_v3.0/docs/system-design.md` — full data flow and Flask routes.
- `ci_runner/README.md` + `ci_runner/ci_runner-ci-usage.md` — CI runner usage, config, extension points.
- `grafana_v2.0/CLAUDE.md`, `grafana_nginx/CLAUDE.md` — reference for the older designs.

## Cross-Cutting Conventions

- **Everything ships as a Docker image** — the dashboards run one container under `supervisord`; `ci_runner` uses `docker compose`.
- **UTC storage, CST (UTC+8) display** — timestamps stored as RFC3339 UTC (`...Z`), converted only at render time: SQLite `date(time,'+8 hours')`, Python `datetime.now(CST)`, Jinja filter `utc_to_cst`.
- **nginx Basic Auth is hardcoded `user:pass123`** in each dashboard Dockerfile — changing it requires a rebuild.
- **Offline deployment** uses `docker export` / `docker import`, which drops the image `CMD` — `docker run` must re-specify the supervisord command explicitly.
- **China mirrors** (`mirrors.tuna.tsinghua.edu.cn`) are used in the Dockerfiles for apt/pip.
- **On WSL2**, reach containers via the WSL2 IP (e.g. `http://172.31.147.150:9696`), not `localhost`, unless `networkingMode=mirrored` is set in `%USERPROFILE%\.wslconfig`.

## Git Conventions

Single repo, one branch (`main`). Commit messages are prefixed with the subsystem they touch, e.g. `[grafana_v3.0] fix: ...`, `[grafana_v2.0] feat: ...`. Match the directory you're changing.

## ci_runner Architecture (the only subsystem without its own CLAUDE.md)

FastAPI + APScheduler app in `ci_runner/app/`:

- `main.py` — FastAPI routes; lazy `_init_app()` sets up singletons; tests override them directly after import.
- `pipeline.py` — `Pipeline.run()` is the single entry point all three triggers (cron / HTTP / CLI) converge on.
- `db.py` — SQLite (`data/db.sqlite`) run metadata. `config.py` — YAML config. `locks.py` — non-blocking run lock. `notifier.py` — `NoopNotifier` (extension point). `cli.py` — `docker exec` CLI.

Dev/test:

```bash
cd ci_runner
source .venv/bin/activate
pytest tests/unit tests/integration tests/e2e -v
```

Tests are split three ways: `unit` (fast), `integration` (fake git repo + fake commands), `e2e` (HTTP/CLI). No real GitLab or C++ build needed.
