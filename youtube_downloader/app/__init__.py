"""Media Web Downloader add-on application."""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from flask import Flask, request, session, url_for

from .config import AppConfig
from .i18n import download_type_labels, frontend_catalog, status_labels, translate
from .services.file_service import FileService
from .services.ha_notifications import HomeAssistantNotifier
from .services.job_manager import JobManager
from .services.media_service import MediaService
from .services.ytdlp_updater import YtDlpUpdater

LOGGER = logging.getLogger(__name__)
INGRESS_PATH_RE = re.compile(r"^/[A-Za-z0-9/_-]*$")


class RequestLimiter:
    """Small in-memory fixed-window limiter for expensive and mutating requests."""

    def __init__(self) -> None:
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_limited(self, key: str, bucket: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        identity = (key, bucket)
        with self._lock:
            timestamps = self._requests[identity]
            while timestamps and timestamps[0] <= now - window:
                timestamps.popleft()
            if len(timestamps) >= limit:
                return True
            timestamps.append(now)
            return False


def get_ingress_path() -> str:
    """Return a sanitized Ingress prefix supplied by Home Assistant."""

    prefix = request.headers.get("X-Ingress-Path", "").strip()
    if not prefix or prefix == "/":
        return ""
    prefix = "/" + prefix.strip("/")
    if not INGRESS_PATH_RE.fullmatch(prefix):
        LOGGER.warning("Odrzucono niepoprawny nagłówek X-Ingress-Path")
        return ""
    return prefix


def ingress_url(endpoint: str, **values: object) -> str:
    """Build a URL that works directly and behind Home Assistant Ingress."""

    generated = url_for(endpoint, **values)
    prefix = get_ingress_path()
    if not prefix:
        return generated
    parts = urlsplit(generated)
    return f"{prefix}{parts.path}" + (f"?{parts.query}" if parts.query else "")


def csrf_token() -> str:
    """Create a synchronizer token for HTML form mutations."""

    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return str(token)


def valid_csrf_token(candidate: str | None) -> bool:
    """Check an HTML form token without leaking its value."""

    expected = session.get("_csrf_token")
    return bool(
        expected and candidate and secrets.compare_digest(str(expected), str(candidate))
    )


def create_app() -> Flask:
    """Create and configure the Flask application."""

    settings = AppConfig.load()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__)
    app.config["APP_SETTINGS"] = settings
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.secret_key = settings.secret_key

    file_service = FileService(settings.download_dir, settings.history_file)
    media_service = MediaService(settings.download_dir)
    notifier = HomeAssistantNotifier()
    ytdlp_updater = YtDlpUpdater(settings.jobs_dir / "ytdlp_update.json")
    job_manager = JobManager(
        media_service=media_service,
        file_service=file_service,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        jobs_file=settings.jobs_dir / "queue.json",
        notifier=notifier,
    )

    app.extensions["file_service"] = file_service
    app.extensions["media_service"] = media_service
    app.extensions["job_manager"] = job_manager
    app.extensions["ha_notifier"] = notifier
    app.extensions["ytdlp_updater"] = ytdlp_updater
    app.extensions["request_limiter"] = RequestLimiter()
    ytdlp_updater.start_background()

    from .routes.api import api_bp
    from .routes.web import web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    @app.template_filter("duration")
    def format_duration(value: object) -> str:
        try:
            seconds = int(float(str(value)))
        except (TypeError, ValueError):
            return "brak danych"
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )

    @app.template_filter("filesize")
    def format_filesize(value: object) -> str:
        try:
            size = float(str(value))
        except (TypeError, ValueError):
            return "brak danych"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return "brak danych"

    @app.context_processor
    def inject_helpers() -> dict[str, object]:
        language = settings.ui_language
        return {
            "ingress_url": ingress_url,
            "ingress_path": get_ingress_path(),
            "status_labels": status_labels(language),
            "download_type_labels": download_type_labels(language),
            "csrf_token": csrf_token,
            "app_settings": settings,
            "active_job_statuses": sorted(JobManager.ACTIVE_STATUSES),
            "ui_language": language,
            "ui_translations": frontend_catalog(language),
            "t": lambda key, **values: translate(language, key, **values),
        }

    app.jinja_env.globals.update(
        ui_language=settings.ui_language,
        ui_translations=frontend_catalog(settings.ui_language),
        status_labels=status_labels(settings.ui_language),
        download_type_labels=download_type_labels(settings.ui_language),
        t=lambda key, **values: translate(settings.ui_language, key, **values),
    )

    LOGGER.info(
        "Aplikacja gotowa: download_dir=%s, max_concurrent_jobs=%s",
        settings.download_dir,
        settings.max_concurrent_jobs,
    )
    return app
