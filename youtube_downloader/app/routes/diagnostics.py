"""Diagnostics routes."""

from __future__ import annotations

from .shared import *  # noqa: F401,F403

@web_bp.get("/diagnostics")
def diagnostics():
    """Render operational diagnostics for the add-on."""

    return render_template("diagnostics.html", diagnostics=_diagnostics_snapshot())

@web_bp.app_errorhandler(404)
def not_found(_: Any):
    return render_template("error.html", message="Nie znaleziono ĹĽÄ…danej strony."), 404

@web_bp.app_errorhandler(500)
def server_error(error: Exception):
    LOGGER.exception("BĹ‚Ä…d serwera", exc_info=error)
    return render_template(
        "error.html", message="WystÄ…piĹ‚ wewnÄ™trzny bĹ‚Ä…d aplikacji."
    ), 500
