"""E2E tests via FastAPI TestClient + CLI subprocess."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.db import Database
from app.locks import RunLock
from app.notifier import NoopNotifier
from app.pipeline import Pipeline


def _create_fake_repo(tmp_path: Path) -> str:
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


@pytest.fixture
def pipeline_and_client(tmp_path, monkeypatch):
    """Create a pipeline + TestClient, monkey-patching app.main globals."""
    url = _create_fake_repo(tmp_path)
    config_yaml = f"""
timezone: Asia/Shanghai
defaults:
  clone_depth: 1
  build_timeout_sec: 30
  test_timeout_sec: 30
  keep_runs: 3
projects:
  - name: test
    repo_url: {url}
    branch: main
    cron: "0 0 * * *"
    workdir: ""
    build_cmd: exit 0
    test_cmd: exit 0
    env:
      CCACHE_DIR: /tmp/ccache
"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(config_yaml)
    config = load_config(cfg_path)
    db = Database(tmp_path / "test.sqlite")
    lock = RunLock()
    notifier = NoopNotifier()
    pipeline = Pipeline(config=config, db=db, lock=lock, notifier=notifier,
                        data_dir=tmp_path / "data")

    # Import app.main — it no longer auto-initialises singletons.
    import app.main as m
    # Override the lazy singletons with our test instances.
    m.config = config
    m.db = db
    m.lock = lock
    m.notifier = notifier
    m.pipeline = pipeline

    client = TestClient(m.app)
    return pipeline, client, db


# ---------------------------------------------------------------------------
# HTTP tests
# ---------------------------------------------------------------------------

class TestHTTP:
    def test_healthz(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_trigger_and_poll(self, pipeline_and_client):
        _, client, db = pipeline_and_client
        resp = client.post("/projects/test/run")
        assert resp.status_code == 200
        data = resp.json()
        run_id = data["run_id"]
        # The pipeline runs synchronously in the same thread, so by the time
        # the HTTP response is returned the run is already finished.
        assert data["status"] in ("running", "success")

        # Poll until done.
        import time
        for _ in range(10):
            time.sleep(0.3)
            r = client.get(f"/runs/{run_id}")
            if r.json()["status"] in ("success", "failed"):
                break
        meta = r.json()
        assert meta["status"] == "success"
        assert meta["build_exit"] == 0
        assert meta["test_exit"] == 0

    def test_trigger_unknown_project(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.post("/projects/nonexistent/run")
        assert resp.status_code == 404

    def test_concurrent_409(self, pipeline_and_client):
        pipeline, client, _ = pipeline_and_client
        # Lock first.
        pipeline.lock.try_acquire("blocker")
        resp = client.post("/projects/test/run")
        assert resp.status_code == 409
        assert resp.json()["detail"]["status"] == "skipped"
        pipeline.lock.release()

    def test_list_runs(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_projects(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.get("/projects")
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["name"] == "test"

    def test_get_run_log(self, pipeline_and_client):
        pipeline, client, _ = pipeline_and_client
        run = pipeline.run("test", trigger="http")
        for log_name in ("clone", "build", "test"):
            resp = client.get(f"/runs/{run.id}/log/{log_name}")
            assert resp.status_code == 200

    def test_get_run_log_not_found(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.get("/runs/nonexistent/log/build")
        assert resp.status_code == 404

    def test_get_run_log_invalid_name(self, pipeline_and_client):
        _, client, _ = pipeline_and_client
        resp = client.get("/runs/some-id/log/invalid")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_run_unknown_project(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "run", "nonexistent"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent.parent,
        )
        # CLI tries to connect to localhost, which won't be running.
        assert result.returncode == 3

    def test_cli_list(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "list"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent.parent,
        )
        # No server running, so connection error.
        assert result.returncode == 3

    def test_cli_no_args(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 2

    def test_cli_help_via_unknown_command(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "unknown"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 2