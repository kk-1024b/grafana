"""Tests for app/db.py."""
from __future__ import annotations

from app.db import Database, Run


def test_insert_and_get(in_memory_db: Database):
    run = Run(id="p-2024-01-01T00-00-00", project="p", trigger="scheduled",
              status="running", started_at="2024-01-01T00:00:00+08:00",
              log_dir="/tmp/runs/p-2024-01-01T00-00-00")
    in_memory_db.insert(run)
    got = in_memory_db.get(run.id)
    assert got is not None
    assert got.status == "running"
    assert got.project == "p"


def test_update(in_memory_db: Database):
    run = Run(id="p-2024-01-01T00-00-00", project="p", trigger="scheduled",
              status="running", started_at="2024-01-01T00:00:00+08:00",
              log_dir="/tmp/runs/p-2024-01-01T00-00-00")
    in_memory_db.insert(run)
    in_memory_db.update(run.id, status="success", build_exit=0, test_exit=0)
    got = in_memory_db.get(run.id)
    assert got.status == "success"
    assert got.build_exit == 0
    assert got.test_exit == 0


def test_list(in_memory_db: Database):
    for i in range(5):
        run = Run(id=f"p-2024-01-01T00-00-{i:02d}", project="p", trigger="cli",
                  status="success", started_at=f"2024-01-01T00:00:0{i}+08:00",
                  log_dir=f"/tmp/runs/p-2024-01-01T00-00-{i:02d}")
        in_memory_db.insert(run)
    rows = in_memory_db.list(limit=3)
    assert len(rows) == 3
    # Latest first.
    dates = [r.started_at for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_list_filter_project(in_memory_db: Database):
    for p in ("a", "b"):
        run = Run(id=f"{p}-1", project=p, trigger="http", status="failed",
                  started_at="2024-01-01T00:00:00+08:00", log_dir=f"/tmp/runs/{p}-1")
        in_memory_db.insert(run)
    rows = in_memory_db.list(project="a")
    assert len(rows) == 1
    assert rows[0].project == "a"


def test_latest_by_project(in_memory_db: Database):
    for i, status in enumerate(["running", "success", "failed"]):
        run = Run(id=f"p-{i}", project="p", trigger="http", status=status,
                  started_at=f"2024-01-01T00:00:0{i}+08:00", log_dir=f"/tmp/runs/p-{i}")
        in_memory_db.insert(run)
    latest = in_memory_db.latest_by_project()
    assert latest["p"].status == "failed"


def test_mark_orphaned_runs(in_memory_db: Database):
    run = Run(id="p-1", project="p", trigger="scheduled", status="running",
              started_at="2024-01-01T00:00:00+08:00", log_dir="/tmp/runs/p-1")
    in_memory_db.insert(run)
    count = in_memory_db.mark_orphaned_runs()
    assert count == 1
    got = in_memory_db.get("p-1")
    assert got.status == "failed"
    assert got.note == "orphaned"


def test_get_nonexistent(in_memory_db: Database):
    assert in_memory_db.get("nonexistent") is None