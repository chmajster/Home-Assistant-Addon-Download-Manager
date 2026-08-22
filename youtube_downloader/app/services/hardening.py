"""Runtime hardening layered on top of the core download manager."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
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

from .job_state import JobStatus

LOGGER = logging.getLogger(__name__)
OPTIONS_FILE = Path("/data/options.json")
EXTERNAL_SESSION_KEY = "_external_access_granted"
MIN_EXTERNAL_TOKEN_LENGTH = 20
PUBLIC_HEALTH_PATHS = {"/health", "/health/live", "/health/ready"}
EXTERNAL_SESSION_HOURS = 12
EXTERNAL_LOGIN_ATTEMPTS = 10
EXTERNAL_LOGIN_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class RuntimeHardeningOptions:
    """Security/runtime options intentionally independent from the main config dataclass."""

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


def _external_request_key() -> str:
    return request.remote_addr or "unknown"


def _install_external_auth(app: Flask, options: RuntimeHardeningOptions) -> None:
    """Require authentication only on the dedicated non-Ingress listener."""

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=EXTERNAL_SESSION_HOURS)

    @app.before_request
    def require_external_authentication():
        if not options.allow_external_port:
            return None
        if _server_port() != options.external_port:
            return None
        if request.path in PUBLIC_HEALTH_PATHS or request.path in {
            "/external-login",
            "/external-logout",
        }:
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
            limiter = app.extensions.get("request_limiter")
            if limiter and limiter.is_limited(
                _external_request_key(),
                "external-login",
                EXTERNAL_LOGIN_ATTEMPTS,
                EXTERNAL_LOGIN_WINDOW_SECONDS,
            ):
                return _external_error(
                    "Zbyt wiele prób logowania. Spróbuj ponownie za kilka minut.",
                    429,
                )
            if _token_matches(request.form.get("token"), options.external_access_token):
                session.clear()
                session.permanent = True
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

    @app.route("/external-logout", methods=["GET", "POST"])
    def external_logout():
        if not options.allow_external_port or _server_port() != options.external_port:
            return Response("Not found", status=404)
        session.clear()
        return redirect("/external-login")


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


def _install_runtime_routes(app: Flask, manager: Any) -> None:
    queue_gate = manager.queue_gate

    def runtime_payload() -> dict[str, Any]:
        return {
            "queue": queue_gate.snapshot(manager),
            "jobs": [_runtime_job(manager, job) for job in manager.list_jobs()],
        }

    @app.get("/api/runtime")
    @app.get("/api/v1/runtime")
    def runtime_status():
        response = jsonify(runtime_payload())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/jobs/<job_id>/runtime")
    @app.get("/api/v1/jobs/<job_id>/runtime")
    def runtime_job_status(job_id: str):
        try:
            job = manager.get_job(job_id)
        except KeyError:
            return jsonify({"error": "Nie znaleziono zadania."}), 404
        response = jsonify(_runtime_job(manager, job))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/queue/pause")
    @app.post("/api/v1/queue/pause")
    def pause_queue():
        queue_gate.pause()
        return jsonify(queue_gate.snapshot(manager))

    @app.post("/api/queue/resume")
    @app.post("/api/v1/queue/resume")
    def resume_queue():
        queue_gate.resume()
        return jsonify(queue_gate.snapshot(manager))


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
    """Install external authentication, queue control and runtime diagnostics."""

    if app.extensions.get("runtime_hardening_installed"):
        return

    options = load_runtime_hardening_options()
    manager = app.extensions["job_manager"]
    app.extensions["queue_gate"] = manager.queue_gate
    app.extensions["runtime_hardening_options"] = options
    _install_external_auth(app, options)
    _install_runtime_routes(app, manager)
    app.extensions["runtime_hardening_installed"] = True

    if options.resume_interrupted_downloads_on_startup:
        _resume_interrupted_jobs(manager)
