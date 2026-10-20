"""run_pipeline() — the single entry point all three triggers converge on."""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Config, Project
from .db import Database, Run
from .locks import RunLock
from .notifier import Notifier

logger = logging.getLogger(__name__)

# Unix convention for timeout exit code.
TIMEOUT_EXIT = 124


class Pipeline:
    def __init__(
        self,
        config: Config,
        db: Database,
        lock: RunLock,
        notifier: Notifier,
        data_dir: Path,
    ) -> None:
        self.config = config
        self.db = db
        self.lock = lock
        self.notifier = notifier
        self.data_dir = data_dir
        self.tz = ZoneInfo(config.timezone)

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _generate_run_id(self, project: str, now: datetime) -> str:
        return f"{project}-{now.strftime('%Y-%m-%dT%H-%M-%S')}"

    def run(self, project_name: str, trigger: str) -> Run:
        """Trigger a pipeline run. Returns the resulting Run row.

        If another run is in progress, records a 'skipped' row and returns it
        (rather than raising) so scheduled triggers don't crash APScheduler.
        """
        try:
            project = self.config.project(project_name)
        except KeyError:
            raise ValueError(f"unknown project: {project_name}")

        now = self._now()
        run_id = self._generate_run_id(project_name, now)
        log_dir = self.data_dir / "runs" / run_id
        started_at = now.isoformat()

        with self.lock.acquired(run_id) as got:
            if not got:
                blocker = self.lock.current()
                run = Run(
                    id=run_id,
                    project=project_name,
                    trigger=trigger,
                    status="skipped",
                    started_at=started_at,
                    finished_at=started_at,
                    log_dir=str(log_dir),
                    note=f"skipped: another run in progress ({blocker})",
                )
                self.db.insert(run)
                return run

            log_dir.mkdir(parents=True, exist_ok=True)
            run = Run(
                id=run_id,
                project=project_name,
                trigger=trigger,
                status="running",
                started_at=started_at,
                log_dir=str(log_dir),
            )
            self.db.insert(run)

            tmp_clone = Path(tempfile.mkdtemp(prefix=f"ci_runner-{project_name}-"))
            try:
                self._execute(project, run, log_dir, tmp_clone)
            except Exception:
                logger.exception("pipeline crashed for run %s", run_id)
                run.status = "failed"
                if not run.note:
                    run.note = "pipeline crashed"
            finally:
                run.finished_at = self._now().isoformat()
                self._finalize(run, log_dir)
                shutil.rmtree(tmp_clone, ignore_errors=True)
                try:
                    self.notifier.on_finish(run)
                except Exception:
                    logger.exception("notifier raised (swallowed)")
                self._rotate_old_runs(project_name, self.config.defaults.keep_runs)

            return run

    def _execute(self, project: Project, run: Run, log_dir: Path, tmp: Path) -> None:
        clone_rc = self._clone(project, tmp, log_dir / "clone.log")
        if clone_rc != 0:
            run.status = "failed"
            run.note = "clone failed"
            return

        run.commit_sha = _git_head_sha(tmp)

        work = tmp / project.workdir if project.workdir else tmp
        env = {**os.environ, **project.env}

        build_rc = self._spawn(
            project.build_cmd,
            work,
            env,
            self.config.defaults.build_timeout_sec,
            log_dir / "build.log",
        )
        run.build_exit = build_rc
        if build_rc != 0:
            run.status = "failed"
            run.note = "build timeout" if build_rc == TIMEOUT_EXIT else "build failed"
            return

        test_rc = self._spawn(
            project.test_cmd,
            work,
            env,
            self.config.defaults.test_timeout_sec,
            log_dir / "test.log",
        )
        run.test_exit = test_rc
        if test_rc == 0:
            run.status = "success"
        else:
            run.status = "failed"
            run.note = "test timeout" if test_rc == TIMEOUT_EXIT else "test failed"

    def _clone(self, project: Project, dest: Path, log_path: Path) -> int:
        cmd = [
            "git",
            "clone",
            "--depth",
            str(self.config.defaults.clone_depth),
            "-b",
            project.branch,
            project.repo_url,
            str(dest),
        ]
        with open(log_path, "wb") as log:
            log.write(f"$ {' '.join(cmd)}\n".encode())
            log.flush()
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        return proc.returncode

    def _spawn(
        self,
        cmd: str,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        log_path: Path,
    ) -> int:
        """Run a shell command in its own process group; kill the group on timeout."""
        with open(log_path, "wb") as log:
            log.write(f"$ (in {cwd})\n{cmd}\n\n".encode())
            log.flush()
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(cwd),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if sys.platform != "win32" else None,
            )
            try:
                return proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                log.write(b"\n[TIMEOUT] process group killed\n")
                return TIMEOUT_EXIT

    def _finalize(self, run: Run, log_dir: Path) -> None:
        self.db.update(
            run.id,
            status=run.status,
            commit_sha=run.commit_sha,
            finished_at=run.finished_at,
            build_exit=run.build_exit,
            test_exit=run.test_exit,
            note=run.note,
        )
        try:
            status_path = log_dir / "status.json"
            with open(status_path, "w", encoding="utf-8") as fh:
                json.dump(asdict(run), fh, indent=2, ensure_ascii=False)
        except OSError:
            logger.exception("failed to write status.json for %s", run.id)

    def _rotate_old_runs(self, project: str, keep: int) -> None:
        runs_root = self.data_dir / "runs"
        if not runs_root.is_dir():
            return
        prefix = f"{project}-"
        dirs = sorted(
            (p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in dirs[keep:]:
            shutil.rmtree(old, ignore_errors=True)


def _git_head_sha(repo: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
