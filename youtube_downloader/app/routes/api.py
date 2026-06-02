"""JSON API and health endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..services.job_manager import JobManager

api_bp = Blueprint("api", __name__)


def _job_manager() -> JobManager:
    return current_app.extensions["job_manager"]


@api_bp.get("/api/jobs")
def jobs_list():
    """Return all in-memory jobs for polling clients."""

    manager = _job_manager()
    response = jsonify({"jobs": [manager.job_dict(job) for job in manager.list_jobs()]})
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    """Return one job state."""

    manager = _job_manager()
    try:
        response = jsonify(manager.job_dict(manager.get_job(job_id)))
        response.headers["Cache-Control"] = "no-store"
        return response
    except KeyError:
        return jsonify({"error": "Nie znaleziono zadania."}), 404


@api_bp.get("/health")
def health():
    """Home Assistant watchdog probe."""

    return jsonify({"status": "ok"})
