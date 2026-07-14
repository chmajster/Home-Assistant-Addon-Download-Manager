"""Jobs routes."""

from __future__ import annotations

from .shared import *  # noqa: F401,F403

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

    return_endpoint = "web.jobs" if request.form.get("return_to") == "jobs" else "web.index"
    if not _valid_form():
        return redirect(ingress_url(return_endpoint))
    action = str(request.form.get("action") or "")
    job_ids = list(dict.fromkeys(request.form.getlist("job_ids")))
    if not job_ids:
        flash("Zaznacz wpisy, dla których chcesz wykonać akcję.", "warning")
        return redirect(ingress_url(return_endpoint))

    manager = _job_manager()
    jobs_by_id = {job.job_id: job for job in manager.list_jobs()}
    selected_jobs = [
        jobs_by_id[job_id]
        for job_id in job_ids
        if job_id in jobs_by_id and jobs_by_id[job_id].status == "completed"
    ]
    if not selected_jobs:
        flash("Nie znaleziono zakończonych wpisów do obsłużenia.", "warning")
        return redirect(ingress_url(return_endpoint))

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
                return redirect(ingress_url(return_endpoint))
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
    return redirect(ingress_url(return_endpoint))

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

@web_bp.get("/jobs")
def jobs():
    """Render active and completed jobs."""

    manager = _job_manager()
    allowed_filters = {
        "all",
        "active",
        "queued",
        "completed",
        "errors",
        "stopped",
        "interrupted",
    }
    requested_filter = request.args.get("filter")
    if requested_filter == "in_progress":
        requested_filter = "active"
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

@web_bp.get("/jobs/log/<job_id>.txt")
def job_log_text(job_id: str):
    """Download the retained full SQLite log as a UTF-8 text file."""
    try:
        _job_manager().get_job(job_id)
    except KeyError:
        return render_template("error.html", message="Nie znaleziono zadania."), 404
    content = "\n".join(_job_manager().state_store.job_logs(job_id)) + "\n"
    return current_app.response_class(
        content,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}.log.txt"'},
    )
