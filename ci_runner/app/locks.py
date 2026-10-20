"""Global non-blocking lock: only one pipeline run at a time."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional


class RunLock:
    """Single global lock, non-blocking acquire.

    Also tracks the currently-running run_id so a rejected caller can know
    what's blocking them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_run_id: Optional[str] = None
        self._meta_lock = threading.Lock()

    def try_acquire(self, run_id: str) -> bool:
        got = self._lock.acquire(blocking=False)
        if got:
            with self._meta_lock:
                self._current_run_id = run_id
        return got

    def release(self) -> None:
        with self._meta_lock:
            self._current_run_id = None
        self._lock.release()

    def current(self) -> Optional[str]:
        with self._meta_lock:
            return self._current_run_id

    @contextmanager
    def acquired(self, run_id: str) -> Iterator[bool]:
        got = self.try_acquire(run_id)
        try:
            yield got
        finally:
            if got:
                self.release()
