"""Application configuration assembled from Home Assistant add-on options."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from .services.ha_options import load_options


@dataclass(frozen=True)
class AppConfig:
    """Validated runtime settings."""

    storage_mode: str
    download_dir: Path
    nfs_download_dir: Path
    nfs_server: str
    nfs_export_path: str
    nfs_username: str
    nfs_password: str
    nfs_mount_options: str
    jobs_dir: Path
    history_file: Path
    max_concurrent_jobs: int
    update_ytdlp_on_start: bool
    allow_external_port: bool
    external_port: int
    debug: bool
    preferred_format: str
    secret_key: str

    @classmethod
    def load(cls) -> "AppConfig":
        """Load validated settings from /data/options.json."""

        options = load_options()
        jobs_dir = Path("/data/jobs")
        jobs_dir.mkdir(parents=True, exist_ok=True)
        options.download_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            storage_mode=options.storage_mode,
            download_dir=options.download_dir,
            nfs_download_dir=options.nfs_download_dir,
            nfs_server=options.nfs_server,
            nfs_export_path=options.nfs_export_path,
            nfs_username=options.nfs_username,
            nfs_password=options.nfs_password,
            nfs_mount_options=options.nfs_mount_options,
            jobs_dir=jobs_dir,
            history_file=jobs_dir / "history.json",
            max_concurrent_jobs=options.max_concurrent_jobs,
            update_ytdlp_on_start=options.update_ytdlp_on_start,
            allow_external_port=options.allow_external_port,
            external_port=options.external_port,
            debug=options.debug,
            preferred_format=options.preferred_format,
            secret_key=secrets.token_hex(32),
        )
