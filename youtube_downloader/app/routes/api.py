"""JSON API and health endpoints."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time

from flask import Blueprint, Response, current_app, jsonify, stream_with_context

from ..i18n import localize_job
from ..services.job_manager import JobManager

api_bp = Blueprint("api", __name__)
SSE_STREAM_LIMIT = 2
_SSE_STREAM_SLOTS = threading.BoundedSemaphore(SSE_STREAM_LIMIT)


def _job_manager() -> JobManager:
    return current_app.extensions["job_manager"]


def _localized_jobs(manager: JobManager) -> list[dict[str, object]]:
    language = current_app.config["APP_SETTINGS"].ui_language
    return [localize_job(manager.job_dict(job), language) for job in manager.list_jobs()]


@api_bp.get("/api/jobs")
@api_bp.get("/api/v1/jobs")
def jobs_list():
    """Return all in-memory jobs for polling clients."""

    manager = _job_manager()
    response = jsonify({"jobs": _localized_jobs(manager)})
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/api/jobs/<job_id>")
@api_bp.get("/api/v1/jobs/<job_id>")
def job_status(job_id: str):
    """Return one job state."""

    manager = _job_manager()
    language = current_app.config["APP_SETTINGS"].ui_language
    try:
        response = jsonify(localize_job(manager.job_dict(manager.get_job(job_id)), language))
        response.headers["Cache-Control"] = "no-store"
        return response
    except KeyError:
        return jsonify({"error": "Nie znaleziono zadania."}), 404


@api_bp.get("/api/events")
@api_bp.get("/api/v1/events")
def job_events():
    """Stream changed job/queue snapshots over Server-Sent Events."""

    if not _SSE_STREAM_SLOTS.acquire(blocking=False):
        response = jsonify(
            {
                "error": (
                    "Osiągnięto limit aktywnych strumieni zdarzeń. "
                    "Spróbuj ponownie za kilka sekund."
                )
            }
        )
        response.status_code = 503
        response.headers["Retry-After"] = "3"
        response.headers["Cache-Control"] = "no-store"
        return response

    manager = _job_manager()
    language = current_app.config["APP_SETTINGS"].ui_language
    queue_gate = current_app.extensions.get("queue_gate")

    @stream_with_context
    def stream():
        previous = ""
        event_id = 0
        last_keepalive = 0.0
        yield "retry: 3000\n\n"
        while not manager._shutdown_event.is_set():
            jobs = [localize_job(manager.job_dict(job), language) for job in manager.list_jobs()]
            payload: dict[str, object] = {"jobs": jobs}
            if queue_gate is not None:
                payload["queue"] = queue_gate.snapshot(manager)
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            now = time.monotonic()
            if serialized != previous:
                event_id += 1
                previous = serialized
                last_keepalive = now
                yield f"id: {event_id}\nevent: snapshot\ndata: {serialized}\n\n"
            elif now - last_keepalive >= 15:
                last_keepalive = now
                yield ": keepalive\n\n"
            time.sleep(1)

    response = Response(stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store"
    response.headers["X-Accel-Buffering"] = "no"
    response.call_on_close(_SSE_STREAM_SLOTS.release)
    return response


@api_bp.get("/api/home-assistant/state")
@api_bp.get("/api/v1/home-assistant/state")
def home_assistant_state():
    """Expose stable values suitable for HA REST sensors."""
    manager = _job_manager()
    jobs = manager.list_jobs()
    active = [job for job in jobs if job.status in manager.ACTIVE_STATUSES]
    queued = [job for job in jobs if job.status in {"pending", "waiting"}]
    finished = [job for job in jobs if job.status in manager.REMOVABLE_STATUSES]
    finished.sort(key=lambda job: job.finished_at or job.created_at, reverse=True)
    storage = current_app.extensions["file_service"].storage_usage()
    try:
        database_ready = manager.state_store.quick_check() == "ok"
    except Exception:
        database_ready = False
    ready = database_ready and not manager._shutdown_event.is_set()
    last = finished[0] if finished else None
    return jsonify(
        {
            "sensor.download_manager_active_jobs": len(active),
            "sensor.download_manager_queue_size": len(queued),
            "sensor.download_manager_storage_free": storage.get("free"),
            "sensor.download_manager_last_result": (
                {
                    "job_id": last.job_id,
                    "title": last.title,
                    "status": last.status,
                    "filename": last.output_file,
                    "error_code": last.error_code,
                }
                if last
                else None
            ),
            "binary_sensor.download_manager_ready": ready,
        }
    )


@api_bp.get("/health")
def health():
    """Compatibility alias for the readiness probe."""

    return health_ready()


@api_bp.get("/health/live")
def health_live():
    """Report only that the Flask worker is serving requests."""

    return jsonify({"status": "ok"})


@api_bp.get("/health/ready")
def health_ready():
    """Check dependencies required to accept and persist download jobs."""
    manager = _job_manager()
    settings = current_app.config["APP_SETTINGS"]
    checks: dict[str, str] = {}
    try:
        checks["database"] = "ok" if manager.state_store.quick_check() == "ok" else "error"
    except Exception:
        checks["database"] = "error"
    checks["yt_dlp"] = "ok" if shutil.which("yt-dlp") else "error"
    checks["ffmpeg"] = "ok" if shutil.which("ffmpeg") else "error"
    checks["ffprobe"] = "ok" if shutil.which("ffprobe") else "error"
    storage = settings.download_dir
    checks["storage_read"] = "ok" if storage.is_dir() and os.access(storage, os.R_OK) else "error"
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".health-", dir=storage)
        os.close(descriptor)
        os.unlink(probe)
        checks["storage_write"] = "ok"
    except OSError:
        checks["storage_write"] = "error"
    checks["job_manager"] = "error" if manager._shutdown_complete else "ok"
    checks["shutdown"] = "error" if manager._shutdown_event.is_set() else "ok"
    status = "ok" if all(value == "ok" for value in checks.values()) else "error"
    return jsonify({"status": status, "checks": checks}), 200 if status == "ok" else 503
