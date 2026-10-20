"""Notifier extension point. v1 ships NoopNotifier."""
from __future__ import annotations

from .db import Run


class Notifier:
    def on_finish(self, run: Run) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NoopNotifier(Notifier):
    def on_finish(self, run: Run) -> None:
        return None
