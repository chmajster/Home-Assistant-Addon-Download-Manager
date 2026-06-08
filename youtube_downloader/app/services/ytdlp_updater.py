"""Keep yt-dlp fresh while the add-on is running."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(hours=24)
BACKGROUND_POLL_SECONDS = 60 * 60


class YtDlpUpdater:
    """Update yt-dlp at most once per configured interval, retrying failures."""

    def __init__(
        self,
        state_file: Path,
        *,
        update_interval: timedelta = UPDATE_INTERVAL,
        background_poll_seconds: int = BACKGROUND_POLL_SECONDS,
        command: list[str] | None = None,
    ) -> None:
        self.state_file = state_file
        self.update_interval = update_interval
        self.background_poll_seconds = background_poll_seconds
        self.command = command or [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--retries",
            "3",
            "--timeout",
            "20",
            "--upgrade",
            "yt-dlp",
        ]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start_background(self) -> None:
        """Start a lightweight periodic updater thread."""

        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._background_loop,
            name="yt-dlp-updater",
            daemon=True,
        )
        self._thread.start()

    def ensure_recent(self) -> bool:
        """Update yt-dlp if the last successful update is stale or failed."""

        with self._lock:
            state = self._read_state()
            if not self._needs_update(state):
                return True
            LOGGER.info("Aktualizuję yt-dlp do najnowszej wersji...")
            try:
                result = subprocess.run(
                    self.command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                LOGGER.warning("Aktualizacja yt-dlp nie powiodła się: %s", error)
                updated = {
                    **state,
                    "last_attempt": self._now(),
                    "last_error": str(error),
                }
                self._write_state(updated)
                return False
            if result.returncode == 0:
                LOGGER.info("yt-dlp został zaktualizowany.")
                updated_at = self._now()
                self._write_state(
                    {"last_attempt": updated_at, "last_success": updated_at}
                )
                self._invalidate_yt_dlp_imports()
                return True

            error = (result.stderr or result.stdout or "").strip()
            LOGGER.warning(
                "Aktualizacja yt-dlp nie powiodła się: %s",
                error or result.returncode,
            )
            updated = {**state, "last_attempt": self._now(), "last_error": error}
            self._write_state(updated)
            return False

    def _background_loop(self) -> None:
        while not self._stop.wait(self.background_poll_seconds):
            try:
                self.ensure_recent()
            except Exception:
                LOGGER.exception("Nieoczekiwany błąd okresowej aktualizacji yt-dlp")

    def _needs_update(self, state: dict[str, Any]) -> bool:
        last_success = self._parse_time(state.get("last_success"))
        last_attempt = self._parse_time(state.get("last_attempt"))
        if not last_success:
            return True
        if last_attempt and last_attempt > last_success:
            return True
        return datetime.now(UTC) - last_success >= self.update_interval

    def _read_state(self) -> dict[str, Any]:
        try:
            with self.state_file.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file_handle:
            json.dump(state, file_handle, ensure_ascii=False, indent=2)
        os.replace(temporary, self.state_file)

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _invalidate_yt_dlp_imports() -> None:
        for module_name in list(sys.modules):
            if module_name == "yt_dlp" or module_name.startswith("yt_dlp."):
                del sys.modules[module_name]
