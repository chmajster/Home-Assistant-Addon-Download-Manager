"""Named storage model for current and future download targets."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .error_messages import NO_DISK_SPACE, STORAGE_ERROR_MESSAGE
from .media_service import MediaServiceError

STORAGE_LOCAL = "local"
STORAGE_MEDIA = "media"
STORAGE_NFS = "nfs"
KNOWN_STORAGES = {STORAGE_LOCAL, STORAGE_MEDIA, STORAGE_NFS}
GIB = 1024**3


@dataclass(frozen=True)
class StorageTarget:
    """One named storage target."""

    name: str
    path: Path
    enabled: bool = True


class StorageManager:
    """Validate and expose named storage targets while keeping legacy defaults."""

    def __init__(
        self,
        targets: dict[str, Path],
        default_name: str,
        min_free_space_bytes: int = 0,
    ) -> None:
        self.targets = {
            name: StorageTarget(name=name, path=path.resolve())
            for name, path in targets.items()
            if name in KNOWN_STORAGES
        }
        self.default_name = default_name if default_name in self.targets else STORAGE_LOCAL
        self.min_free_space_bytes = max(0, int(min_free_space_bytes))

    @classmethod
    def from_settings(cls, settings: Any) -> StorageManager:
        download_dir = Path(settings.download_dir)
        nfs_dir = Path(getattr(settings, "nfs_download_dir", download_dir))
        targets = {
            STORAGE_LOCAL: download_dir,
            STORAGE_MEDIA: Path("/media/youtube_downloader"),
            STORAGE_NFS: nfs_dir,
        }
        mode = getattr(settings, "storage_mode", STORAGE_LOCAL)
        default_name = mode if mode in KNOWN_STORAGES else STORAGE_LOCAL
        try:
            min_free_space_gb = float(getattr(settings, "min_free_space_gb", 0.0))
        except (TypeError, ValueError):
            min_free_space_gb = 0.0
        return cls(
            targets,
            default_name,
            min_free_space_bytes=int(max(0.0, min_free_space_gb) * GIB),
        )

    def path_for(self, storage_name: str | None = None) -> Path:
        return self.target(storage_name).path

    def target(self, storage_name: str | None = None) -> StorageTarget:
        name = str(storage_name or self.default_name)
        if name not in self.targets:
            raise MediaServiceError(f"Nieznany storage: {name}.")
        return self.targets[name]

    def validate(self, storage_name: str | None = None, create: bool = True) -> StorageTarget:
        target = self.target(storage_name)
        if create:
            target.path.mkdir(parents=True, exist_ok=True)
        if not target.path.is_dir():
            raise MediaServiceError(f"Storage {target.name} nie istnieje: {target.path}.")
        if not os.access(target.path, os.W_OK):
            raise MediaServiceError(f"Storage {target.name} nie jest zapisywalny: {target.path}.")
        return target

    def ensure_capacity(self, storage_name: str | None = None) -> StorageTarget:
        """Validate a target and enforce the configured free-space reserve."""

        target = self.validate(storage_name)
        try:
            usage = shutil.disk_usage(target.path)
        except OSError as error:
            raise MediaServiceError(
                f"Nie mozna sprawdzic storage {target.name}: {error}"
            ) from error
        if usage.free < self.min_free_space_bytes:
            required_gb = self.min_free_space_bytes / GIB
            free_gb = usage.free / GIB
            raise StorageError(
                f"{STORAGE_ERROR_MESSAGE} Wolne: {free_gb:.2f} GiB; "
                f"wymagana rezerwa: {required_gb:.2f} GiB.",
                NO_DISK_SPACE,
            )
        return target


class StorageError(MediaServiceError):
    """Storage validation error with a stable error code."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
