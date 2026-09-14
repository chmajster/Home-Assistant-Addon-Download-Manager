"""Shared, testable primitives for multi-file history operations."""

from __future__ import annotations

import logging
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

LOGGER = logging.getLogger(__name__)


def output_filenames(job: Any) -> list[str]:
    """Include additional outputs and the primary output exactly once, in order."""
    outputs = getattr(job, "output_files", None)
    candidates = list(outputs) if isinstance(outputs, (list, tuple)) else []
    candidates.append(getattr(job, "output_file", None))
    return list(dict.fromkeys(name for name in candidates if isinstance(name, str) and name))


def repeat_download_options(job: Any) -> dict[str, Any]:
    """Keep saved options/storage without sharing mutable state with the new job."""
    saved = getattr(job, "download_options", None)
    options = deepcopy(saved) if isinstance(saved, dict) else {}
    options.setdefault("storage_name", getattr(job, "storage_name", None) or "local")
    return options


def archive_member_name(filename: str, used_names: set[str]) -> str:
    """Reject unsafe portable ZIP paths and disambiguate case-insensitive names."""
    normalized = filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or ":" in path.parts[0]
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("Niebezpieczna nazwa pliku w archiwum ZIP.")
    candidate = path.as_posix()
    index = 2
    while candidate.casefold() in used_names:
        candidate = str(path.with_name(f"{path.stem}-{index}{path.suffix}"))
        index += 1
    used_names.add(candidate.casefold())
    return candidate


def remove_archive(path: Path) -> None:
    """Make response cleanup idempotent, including disconnected clients."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("Nie można usunąć tymczasowego archiwum %s", path, exc_info=True)


def create_download_archive(files: list[tuple[str, Path]]) -> Path:
    """Create a ZIP and remove it on every failed construction path."""
    with tempfile.NamedTemporaryFile(
        prefix="media-web-downloader-", suffix=".zip", delete=False
    ) as temporary:
        archive_path = Path(temporary.name)
    try:
        used_names: set[str] = set()
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
            strict_timestamps=False,
        ) as archive:
            for filename, path in files:
                archive.write(path, arcname=archive_member_name(filename, used_names))
    except BaseException:
        remove_archive(archive_path)
        raise
    return archive_path
