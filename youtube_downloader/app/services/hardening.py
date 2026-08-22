"""Runtime hardening layered on top of the core download manager."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
)

from .job_state import JobStatus, ensure_job_transition

LOGGER = logging.getLogger(__name__)
OPTIONS_FILE = Path("/data/options.json")
EXTERNAL_SESSION_KEY = "_external_access_granted"
MIN_EXTERNAL_TOKEN_LENGTH = 20
PUBLIC_HEALTH_PATHS = {"/health", "/health/live", "/health/ready"}


@dataclass(frozen=True)
class RuntimeHardeningOptions:
    """Options intentionally kept independent from the main config dataclass."""

    allow_external_port: bool = False
    external_port: int = 999
    external_access_token: str = ""
    resume_interrupted_downloads_on_startup: bool = False


def load_runtime_hardening_options(path: Path = OPTIONS_FILE) -> RuntimeHardeningOptions:
    """Read hardening settings directly from Supervisor options with safe defaults."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except OSError, json.JSONDecodeError:
        LOGGER.warning("Nie można odczytać opcji hardeningu; używam bezpiecznych wartości.")
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        external_port = int(payload.get("external_port", 999))
    except TypeError, ValueError:
        external_port = 999
    if not 1 <= external_port <= 65535:
        external_port = 999

    token = str(payload.get("external_access_token") or "").strip()
    return RuntimeHardeningOptions(
        allow_external_port=payload.get("allow_external_port") is True,
        external_port=external_port,
        external_access_token=token[:512],
        resume_interrupted_downloads_on_startup=(
            payload.get("resume_interrupted_downloads_on_startup") is True
        ),
    )


class QueueGate:
    """Pause new regular download workers without touching active transfers or live jobs."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self._paused = False
        self._condition = threading.Condition()
        self._original_run_download: Callable[..., Any] = manager._run_download
        manager._run_download = self._gated_run_download

    def _gated_run_download(self, job_id: str, stop_event: threading.Event) -> Any:
        with self._condition:
            while (
                self._paused
                and not stop_event.is_set()
                and not self.manager._shutdown_event.is_set()
            ):
                self._condition.wait(timeout=0.5)
        return self._original_run_download(job_id, stop_event)

    def pause(self) -> None:
        with self._condition:
            self._paused = True

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def snapshot(self) -> dict[str, Any]:
        jobs = self.manager.list_jobs()
        return {
            "paused": self.paused,
            "pending_regular_jobs": sum(
                1 for job in jobs if not job.is_live and job.status == JobStatus.PENDING
            ),
            "active_jobs": sum(1 for job in jobs if job.status in self.manager.ACTIVE_STATUSES),
            "max_concurrent_jobs": self.manager.max_concurrent_jobs,
        }


def _install_state_guards(manager: Any) -> None:
    """Validate critical transitions without changing the persisted state format."""

    original_start = manager._start
    original_finish = manager._finish
    original_reset_for_retry = manager._reset_for_retry
    original_resume_download = manager.resume_download
    original_stop_download = manager.stop_download
    original_shutdown = manager.shutdown

    def guarded_start(job: Any) -> Any:
        ensure_job_transition(job.status, JobStatus.DOWNLOADING)
        return original_start(job)

    def guarded_finish(job: Any, status: str, error_code: str | None = None) -> Any:
        if (
            manager._shutdown_event.is_set()
            and job.status == JobStatus.INTERRUPTED
            and status == JobStatus.ERROR
        ):
            return original_finish(job, status, error_code=error_code)
        ensure_job_transition(job.status, status)
        return original_finish(job, status, error_code=error_code)

    def guarded_reset_for_retry(job: Any, reset_auto_retry: bool = True) -> Any:
        ensure_job_transition(job.status, JobStatus.PENDING)
        return original_reset_for_retry(job, reset_auto_retry=reset_auto_retry)

    def guarded_resume_download(job_id: str) -> Any:
        job = manager.get_job(job_id)
        ensure_job_transition(job.status, JobStatus.PENDING)
        return original_resume_download(job_id)

    def guarded_stop_download(job_id: str) -> Any:
        job = manager.get_job(job_id)
        if job.status in manager.STOPPABLE_STATUSES and not job.is_live:
            target = JobStatus.STOPPED if job.status == JobStatus.PENDING else JobStatus.STOPPING
            ensure_job_transition(job.status, target)
        return original_stop_download(job_id)

    def guarded_shutdown(timeout: float = 20.0) -> Any:
        for job in manager.list_jobs():
            if job.status in manager.ACTIVE_STATUSES:
                ensure_job_transition(job.status, JobStatus.INTERRUPTED)
        return original_shutdown(timeout=timeout)

    manager._start = guarded_start
    manager._finish = guarded_finish
    manager._reset_for_retry = guarded_reset_for_retry
    manager.resume_download = guarded_resume_download
    manager.stop_download = guarded_stop_download
    manager.shutdown = guarded_shutdown


def _server_port() -> int | None:
    try:
        return int(request.environ.get("SERVER_PORT", ""))
    except TypeError, ValueError:
        return None


def _external_api_token() -> str | None:
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    api_key = request.headers.get("X-API-Key", "").strip()
    return api_key or None


def _token_matches(candidate: str | None, expected: str) -> bool:
    return bool(candidate and expected and secrets.compare_digest(candidate, expected))


def _external_error(message: str, status: int) -> Response:
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        response = jsonify({"error": message})
        response.status_code = status
        return response
    return Response(message, status=status, content_type="text/plain; charset=utf-8")


def _install_external_auth(app: Flask, options: RuntimeHardeningOptions) -> None:
    """Require authentication only on the dedicated non-Ingress listener."""

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.before_request
    def require_external_authentication():
        if not options.allow_external_port:
            return None
        if _server_port() != options.external_port:
            return None
        if request.path in PUBLIC_HEALTH_PATHS or request.path == "/external-login":
            return None
        if len(options.external_access_token) < MIN_EXTERNAL_TOKEN_LENGTH:
            return _external_error(
                "Dostęp zewnętrzny wymaga external_access_token o długości co najmniej 20 znaków.",
                503,
            )
        if session.get(EXTERNAL_SESSION_KEY) is True:
            return None
        if _token_matches(_external_api_token(), options.external_access_token):
            return None
        if request.path.startswith("/api/"):
            return _external_error("Brak poprawnego tokenu dostępu.", 401)
        return redirect("/external-login")

    @app.route("/external-login", methods=["GET", "POST"])
    def external_login():
        if not options.allow_external_port or _server_port() != options.external_port:
            return Response("Not found", status=404)
        if len(options.external_access_token) < MIN_EXTERNAL_TOKEN_LENGTH:
            return _external_error(
                "Skonfiguruj external_access_token przed użyciem portu zewnętrznego.",
                503,
            )
        error = ""
        if request.method == "POST":
            if _token_matches(request.form.get("token"), options.external_access_token):
                session[EXTERNAL_SESSION_KEY] = True
                return redirect("/")
            error = "Niepoprawny token."
        return render_template_string(
            """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Media Web Downloader - logowanie</title>
