"""Downloads routes."""

from __future__ import annotations

from .shared import *  # noqa: F401,F403

@web_bp.get("/")
def index():
    """Main panel with URL form and recent completed jobs."""

    file_service = _file_service()
    return render_template(
        "index.html",
        storage=file_service.storage_usage(),
        options=current_app.config["APP_SETTINGS"],
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
        if request.form.get("quick_download") and not format_id and not request.form.get("playlist_picker"):
            media = None
            try:
                media = _media_service().analyze(validated_url)
            except MediaServiceError as error:
                LOGGER.info(
                    "Szybka analiza URL przed pobraniem nie powiodla sie, kontynuuje zwykle pobieranie: %s",
                    error,
                )
            if media and media.get("content_type") == "live" and media.get("is_live"):
                job = _job_manager().start_live(
                    str(media.get("url") or validated_url),
                    str(media.get("title") or title),
                    live_from_start=True,
                )
                flash(
                    f"URL prowadzi do aktywnej transmisji. Uruchomiono zapis od początku {job.job_id[:8]}.",
                    "success",
                )
                return redirect(ingress_url("web.jobs"))
        download_options = _download_options_from_form(
            title if request.form.get("playlist_picker") else None
        )
        duplicate_warnings = _duplicate_download_warnings(
            validated_url,
            title,
            source_id=str(request.form.get("source_id") or "").strip(),
            extractor_key=str(request.form.get("extractor_key") or "").strip(),
        )
        if download_options.get("duplicate_action") == "skip" and duplicate_warnings:
            flash("Pominięto duplikat zgodnie z wybraną polityką.", "info")
            return redirect(ingress_url("web.jobs"))
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
                duplicate_warnings
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
        flash("Zbyt wiele prób importu listy URL. Odczekaj chwilę.", "warning")
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
        flash(f"Pominięto niepoprawne linki: {skipped}.", "warning")
    if not created and not skipped:
        flash("Nie znaleziono linków do importu.", "warning")
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
            "source_thumbnail_exists": enriched_record.get("source_thumbnail_exists"),
            "source_thumbnail_filename": enriched_record.get("source_thumbnail_filename"),
            "thumbnail_types": enriched_record.get("thumbnail_types", {}),
            "storage_name": enriched_record.get("storage_name"),
            "error_code": enriched_record.get("error_code"),
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
    if request.form.get("return_to") == "jobs":
        return redirect(ingress_url("web.jobs"))
    if request.form.get("return_to") == "job_details" and request.form.get("job_id"):
        return redirect(
            ingress_url("web.job_details", job_id=request.form["job_id"])
        )
    return redirect(ingress_url("web.index"))
