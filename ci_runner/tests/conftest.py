"""Shared fixtures for all test layers."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from app.config import Config, load_config
from app.db import Database
from app.locks import RunLock
from app.notifier import NoopNotifier


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

SAMPLE_YAML = """
timezone: Asia/Shanghai

defaults:
  clone_depth: 1
  build_timeout_sec: 60
  test_timeout_sec: 60
  keep_runs: 3

projects:
  - name: test_project
    repo_url: {repo_url}
    branch: main
    cron: "0 0 * * *"
    workdir: ""
    build_cmd: exit 0
    test_cmd: exit 0
    env:
      CCACHE_DIR: /tmp/ccache
"""


@pytest.fixture
def tmp_config(tmp_path: Path, fake_git_url: str) -> Path:
    """Write a temporary config.yaml pointing to a fake git repo."""
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_YAML.format(repo_url=fake_git_url))
    return path


@pytest.fixture
def loaded_config(tmp_config: Path) -> Config:
    return load_config(tmp_config)


# ---------------------------------------------------------------------------
# Fake git repository fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_git_url(tmp_path: Path) -> str:
    """Create a bare git repo with a 'main' branch and one commit.

    Returns a file:// URL suitable for ``repo_url`` in config.
    """
    bare = tmp_path / "fake-repo.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    # Clone, add a file, commit, push.
    clone = tmp_path / "clone-for-commit"
    subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=clone, check=True, capture_output=True)
    (clone / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=clone,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"},
    )
    subprocess.run(["git", "push", "origin", "main", "--set-upstream"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"],
                   cwd=str(bare), check=True, capture_output=True)
    shutil.rmtree(clone)
    return f"file://{bare.resolve()}"


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.sqlite")


@pytest.fixture
def in_memory_db() -> Database:
    """Using a real file under a tmpdir so the WAL doesn't interfere."""
    import tempfile as _tf
    f = _tf.NamedTemporaryFile(suffix=".sqlite", delete=False)
    f.close()
    d = Database(f.name)
    yield d
    os.unlink(f.name)


# ---------------------------------------------------------------------------
# Lock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def run_lock() -> RunLock:
    return RunLock()


# ---------------------------------------------------------------------------
# Pipeline fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_instance(loaded_config: Config, in_memory_db: Database, run_lock: RunLock, tmp_path: Path):
    from app.pipeline import Pipeline
    return Pipeline(
        config=loaded_config,
        db=in_memory_db,
        lock=run_lock,
        notifier=NoopNotifier(),
        data_dir=tmp_path / "data",
    )