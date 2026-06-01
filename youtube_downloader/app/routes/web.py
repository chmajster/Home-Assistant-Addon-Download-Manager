"""HTML views and form actions."""

from __future__ import annotations

import logging
from typing import Any

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
from ..services.file_service import FileService, UnsafeFilenameError
from ..services.job_manager import JobManager
from ..services.media_service import MediaService, MediaServiceError

LOGGER = logging.getLogger(__name__)
web_bp = Blueprint("web", __name__)


def _file_service() -> FileService:
    return current_app.extensions["file_service"]


def _media_service() -> MediaService:
    return current_app.extensions["media_service"]


def _job_manager() -> JobManager:
    return current_app.extensions["job_manager"]


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
    """Main panel with URL form and persistent history."""

    file_service = _file_service()
    return render_template(
        "index.html",
        history=file_service.history(),
        files=file_service.list_files(),
        storage=file_service.storage_usage(),
        options=current_app.config["APP_SETTINGS"],
    )


@web_bp.post("/analyze")
def analyze():
    """Extract metadata for one supported public media URL."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("analyze", 6):
        flash("Zbyt wiele prób analizy. Odczekaj chwilę i spróbuj ponownie.", "warning")
        return redirect(ingress_url("web.index"))
    try:
        media = _media_service().analyze(request.form.get("url", ""))
        return render_template("result.html", media=media)
    except MediaServiceError as error:
        return render_template("error.html", message=str(error)), 400


@web_bp.post("/download")
def start_download():
    """Queue a regular video, audio, playlist, or explicit-format download."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("download", 10):
        flash("Zbyt wiele prób uruchomienia pobierania. Odczekaj chwilę.", "warning")
        return redirect(ingress_url("web.jobs"))
    try:
        job = _job_manager().start_download(
            url=request.form.get("url", ""),
            title=request.form.get("title", ""),
            download_type=request.form.get("download_type", "best"),
            format_id=request.form.get("format_id") or None,
        )
        flash(f"Uruchomiono zadanie {job.job_id[:8]}.", "success")
    except MediaServiceError as error:
        flash(str(error), "danger")
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
        media = _media_service().analyze(request.form.get("url", ""))
        if media["content_type"] != "live":
            raise MediaServiceError("Podany adres nie prowadzi do transmisji live.")
        if not media["is_live"]:
            raise MediaServiceError("Ta transmisja jeszcze się nie rozpoczęła.")
        job = _job_manager().start_live(media["url"], media["title"])
        flash(f"Uruchomiono zapis transmisji {job.job_id[:8]}.", "success")
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


@web_bp.get("/jobs")
def jobs():
    """Render active and completed jobs."""

    manager = _job_manager()
    return render_template(
        "jobs.html", jobs=[manager.job_dict(job) for job in manager.list_jobs()]
    )


@web_bp.get("/downloaded/<filename>")
def downloaded(filename: str):
    """Serve one managed downloaded file."""

    try:
        path = _file_service().resolve_download(filename)
        return send_file(path, as_attachment=True, download_name=path.name)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template(
            "error.html", message="Nie znaleziono pobranego pliku."
        ), 404


@web_bp.post("/delete/<filename>")
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
    return redirect(ingress_url("web.index"))


@web_bp.app_errorhandler(404)
def not_found(_: Any):
    return render_template("error.html", message="Nie znaleziono żądanej strony."), 404


@web_bp.app_errorhandler(500)
def server_error(error: Exception):
    LOGGER.exception("Błąd serwera", exc_info=error)
    return render_template(
        "error.html", message="Wystąpił wewnętrzny błąd aplikacji."
    ), 500
