"""SQLite schema + CRUD for run history."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id           TEXT PRIMARY KEY,
  project      TEXT NOT NULL,
  trigger      TEXT NOT NULL,
  status       TEXT NOT NULL,
  commit_sha   TEXT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  build_exit   INTEGER,
  test_exit    INTEGER,
  log_dir      TEXT NOT NULL,
  note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_project_started ON runs(project, started_at DESC);
"""


@dataclass
class Run:
    id: str
    project: str
    trigger: str
    status: str
    started_at: str
    log_dir: str
    commit_sha: Optional[str] = None
    finished_at: Optional[str] = None
    build_exit: Optional[int] = None
    test_exit: Optional[int] = None
    note: Optional[str] = None


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def insert(self, run: Run) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO runs (id, project, trigger, status, commit_sha,
                        started_at, finished_at, build_exit, test_exit, log_dir, note)
                   VALUES (:id,:project,:trigger,:status,:commit_sha,
                        :started_at,:finished_at,:build_exit,:test_exit,:log_dir,:note)""",
                asdict(run),
            )

    def update(self, run_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        params = {**fields, "id": run_id}
        with self._conn() as c:
            c.execute(f"UPDATE runs SET {cols} WHERE id = :id", params)

    def get(self, run_id: str) -> Optional[Run]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list(self, project: Optional[str] = None, limit: int = 20) -> list[Run]:
        sql = "SELECT * FROM runs"
        args: tuple = ()
        if project:
            sql += " WHERE project = ?"
            args = (project,)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_run(r) for r in rows]

    def latest_by_project(self) -> dict[str, Run]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT r.* FROM runs r
                   JOIN (SELECT project, MAX(started_at) AS m FROM runs GROUP BY project) g
                     ON r.project = g.project AND r.started_at = g.m"""
            ).fetchall()
        return {r["project"]: _row_to_run(r) for r in rows}

    def mark_orphaned_runs(self) -> int:
        """On startup, any status='running' row is a leftover from a crash."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE runs SET status = 'failed', note = 'orphaned' "
                "WHERE status = 'running'"
            )
            return cur.rowcount


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(**{k: row[k] for k in row.keys()})
