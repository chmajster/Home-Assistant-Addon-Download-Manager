"""Persistent pause/resume gate for regular download workers."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
QUEUE_PAUSED_KEY = "queue_paused"


class PersistentQueueGate:
    """Pause new regular download workers and persist that operator decision."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self._condition = threading.Condition()
        self._paused = self._load_paused()

    def _load_paused(self) -> bool:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except OSError, json.JSONDecodeError:
            LOGGER.warning("Nie można odczytać trwałego stanu kolejki; uruchamiam kolejkę.")
            return False
        return bool(payload.get(QUEUE_PAUSED_KEY) is True) if isinstance(payload, dict) else False

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {QUEUE_PAUSED_KEY: self._paused}
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def wait_until_runnable(
        self,
        stop_event: threading.Event,
        shutdown_event: threading.Event,
    ) -> None:
        """Block while paused, but react promptly to stop and shutdown requests."""

        with self._condition:
            while self._paused and not stop_event.is_set() and not shutdown_event.is_set():
                self._condition.wait(timeout=0.25)

    @contextmanager
    def start_guard(self) -> Iterator[bool]:
        """Serialize pause changes with the final decision to start a regular job."""

        with self._condition:
            yield not self._paused

    def pause(self) -> None:
        with self._condition:
            if self._paused:
                return
            self._paused = True
            self._persist()

    def resume(self) -> None:
        with self._condition:
            if not self._paused:
                return
            self._paused = False
            self._persist()
            self._condition.notify_all()

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def snapshot(self, manager: Any) -> dict[str, Any]:
        jobs = manager.list_jobs()
        return {
            "paused": self.paused,
            "pending_regular_jobs": sum(
                1 for job in jobs if not job.is_live and job.status == "pending"
            ),
            "active_jobs": sum(1 for job in jobs if job.status in manager.ACTIVE_STATUSES),
            "max_concurrent_jobs": manager.max_concurrent_jobs,
        }
