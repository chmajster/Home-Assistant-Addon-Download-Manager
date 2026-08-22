"""Regression tests for bounded Server-Sent Events connections."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from app.routes import api as api_module
from flask import Flask


class FakeManager:
    ACTIVE_STATUSES: set[str] = set()
    REMOVABLE_STATUSES: set[str] = set()

    def __init__(self) -> None:
        self._shutdown_event = threading.Event()
        self._shutdown_complete = False

    def list_jobs(self) -> list[object]:
        return []

    def job_dict(self, job: object) -> dict[str, object]:
        return {}


class ApiStreamingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        api_module._SSE_STREAM_SLOTS = threading.BoundedSemaphore(api_module.SSE_STREAM_LIMIT)
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["APP_SETTINGS"] = SimpleNamespace(ui_language="pl")
        self.app.extensions["job_manager"] = FakeManager()
        self.app.register_blueprint(api_module.api_bp)

    def test_sse_limit_preserves_request_capacity(self) -> None:
        responses = []
        try:
            for _ in range(api_module.SSE_STREAM_LIMIT):
                response = self.app.test_client().get("/api/v1/events", buffered=False)
                self.assertEqual(response.status_code, 200)
                responses.append(response)

            blocked = self.app.test_client().get("/api/v1/events", buffered=False)
            self.assertEqual(blocked.status_code, 503)
            self.assertEqual(blocked.headers.get("Retry-After"), "3")

            responses.pop().close()
            replacement = self.app.test_client().get("/api/v1/events", buffered=False)
            self.assertEqual(replacement.status_code, 200)
            replacement.close()
        finally:
            for response in responses:
                response.close()


if __name__ == "__main__":
    unittest.main()