</head>
<body style="font-family:sans-serif;max-width:32rem;margin:4rem auto;padding:1rem">
  <h1>Dostęp zewnętrzny</h1>
  <p>Podaj token skonfigurowany w opcjach dodatku.</p>
  {% if error %}<p role="alert"><strong>{{ error }}</strong></p>{% endif %}
  <form method="post">
    <label>
      Token
      <input name="token" type="password" autocomplete="current-password" required>
    </label>
    <button type="submit">Zaloguj</button>
  </form>
</body>
</html>
            """,
            error=error,
        )


def _runtime_stage(manager: Any, job: Any) -> str:
    operation = manager.blocking_file_operations().get(job.job_id)
    if operation:
        return operation
    if job.status == JobStatus.WAITING:
        return "waiting-live"
    if job.status == JobStatus.DOWNLOADING:
        return "recording-live" if job.is_live else "downloading"
    if job.status == JobStatus.STOPPING:
        return "stopping"
    return str(job.status)


def _runtime_job(manager: Any, job: Any) -> dict[str, Any]:
    process = manager._live_processes.get(job.job_id) if job.is_live else None
    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": _runtime_stage(manager, job),
        "is_live": job.is_live,
        "pid": process.pid if process and process.poll() is None else None,
        "worker_model": "live-process-group" if job.is_live else "isolated-download-process",
        "progress": job.progress,
        "downloaded_bytes": job.downloaded_bytes,
        "speed": job.speed,
        "eta": job.eta,
        "started_at": job.started_at,
        "retry_attempts": job.auto_retry_attempts,
        "retry_max_attempts": job.auto_retry_max_attempts,
        "next_retry_at": job.next_retry_at,
    }


def _install_runtime_routes(app: Flask, manager: Any, queue_gate: QueueGate) -> None:
    @app.get("/api/runtime")
    def runtime_status():
        response = jsonify(
            {
                "queue": queue_gate.snapshot(),
                "jobs": [_runtime_job(manager, job) for job in manager.list_jobs()],
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/jobs/<job_id>/runtime")
    def runtime_job_status(job_id: str):
        try:
            job = manager.get_job(job_id)
        except KeyError:
            return jsonify({"error": "Nie znaleziono zadania."}), 404
        response = jsonify(_runtime_job(manager, job))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/queue/pause")
    def pause_queue():
        queue_gate.pause()
        return jsonify(queue_gate.snapshot())

    @app.post("/api/queue/resume")
    def resume_queue():
        queue_gate.resume()
        return jsonify(queue_gate.snapshot())


def _resume_interrupted_jobs(manager: Any) -> int:
    resumed = 0
    for job in manager.list_jobs():
        if job.is_live or job.status != JobStatus.INTERRUPTED:
            continue
        try:
            manager.resume_download(job.job_id)
        except Exception as error:  # startup must survive one malformed legacy job
            LOGGER.warning("Nie udało się automatycznie wznowić %s: %s", job.job_id, error)
            continue
        resumed += 1
    if resumed:
        LOGGER.info("Automatycznie wznowiono przerwane pobrania: %s", resumed)
    return resumed


def install_runtime_hardening(app: Flask) -> None:
    """Install security, state guards, queue control and operational diagnostics."""

    if app.extensions.get("runtime_hardening_installed"):
        return

    options = load_runtime_hardening_options()
    manager = app.extensions["job_manager"]
    _install_state_guards(manager)
    queue_gate = QueueGate(manager)
    app.extensions["queue_gate"] = queue_gate
    app.extensions["runtime_hardening_options"] = options
    _install_external_auth(app, options)
    _install_runtime_routes(app, manager, queue_gate)
    app.extensions["runtime_hardening_installed"] = True

    if options.resume_interrupted_downloads_on_startup:
        _resume_interrupted_jobs(manager)
