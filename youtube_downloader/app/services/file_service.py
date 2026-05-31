"""Safe access to persistent downloaded files and JSON history."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class UnsafeFilenameError(ValueError):
    """Raised when a client-provided filename escapes the download folder."""


class FileService:
    """Manage persistent downloads without allowing arbitrary filesystem access."""

    def __init__(self, download_dir: Path, history_file: Path) -> None:
        self.download_dir = download_dir.resolve()
        self.history_file = history_file
        self._history_lock = threading.RLock()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self._write_history([])

    def resolve_download(self, filename: str, require_exists: bool = True) -> Path:
        """Resolve a basename inside download_dir and reject traversal."""

        if not filename or filename in {".", ".."} or Path(filename).name != filename:
            raise UnsafeFilenameError("Niepoprawna nazwa pliku.")
        candidate = (self.download_dir / filename).resolve()
        if candidate.parent != self.download_dir:
            raise UnsafeFilenameError("Niepoprawna ścieżka pliku.")
        if require_exists and not candidate.is_file():
            raise FileNotFoundError(filename)
        return candidate

    def is_managed_file(self, path: str | Path) -> bool:
        """Return true for files located directly in the configured download folder."""

        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        return resolved.parent == self.download_dir

    def list_files(self) -> list[dict[str, Any]]:
        """List downloadable files from persistent storage."""

        files: list[dict[str, Any]] = []
        for path in sorted(
            self.download_dir.iterdir(),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            if path.is_file() and not path.name.endswith((".part", ".ytdl")):
                stat = path.stat()
                files.append(
                    {
                        "filename": path.name,
                        "size": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, UTC
                        ).isoformat(),
                    }
                )
        return files

    def storage_usage(self) -> dict[str, int | float]:
        """Return filesystem capacity available to the configured download folder."""

        usage = shutil.disk_usage(self.download_dir)
        used_percent = (
            round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
        )
        free_percent = (
            round((usage.free / usage.total) * 100, 1) if usage.total else 0.0
        )
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "used_percent": used_percent,
            "free_percent": free_percent,
        }

    def delete_file(self, filename: str) -> None:
        """Delete one managed file and update history."""

        path = self.resolve_download(filename)
        path.unlink()
        self.mark_file_deleted(filename)
        LOGGER.info("Usunięto plik %s", filename)

    def history(self) -> list[dict[str, Any]]:
        """Load download history and enrich it with current file existence."""

        with self._history_lock:
            records = self._read_history()
        for record in records:
            filename = str(record.get("filename", ""))
            try:
                path = self.resolve_download(filename)
                record["file_exists"] = True
                record["size"] = path.stat().st_size
            except (FileNotFoundError, UnsafeFilenameError):
                record["file_exists"] = False
        return records

    def record_download(
        self, title: str, url: str, download_type: str, filename: str, status: str
    ) -> None:
        """Append a completed or partial output to persistent history."""

        path = self.resolve_download(filename)
        record = {
            "title": title,
            "url": url,
            "type": download_type,
            "filename": filename,
            "size": path.stat().st_size,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "status": status,
            "file_exists": True,
        }
        with self._history_lock:
            records = self._read_history()
            records.insert(0, record)
            self._write_history(records[:200])

    def mark_file_deleted(self, filename: str) -> None:
        """Persist deleted state for matching history records."""

        with self._history_lock:
            records = self._read_history()
            for record in records:
                if record.get("filename") == filename:
                    record["file_exists"] = False
            self._write_history(records)

    def _read_history(self) -> list[dict[str, Any]]:
        try:
            with self.history_file.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.error("Nie można odczytać historii: %s", error)
            return []

    def _write_history(self, records: list[dict[str, Any]]) -> None:
        temp_file = self.history_file.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as file_handle:
            json.dump(records, file_handle, ensure_ascii=False, indent=2)
        os.replace(temp_file, self.history_file)
