"""Integration tests for app/pipeline.py — uses fake git repo + fake commands."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.config import load_config
from app.db import Database
from app.locks import RunLock
from app.notifier import NoopNotifier
from app.pipeline import Pipeline


def _make_pipeline(tmp_path: Path, build_cmd: str, test_cmd: str,
                   repo_url: str, keep_runs: int = 3) -> Pipeline:
    """Build a Pipeline instance pointing at a fake repo."""
    config_yaml = f"""
timezone: Asia/Shanghai
defaults:
  clone_depth: 1
  build_timeout_sec: 30
  test_timeout_sec: 30
  keep_runs: {keep_runs}
projects:
  - name: test
    repo_url: {repo_url}
    branch: main
    cron: "0 0 * * *"
    workdir: ""
    build_cmd: {build_cmd!r}
    test_cmd: {test_cmd!r}
    env:
      CCACHE_DIR: /tmp/ccache
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(config_yaml)
    config = load_config(cfg_path)
    db = Database(tmp_path / "test.sqlite")
    lock = RunLock()
    notifier = NoopNotifier()
    return Pipeline(config=config, db=db, lock=lock, notifier=notifier,
                    data_dir=tmp_path / "data")


def _create_fake_repo(tmp_path: Path) -> str:
    """Create a bare git repo with a main branch, return file:// URL."""
    bare = tmp_path / "fake-repo.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    clone = tmp_path / "clone-for-commit"
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=clone, check=True, capture_output=True)
    (clone / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=clone,
                   check=True, capture_output=True)
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"],
                   cwd=str(bare), check=True, capture_output=True)
    shutil.rmtree(clone)
    return f"file://{bare.resolve()}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    run = pipeline.run("test", trigger="http")
    assert run.status == "success"
    assert run.build_exit == 0
    assert run.test_exit == 0
    assert run.commit_sha is not None
    assert run.finished_at is not None


def test_build_failure(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 3", "exit 0", url)
    run = pipeline.run("test", trigger="http")
    assert run.status == "failed"
    assert run.build_exit == 3
    assert run.test_exit is None  # test not run
    assert run.note == "build failed"


def test_test_failure(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 5", url)
    run = pipeline.run("test", trigger="http")
    assert run.status == "failed"
    assert run.build_exit == 0
    assert run.test_exit == 5
    assert run.note == "test failed"


def test_build_timeout(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "sleep 60", "exit 0", url)
    run = pipeline.run("test", trigger="http")
    assert run.status == "failed"
    assert run.build_exit == 124
    assert run.test_exit is None
    assert run.note == "build timeout"


def test_clone_failure(tmp_path):
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0",
                              "file:///nonexistent/repo.git")
    run = pipeline.run("test", trigger="http")
    assert run.status == "failed"
    assert run.note == "clone failed"
    assert run.build_exit is None
    assert run.test_exit is None


def test_concurrent_skipped(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    # Acquire the lock externally.
    pipeline.lock.try_acquire("blocker")
    run = pipeline.run("test", trigger="http")
    assert run.status == "skipped"
    assert run.note and "blocker" in run.note
    pipeline.lock.release()


def test_orphaned_runs_on_startup(tmp_path):
    """Simulate a crash: insert a 'running' row, then init a new Database."""
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    # Manually insert a running row.
    from app.db import Run
    pipeline.db.insert(Run(
        id="orphan-1", project="test", trigger="cli", status="running",
        started_at="2024-01-01T00:00:00+08:00", log_dir="/tmp/orphan",
    ))
    count = pipeline.db.mark_orphaned_runs()
    assert count == 1
    got = pipeline.db.get("orphan-1")
    assert got.status == "failed"
    assert got.note == "orphaned"


def test_log_rotation(tmp_path):
    """Run N times with keep_runs=2, verify only 2 log dirs remain."""
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url, keep_runs=2)
    import time
    for i in range(4):
        pipeline._now = lambda i=i: datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(seconds=3 - i)
        pipeline.run("test", trigger="http")
    runs_root = tmp_path / "data" / "runs"
    dirs = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("test-")]
    assert len(dirs) == 2


def test_log_files_written(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    run = pipeline.run("test", trigger="http")
    log_dir = Path(run.log_dir)
    assert (log_dir / "clone.log").is_file()
    assert (log_dir / "build.log").is_file()
    assert (log_dir / "test.log").is_file()
    assert (log_dir / "status.json").is_file()
    with open(log_dir / "status.json") as fh:
        data = json.load(fh)
    assert data["status"] == "success"


def test_status_json_mirrors_db(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    run = pipeline.run("test", trigger="http")
    with open(Path(run.log_dir) / "status.json") as fh:
        data = json.load(fh)
    assert data["id"] == run.id
    assert data["status"] == run.status


def test_unknown_project(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    with pytest.raises(ValueError, match="unknown project"):
        pipeline.run("nonexistent", trigger="http")


def test_different_triggers(tmp_path):
    url = _create_fake_repo(tmp_path)
    pipeline = _make_pipeline(tmp_path, "exit 0", "exit 0", url)
    triggers = ["http", "cli", "scheduled"]
    for i, trigger in enumerate(triggers):
        pipeline._now = lambda i=i: datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(seconds=2 - i)
        run = pipeline.run("test", trigger=trigger)
        assert run.trigger == trigger
        assert run.status == "success"