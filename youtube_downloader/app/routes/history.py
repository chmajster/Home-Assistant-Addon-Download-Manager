"""History routes."""

from __future__ import annotations

from .shared import *  # noqa: F401,F403

@web_bp.get("/history")
def history():
    """Redirect legacy history links to the unified jobs view."""

    return redirect(ingress_url("web.jobs"))

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
        flash("Wpis zostaĹ‚ usuniÄ™ty z historii.", "success")
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
        flash("Tagi wpisu zostaĹ‚y zapisane.", "success")
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
        flash("Zaznacz wpisy, dla ktĂłrych chcesz wykonaÄ‡ akcjÄ™.", "warning")
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
                LOGGER.warning("Odrzucono prĂłbÄ™ masowego usuniÄ™cia %s", filename)
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
                LOGGER.warning("Nie moĹĽna ponowiÄ‡ pobierania: %s", error)
                skipped += 1
        _flash_bulk_history_result(action, done, skipped)
    else:
        flash("Wybierz poprawnÄ… akcjÄ™ dla zaznaczonych wpisĂłw.", "warning")
    return _history_redirect()
