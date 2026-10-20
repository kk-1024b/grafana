"""YAML config loading + pydantic validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator, model_validator


class Defaults(BaseModel):
    clone_depth: int = 1
    build_timeout_sec: int = 3600
    test_timeout_sec: int = 1800
    keep_runs: int = 30


class Project(BaseModel):
    name: str = Field(min_length=1)
    repo_url: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    cron: str = Field(min_length=1)
    workdir: str = ""
    build_cmd: str = Field(min_length=1)
    test_cmd: str = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("cron")
    @classmethod
    def _cron_is_parseable(cls, v: str) -> str:
        CronTrigger.from_crontab(v)
        return v


class Config(BaseModel):
    timezone: str = "Asia/Shanghai"
    defaults: Defaults = Field(default_factory=Defaults)
    projects: list[Project] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_project_names(self) -> "Config":
        names = [p.name for p in self.projects]
        if len(names) != len(set(names)):
            raise ValueError("project names must be unique")
        return self

    def project(self, name: str) -> Project:
        for p in self.projects:
            if p.name == name:
                return p
        raise KeyError(name)


def load_config(path: str | Path) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh)
    return Config.model_validate(data)
