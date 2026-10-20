"""FastAPI application entry point — starts APScheduler and serves HTTP.

Module-level bootstrap is lazy: calling ``_init_app()`` (once) sets up the
singletons.  In production, uvicorn triggers this via the lifespan context.
In tests, override the singletons directly after importing ``app.main``.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from zoneinfo import ZoneInfo

from .config import load_config
from .db import Database
from .locks import RunLock
from .notifier import NoopNotifier
from .pipeline import Pipeline

logger = logging.getLogger(__name__)

# Lazy-initialised singletons (set by _init_app or overridden by tests).
config = None
db = None
lock = None
notifier = None
pipeline = None
scheduler = None


def _init_app() -> None:
    """Load config, connect DB, start scheduler. Idempotent."""
    global config, db, lock, notifier, pipeline, scheduler
    if config is not None:
        return  # already initialised

    cfg_path = Path(os.environ.get("CONFIG_PATH", "/app/config/config.yaml"))
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    db_path = data_dir / "db.sqlite"

    config = load_config(cfg_path)
    db = Database(db_path)

    orphaned = db.mark_orphaned_runs()
    if orphaned:
        logger.info("marked %d orphaned run(s) as failed", orphaned)

    lock = RunLock()
    notifier = NoopNotifier()
    pipeline = Pipeline(config=config, db=db, lock=lock, notifier=notifier, data_dir=data_dir)

    scheduler = BackgroundScheduler(timezone=ZoneInfo(config.timezone))
    for project in config.projects:
        scheduler.add_job(
            pipeline.run,
            trigger=CronTrigger.from_crontab(project.cron, timezone=config.timezone),
            args=[project.name, "scheduled"],
            id=f"cron-{project.name}",
            replace_existing=True,
            name=f"cron-{project.name}",
            misfire_grace_time=300,
        )
        logger.info("scheduled cron job for %s: %s", project.name, project.cron)
    scheduler.start()


def _shutdown_app() -> None:
    """Shut down the scheduler cleanly."""
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# FastAPI — lifespan context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_app()
    try:
        yield
    finally:
        _shutdown_app()


app = FastAPI(title="ci_runner", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/projects")
def list_projects():
    db_ = db
    config_ = config
    latest = db_.latest_by_project()
    result = []
    for p in config_.projects:
        info = {"name": p.name, "cron": p.cron, "branch": p.branch}
        last = latest.get(p.name)
        if last:
            info["last_run"] = {
                "id": last.id,
                "status": last.status,
                "started_at": last.started_at,
                "duration": _duration(last),
            }
        result.append(info)
    return result


@app.post("/projects/{name}/run")
def trigger_run(name: str):
    try:
        run = pipeline.run(name, trigger="http")
    except ValueError as e:
        raise HTTPException(404, str(e))

    if run.status == "skipped":
        raise HTTPException(
            409,
            detail={
                "run_id": run.id,
                "status": run.status,
                "note": run.note,
            },
        )
    return {"run_id": run.id, "status": run.status, "note": run.note}


@app.get("/runs")
def list_runs(project: str | None = None, limit: int = 20):
    return [
        {
            "id": r.id,
            "project": r.project,
            "trigger": r.trigger,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "build_exit": r.build_exit,
            "test_exit": r.test_exit,
            "note": r.note,
        }
        for r in db.list(project=project, limit=limit)
    ]


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    row = db.get(run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return {
        "id": row.id,
        "project": row.project,
        "trigger": row.trigger,
        "status": row.status,
        "commit_sha": row.commit_sha,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "build_exit": row.build_exit,
        "test_exit": row.test_exit,
        "log_dir": row.log_dir,
        "note": row.note,
    }


@app.get("/runs/{run_id}/log/{log_name}")
def get_run_log(run_id: str, log_name: str):
    if log_name not in ("clone", "build", "test"):
        raise HTTPException(400, "log_name must be clone/build/test")

    row = db.get(run_id)
    if not row:
        raise HTTPException(404, "run not found")

    log_path = Path(row.log_dir) / f"{log_name}.log"
    if not log_path.is_file():
        raise HTTPException(404, "log not found")

    def _stream():
        with open(log_path, "rb") as fh:
            yield from fh

    return StreamingResponse(_stream(), media_type="text/plain")


def _duration(run) -> str | None:
    if run.started_at and run.finished_at:
        try:
            from datetime import datetime as dt

            s = dt.fromisoformat(run.started_at)
            f = dt.fromisoformat(run.finished_at)
            return str(f - s)
        except Exception:
            pass
    return None