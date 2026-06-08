"""Read and validate Home Assistant add-on options."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
OPTIONS_FILE = Path("/data/options.json")
DEFAULT_DOWNLOAD_DIR = Path("/share/youtube_downloader")
ALLOWED_DOWNLOAD_ROOTS = (Path("/share"), Path("/media"))
PREFERRED_FORMATS = {"best", "audio", "video", "video-360", "video-720", "video-1080"}

DEFAULT_OPTIONS: dict[str, Any] = {
    "storage_mode": "local",
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "nfs_download_dir": "/media/youtube_downloader_nfs",
    "nfs_server": "",
    "nfs_export_path": "",
    "nfs_username": "",
    "nfs_password": "",
    "nfs_mount_options": "vers=4",
    "max_concurrent_jobs": 2,
    "allow_external_port": False,
    "external_port": 999,
    "debug": False,
    "preferred_format": "best",
}


@dataclass(frozen=True)
class HomeAssistantOptions:
    """Validated options provided by Supervisor."""

    storage_mode: str
    download_dir: Path
    nfs_download_dir: Path
    nfs_server: str
    nfs_export_path: str
    nfs_username: str
    nfs_password: str
    nfs_mount_options: str
    max_concurrent_jobs: int
    allow_external_port: bool
    external_port: int
    debug: bool
    preferred_format: str


def _read_json() -> dict[str, Any]:
    if not OPTIONS_FILE.exists():
        LOGGER.info("Brak %s. Używam wartości domyślnych.", OPTIONS_FILE)
        return {}
    try:
        with OPTIONS_FILE.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
        if not isinstance(payload, dict):
            raise ValueError("główny element JSON nie jest obiektem")
        return payload
    except (OSError, ValueError, json.JSONDecodeError) as error:
        LOGGER.error(
            "Nie można odczytać %s: %s. Używam wartości domyślnych.",
            OPTIONS_FILE,
            error,
        )
        return {}


def _validated_download_dir(value: Any, default: Path = DEFAULT_DOWNLOAD_DIR) -> Path:
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        LOGGER.warning(
            "Katalog pobrań musi być ścieżką bezwzględną. Używam wartości domyślnej."
        )
        return default
    resolved = candidate.resolve()
    if not any(
        resolved == root or root in resolved.parents for root in ALLOWED_DOWNLOAD_ROOTS
    ):
        LOGGER.warning(
            "Katalog pobrań musi znajdować się w /share lub /media. Używam wartości domyślnej."
        )
        return default
    return resolved


def _validated_nfs_download_dir(value: Any) -> Path:
    """Validate an NFS-backed directory without silently falling back locally."""

    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        raise RuntimeError("Katalog NFS musi być ścieżką bezwzględną.")
    resolved = candidate.resolve()
    if not any(root in resolved.parents for root in ALLOWED_DOWNLOAD_ROOTS):
        raise RuntimeError("Katalog NFS musi znajdować się wewnątrz /share lub /media.")
    return resolved


def _network_mount_root(path: Path) -> Path:
    """Return /media/<name> or /share/<name> for an NFS-backed target path."""

    for root in ALLOWED_DOWNLOAD_ROOTS:
        if root in path.parents:
            relative = path.relative_to(root)
            if relative.parts:
                return root / relative.parts[0]
    raise ValueError("Ścieżka NFS musi wskazywać katalog wewnątrz /media lub /share.")


def _validated_storage_mode(value: Any) -> str:
    return str(value) if str(value) in {"local", "nfs"} else "local"


def _validated_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if minimum <= number <= maximum else default


def _validated_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _validated_text(value: Any, default: str = "", max_length: int = 300) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text[:max_length] if text else default


def load_options() -> HomeAssistantOptions:
    """Load options.json and safely fall back for malformed values."""

    provided = _read_json()
    values = {**DEFAULT_OPTIONS, **provided}
    storage_mode = _validated_storage_mode(values["storage_mode"])
    local_download_dir = _validated_download_dir(values["download_dir"])
    if storage_mode == "nfs":
        nfs_download_dir = _validated_nfs_download_dir(values["nfs_download_dir"])
    else:
        nfs_download_dir = _validated_download_dir(
            values["nfs_download_dir"], Path("/media/youtube_downloader_nfs")
        )
    if storage_mode == "nfs":
        mount_root = _network_mount_root(nfs_download_dir)
        if not mount_root.is_dir():
            raise RuntimeError(
                f"Nie znaleziono udziału NFS {mount_root}. "
                "Dodaj magazyn sieciowy w Home Assistant i uruchom dodatek ponownie."
            )
        nfs_download_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(nfs_download_dir, os.W_OK):
            raise RuntimeError(f"Katalog NFS {nfs_download_dir} nie jest zapisywalny.")
    preferred_format = str(values["preferred_format"])
    if preferred_format not in PREFERRED_FORMATS:
        preferred_format = str(DEFAULT_OPTIONS["preferred_format"])
    elif preferred_format == "video":
        preferred_format = "best"

    return HomeAssistantOptions(
        storage_mode=storage_mode,
        download_dir=nfs_download_dir if storage_mode == "nfs" else local_download_dir,
        nfs_download_dir=nfs_download_dir,
        nfs_server=_validated_text(values["nfs_server"]),
        nfs_export_path=_validated_text(values["nfs_export_path"]),
        nfs_username=_validated_text(values["nfs_username"], max_length=120),
        nfs_password=_validated_text(values["nfs_password"], max_length=300),
        nfs_mount_options=_validated_text(values["nfs_mount_options"], "vers=4"),
        max_concurrent_jobs=_validated_int(values["max_concurrent_jobs"], 2, 1, 5),
        allow_external_port=_validated_bool(values["allow_external_port"], False),
        external_port=_validated_int(values["external_port"], 999, 1, 65535),
        debug=_validated_bool(values["debug"], False),
        preferred_format=preferred_format,
    )
