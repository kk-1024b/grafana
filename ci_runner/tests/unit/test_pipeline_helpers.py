"""Tests for helper functions in app/pipeline.py."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.pipeline import Pipeline, _git_head_sha


def test_generate_run_id(loaded_config, in_memory_db, run_lock, tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.notifier import NoopNotifier

    p = Pipeline(
        config=loaded_config,
        db=in_memory_db,
        lock=run_lock,
        notifier=NoopNotifier(),
        data_dir=tmp_path / "data",
    )
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    run_id = p._generate_run_id("my_project", now)
    assert run_id.startswith("my_project-")
    assert "T" in run_id


def test_git_head_sha(fake_git_url, tmp_path):
    """Clone the fake repo and verify HEAD SHA is readable."""
    repo = tmp_path / "cloned"
    subprocess.run(["git", "clone", fake_git_url, str(repo)], check=True, capture_output=True)
    sha = _git_head_sha(repo)
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_git_head_sha_not_a_repo(tmp_path):
    assert _git_head_sha(tmp_path) is None