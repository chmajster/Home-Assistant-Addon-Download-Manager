"""Focused regressions for the download workspace fixes."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.routes.request_parsing import _bulk_url_candidates


ROOT = Path(__file__).resolve().parents[2]
ADDON_ROOT = ROOT / "youtube_downloader"


class GuiRegressionTestCase(unittest.TestCase):
    def test_backend_preserves_commas_and_semicolons_inside_url(self) -> None:
        signed = "https://example.com/video;token=abc,def?signature=a,b;c"
        other = "https://example.org/other"

        self.assertEqual(_bulk_url_candidates(f"{signed}\n{other}\n{signed}"), [signed, other])

    def test_bootstrap_is_served_locally_at_runtime(self) -> None:
        template = (ADDON_ROOT / "app/templates/base.html").read_text(encoding="utf-8")
        dockerfile = (ADDON_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("cdn.jsdelivr.net/npm/bootstrap", template)
        self.assertIn("vendor/bootstrap/bootstrap.min.css", template)
        self.assertIn("vendor/bootstrap/bootstrap.bundle.min.js", template)
        self.assertIn("raw.githubusercontent.com/twbs/bootstrap/6e1f75f420f68e1d52733b8e407fc7c3766c9dba", dockerfile)

    def test_success_toast_jobs_link_is_contextual(self) -> None:
        template = (ADDON_ROOT / "app/templates/base.html").read_text(encoding="utf-8")

        self.assertIn("show_jobs_link", template)
        self.assertIn("{% if show_jobs_link %}", template)
        self.assertNotIn("{% if category == 'success' %}<a", template)


if __name__ == "__main__":
    unittest.main()
