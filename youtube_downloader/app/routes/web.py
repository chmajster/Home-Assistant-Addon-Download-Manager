"""HTML views and form actions."""

from __future__ import annotations

import logging
import mimetypes
from datetime import UTC, datetime
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


def _file_service() -> FileService:
    return current_app.extensions["file_service"]


def _media_service() -> MediaService:
    return current_app.extensions["media_service"]


def _job_manager() -> JobManager:
    return current_app.extensions["job_manager"]


def _ytdlp_updater() -> YtDlpUpdater:
    return current_app.extensions["ytdlp_updater"]


def _ensure_ytdlp_recent() -> None:
    _ytdlp_updater().ensure_recent()


def _duration_value(value: object) -> int | None:
    try:
        seconds = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


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

    for record in _file_service().history():
        record_url = _duplicate_url_key(record.get("url"))
        record_title = str(record.get("title") or "")
        filename = str(record.get("filename") or "")
        if record_url == normalized_url:
            add("url", "history", record_title, filename)
        elif title_key and record.get("file_exists") and _duplicate_key(record_title) == title_key:
            add("file", "history", record_title, filename)

    for job in _job_manager().list_jobs():
        if job.status not in JobManager.ACTIVE_STATUSES:
            continue
        if _duplicate_url_key(job.url) == normalized_url:
            add("url", "queue", job.title, job.job_id[:8])
        elif title_key and _duplicate_key(job.title) == title_key:
            add("file", "queue", job.title, job.job_id[:8])
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
    """Main panel with URL form and persistent history."""

    file_service = _file_service()
    return render_template(
        "index.html",
        history=file_service.history(),
        files=file_service.list_files(),
        storage=file_service.storage_usage(),
        options=current_app.config["APP_SETTINGS"],
    )


@web_bp.get("/history")
def history():
    """Searchable full download history."""

    query = request.args.get("q", "").strip()
    sort = _history_sort_key(request.args.get("sort"))
    order = _history_sort_order(request.args.get("order"))
    view = _history_view(request.args.get("view"))
    records = _history_records(_file_service().history())
    filtered = _sort_history(_filter_history(records, query), sort, order)
    return render_template(
        "history.html",
        history=filtered,
        query=query,
        sort=sort,
        order=order,
        view=view,
        sort_labels=HISTORY_SORT_LABELS,
        view_labels=HISTORY_VIEW_LABELS,
        total_history=len(records),
    )


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
        enriched.append(item)
    return enriched


def _history_platform(url: str) -> str:
    try:
        return MediaService.detect_platform(MediaService.validate_url(url))
    except MediaServiceError:
        return "unknown"


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
    query = str(request.form.get("return_q") or "").strip()
    sort = _history_sort_key(request.form.get("return_sort"))
    order = _history_sort_order(request.form.get("return_order"))
    view = _history_view(request.form.get("return_view"))
    values = {"sort": sort, "order": order, "view": view}
    if query:
        values["q"] = query
    return redirect(ingress_url("web.history", **values))


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
    """Extract metadata for one supported public media URL."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    if _limited("analyze", 6):
        flash("Zbyt wiele prób analizy. Odczekaj chwilę i spróbuj ponownie.", "warning")
        return redirect(ingress_url("web.index"))
    try:
        _ensure_ytdlp_recent()
        media = _media_service().analyze(request.form.get("url", ""))
        media["duplicate_warnings"] = _duplicate_download_warnings(
            str(media.get("url") or ""),
            str(media.get("title") or ""),
        )
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
        _ensure_ytdlp_recent()
        if not request.form.get("allow_duplicate"):
            _flash_duplicate_warnings(
                _duplicate_download_warnings(
                    request.form.get("url", ""),
                    request.form.get("title", ""),
                )
            )
        job = _job_manager().start_download(
            url=request.form.get("url", ""),
            title=request.form.get("title", ""),
            download_type=request.form.get("download_type", "best"),
            format_id=request.form.get("format_id") or None,
            duration=_duration_value(request.form.get("duration")),
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
    job_filter = "errors" if request.args.get("filter") == "errors" else "all"
    return render_template(
        "jobs.html",
        jobs=[manager.job_dict(job) for job in manager.list_jobs()],
        job_filter=job_filter,
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


@web_bp.get("/view/<filename>")
def preview(filename: str):
    """Open one managed downloaded file in an inline browser preview."""

    try:
        path = _file_service().resolve_download(filename)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template(
            "error.html", message="Nie znaleziono pobranego pliku."
        ), 404

    record = next(
        (
            item
            for item in _file_service().history()
            if item.get("filename") == path.name
        ),
        {},
    )
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    media_kind = "video" if mime_type.startswith("video/") else "audio"
    if not mime_type.startswith(("video/", "audio/")):
        media_kind = "file"
    stat = path.stat()
    downloaded_at = record.get("downloaded_at") or datetime.fromtimestamp(
        stat.st_mtime, UTC
    ).isoformat()
    return render_template(
        "preview.html",
        title=record.get("title") or path.name,
        filename=path.name,
        mime_type=mime_type,
        media_kind=media_kind,
        file_info={
            "size": stat.st_size,
            "downloaded_at": downloaded_at,
            "source_url": record.get("url"),
            "download_type": record.get("type"),
            "status": record.get("status"),
            "format_id": record.get("format_id"),
        },
    )


@web_bp.get("/media/<filename>")
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


@web_bp.get("/thumbnails/<filename>")
def thumbnail(filename: str):
    """Serve one generated thumbnail without exposing arbitrary files."""

    try:
        path = _file_service().resolve_thumbnail(filename)
        return send_file(path)
    except (FileNotFoundError, UnsafeFilenameError):
        return render_template("error.html", message="Nie znaleziono miniatury."), 404


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


@web_bp.post("/history/delete")
def delete_history_record():
    """Delete one download history record without removing its file."""

    if not _valid_form():
        return redirect(ingress_url("web.index"))
    deleted = _file_service().delete_history_record(
        request.form.get("filename", ""),
        request.form.get("downloaded_at", ""),
    )
    if deleted:
        flash("Wpis został usunięty z historii.", "success")
    else:
        flash("Nie znaleziono wpisu w historii.", "warning")
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
