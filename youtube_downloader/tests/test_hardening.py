"""Focused regression tests for runtime hardening features."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.hardening import (
    MIN_EXTERNAL_TOKEN_LENGTH,
    QueueGate,
    RuntimeHardeningOptions,
    _install_external_auth,
    load_runtime_hardening_options,
)
from app.services.job_state import InvalidJobTransition, JobStatus, ensure_job_transition
from flask import Flask, jsonify


class JobStateTestCase(unittest.TestCase):
    def test_expected_transitions_are_allowed(self) -> None:
        for current, target in (
            ("pending", "downloading"),
            ("pending", "waiting"),
            ("downloading", "stopping"),
            ("stopping", "stopped"),
            ("stopping", "completed"),
            ("error", "pending"),
            ("interrupted", "pending"),
        ):
            ensure_job_transition(current, target)

    def test_invalid_terminal_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidJobTransition):
            ensure_job_transition("completed", "downloading")

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(InvalidJobTransition):
            ensure_job_transition("mystery", "pending")


class RuntimeOptionsTestCase(unittest.TestCase):
    def test_runtime_options_are_loaded_without_expanding_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "allow_external_port": True,
                        "external_port": 10001,
                        "external_access_token": "x" * MIN_EXTERNAL_TOKEN_LENGTH,
                        "resume_interrupted_downloads_on_startup": True,
                    }
                ),
                encoding="utf-8",
            )
            options = load_runtime_hardening_options(path)
        self.assertTrue(options.allow_external_port)
        self.assertEqual(options.external_port, 10001)
        self.assertEqual(
            options.external_access_token,
            "x" * MIN_EXTERNAL_TOKEN_LENGTH,
        )
        self.assertTrue(options.resume_interrupted_downloads_on_startup)

    def test_invalid_file_falls_back_to_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "options.json"
            path.write_text("not json", encoding="utf-8")
            options = load_runtime_hardening_options(path)
        self.assertFalse(options.allow_external_port)
        self.assertEqual(options.external_access_token, "")
        self.assertFalse(options.resume_interrupted_downloads_on_startup)


class ExternalAuthenticationTestCase(unittest.TestCase):
    TOKEN = "correct-hardened-token-123456789"

    def _app(self, token: str | None = None) -> Flask:
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.add_url_rule("/", "index", lambda: "ok")
        app.add_url_rule("/health/ready", "ready", lambda: "ready")
        app.add_url_rule(
            "/api/probe",
            "probe",
            lambda: jsonify({"ok": True}),
        )
        _install_external_auth(
            app,
            RuntimeHardeningOptions(
                allow_external_port=True,
                external_port=999,
                external_access_token=self.TOKEN if token is None else token,
            ),
        )
        app.config["TESTING"] = True
        return app

    def test_ingress_listener_is_not_forced_through_external_login(self) -> None:
        response = (
            self._app()
            .test_client()
            .get(
                "/",
                base_url="http://localhost:8099",
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_external_browser_redirect_and_session_login(self) -> None:
        client = self._app().test_client()
        blocked = client.get("/", base_url="http://localhost:999")
        self.assertEqual(blocked.status_code, 302)
        self.assertTrue(blocked.headers["Location"].endswith("/external-login"))

        login = client.post(
            "/external-login",
            data={"token": self.TOKEN},
            base_url="http://localhost:999",
        )
        self.assertEqual(login.status_code, 302)
        allowed = client.get("/", base_url="http://localhost:999")
        self.assertEqual(allowed.status_code, 200)

    def test_external_api_accepts_bearer_and_rejects_missing_token(self) -> None:
        client = self._app().test_client()
        blocked = client.get("/api/probe", base_url="http://localhost:999")
        self.assertEqual(blocked.status_code, 401)
        allowed = client.get(
            "/api/probe",
            headers={"Authorization": f"Bearer {self.TOKEN}"},
            base_url="http://localhost:999",
        )
        self.assertEqual(allowed.status_code, 200)

    def test_external_listener_without_configured_token_fails_closed(self) -> None:
        response = (
            self._app(token="")
            .test_client()
            .get(
                "/api/probe",
                base_url="http://localhost:999",
            )
        )
        self.assertEqual(response.status_code, 503)

    def test_health_probe_remains_public_on_external_listener(self) -> None:
        response = (
            self._app()
            .test_client()
            .get(
                "/health/ready",
                base_url="http://localhost:999",
            )
        )
        self.assertEqual(response.status_code, 200)


class QueueGateTestCase(unittest.TestCase):
    def test_paused_gate_delays_new_regular_worker_until_resume(self) -> None:
        called = threading.Event()
        shutdown_event = threading.Event()

        def run_download(_job_id: str, _stop_event: threading.Event) -> None:
            called.set()

        manager = SimpleNamespace(
            _run_download=run_download,
            _shutdown_event=shutdown_event,
            list_jobs=lambda: [],
            ACTIVE_STATUSES={"pending", "downloading", "stopping", "waiting"},
            max_concurrent_jobs=2,
        )
        gate = QueueGate(manager)
        gate.pause()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=manager._run_download,
            args=("job", stop_event),
        )
        worker.start()
        time.sleep(0.05)
        self.assertFalse(called.is_set())
        self.assertTrue(gate.snapshot()["paused"])

        gate.resume()
        worker.join(timeout=1)
        self.assertTrue(called.is_set())
        self.assertFalse(gate.snapshot()["paused"])

    def test_stop_event_releases_a_paused_worker(self) -> None:
        called = threading.Event()
        manager = SimpleNamespace(
            _run_download=lambda *_args: called.set(),
            _shutdown_event=threading.Event(),
            list_jobs=lambda: [SimpleNamespace(is_live=False, status=JobStatus.PENDING)],
            ACTIVE_STATUSES={"pending", "downloading", "stopping", "waiting"},
            max_concurrent_jobs=1,
        )
        gate = QueueGate(manager)
        gate.pause()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=manager._run_download,
            args=("job", stop_event),
        )
        worker.start()
        stop_event.set()
        worker.join(timeout=1)
        self.assertTrue(called.is_set())


if __name__ == "__main__":
    unittest.main()
