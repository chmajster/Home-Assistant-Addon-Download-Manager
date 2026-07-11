"""Diagnostics routes."""

from __future__ import annotations

from .shared import *  # noqa: F401,F403

@web_bp.get("/diagnostics")
def diagnostics():
    """Render operational diagnostics for the add-on."""

    return render_template("diagnostics.html", diagnostics=_diagnostics_snapshot())

@web_bp.post("/diagnostics/ytdlp-update")
def diagnostics_ytdlp_update():
    """Run an explicitly requested update only when downloads are idle."""
    if not _valid_form():
        return redirect(ingress_url("web.diagnostics"))
    settings = current_app.config["APP_SETTINGS"]
    if settings.ytdlp_update_mode != "manual":
        flash("Aktualizacja ręczna wymaga trybu manual.", "warning")
    elif any(job.status in JobManager.ACTIVE_STATUSES for job in _job_manager().list_jobs()):
        flash("Nie można aktualizować yt-dlp podczas aktywnych zadań.", "warning")
    else:
        success = _ytdlp_updater().ensure_recent(force=True)
        flash("Aktualizacja yt-dlp zakończona." if success else "Aktualizacja yt-dlp nie powiodła się.",
              "success" if success else "danger")
    return redirect(ingress_url("web.diagnostics"))

@web_bp.app_errorhandler(404)
def not_found(_: Any):
    return render_template("error.html", message="Nie znaleziono żądanej strony."), 404

@web_bp.app_errorhandler(500)
def server_error(error: Exception):
    LOGGER.exception("Błąd serwera", exc_info=error)
    return render_template(
        "error.html", message="Wystąpił wewnętrzny błąd aplikacji."
    ), 500
