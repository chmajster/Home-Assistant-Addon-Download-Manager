"""Safe access to persistent downloaded files and download history."""

from __future__ import annotations

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
from .state_store import SQLiteStateStore

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
MAX_HISTORY_TAGS = 20
MAX_HISTORY_TAG_LENGTH = 40


class UnsafeFilenameError(ValueError):
    """Raised when a client-provided filename escapes the download folder."""


def normalize_history_tags(tags: object) -> list[str]:
    """Return a compact, duplicate-free list of manually assigned tags."""

    if tags is None:
        raw_tags: list[str] = []
    elif isinstance(tags, list):
        raw_tags = [str(tag) for tag in tags]
    else:
        normalized = str(tags).replace(";", ",").replace("\n", ",")
        raw_tags = normalized.split(",")

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags:
        tag = " ".join(raw_tag.strip().split())[:MAX_HISTORY_TAG_LENGTH]
        key = tag.casefold()
        if not tag or key in seen:
            continue
        cleaned.append(tag)
        seen.add(key)
        if len(cleaned) >= MAX_HISTORY_TAGS:
            break
    return cleaned


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
        self.state_store = SQLiteStateStore(history_file.parent / "state.sqlite3")
        self._history_lock = threading.RLock()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_store.migrate_history_json(self.history_file)

    def resolve_download(self, filename: str, require_exists: bool = True) -> Path:
        """Resolve a relative path inside download_dir and reject traversal."""

        relative = Path(filename)
        if (
            not filename
            or filename in {".", ".."}
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.parts[:1] == (THUMBNAIL_DIRNAME,)
        ):
            raise UnsafeFilenameError("Niepoprawna nazwa pliku.")
        candidate = (self.download_dir / relative).resolve()
        try:
            candidate.relative_to(self.download_dir)
        except ValueError as error:
            raise UnsafeFilenameError("Niepoprawna ścieżka pliku.") from error
        if candidate == self.download_dir:
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
            raise UnsafeFilenameError("Niepoprawna ścieżka miniatury.")
        if require_exists and not candidate.is_file():
            raise FileNotFoundError(filename)
        return candidate

    def is_managed_file(self, path: str | Path) -> bool:
        """Return true for files located inside the configured download folder."""

        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(self.download_dir)
        except ValueError:
            return False
        return resolved != self.download_dir

    def list_files(self) -> list[dict[str, Any]]:
        """List downloadable files from persistent storage."""

        files: list[dict[str, Any]] = []
        for path in sorted(
            self.download_dir.rglob("*"),
            key=lambda item: item.stat().st_mtime if item.is_file() else 0,
            reverse=True,
        ):
            if (
                path.is_file()
                and self.is_managed_file(path)
                and THUMBNAIL_DIRNAME not in path.relative_to(self.download_dir).parts
                and not path.name.endswith((".part", ".ytdl"))
            ):
                stat = path.stat()
                filename = path.relative_to(self.download_dir).as_posix()
                files.append(
                    {
                        "filename": filename,
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
        self._remove_empty_parent_dirs(path.parent)
        LOGGER.info("Usunięto plik %s", filename)

    def generate_thumbnail(self, filename: str) -> ThumbnailResult:
        """Create a JPG preview for a managed video file."""

        source = self.resolve_download(filename)
        if source.suffix.lower() not in VIDEO_EXTENSIONS:
            return ThumbnailResult()
        thumbnail_key = self._thumbnail_key(filename)
        thumbnail = self.resolve_thumbnail(f"{thumbnail_key}.jpg", require_exists=False)
        temporary = self.resolve_thumbnail(
            f"{thumbnail_key}.{os.getpid()}.{threading.get_ident()}.tmp.jpg",
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
                "Nie można wygenerować miniatury dla %s: %s",
                filename,
                error_message,
            )
            return ThumbnailResult(
                warning_message=thumbnail_warning_message(error_message)
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            LOGGER.warning(
                "Nie można wygenerować miniatury dla %s: %s", filename, error
            )
            return ThumbnailResult(
                warning_message=thumbnail_warning_message(str(error))
            )
        finally:
            temporary.unlink(missing_ok=True)

    def generate_timeline_thumbnails(
        self,
        filename: str,
        duration: int | None,
        interval_seconds: int = 30,
        max_frames: int = 60,
    ) -> list[dict[str, int | str]]:
        """Create cached timeline thumbnails for hover previews."""

        source = self.resolve_download(filename)
        if source.suffix.lower() not in VIDEO_EXTENSIONS or not duration or duration < 10:
            return []
        interval = max(10, int(interval_seconds))
        frame_count = min(max_frames, max(1, int(duration // interval) + 1))
        timestamps = [min(max(1, index * interval), max(1, duration - 1)) for index in range(frame_count)]
        frames: list[dict[str, int | str]] = []
        thumbnail_key = self._thumbnail_key(filename)
        for timestamp in timestamps:
            thumbnail = self.resolve_thumbnail(
                f"{thumbnail_key}.timeline-{timestamp:05d}.jpg",
                require_exists=False,
            )
            if not thumbnail.is_file():
                temporary = self.resolve_thumbnail(
                    f"{thumbnail_key}.timeline-{timestamp:05d}.{os.getpid()}.{threading.get_ident()}.tmp.jpg",
                    require_exists=False,
                )
                try:
                    command = [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        str(timestamp),
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=320:-2:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "4",
                        str(temporary),
                    ]
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=20,
                    )
                    if result.returncode == 0 and temporary.is_file():
                        os.replace(temporary, thumbnail)
                    else:
                        LOGGER.debug(
                            "Nie wygenerowano miniatury osi czasu %s @ %ss: %s",
                            filename,
                            timestamp,
                            result.stderr.strip(),
                        )
                except (OSError, subprocess.TimeoutExpired) as error:
                    LOGGER.debug(
                        "Nie wygenerowano miniatury osi czasu %s @ %ss: %s",
                        filename,
                        timestamp,
                        error,
                    )
                finally:
                    temporary.unlink(missing_ok=True)
            if thumbnail.is_file():
                frames.append({"time": timestamp, "filename": thumbnail.name})
        return frames

    def delete_thumbnail(self, filename: str) -> None:
        """Remove a generated thumbnail associated with a managed download."""

        thumbnail_key = self._thumbnail_key(filename)
        thumbnail = self.resolve_thumbnail(f"{thumbnail_key}.jpg", require_exists=False)
        thumbnail.unlink(missing_ok=True)
        prefix = f"{thumbnail_key}.timeline-"
        for timeline_thumbnail in self.thumbnail_dir.iterdir():
            if timeline_thumbnail.is_file() and timeline_thumbnail.name.startswith(prefix):
                timeline_thumbnail.unlink(missing_ok=True)

    @staticmethod
    def _thumbnail_key(filename: str) -> str:
        return filename.replace("\\", "__").replace("/", "__")

    def _remove_empty_parent_dirs(self, path: Path) -> None:
        while path != self.download_dir:
            try:
                path.rmdir()
            except OSError:
                return
            path = path.parent

    def history(self) -> list[dict[str, Any]]:
        """Load download history and enrich it with current file existence."""

        with self._history_lock:
            records = self._read_history()
        for record in records:
            record["tags"] = normalize_history_tags(record.get("tags"))
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
            "tags": [],
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

    def update_history_tags(
        self, filename: str, downloaded_at: str, tags: object
    ) -> bool:
        """Replace tags for one matching history record."""

        normalized = normalize_history_tags(tags)
        with self._history_lock:
            records = self._read_history()
            for record in records:
                if (
                    record.get("filename") == filename
                    and record.get("downloaded_at") == downloaded_at
                ):
                    record["tags"] = normalized
                    self._write_history(records)
                    LOGGER.info("Zaktualizowano tagi historii dla pliku %s", filename)
                    return True
        return False

    def _read_history(self) -> list[dict[str, Any]]:
        return self.state_store.history_all()

    def _write_history(self, records: list[dict[str, Any]]) -> None:
        self.state_store.history_replace(records)
