"""Authenticated-by-Ingress host control routes."""

from __future__ import annotations

import logging

from flask import current_app, jsonify, request

from .. import valid_csrf_token
from ..services.host_shutdown import HostShutdownError, HostShutdownService
from .shared import _job_manager, _limited, web_bp

LOGGER = logging.getLogger(__name__)


def _shutdown_service() -> HostShutdownService:
    return current_app.extensions["host_shutdown_service"]


def _shutdown_state() -> dict[str, object]:
    operations = _job_manager().blocking_file_operations()
    return {
        "available": _shutdown_service().available,
        "blocked": bool(operations),
        "blocking_operations": len(operations),
    }


@web_bp.get("/system/shutdown/status")
def shutdown_status():
    """Return whether a critical copy/move operation blocks shutdown."""

    response = jsonify(_shutdown_state())
    response.headers["Cache-Control"] = "no-store"
    return response


@web_bp.post("/system/shutdown")
def shutdown_host():
    """Request host shutdown after rechecking CSRF and critical file operations."""

    if not valid_csrf_token(request.form.get("_csrf_token")):
        return jsonify({"error": "Sesja wygasła. Odśwież stronę i spróbuj ponownie."}), 403
    if _limited("host-shutdown", 6):
        return jsonify({"error": "Zbyt wiele prób wyłączenia. Odczekaj chwilę."}), 429
    state = _shutdown_state()
    if state["blocked"]:
        return jsonify(state), 409
    try:
        _shutdown_service().shutdown()
    except HostShutdownError as error:
        LOGGER.warning("Nie udało się wyłączyć hosta: %s", error)
        return jsonify({"error": str(error)}), 503
    LOGGER.warning("Użytkownik zlecił wyłączenie hosta przez panel dodatku.")
    return jsonify({"accepted": True}), 202
