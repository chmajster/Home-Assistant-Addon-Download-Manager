"""HTML views and form actions."""

from __future__ import annotations

import logging
import json
import mimetypes
import os
import re
import socket
import subprocess
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
)

from .. import ingress_url, valid_csrf_token
from ..i18n import localize_job, translate
from ..services.file_service import (
    FileService,
    UnsafeFilenameError,
    normalize_history_tags,
)
from ..services.job_manager import JobManager
from ..services.media_service import MediaService, MediaServiceError
from ..services.ytdlp_updater import YtDlpUpdater

LOGGER = logging.getLogger(__name__)
web_bp = Blueprint("web", __name__)
BULK_URL_IMPORT_LIMIT = 50
DOWNLOAD_PROFILES = {
    "best-quality": {
        "label": "Najlepsza jakość",
        "download_type": "best",
        "description": "Najlepszy dostępny wariant audio i wideo.",
    },
    "manual": {
        "label": "Ręczny wybór",
        "download_type": None,
        "description": "Własny wariant jakości lub konkretny format.",
    },
    "audio-mp3": {
        "label": "Audio MP3",
        "download_type": "audio",
        "description": "Tylko ścieżka audio i konwersja do MP3.",
    },
    "video-1080": {
        "label": "1080p",
        "download_type": "video-1080",
        "description": "Najlepszy wariant do Full HD.",
    },
    "live-archive": {
        "label": "Archiwum live",
        "download_type": "best",
        "description": "Najlepsza jakość dla zapisanych transmisji.",
    },
    "twitch-only": {
        "label": "Tylko Twitch",
        "download_type": "best",
        "platform": "twitch",
        "description": "Preset dla VOD-ów, klipów i transmisji Twitch.",
    },
}
HISTORY_VIEW_LABELS = {
    "table": "tabela",
    "gallery": "galeria",
}
HISTORY_SORT_LABELS = {
    "date": "data",
    "size": "rozmiar",
    "duration": "długość",
    "title": "tytuł",
    "platform": "serwis",
}
DOWNLOAD_PROFILE_TRANSLATION_KEYS = {
    "best-quality": ("profile.best.label", "profile.best.description"),
    "manual": ("profile.manual.label", "profile.manual.description"),
    "audio-mp3": ("profile.audio.label", "profile.audio.description"),
    "video-1080": ("profile.video1080.label", "profile.video1080.description"),
    "live-archive": ("profile.live.label", "profile.live.description"),
    "twitch-only": ("profile.twitch.label", "profile.twitch.description"),
}
PLATFORM_LABELS = {
    "youtube": "YouTube",
    "twitch": "Twitch",
    "vimeo": "Vimeo",
    "soundcloud": "SoundCloud",
    "instagram": "Instagram",
    "kick": "Kick",
}
DEFAULT_PLATFORM_CHIPS = ("youtube", "twitch", "vimeo", "soundcloud")
PLATFORM_CHIP_LIMIT = 7


def _file_service() -> FileService:
    return current_app.extensions["file_service"]


def _media_service() -> MediaService:
    return current_app.extensions["media_service"]


def _job_manager() -> JobManager:
    return current_app.extensions["job_manager"]


def _ytdlp_updater() -> YtDlpUpdater:
    return current_app.extensions["ytdlp_updater"]


def _ha_notifier():
    return current_app.extensions["ha_notifier"]


def _language() -> str:
    return current_app.config["APP_SETTINGS"].ui_language


def _t(key: str, **values: object) -> str:
    return translate(_language(), key, **values)


def _ensure_ytdlp_recent() -> None:
    _ytdlp_updater().ensure_recent()


def _installed_package_version(package_name: str) -> str:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "brak danych"


def _command_first_line(command: list[str], timeout: float = 3.0) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "version": "brak danych", "error": str(error)}
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return {
        "available": result.returncode == 0,
        "version": output[0] if output else "brak danych",
        "error": ""
        if result.returncode == 0
        else (result.stderr or result.stdout or "").strip(),
    }


def _directory_write_test(path: object) -> dict[str, Any]:
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".diagnostic-write-",
            suffix=".tmp",
            dir=str(path),
            delete=False,
        ) as handle:
            handle.write(b"ok")
            temporary_name = handle.name
        os.unlink(temporary_name)
        return {"available": True, "message": "Zapis i usuwanie pliku działa."}
    except OSError as error:
        return {"available": False, "message": str(error)}


def _network_test(host: str = "github.com", port: int = 443) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=3.0):
            return {
                "available": True,
                "message": f"Połączono z {host}:{port}.",
            }
    except OSError as error:
        return {"available": False, "message": str(error)}


