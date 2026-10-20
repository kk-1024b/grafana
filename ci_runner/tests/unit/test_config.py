"""Tests for app/config.py."""
from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from app.config import Config, load_config


def test_valid_config(tmp_path):
    cfg = {
        "timezone": "Asia/Shanghai",
        "defaults": {"clone_depth": 2, "keep_runs": 10},
        "projects": [{"name": "p1", "repo_url": "git@x:y.git", "branch": "main",
                       "cron": "0 0 * * *", "build_cmd": "make", "test_cmd": "ctest"}],
    }
    path = tmp_path / "c.yaml"
    path.write_text(yaml.dump(cfg))
    c = load_config(path)
    assert c.timezone == "Asia/Shanghai"
    assert c.defaults.clone_depth == 2
    assert len(c.projects) == 1


def test_duplicate_project_names(tmp_path):
    cfg = {
        "projects": [
            {"name": "dup", "repo_url": "a", "branch": "m", "cron": "0 * * * *",
             "build_cmd": "m", "test_cmd": "t"},
            {"name": "dup", "repo_url": "b", "branch": "m", "cron": "0 * * * *",
             "build_cmd": "m", "test_cmd": "t"},
        ]
    }
    with pytest.raises(ValidationError, match="unique"):
        Config.model_validate(cfg)


def test_invalid_cron(tmp_path):
    with pytest.raises(ValidationError):
        Config.model_validate({
            "projects": [{"name": "p", "repo_url": "a", "branch": "m",
                           "cron": "not-a-cron", "build_cmd": "m", "test_cmd": "t"}]
        })


def test_project_lookup(loaded_config):
    p = loaded_config.project("test_project")
    assert p.name == "test_project"

    with pytest.raises(KeyError):
        loaded_config.project("nonexistent")


def test_defaults_are_applied(tmp_path):
    cfg = {
        "projects": [{"name": "p", "repo_url": "a", "branch": "m",
                       "cron": "0 * * * *", "build_cmd": "m", "test_cmd": "t"}],
    }
    c = Config.model_validate(cfg)
    assert c.defaults.clone_depth == 1
    assert c.defaults.build_timeout_sec == 3600
    assert c.defaults.keep_runs == 30


def test_empty_projects():
    c = Config.model_validate({})
    assert c.projects == []
    assert c.timezone == "Asia/Shanghai"