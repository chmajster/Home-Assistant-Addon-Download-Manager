"""Focused regression tests for runtime hardening features."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.services.hardening import (
    MIN_EXTERNAL_TOKEN_LENGTH,
    RuntimeHardeningOptions,
    _install_external_auth,
    load_runtime_hardening_options,
)
from app.services.job_state import InvalidJobTransition, ensure_job_transition
from app.services.queue_gate import PersistentQueueGate
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

        logout = client.post("/external-logout", base_url="http://localhost:999")
        self.assertEqual(logout.status_code, 302)
        blocked_again = client.get("/", base_url="http://localhost:999")
        self.assertEqual(blocked_again.status_code, 302)

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
        with tempfile.TemporaryDirectory() as temp_dir:
            gate = PersistentQueueGate(Path(temp_dir) / "runtime.json")
            gate.pause()
            called = threading.Event()
            stop_event = threading.Event()
            shutdown_event = threading.Event()

            def worker() -> None:
                gate.wait_until_runnable(stop_event, shutdown_event)
                called.set()

            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.05)
            self.assertFalse(called.is_set())
            self.assertTrue(gate.paused)

            gate.resume()
            thread.join(timeout=1)
            self.assertTrue(called.is_set())
            self.assertFalse(gate.paused)

    def test_stop_event_releases_a_paused_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gate = PersistentQueueGate(Path(temp_dir) / "runtime.json")
            gate.pause()
            called = threading.Event()
            stop_event = threading.Event()
            shutdown_event = threading.Event()

            def worker() -> None:
                gate.wait_until_runnable(stop_event, shutdown_event)
                called.set()

            thread = threading.Thread(target=worker)
            thread.start()
            stop_event.set()
            thread.join(timeout=1)
            self.assertTrue(called.is_set())

    def test_pause_state_survives_gate_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "runtime.json"
            first = PersistentQueueGate(state_path)
            first.pause()
            second = PersistentQueueGate(state_path)
            self.assertTrue(second.paused)
            second.resume()
            third = PersistentQueueGate(state_path)
            self.assertFalse(third.paused)

    def test_pause_cannot_interleave_with_start_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gate = PersistentQueueGate(Path(temp_dir) / "runtime.json")
            pause_done = threading.Event()

            def pause_queue() -> None:
                gate.pause()
                pause_done.set()

            with gate.start_guard() as permitted:
                self.assertTrue(permitted)
                thread = threading.Thread(target=pause_queue)
                thread.start()
                self.assertFalse(pause_done.wait(timeout=0.05))

            self.assertTrue(pause_done.wait(timeout=1))
            thread.join(timeout=1)
            self.assertTrue(gate.paused)

    def test_start_guard_denies_start_when_already_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gate = PersistentQueueGate(Path(temp_dir) / "runtime.json")
            gate.pause()
            with gate.start_guard() as permitted:
                self.assertFalse(permitted)


if __name__ == "__main__":
    unittest.main()