def _mount_type(path: object) -> str | None:
    try:
        resolved = os.path.realpath(os.fspath(path))
        best_match = ""
        best_type: str | None = None
        with open("/proc/mounts", "r", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mount_point = parts[1].replace("\\040", " ")
                if resolved == mount_point or resolved.startswith(mount_point.rstrip("/") + "/"):
                    if len(mount_point) > len(best_match):
                        best_match = mount_point
                        best_type = parts[2]
        return best_type
    except OSError:
        return None


def _nfs_test(settings: Any, download_dir: object) -> dict[str, Any]:
    if settings.storage_mode != "nfs":
        return {
            "available": True,
            "status": "ok",
            "value": "lokalny",
            "message": "Tryb NFS jest wyłączony.",
        }
    if not os.path.isdir(download_dir):
        return {
            "available": False,
            "status": "error",
            "value": "brak katalogu",
            "message": f"Nie znaleziono katalogu NFS: {download_dir}.",
        }
    mount_type = _mount_type(download_dir)
    if mount_type and "nfs" in mount_type.casefold():
        return {
            "available": True,
            "status": "ok",
            "value": mount_type,
            "message": f"Udział NFS jest zamontowany w {download_dir}.",
        }
    if mount_type:
        return {
            "available": True,
            "status": "warning",
            "value": mount_type,
            "message": "Katalog działa, ale typ montowania nie wygląda na NFS.",
        }
    return {
        "available": True,
        "status": "warning",
        "value": "niezweryfikowany",
        "message": "Nie można odczytać typu montowania z /proc/mounts.",
    }


def _diagnostic_status_label(status: str) -> str:
    return {
        "ok": _t("common.ok"),
        "warning": "ostrzeżenie",
        "error": "błąd",
    }.get(status, status)


def _diagnostic_row(
    label: str,
    value: object,
    status: str = "ok",
    details: object = "",
) -> dict[str, str]:
    return {
        "label": label,
        "value": str(value or _t("common.no_data")),
        "status": status,
        "status_label": _diagnostic_status_label(status),
        "details": str(details or ""),
    }


def _diagnostic_rows(
    ytdlp: dict[str, Any],
    ffmpeg: dict[str, Any],
    storage: dict[str, Any],
    paths: dict[str, str],
    home_assistant: dict[str, Any],
) -> list[dict[str, str]]:
    ytdlp_version_status = "error" if ytdlp.get("version") == "brak danych" else "ok"
    ytdlp_update_status = "ok"
    ytdlp_update_details = ""
    if ytdlp.get("last_error"):
        ytdlp_update_status = "error"
        ytdlp_update_details = ytdlp["last_error"]
    elif ytdlp.get("needs_update"):
        ytdlp_update_status = "warning"
        ytdlp_update_details = (
            "Ostatnia udana aktualizacja jest nieaktualna albo nieznana."
        )

    ffmpeg_status = "ok" if ffmpeg.get("available") else "error"
    storage_status = "ok"
    if float(storage.get("free_percent") or 0) < 5:
        storage_status = "error"
    elif float(storage.get("free_percent") or 0) < 15:
        storage_status = "warning"

    ha_status = "ok" if home_assistant.get("available") else "error"
    return [
        _diagnostic_row(_t("diag.ytdlp_version"), ytdlp.get("version"), ytdlp_version_status),
        _diagnostic_row(
            _t("diag.ytdlp_update"),
            _date_time_label(ytdlp.get("last_success")),
            ytdlp_update_status,
            ytdlp_update_details,
        ),
        _diagnostic_row(
            _t("diag.ffmpeg_version"),
            ffmpeg.get("version"),
            ffmpeg_status,
            ffmpeg.get("error"),
        ),
        _diagnostic_row(
            _t("diag.free_space"),
            f"{_filesize_label(storage.get('free'))} ({storage.get('free_percent')}%)",
            storage_status,
            f"Zajęte: {_filesize_label(storage.get('used'))} z {_filesize_label(storage.get('total'))}.",
        ),
        _diagnostic_row("Katalog pobrań", paths.get("download_dir")),
        _diagnostic_row(
            _t("diag.ha_api"),
            "połączono" if home_assistant.get("available") else "problem",
            ha_status,
            home_assistant.get("message"),
        ),
    ]


def _last_diagnostic_error(rows: list[dict[str, str]]) -> str:
    for row in rows:
        if row["status"] == "error" and row["details"]:
            return row["details"]
    for row in rows:
        if row["status"] == "error":
            return f"{row['label']}: {row['value']}"
    return ""


def _date_time_label(value: object) -> str:
    if not value:
        return "brak danych"
    return str(value).replace("T", " ")[:19]


def _diagnostics_snapshot() -> dict[str, Any]:
    file_service = _file_service()
    settings = current_app.config["APP_SETTINGS"]
    jobs = _job_manager().list_jobs()
    ytdlp_update = _ytdlp_updater().diagnostics()
    ytdlp = {
        "version": _installed_package_version("yt-dlp"),
        **ytdlp_update,
    }
    ffmpeg = _command_first_line(["ffmpeg", "-version"])
    storage = file_service.storage_usage()
    paths = {
        "download_dir": str(file_service.download_dir),
        "thumbnail_dir": str(file_service.thumbnail_dir),
        "history_file": str(file_service.history_file),
        "state_db": str(file_service.state_store.db_path),
        "jobs_dir": str(settings.jobs_dir),
    }
    home_assistant = _ha_notifier().health_status()
    rows = _diagnostic_rows(ytdlp, ffmpeg, storage, paths, home_assistant)
    write_test = _directory_write_test(file_service.download_dir)
    ytdlp_cli = _command_first_line(["yt-dlp", "--version"])
    network = _network_test()
    nfs = _nfs_test(settings, file_service.download_dir)
    rows.extend(
        [
            _diagnostic_row(
                _t("diag.write_test"),
                "działa" if write_test.get("available") else "problem",
                "ok" if write_test.get("available") else "error",
                write_test.get("message"),
            ),
            _diagnostic_row(
                _t("diag.ffmpeg_test"),
                "działa" if ffmpeg.get("available") else "problem",
                "ok" if ffmpeg.get("available") else "error",
                ffmpeg.get("error") or ffmpeg.get("version"),
            ),
            _diagnostic_row(
                _t("diag.ytdlp_cli"),
                ytdlp_cli.get("version"),
                "ok" if ytdlp_cli.get("available") else "warning",
                ytdlp_cli.get("error") or "CLI yt-dlp odpowiada.",
            ),
            _diagnostic_row(
                _t("diag.network_test"),
                "połączono" if network.get("available") else "problem",
                "ok" if network.get("available") else "error",
                network.get("message"),
            ),
            _diagnostic_row(
                _t("diag.nfs_test"),
                nfs.get("value"),
                str(nfs.get("status") or "ok"),
                nfs.get("message"),
            ),
        ]
    )
    quick_checks = [
        _diagnostic_row(
            _t("diag.ytdlp_cli"),
            ytdlp_cli.get("version"),
            "ok" if ytdlp_cli.get("available") else "warning",
            ytdlp_cli.get("error") or "CLI yt-dlp odpowiada.",
        ),
        _diagnostic_row(
            "ffmpeg",
            "działa" if ffmpeg.get("available") else "problem",
            "ok" if ffmpeg.get("available") else "error",
            ffmpeg.get("error") or ffmpeg.get("version"),
        ),
        _diagnostic_row(
            _t("diag.write_test"),
            "działa" if write_test.get("available") else "problem",
            "ok" if write_test.get("available") else "error",
            write_test.get("message"),
        ),
        _diagnostic_row(
            "Sieć",
            "połączono" if network.get("available") else "problem",
            "ok" if network.get("available") else "error",
            network.get("message"),
        ),
    ]
    return {
        "rows": rows,
        "quick_checks": quick_checks,
        "last_error": _last_diagnostic_error(rows),
        "yt_dlp": ytdlp,
        "ffmpeg": ffmpeg,
        "storage": storage,
        "paths": paths,
        "home_assistant": home_assistant,
        "checks": {
            "write": write_test,
            "yt_dlp_cli": ytdlp_cli,
            "network": network,
            "nfs": nfs,
        },
        "jobs": {
            "total": len(jobs),
            "active": sum(1 for job in jobs if job.status in JobManager.ACTIVE_STATUSES),
            "failed": sum(1 for job in jobs if job.status == "error"),
        },
    }


def _job_parameter_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Return the full yt-dlp parameter block saved in the job log."""

    lines = list(job.get("log_lines") or [])
    marker = "[yt-dlp] Parametry pobierania:"
    if marker in lines:
        start = lines.index(marker) + 1
        collected: list[str] = []
        balance = 0
        for line in lines[start:]:
            if line.startswith("[") and collected:
                break
            collected.append(line)
            balance += line.count("{") - line.count("}")
            if collected and balance <= 0 and line.strip().endswith("}"):
                break
        raw_json = "\n".join(collected).strip()
        if raw_json:
            try:
                return json.loads(raw_json)
            except json.JSONDecodeError:
                return {"raw": raw_json}
    return {
        "url": job.get("url"),
        "download_type": job.get("download_type"),
        "format_id": job.get("format_id"),
        "is_live": job.get("is_live"),
        "live_from_start": job.get("live_from_start"),
        "duration": job.get("duration"),
    }


def _job_timeline(job: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []

    def add(label: str, timestamp: object, detail: object = "", status: str = "ok") -> None:
        if not timestamp:
            return
        events.append(
            {
                "label": label,
                "time": _date_time_label(timestamp),
                "detail": str(detail or ""),
                "status": status,
            }
        )

    add("Dodano do kolejki", job.get("created_at"), job.get("url"))
    add("Rozpoczęto", job.get("started_at"), job.get("status_label"))
    for line in job.get("log_lines") or []:
        line_text = str(line)
        if line_text.startswith("[retry]"):
            add(
                "Ponowienie",
                job.get("finished_at") or job.get("created_at"),
                line_text,
                "warning",
            )
        elif line_text.startswith("[error]"):
            add(
                "Błąd",
                job.get("finished_at") or job.get("created_at"),
                line_text.removeprefix("[error] ").strip(),
                "error",
            )
    add("Następna próba", job.get("next_retry_at"), "Automatyczne ponowienie", "warning")
    add(
        "Zakończono",
        job.get("finished_at"),
        job.get("status_label"),
        "error" if job.get("status") == "error" else "ok",
    )
    return events


def _job_retry_history(job: dict[str, Any]) -> list[str]:
    history = [
        str(line)
        for line in job.get("log_lines") or []
        if str(line).startswith("[retry]")
    ]
    if not history and (job.get("auto_retry_attempts") or job.get("next_retry_at")):
        history.append(
            (
                f"Automatyczne próby: {job.get('auto_retry_attempts')}/"
                f"{job.get('auto_retry_max_attempts')}"
            )
        )
    return history


def _duration_value(value: object) -> int | None:
    try:
        seconds = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _form_bool(name: str, default: bool = False) -> bool:
    values = request.form.getlist(name)
    if not values:
        return default
    return values[-1].casefold() in {"1", "true", "yes", "on"}


def _download_options_from_form(playlist_title: str | None = None) -> dict[str, Any]:
    options = {
        "audio_format": MediaService.audio_format(
            {"audio_format": request.form.get("audio_format") or "mp3"}
        ),
        "embed_thumbnail": _form_bool("embed_thumbnail", True),
        "add_metadata": _form_bool("add_metadata", True),
    }
    if playlist_title and _form_bool("playlist_folder"):
        options["output_subdir"] = playlist_title
    return options


def _selected_download_profile(value: object) -> dict[str, Any]:
    key = str(value or "manual")
    return DOWNLOAD_PROFILES.get(key, DOWNLOAD_PROFILES["manual"])


def _localized_download_profiles() -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for key, profile in DOWNLOAD_PROFILES.items():
        label_key, description_key = DOWNLOAD_PROFILE_TRANSLATION_KEYS[key]
        profiles[key] = {
            **profile,
            "label": _t(label_key),
            "description": _t(description_key),
        }
    return profiles


def _profile_download_type(
    profile: dict[str, Any],
    download_type: object,
    url: object,
) -> str:
    expected_platform = profile.get("platform")
    if expected_platform:
        validated_url = MediaService.validate_url(str(url or ""))
        if MediaService.detect_platform(validated_url) != expected_platform:
            raise MediaServiceError(
                f"Profil {profile['label']} działa tylko dla serwisu {expected_platform}."
            )
    return str(profile.get("download_type") or download_type or "best")


def _automatic_download_type(
    url: object,
    title: object,
    download_type: str,
    is_live: object = None,
) -> tuple[str, str | None]:
    """Apply lightweight built-in download rules without overriding explicit formats."""

    if download_type == "format":
        return download_type, None
    validated_url = MediaService.validate_url(str(url or ""))
    platform = MediaService.detect_platform(validated_url)
    title_text = str(title or "").casefold()
    url_text = validated_url.casefold()
    if platform == "twitch" and str(is_live).casefold() in {"1", "true", "yes", "on"}:
        return "live", "Twitch live wykryty automatycznie."
    if any(marker in title_text or marker in url_text for marker in ("podcast", "audio", "mp3")):
        return "audio", "Podcast/audio wykryte automatycznie."
    return download_type, None


def _known_source_ids() -> set[str]:
    return {
        str(job.source_id)
        for job in _job_manager().list_jobs()
        if job.source_id and job.status != "error"
    }


def _selected_playlist_entries() -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_ids = _known_source_ids()
    start = _positive_int(request.form.get("playlist_start"))
    end = _positive_int(request.form.get("playlist_end"))
    limit = _positive_int(request.form.get("playlist_limit"))
    skip_existing = _form_bool("skip_existing_ids") or _form_bool("download_only_new")
    skipped_existing = 0
    for raw_index in request.form.getlist("playlist_entries"):
        if not raw_index.isdigit():
            continue
        entry_index = int(raw_index) + 1
        if start and entry_index < start:
            continue
        if end and entry_index > end:
            continue
        entry_url = str(request.form.get(f"playlist_entry_url_{raw_index}") or "").strip()
        if not entry_url:
            continue
        validated_url = MediaService.validate_url(entry_url)
        if validated_url in seen:
            continue
        source_id = str(request.form.get(f"playlist_entry_id_{raw_index}") or "").strip()
        if skip_existing and source_id and source_id in seen_ids:
            skipped_existing += 1
            continue
        seen.add(validated_url)
        entries.append(
            {
                "url": validated_url,
                "source_id": source_id or None,
                "title": str(
                    request.form.get(f"playlist_entry_title_{raw_index}")
                    or request.form.get("title")
                    or _bulk_download_title(validated_url)
                ),
                "duration": _duration_value(
                    request.form.get(f"playlist_entry_duration_{raw_index}")
                ),
            }
        )
        if limit and len(entries) >= limit:
            break
    return entries, skipped_existing


def _bulk_url_candidates(value: object) -> list[str]:
    """Return unique URL-like tokens from a pasted list."""

    raw = str(value or "")
    candidates = [item.strip() for item in re.split(r"[\r\n,;]+", raw) if item.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
        if len(unique) >= BULK_URL_IMPORT_LIMIT:
            break
    return unique


def _validated_url_candidates(urls: list[str]) -> tuple[list[str], list[str]]:
    valid: list[str] = []
    invalid: list[str] = []
    for url in urls:
        try:
            valid.append(MediaService.validate_url(url))
        except MediaServiceError:
            invalid.append(url)
    return valid, invalid


def _invalid_urls_message(urls: list[str]) -> str:
    visible = ", ".join(urls[:10])
    suffix = f" oraz {len(urls) - 10} więcej" if len(urls) > 10 else ""
    return f"Niepoprawne URL-e: {visible}{suffix}."


def _bulk_download_title(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "URL"
    path = parts.path.rstrip("/")
    tail = path.rsplit("/", 1)[-1] if path else ""
    if tail and parts.query:
        return f"{host}/{tail}?{parts.query}"[:120]
    if tail:
        return f"{host}/{tail}"[:120]
    return host[:120]


def _queue_imported_downloads(urls: list[str]) -> int:
    created = 0
    for url in urls:
        _job_manager().start_download(
            url=url,
            title=_bulk_download_title(url),
            download_type="best",
        )
        created += 1
    return created


def _live_from_start_value() -> bool:
    values = request.form.getlist("live_from_start")
    return values[-1] == "1" if values else True


def _duplicate_key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _duplicate_url_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return MediaService.validate_url(raw)
    except MediaServiceError:
        return raw


def _duplicate_download_warnings(url: str, title: str = "") -> list[dict[str, str]]:
    """Return compact duplicate warnings for the analyzed or queued media."""

    normalized_url = _duplicate_url_key(url)
    title_key = _duplicate_key(title)
    warnings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, source: str, item_title: object, detail: object = "") -> None:
        key = (kind, str(detail or item_title or source))
        if key in seen:
            return
        seen.add(key)
        warnings.append(
            {
                "kind": kind,
                "source": source,
                "title": str(item_title or "Bez tytułu"),
                "detail": str(detail or ""),
            }
        )

    for job in _job_manager().list_jobs():
        source = "queue" if job.status in JobManager.ACTIVE_STATUSES else "jobs"
        detail = job.output_file or job.job_id[:8]
        if _duplicate_url_key(job.url) == normalized_url:
            add("url", source, job.title, detail)
        elif title_key and _duplicate_key(job.title) == title_key:
            add("file", source, job.title, detail)
    return warnings[:5]


def _flash_duplicate_warnings(warnings: list[dict[str, str]]) -> None:
    if not warnings:
        return
    first = warnings[0]
    if first["kind"] == "url":
        message = "Uwaga: ten URL był już pobierany lub jest teraz w kolejce."
    else:
        message = "Uwaga: podobny plik lub tytuł był już pobrany albo jest teraz w kolejce."
    flash(f"{message} Możesz kontynuować, jeśli robisz to celowo.", "warning")


def _limited(bucket: str, limit: int, window: int = 60) -> bool:
    limiter = current_app.extensions["request_limiter"]
    remote = request.remote_addr or "unknown"
    return limiter.is_limited(remote, bucket, limit, window)


def _valid_form() -> bool:
    if valid_csrf_token(request.form.get("_csrf_token")):
        return True
    flash("Sesja formularza wygasła. Odśwież stronę i spróbuj ponownie.", "danger")
    return False


@web_bp.get("/")
def index():
    """Main panel with URL form and recent completed jobs."""

    file_service = _file_service()
    history = _completed_job_records(limit=10)
    return render_template(
        "index.html",
        history=history,
        platform_chips=_platform_chips(history),
        files=file_service.list_files(),
        storage=file_service.storage_usage(),
        options=current_app.config["APP_SETTINGS"],
    )


@web_bp.get("/history")
def history():
    """Redirect legacy history links to the unified jobs view."""

    return redirect(ingress_url("web.jobs"))


def _completed_job_records(limit: int | None = None) -> list[dict[str, Any]]:
    """Return completed jobs in the shape used by legacy media views."""

    file_service = _file_service()
    manager = _job_manager()
    records: list[dict[str, Any]] = []
    for job in manager.list_jobs():
        if job.status != "completed" or not job.output_file:
            continue
        payload = localize_job(manager.job_dict(job), _language())
        filename = job.output_file
        try:
            file_service.resolve_download(filename)
            file_exists = True
        except (FileNotFoundError, UnsafeFilenameError):
            file_exists = False
        thumbnail_exists = False
        if job.thumbnail_filename:
            try:
                thumbnail_exists = file_service.resolve_thumbnail(
                    job.thumbnail_filename
                ).is_file()
            except (FileNotFoundError, UnsafeFilenameError):
                thumbnail_exists = False
        records.append(
            {
                "job_id": job.job_id,
                "title": job.title,
                "url": job.url,
                "type": job.download_type,
                "filename": filename,
                "size": job.downloaded_bytes,
                "downloaded_at": job.finished_at or job.created_at,
                "status": job.status,
                "file_exists": file_exists,
                "thumbnail_filename": job.thumbnail_filename,
                "thumbnail_exists": thumbnail_exists,
                "format_id": job.format_id,
                "warning_message": job.warning_message,
                "duration": job.duration,
                "tags": job.tags,
                "status_label": payload["status_label"],
                "can_delete": payload["can_delete"],
                "can_repeat": payload["can_repeat"],
                "can_retry": payload["can_retry"],
                "can_stop": payload["can_stop"],
                "can_resume": payload["can_resume"],
            }
        )
        if limit is not None and len(records) >= limit:
            break
    return _history_records(records)


@web_bp.get("/diagnostics")
def diagnostics():
    """Render operational diagnostics for the add-on."""

    return render_template("diagnostics.html", diagnostics=_diagnostics_snapshot())


def _history_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        mime_type = mimetypes.guess_type(str(item.get("filename") or ""))[0] or ""
        media_kind = ""
        if mime_type.startswith("video/"):
            media_kind = "video"
        elif mime_type.startswith("audio/"):
            media_kind = "audio"
        item["platform"] = _history_platform(str(item.get("url") or ""))
        item["tags"] = normalize_history_tags(item.get("tags"))
        item["auto_tags"] = _automatic_history_tags(item)
        item["visible_auto_tags"] = _visible_auto_tags(item["tags"], item["auto_tags"])
        item["all_tags"] = _combined_history_tags(item["tags"], item["auto_tags"])
        item["tags_label"] = ", ".join(item["tags"])
        item["all_tags_label"] = ", ".join(item["all_tags"])
        item["size_label"] = _filesize_label(item.get("size"))
        item["duration_label"] = _duration_label(item.get("duration"))
        item["downloaded_at_label"] = str(item.get("downloaded_at") or "").replace(
            "T", " "
        )[:19]
        item["inline_media_type"] = mime_type
        item["inline_media_kind"] = media_kind
        item["can_inline_play"] = bool(item.get("file_exists") and media_kind)
        item["can_repeat"] = bool(
            item.get("can_repeat")
            if "can_repeat" in item
            else _history_record_can_repeat(item)
        )
        item["can_delete"] = bool(item.get("can_delete", item.get("job_id")))
        item["can_download_file"] = bool(item.get("file_exists") and item.get("filename"))
        item["can_delete_file"] = item["can_download_file"]
        item["can_view_details"] = bool(item.get("job_id"))
        enriched.append(item)
    return enriched


def _history_platform(url: str) -> str:
    try:
        return MediaService.detect_platform(MediaService.validate_url(url))
    except MediaServiceError:
        return "unknown"


def _platform_chips(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return compact platform chips for the start page hero."""

    platforms = list(DEFAULT_PLATFORM_CHIPS)
    for item in records:
        platform = str(item.get("platform") or "").casefold()
        if not platform or platform == "unknown" or platform in platforms:
            continue
        platforms.append(platform)
        if len(platforms) >= PLATFORM_CHIP_LIMIT:
            break
    chips = [
        {
            "label": PLATFORM_LABELS.get(platform, platform.title()),
            "class": f"platform-{platform}",
        }
        for platform in platforms
    ]
    chips.append({"label": "i inne przez yt-dlp", "class": "platform-ytdlp"})
    return chips


def _automatic_history_tags(item: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    platform = str(item.get("platform") or "")
    download_type = str(item.get("type") or "")
    filename = str(item.get("filename") or "").casefold()

    if platform and platform != "unknown":
        tags.append(platform)
    if download_type == "live":
        tags.append("live")
    if download_type == "audio" or filename.endswith((".mp3", ".m4a", ".opus")):
        tags.append("audio")
    if download_type in {"best", "video"} or download_type.startswith("video-"):
        tags.append("video")
    if download_type.startswith("video-"):
        tags.append(download_type.removeprefix("video-") + "p")
    if download_type == "format":
        tags.append("format")
    return normalize_history_tags(tags)


def _visible_auto_tags(manual_tags: list[str], auto_tags: list[str]) -> list[str]:
    manual = {tag.casefold() for tag in manual_tags}
    return [tag for tag in auto_tags if tag.casefold() not in manual]


def _combined_history_tags(
    manual_tags: list[str], auto_tags: list[str]
) -> list[str]:
    combined = list(manual_tags)
    seen = {tag.casefold() for tag in combined}
    for tag in auto_tags:
        if tag.casefold() not in seen:
            combined.append(tag)
            seen.add(tag.casefold())
    return combined


def _filter_history(records: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not query:
        return records
    needle = query.casefold()
    return [item for item in records if needle in _history_search_text(item)]


def _history_sort_key(value: object) -> str:
    candidate = str(value or "date")
    return candidate if candidate in HISTORY_SORT_LABELS else "date"


def _history_sort_order(value: object) -> str:
    return "asc" if str(value) == "asc" else "desc"


def _history_view(value: object) -> str:
    candidate = str(value or "table")
    return candidate if candidate in HISTORY_VIEW_LABELS else "table"


def _sort_history(
    records: list[dict[str, Any]], sort: str, order: str
) -> list[dict[str, Any]]:
    reverse = order == "desc"
    present = [
        item for item in records if not _history_sort_missing(item, sort)
    ]
    missing = [item for item in records if _history_sort_missing(item, sort)]
    return sorted(
        present,
        key=lambda item: _history_sort_value(item, sort),
        reverse=reverse,
    ) + missing


def _history_sort_missing(item: dict[str, Any], sort: str) -> bool:
    value = item.get(_history_sort_field(sort))
    return value is None or value == ""


def _history_sort_value(item: dict[str, Any], sort: str) -> object:
    if sort == "date":
        return str(item.get("downloaded_at") or "")
    if sort == "size":
        return _numeric_sort_value(item.get("size"))
    if sort == "duration":
        return _numeric_sort_value(item.get("duration"))
    if sort == "platform":
        return str(item.get("platform") or "").casefold()
    return str(item.get("title") or "").casefold()


def _history_sort_field(sort: str) -> str:
    return {
        "date": "downloaded_at",
        "size": "size",
        "duration": "duration",
        "platform": "platform",
        "title": "title",
    }[sort]


def _numeric_sort_value(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _history_search_text(item: dict[str, Any]) -> str:
    values = [
        item.get("title"),
        item.get("filename"),
        item.get("platform"),
        item.get("url"),
        item.get("downloaded_at"),
        item.get("downloaded_at_label"),
        item.get("size"),
        item.get("size_label"),
        item.get("duration"),
        item.get("duration_label"),
        item.get("type"),
        item.get("status"),
        item.get("tags"),
        item.get("auto_tags"),
        item.get("all_tags"),
        item.get("tags_label"),
        item.get("all_tags_label"),
    ]
    return " ".join(str(value) for value in values if value is not None).casefold()


def _selected_history_records(
    records: list[dict[str, Any]], selected_keys: list[str]
) -> list[dict[str, Any]]:
    selected = {key for key in selected_keys if key}
    return [
        record
        for record in records
        if str(record.get("downloaded_at") or "") in selected
    ]


def _history_redirect():
    return redirect(ingress_url("web.jobs"))


def _history_record_can_repeat(record: dict[str, Any]) -> bool:
    if record.get("type") == "live":
        return False
    if record.get("type") == "format" and not record.get("format_id"):
        return False
    return bool(record.get("url"))


def _flash_bulk_history_result(action: str, done: int, skipped: int) -> None:
    if action == "delete_entries":
        if done:
            flash(f"Usunięto wpisy z historii: {done}.", "success")
        else:
            flash("Nie usunięto żadnych wpisów z historii.", "warning")
    elif action == "delete_files":
        if done:
            flash(f"Usunięto pliki: {done}.", "success")
        else:
            flash("Nie usunięto żadnych plików.", "warning")
    elif action == "repeat":
        if done:
            flash(f"Uruchomiono ponowne pobrania: {done}.", "success")
        else:
            flash("Nie uruchomiono żadnego ponownego pobierania.", "warning")
    if skipped:
        flash(f"Pominięto pozycje: {skipped}.", "warning")


def _filesize_label(value: object) -> str:
    try:
        size = float(str(value))
    except (TypeError, ValueError):
        return "brak danych"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "brak danych"


def _duration_label(value: object) -> str:
    seconds = _duration_value(value)
    if seconds is None:
        return "brak danych"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


@web_bp.post("/analyze")
def analyze():
    """Analyze one URL or queue multiple pasted URLs."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    urls = _bulk_url_candidates(request.form.get("url", ""))
    if not urls:
        flash("Wklej co najmniej jeden adres URL.", "warning")
        return redirect(ingress_url("web.index"))

    valid_urls, invalid_urls = _validated_url_candidates(urls)
    if invalid_urls:
        flash(_invalid_urls_message(invalid_urls), "danger")
        return redirect(ingress_url("web.index"))

    if len(valid_urls) > 1:
        if _limited("download-import", 3):
            flash("Zbyt wiele prób importu listy URL. Odczekaj chwilę.", "warning")
            return redirect(ingress_url("web.index"))
        try:
            _ensure_ytdlp_recent()
            created = _queue_imported_downloads(valid_urls)
            flash(f"Zaimportowano zadania z listy URL: {created}.", "success")
        except MediaServiceError as error:
            flash(str(error), "danger")
            return redirect(ingress_url("web.index"))
        return redirect(ingress_url("web.jobs"))

    if _limited("analyze", 6):
        flash("Zbyt wiele prób analizy. Odczekaj chwilę i spróbuj ponownie.", "warning")
        return redirect(ingress_url("web.index"))
    try:
        _ensure_ytdlp_recent()
        media = _media_service().analyze(valid_urls[0])
        media["duplicate_warnings"] = _duplicate_download_warnings(
            str(media.get("url") or ""),
            str(media.get("title") or ""),
        )
        return render_template(
            "result.html", media=media, download_profiles=_localized_download_profiles()
        )
    except MediaServiceError as error:
        return render_template("error.html", message=str(error)), 400


@web_bp.post("/download")
def start_download():
    """Queue a regular video, audio, playlist, or explicit-format download."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    urls = _bulk_url_candidates(request.form.get("url", ""))
    if not urls:
        flash("Wklej co najmniej jeden adres URL.", "warning")
        return redirect(ingress_url("web.index"))
    if len(urls) > 1 and not request.form.get("playlist_picker"):
        flash("Szybkie pobieranie obsługuje jeden link naraz.", "warning")
        return redirect(ingress_url("web.index"))
    if _limited("download", 10):
        flash("Zbyt wiele prób uruchomienia pobierania. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        _ensure_ytdlp_recent()
        validated_url = MediaService.validate_url(urls[0])
        title = str(request.form.get("title") or "").strip() or _bulk_download_title(
            validated_url
        )
        profile = _selected_download_profile(request.form.get("download_profile"))
        download_type = _profile_download_type(
            profile,
            request.form.get("download_type", "best"),
            validated_url,
        )
        download_type, automatic_rule = _automatic_download_type(
            validated_url,
            title,
            download_type,
            request.form.get("is_live"),
        )
        format_id = request.form.get("format_id") or None
        if download_type != "format":
            format_id = None
        download_options = _download_options_from_form(
            title if request.form.get("playlist_picker") else None
        )
        playlist_entries, skipped_existing = _selected_playlist_entries()
        if request.form.get("playlist_picker") and not playlist_entries:
            if skipped_existing:
                flash(
                    f"Pominięto istniejące elementy playlisty: {skipped_existing}.",
                    "warning",
                )
                return redirect(ingress_url("web.jobs"))
            raise MediaServiceError("Zaznacz co najmniej jeden element playlisty.")
        if playlist_entries and download_type == "format":
            raise MediaServiceError(
                "Konkretny format nie jest obsługiwany dla wielu elementów playlisty. Wybierz profil albo jakość."
            )
        if not request.form.get("allow_duplicate"):
            _flash_duplicate_warnings(
                _duplicate_download_warnings(
                    validated_url,
                    title,
                )
            )
        if playlist_entries:
            for entry in playlist_entries:
                entry_download_type, _ = _automatic_download_type(
                    entry["url"],
                    entry["title"],
                    download_type,
                )
                _job_manager().start_download(
                    url=entry["url"],
                    title=entry["title"],
                    download_type=entry_download_type,
                    duration=entry["duration"],
                    source_id=entry["source_id"],
                    download_options=download_options,
                )
            flash(f"Uruchomiono zadania z playlisty: {len(playlist_entries)}.", "success")
            if skipped_existing:
                flash(
                    f"Pominięto istniejące elementy po ID: {skipped_existing}.",
                    "info",
                )
            if automatic_rule:
                flash(f"Zastosowano regułę automatyczną: {automatic_rule}", "info")
            return redirect(ingress_url("web.jobs"))
        job = _job_manager().start_download(
            url=validated_url,
            title=title,
            download_type=download_type,
            format_id=format_id,
            duration=_duration_value(request.form.get("duration")),
            source_id=str(request.form.get("source_id") or "").strip() or None,
            download_options=download_options,
        )
        flash(f"Uruchomiono zadanie {job.job_id[:8]}.", "success")
        if automatic_rule:
            flash(f"Zastosowano regułę automatyczną: {automatic_rule}", "info")
    except MediaServiceError as error:
        flash(str(error), "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/download/import")
def import_downloads():
    """Queue multiple regular downloads from pasted URLs."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("download-import", 3):
        flash("Zbyt wiele prĂłb importu listy URL. Odczekaj chwilÄ™.", "warning")
        return redirect(ingress_url("web.index"))

    urls = _bulk_url_candidates(request.form.get("urls", ""))
    if not urls:
        flash("Wklej co najmniej jeden adres URL do importu.", "warning")
        return redirect(ingress_url("web.index"))

    _, invalid_urls = _validated_url_candidates(urls)
    if invalid_urls:
        flash(_invalid_urls_message(invalid_urls), "danger")
        return redirect(ingress_url("web.index"))

    created = 0
    skipped = 0
    try:
        _ensure_ytdlp_recent()
        for url in urls:
            try:
                validated_url = MediaService.validate_url(url)
                title = _bulk_download_title(validated_url)
                download_type, _ = _automatic_download_type(
                    validated_url,
                    title,
                    "best",
                )
                _job_manager().start_download(
                    url=validated_url,
                    title=title,
                    download_type=download_type,
                )
                created += 1
            except MediaServiceError:
                skipped += 1
    except MediaServiceError as error:
        flash(str(error), "danger")
        return redirect(ingress_url("web.index"))

    if created:
        flash(f"Zaimportowano zadania z listy URL: {created}.", "success")
    if skipped:
        flash(f"PominiÄ™to niepoprawne linki: {skipped}.", "warning")
    if not created and not skipped:
        flash("Nie znaleziono linkĂłw do importu.", "warning")
        return redirect(ingress_url("web.index"))
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/live/start")
def start_live():
    """Verify and start recording an active live stream."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("live-start", 6):
        flash("Zbyt wiele prób uruchomienia zapisu live. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        _ensure_ytdlp_recent()
        media = _media_service().analyze(request.form.get("url", ""))
        if media["content_type"] != "live":
            raise MediaServiceError("Podany adres nie prowadzi do transmisji live.")
        if not media["is_live"]:
            raise MediaServiceError("Ta transmisja jeszcze się nie rozpoczęła.")
        job = _job_manager().start_live(
            media["url"], media["title"], live_from_start=_live_from_start_value()
        )
        flash(f"Uruchomiono zapis transmisji {job.job_id[:8]}.", "success")
    except MediaServiceError as error:
        flash(str(error), "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/live/watch")
def watch_live():
    """Wait for a live stream to begin and start recording automatically."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("live-watch", 6):
        flash("Zbyt wiele prób uruchomienia oczekiwania live. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        _ensure_ytdlp_recent()
        media = _media_service().analyze(request.form.get("url", ""))
        if media["content_type"] != "live":
            raise MediaServiceError("Podany adres nie prowadzi do transmisji live.")
        if media["is_live"]:
            job = _job_manager().start_live(
                media["url"], media["title"], live_from_start=_live_from_start_value()
            )
            flash(f"Uruchomiono zapis transmisji {job.job_id[:8]}.", "success")
        else:
            job = _job_manager().start_live_wait(
                media["url"], media["title"], live_from_start=_live_from_start_value()
            )
            flash(
                f"Rozpoczęto oczekiwanie na transmisję {job.job_id[:8]}.",
                "success",
            )
    except MediaServiceError as error:
        flash(str(error), "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/download/stop/<job_id>")
def stop_download(job_id: str):
    """Stop a regular download and keep its partial files for resuming."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    try:
        _job_manager().stop_download(job_id)
        flash("Zlecono zatrzymanie pobierania.", "success")
    except KeyError:
        flash("Nie znaleziono aktywnego pobierania.", "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/download/resume/<job_id>")
def resume_download(job_id: str):
    """Resume a stopped regular download."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    if _limited("download-resume", 10):
        flash("Zbyt wiele prób wznowienia pobierania. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        _ensure_ytdlp_recent()
        job = _job_manager().resume_download(job_id)
        flash(f"Wznowiono zadanie {job.job_id[:8]}.", "success")
    except KeyError:
        flash("Nie znaleziono pobierania do wznowienia.", "danger")
    except MediaServiceError as error:
        flash(str(error), "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/live/stop/<job_id>")
def stop_live(job_id: str):
    """Stop a live stream recording process."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    try:
        _job_manager().stop_live(job_id)
        flash("Zatrzymano zapis transmisji live.", "success")
    except KeyError:
        flash("Nie znaleziono aktywnego zadania live.", "danger")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/jobs/delete/<job_id>")
def delete_job(job_id: str):
    """Delete one inactive job from the queue."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    try:
        _job_manager().delete_job(job_id)
        flash("Zadanie zostało usunięte.", "success")
    except KeyError:
        flash("Nie znaleziono zadania.", "warning")
    except MediaServiceError as error:
        flash(str(error), "warning")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/jobs/delete")
def delete_jobs():
    """Delete selected inactive jobs from the queue."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    job_ids = request.form.getlist("job_ids")
    if not job_ids:
        flash("Zaznacz zadania, które chcesz usunąć.", "warning")
        return redirect(ingress_url("web.jobs"))
    removed, skipped = _job_manager().delete_jobs(job_ids)
    _flash_deleted_jobs(removed, skipped)
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/history/jobs/bulk")
def bulk_history_jobs():
    """Run one bulk action for completed jobs shown in the unified history."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    action = str(request.form.get("action") or "")
    job_ids = list(dict.fromkeys(request.form.getlist("job_ids")))
    if not job_ids:
        flash("Zaznacz wpisy, dla których chcesz wykonać akcję.", "warning")
        return redirect(ingress_url("web.index"))

    manager = _job_manager()
    jobs_by_id = {job.job_id: job for job in manager.list_jobs()}
    selected_jobs = [
        jobs_by_id[job_id]
        for job_id in job_ids
        if job_id in jobs_by_id and jobs_by_id[job_id].status == "completed"
    ]
    if not selected_jobs:
        flash("Nie znaleziono zakończonych wpisów do obsłużenia.", "warning")
        return redirect(ingress_url("web.index"))

    if action == "delete_jobs":
        removed, skipped = manager.delete_jobs([job.job_id for job in selected_jobs])
        _flash_deleted_jobs(removed, skipped)
    elif action == "delete_files":
        done = 0
        skipped = 0
        filenames = {
            str(job.output_file or "")
            for job in selected_jobs
            if job.output_file
        }
        for filename in filenames:
            try:
                _file_service().delete_file(filename)
                done += 1
            except FileNotFoundError:
                skipped += 1
            except UnsafeFilenameError:
                LOGGER.warning("Odrzucono próbę masowego usunięcia %s", filename)
                skipped += 1
        skipped += len(selected_jobs) - len(filenames)
        _flash_bulk_history_result("delete_files", done, skipped)
    elif action == "repeat":
        candidates = [
            job
            for job in selected_jobs
            if job.url
            and not job.is_live
            and (job.download_type != "format" or bool(job.format_id))
        ]
        if candidates:
            try:
                _ensure_ytdlp_recent()
            except MediaServiceError as error:
                flash(str(error), "danger")
                return redirect(ingress_url("web.index"))
        done = 0
        skipped = len(selected_jobs) - len(candidates)
        for job in candidates:
            try:
                manager.start_download(
                    url=job.url,
                    title=job.title,
                    download_type=job.download_type,
                    format_id=job.format_id,
                    duration=job.duration,
                )
                done += 1
            except MediaServiceError as error:
                LOGGER.warning("Nie można ponowić pobierania: %s", error)
                skipped += 1
        _flash_bulk_history_result("repeat", done, skipped)
    else:
        flash("Wybierz poprawną akcję dla zaznaczonych wpisów.", "warning")
    return redirect(ingress_url("web.index"))


@web_bp.post("/jobs/clear")
def clear_jobs():
    """Delete all inactive jobs from the queue."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    removed, skipped = _job_manager().clear_jobs()
    _flash_deleted_jobs(removed, skipped)
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/jobs/retry-failed")
def retry_failed_jobs():
    """Retry every failed job in the queue."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs"))
    if _limited("jobs-retry-failed", 6):
        flash("Zbyt wiele prób ponawiania zadań. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        _ensure_ytdlp_recent()
        retried, skipped = _job_manager().retry_failed_jobs()
    except MediaServiceError as error:
        flash(str(error), "danger")
        return redirect(ingress_url("web.jobs"))
    if retried:
        flash(f"Ponowiono nieudane zadania: {retried}.", "success")
    else:
        flash("Brak nieudanych zadań do ponowienia.", "warning")
    if skipped:
        flash(f"Pominięto zadania: {skipped}.", "warning")
    return redirect(ingress_url("web.jobs"))


@web_bp.post("/jobs/retry/<job_id>")
def retry_job(job_id: str):
    """Retry one failed job from the queue."""

    if not _valid_form():
        return redirect(ingress_url("web.jobs", filter="errors"))
    if _limited("jobs-retry-one", 20):
        flash("Zbyt wiele prób ponawiania zadań. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs", filter="errors"))
    try:
        _ensure_ytdlp_recent()
        job = _job_manager().retry_job(job_id)
        flash(f"Ponowiono zadanie {job.job_id[:8]}.", "success")
    except KeyError:
        flash("Nie znaleziono zadania.", "warning")
    except MediaServiceError as error:
        flash(str(error), "danger")
    return redirect(ingress_url("web.jobs", filter="errors"))


def _flash_deleted_jobs(removed: int, skipped: int) -> None:
    if removed:
        flash(f"Usunięto zadania: {removed}.", "success")
    elif not skipped:
        flash("Brak zakończonych zadań do usunięcia.", "warning")
    if skipped:
        flash(f"Pominięto aktywne zadania: {skipped}.", "warning")


@web_bp.get("/jobs")
def jobs():
    """Render active and completed jobs."""

    manager = _job_manager()
    allowed_filters = {
        "all",
        "in_progress",
        "completed",
        "errors",
        "stopped",
        "interrupted",
    }
    requested_filter = request.args.get("filter")
    job_filter = requested_filter if requested_filter in allowed_filters else "all"
    return render_template(
        "jobs.html",
        jobs=[localize_job(manager.job_dict(job), _language()) for job in manager.list_jobs()],
        job_filter=job_filter,
    )


@web_bp.get("/jobs/<job_id>")
def job_details(job_id: str):
    """Render detailed diagnostics for one queued job."""

    try:
        job = _job_manager().get_job(job_id)
    except KeyError:
        return render_template("error.html", message="Nie znaleziono zadania."), 404
    payload = localize_job(_job_manager().job_dict(job, include_full_log=True), _language())
    parameters = _job_parameter_snapshot(payload)
    return render_template(
        "job_details.html",
        job=payload,
        parameters=parameters,
        parameters_json=json.dumps(
            parameters,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ),
        timeline=_job_timeline(payload),
        retry_history=_job_retry_history(payload),
        removable_statuses=JobManager.DELETABLE_STATUSES,
    )


@web_bp.get("/jobs/log/<job_id>")
def job_log(job_id: str):
    """Render the full saved log for one job."""

    try:
        job = _job_manager().get_job(job_id)
    except KeyError:
        return render_template("error.html", message="Nie znaleziono zadania."), 404
    return render_template(
        "job_log.html",
        job=localize_job(_job_manager().job_dict(job, include_full_log=True), _language()),
    )


@web_bp.get("/downloaded/<path:filename>")
def downloaded(filename: str):
    """Serve one managed downloaded file."""

    try:
        path = _file_service().resolve_download(filename)
        return send_file(path, as_attachment=True, download_name=path.name)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template(
            "error.html", message="Nie znaleziono pobranego pliku."
        ), 404


@web_bp.get("/view/<path:filename>")
def preview(filename: str):
    """Open one managed downloaded file in an inline browser preview."""

    try:
        path = _file_service().resolve_download(filename)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template(
            "error.html", message="Nie znaleziono pobranego pliku."
        ), 404

    history_records = _completed_job_records()
    current_index = next(
        (
            index
            for index, item in enumerate(history_records)
            if item.get("filename") == filename
        ),
        -1,
    )
    record = history_records[current_index] if current_index >= 0 else {}
    enriched_record = _history_records([record])[0] if record else {}
    next_preview_url = ""
    if current_index >= 0:
        for item in history_records[current_index + 1 :]:
            next_filename = str(item.get("filename") or "")
            if not item.get("file_exists") or not next_filename:
                continue
            next_mime_type = mimetypes.guess_type(next_filename)[0] or ""
            if next_mime_type.startswith(("video/", "audio/")):
                next_preview_url = ingress_url("web.preview", filename=next_filename)
                break
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    media_kind = "video" if mime_type.startswith("video/") else "audio"
    if not mime_type.startswith(("video/", "audio/")):
        media_kind = "file"
    stat = path.stat()
    downloaded_at = record.get("downloaded_at") or datetime.fromtimestamp(
        stat.st_mtime, UTC
    ).isoformat()
    duration = _duration_value(enriched_record.get("duration"))
    timeline_thumbnails = []
    if media_kind == "video":
        timeline_thumbnails = [
            {
                "time": frame["time"],
                "url": ingress_url("web.thumbnail", filename=str(frame["filename"])),
            }
            for frame in _file_service().generate_timeline_thumbnails(filename, duration)
        ]
    return render_template(
        "preview.html",
        title=enriched_record.get("title") or path.name,
        filename=filename,
        mime_type=mime_type,
        media_kind=media_kind,
        next_preview_url=next_preview_url,
        timeline_thumbnails=timeline_thumbnails,
        file_info={
            "size": stat.st_size,
            "downloaded_at": downloaded_at,
            "source_url": enriched_record.get("url"),
            "download_type": enriched_record.get("type"),
            "status": enriched_record.get("status"),
            "format_id": enriched_record.get("format_id"),
            "tags": enriched_record.get("tags", []),
            "visible_auto_tags": enriched_record.get("visible_auto_tags", []),
            "all_tags": enriched_record.get("all_tags", []),
            "thumbnail_exists": enriched_record.get("thumbnail_exists"),
            "thumbnail_filename": enriched_record.get("thumbnail_filename"),
            "duration": duration,
        },
    )


@web_bp.get("/media/<path:filename>")
def media(filename: str):
    """Serve one managed downloaded file inline for the preview player."""

    try:
        path = _file_service().resolve_download(filename)
        return send_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0],
            conditional=True,
            download_name=path.name,
        )
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template(
            "error.html", message="Nie znaleziono pobranego pliku."
        ), 404


def _subtitle_label(subtitle_path, media_path) -> str:
    subtitle_stem = subtitle_path.stem
    media_stem = media_path.with_suffix("").name
    language_prefix = f"{media_stem}."
    if subtitle_stem.startswith(language_prefix):
        language = subtitle_stem[len(language_prefix) :].strip()
        if language:
            return language.upper()
    return "Napisy"


def _subtitle_source_label(source: object) -> str:
    return {
        "automatic": "automatyczne",
        "official": "z serwisu",
        "file": "plik lokalny",
    }.get(str(source or ""), "brak danych")


@web_bp.post("/subtitles/<path:filename>")
def download_subtitle(filename: str):
    """Check, download, and expose subtitles for one managed preview video."""

    if not _valid_form():
        return {
            "ok": False,
            "message": "Sesja wygasła. Odśwież stronę i spróbuj ponownie.",
        }, 400
    try:
        media_path = _file_service().resolve_download(filename)
    except (FileNotFoundError, UnsafeFilenameError):
        return {"ok": False, "message": "Nie znaleziono pliku wideo."}, 404
    if not (mimetypes.guess_type(media_path.name)[0] or "").startswith("video/"):
        return {"ok": False, "message": "Napisy są dostępne tylko dla plików wideo."}, 400

    source_url = ""
    for record in _completed_job_records():
        if str(record.get("filename") or "") == filename:
            source_url = str(record.get("url") or "")
            break
    if not source_url:
        return {"ok": False, "message": "Nie znaleziono adresu źródłowego dla tego pliku."}, 404

    try:
        _ensure_ytdlp_recent()
        subtitle_result = _media_service().download_subtitle(
            source_url, media_path, mode=request.form.get("mode") or "pl"
        )
    except MediaServiceError as error:
        message = str(error)
        reason = "unavailable" if "napis" in message.casefold() and "udost" in message.casefold() else "error"
        return {"ok": False, "message": message, "reason": reason}, 404 if reason == "unavailable" else 409

    if isinstance(subtitle_result, dict):
        subtitle_path = subtitle_result["path"]
        language = str(subtitle_result.get("language") or "")
        source = str(subtitle_result.get("source") or "")
    else:
        subtitle_path = subtitle_result
        language = ""
        source = "file"
    subtitle_filename = subtitle_path.relative_to(_file_service().download_dir).as_posix()
    return {
        "ok": True,
        "url": ingress_url("web.subtitle", filename=subtitle_filename),
        "label": language.upper() if language else _subtitle_label(subtitle_path, media_path),
        "language": language,
        "source": source,
        "source_label": _subtitle_source_label(source),
    }


@web_bp.get("/subtitles/<path:filename>")
def subtitle(filename: str):
    """Serve one downloaded VTT subtitle file for the preview player."""

    try:
        path = _file_service().resolve_download(filename)
        if path.suffix.casefold() != ".vtt":
            raise UnsafeFilenameError("Niepoprawny format napisów.")
        return send_file(
            path,
            mimetype="text/vtt; charset=utf-8",
            conditional=True,
            download_name=path.name,
        )
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template("error.html", message="Nie znaleziono napisów."), 404


@web_bp.get("/thumbnails/<filename>")
def thumbnail(filename: str):
    """Serve one generated thumbnail without exposing arbitrary files."""

    try:
        path = _file_service().resolve_thumbnail(filename)
        return send_file(path)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template("error.html", message="Nie znaleziono miniatury."), 404


@web_bp.post("/delete/<path:filename>")
def delete(filename: str):
    """Delete one managed file."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    try:
        _file_service().delete_file(filename)
        flash("Plik został usunięty.", "success")
    except FileNotFoundError:
        flash("Plik już nie istnieje.", "warning")
    except UnsafeFilenameError:
        LOGGER.warning("Odrzucono próbę usunięcia niepoprawnej ścieżki")
        flash("Niepoprawna nazwa pliku.", "danger")
    if request.form.get("return_to") == "history":
        return _history_redirect()
    return redirect(ingress_url("web.index"))


@web_bp.post("/history/delete")
def delete_history_record():
    """Delete one download history record without removing its file."""

    if not _valid_form():
        if request.form.get("return_to") == "history":
            return _history_redirect()
        return redirect(ingress_url("web.index"))
    deleted = _file_service().delete_history_record(
        request.form.get("filename", ""),
        request.form.get("downloaded_at", ""),
    )
    if deleted:
        flash("Wpis został usunięty z historii.", "success")
    else:
        flash("Nie znaleziono wpisu w historii.", "warning")
    if request.form.get("return_to") == "history":
        return _history_redirect()
    return redirect(ingress_url("web.index"))


@web_bp.post("/history/tags")
def update_history_tags():
    """Update manual tags for one history record."""

    if not _valid_form():
        return _history_redirect()
    updated = _file_service().update_history_tags(
        request.form.get("filename", ""),
        request.form.get("downloaded_at", ""),
        request.form.get("tags", ""),
    )
    if updated:
        flash("Tagi wpisu zostały zapisane.", "success")
    else:
        flash("Nie znaleziono wpisu do otagowania.", "warning")
    return _history_redirect()


@web_bp.post("/history/bulk")
def bulk_history():
    """Run one action for selected full-history records."""

    if not _valid_form():
        return _history_redirect()
    action = str(request.form.get("action") or "")
    records = _selected_history_records(
        _file_service().history(), request.form.getlist("history_keys")
    )
    if not records:
        flash("Zaznacz wpisy, dla których chcesz wykonać akcję.", "warning")
        return _history_redirect()

    if action == "delete_entries":
        done = 0
        for record in records:
            if _file_service().delete_history_record(
                str(record.get("filename") or ""),
                str(record.get("downloaded_at") or ""),
            ):
                done += 1
        _flash_bulk_history_result(action, done, len(records) - done)
    elif action == "delete_files":
        done = 0
        skipped = 0
        filenames = {
            str(record.get("filename") or "")
            for record in records
            if record.get("filename")
        }
        for filename in filenames:
            try:
                _file_service().delete_file(filename)
                done += 1
            except FileNotFoundError:
                skipped += 1
            except UnsafeFilenameError:
                LOGGER.warning("Odrzucono próbę masowego usunięcia %s", filename)
                skipped += 1
        _flash_bulk_history_result(action, done, skipped)
    elif action == "repeat":
        done = 0
        skipped = 0
        candidates = [
            record for record in records if _history_record_can_repeat(record)
        ]
        if candidates:
            try:
                _ensure_ytdlp_recent()
            except MediaServiceError as error:
                flash(str(error), "danger")
                return _history_redirect()
        for record in records:
            if not _history_record_can_repeat(record):
                skipped += 1
                continue
            try:
                _job_manager().start_download(
                    url=str(record.get("url") or ""),
                    title=str(record.get("title") or ""),
                    download_type=str(record.get("type") or "best"),
                    format_id=record.get("format_id") or None,
                    duration=_duration_value(record.get("duration")),
                )
                done += 1
            except MediaServiceError as error:
                LOGGER.warning("Nie można ponowić pobierania: %s", error)
                skipped += 1
        _flash_bulk_history_result(action, done, skipped)
    else:
        flash("Wybierz poprawną akcję dla zaznaczonych wpisów.", "warning")
    return _history_redirect()


@web_bp.app_errorhandler(404)
def not_found(_: Any):
    return render_template("error.html", message="Nie znaleziono żądanej strony."), 404


@web_bp.app_errorhandler(500)
def server_error(error: Exception):
    LOGGER.exception("Błąd serwera", exc_info=error)
    return render_template(
        "error.html", message="Wystąpił wewnętrzny błąd aplikacji."
    ), 500
