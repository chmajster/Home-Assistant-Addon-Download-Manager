"""Safe access to persistent downloaded files and JSON history."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .error_messages import thumbnail_warning_message

LOGGER = logging.getLogger(__name__)
THUMBNAIL_DIRNAME = ".thumbnails"
VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
}


class UnsafeFilenameError(ValueError):
    """Raised when a client-provided filename escapes the download folder."""


@dataclass(frozen=True)
class ThumbnailResult:
    """Generated thumbnail basename and an optional non-fatal warning."""

    filename: str | None = None
    warning_message: str | None = None


class FileService:
    """Manage persistent downloads without allowing arbitrary filesystem access."""

    def __init__(self, download_dir: Path, history_file: Path) -> None:
        self.download_dir = download_dir.resolve()
        self.thumbnail_dir = self.download_dir / THUMBNAIL_DIRNAME
        self.history_file = history_file
        self._history_lock = threading.RLock()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
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

    def resolve_thumbnail(self, filename: str, require_exists: bool = True) -> Path:
        """Resolve a generated thumbnail basename inside its private folder."""

        if not filename or filename in {".", ".."} or Path(filename).name != filename:
            raise UnsafeFilenameError("Niepoprawna nazwa miniatury.")
        candidate = (self.thumbnail_dir / filename).resolve()
        if candidate.parent != self.thumbnail_dir:
            raise UnsafeFilenameError("Niepoprawna sciezka miniatury.")
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
        self.delete_thumbnail(filename)
        self.mark_file_deleted(filename)
        LOGGER.info("Usunięto plik %s", filename)

    def generate_thumbnail(self, filename: str) -> ThumbnailResult:
        """Create a JPG preview for a managed video file."""

        source = self.resolve_download(filename)
        if source.suffix.lower() not in VIDEO_EXTENSIONS:
            return ThumbnailResult()
        thumbnail = self.resolve_thumbnail(f"{source.name}.jpg", require_exists=False)
        temporary = self.resolve_thumbnail(
            f"{source.name}.{os.getpid()}.{threading.get_ident()}.tmp.jpg",
            require_exists=False,
        )
        try:
            error_message = ""
            for seek_seconds in ("1", None):
                temporary.unlink(missing_ok=True)
                command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
                if seek_seconds is not None:
                    command.extend(["-ss", seek_seconds])
                command.extend(
                    [
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=640:-2:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "3",
                        str(temporary),
                    ]
                )
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and temporary.is_file():
                    os.replace(temporary, thumbnail)
                    return ThumbnailResult(filename=thumbnail.name)
                error_message = result.stderr.strip()
            LOGGER.warning(
                "Nie mozna wygenerowac miniatury dla %s: %s",
                filename,
                error_message,
            )
            return ThumbnailResult(
                warning_message=thumbnail_warning_message(error_message)
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            LOGGER.warning(
                "Nie mozna wygenerowac miniatury dla %s: %s", filename, error
            )
            return ThumbnailResult(
                warning_message=thumbnail_warning_message(str(error))
            )
        finally:
            temporary.unlink(missing_ok=True)

    def delete_thumbnail(self, filename: str) -> None:
        """Remove a generated thumbnail associated with a managed download."""

        thumbnail = self.resolve_thumbnail(f"{filename}.jpg", require_exists=False)
        thumbnail.unlink(missing_ok=True)

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
            thumbnail_filename = record.get("thumbnail_filename")
            try:
                record["thumbnail_exists"] = bool(
                    thumbnail_filename
                    and self.resolve_thumbnail(str(thumbnail_filename)).is_file()
                )
            except (FileNotFoundError, UnsafeFilenameError):
                record["thumbnail_exists"] = False
        return records

    def record_download(
        self,
        title: str,
        url: str,
        download_type: str,
        filename: str,
        status: str,
        thumbnail_filename: str | None = None,
        format_id: str | None = None,
        warning_message: str | None = None,
        duration: int | None = None,
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
            "thumbnail_filename": thumbnail_filename,
            "format_id": format_id,
            "warning_message": warning_message,
            "duration": duration,
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

    def delete_history_record(self, filename: str, downloaded_at: str) -> bool:
        """Delete one matching history record without removing its downloaded file."""

        with self._history_lock:
            records = self._read_history()
            for index, record in enumerate(records):
                if (
                    record.get("filename") == filename
                    and record.get("downloaded_at") == downloaded_at
                ):
                    del records[index]
                    self._write_history(records)
                    LOGGER.info("Usunięto wpis historii dla pliku %s", filename)
                    return True
        return False

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
