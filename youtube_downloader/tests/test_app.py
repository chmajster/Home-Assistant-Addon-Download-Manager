"""Regression tests for routes and URL safety."""

from __future__ import annotations

import errno
import json
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app
from app.services.error_messages import (
    FFMPEG_ERROR_MESSAGE,
    INTERNET_ERROR_MESSAGE,
    STORAGE_ERROR_MESSAGE,
    THUMBNAIL_FFMPEG_WARNING,
    THUMBNAIL_STORAGE_WARNING,
)
from app.services.file_service import FileService, ThumbnailResult
from app.services.ha_options import (
    _network_mount_root,
    _validated_storage_mode,
    load_options,
)
from app.services.ha_notifications import HomeAssistantNotifier
from app.services.job_manager import JobManager, now_iso
from app.services.media_service import MediaService, MediaServiceError
from app.services.ytdlp_updater import YtDlpUpdater


class ApplicationTestCase(unittest.TestCase):
    """Exercise behavior that must keep working behind Home Assistant Ingress."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = SimpleNamespace(
            storage_mode="local",
            download_dir=root / "downloads",
            nfs_download_dir=root / "nfs",
            nfs_server="",
            nfs_export_path="",
            nfs_username="",
            nfs_password="",
            nfs_mount_options="vers=4",
            jobs_dir=root / "jobs",
            history_file=root / "jobs" / "history.json",
            max_concurrent_jobs=2,
            allow_external_port=False,
            external_port=999,
            debug=False,
            preferred_format="best",
            secret_key="test-secret",
        )
        with patch("app.AppConfig.load", return_value=settings):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _csrf_token(self) -> str:
        self.client.get("/jobs")
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def test_healthcheck(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_ingress_prefix_is_used_for_generated_links(self) -> None:
        response = self.client.get(
            "/", headers={"X-Ingress-Path": "/api/hassio_ingress/token"}
        )
        body = response.get_data(as_text=True)
        self.assertIn("/api/hassio_ingress/token/static/css/style.css", body)
        self.assertIn("/api/hassio_ingress/token/analyze", body)

    def test_empty_job_api(self) -> None:
        response = self.client.get("/api/jobs")
        self.assertEqual(response.get_json(), {"jobs": []})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_jobs_page_describes_live_refresh(self) -> None:
        body = self.client.get("/jobs").get_data(as_text=True)
        self.assertIn("Status odświeża się na żywo.", body)

    def test_jobs_frontend_uses_live_refresh(self) -> None:
        response = self.client.get("/static/js/app.js")
        try:
            body = response.get_data(as_text=True)
            self.assertIn("jobsViewVisible ? 500 : 2500", body)
            self.assertIn('cache: "no-store"', body)
            self.assertIn('"visibilitychange"', body)
            self.assertIn("selectedJobIds", body)
            self.assertIn("/jobs/delete/", body)
            self.assertIn("/jobs/retry/", body)
            self.assertIn("jobs-retry-failed-form", body)
            self.assertIn("jobs-failed-count", body)
            self.assertIn("data-jobs-filter", body)
            self.assertIn("jobErrorHint", body)
            self.assertIn("job-error-copy", body)
            self.assertIn("copyTextToClipboard", body)
            self.assertIn("navigator.clipboard", body)
            self.assertIn("jobLogBlock", body)
            self.assertIn("log_lines", body)
            self.assertIn("jobAutoRetryBlock", body)
            self.assertIn("next_retry_at", body)
            self.assertIn("auto_retry_attempts", body)
        finally:
            response.close()

    def test_jobs_page_exposes_delete_toolbar(self) -> None:
        body = self.client.get("/jobs").get_data(as_text=True)
        self.assertIn('id="jobs-delete-selected-form"', body)
        self.assertIn('id="jobs-clear-form"', body)
        self.assertIn('id="jobs-select-all"', body)
        self.assertIn('id="jobs-retry-failed-form"', body)
        self.assertIn('id="jobs-failed-count"', body)
        self.assertIn('id="jobs-filter-errors"', body)
        self.assertIn('id="jobs-error-panel"', body)
        self.assertIn('id="jobs-select-errors"', body)
        self.assertIn('id="jobs-filter-empty"', body)

    def test_jobs_page_can_open_error_filter(self) -> None:
        body = self.client.get("/jobs", query_string={"filter": "errors"}).get_data(
            as_text=True
        )
        self.assertIn('id="jobs-filter-state" data-initial-filter="errors"', body)

    def test_inactive_job_can_be_deleted_from_jobs_page(self) -> None:
        manager = self.app.extensions["job_manager"]
        job = manager._new_job("https://youtu.be/abc", "Example", "best", is_live=False)
        manager.stop_download(job.job_id)
        response = self.client.post(
            f"/jobs/delete/{job.job_id}",
            data={"_csrf_token": self._csrf_token()},
            follow_redirects=True,
        )
        self.assertEqual(manager.list_jobs(), [])
        self.assertIn("Zadanie zostało usunięte.", response.get_data(as_text=True))

    def test_selected_jobs_can_be_deleted_from_jobs_page(self) -> None:
        manager = self.app.extensions["job_manager"]
        jobs = [
            manager._new_job("https://youtu.be/abc", "Example", "best", is_live=False)
            for _ in range(2)
        ]
        for job in jobs:
            manager.stop_download(job.job_id)
        response = self.client.post(
            "/jobs/delete",
            data={
                "_csrf_token": self._csrf_token(),
                "job_ids": [job.job_id for job in jobs],
            },
            follow_redirects=True,
        )
        self.assertEqual(manager.list_jobs(), [])
        self.assertIn("Usunięto zadania: 2.", response.get_data(as_text=True))

    def test_clear_jobs_preserves_active_records(self) -> None:
        manager = self.app.extensions["job_manager"]
        active = manager._new_job(
            "https://youtu.be/active", "Active", "best", is_live=False
        )
        inactive = manager._new_job(
            "https://youtu.be/done", "Done", "best", is_live=False
        )
        manager.stop_download(inactive.job_id)
        response = self.client.post(
            "/jobs/clear",
            data={"_csrf_token": self._csrf_token()},
            follow_redirects=True,
        )
        self.assertEqual([job.job_id for job in manager.list_jobs()], [active.job_id])
        self.assertIn("Pominięto aktywne zadania: 1.", response.get_data(as_text=True))

    def test_failed_jobs_can_be_retried_from_jobs_page(self) -> None:
        class FakeUpdater:
            calls = 0

            def ensure_recent(self) -> bool:
                self.calls += 1
                return True

        updater = FakeUpdater()
        self.app.extensions["ytdlp_updater"] = updater
        manager = self.app.extensions["job_manager"]
        with patch.object(manager, "retry_failed_jobs", return_value=(2, 1)) as retry:
            response = self.client.post(
                "/jobs/retry-failed",
                data={"_csrf_token": self._csrf_token()},
                follow_redirects=True,
            )

        retry.assert_called_once_with()
        self.assertEqual(updater.calls, 1)
        body = response.get_data(as_text=True)
        self.assertIn("Ponowiono nieudane zadania: 2.", body)
        self.assertIn("Pomini", body)

    def test_one_failed_job_can_be_retried_from_jobs_page(self) -> None:
        class FakeUpdater:
            calls = 0

            def ensure_recent(self) -> bool:
                self.calls += 1
                return True

        updater = FakeUpdater()
        self.app.extensions["ytdlp_updater"] = updater
        manager = self.app.extensions["job_manager"]
        job = manager._new_job(
            "https://youtu.be/abc", "Example", "best", is_live=False
        )
        with patch.object(manager, "retry_job", return_value=job) as retry:
            response = self.client.post(
                f"/jobs/retry/{job.job_id}",
                data={"_csrf_token": self._csrf_token()},
                follow_redirects=False,
            )

        retry.assert_called_once_with(job.job_id)
        self.assertEqual(updater.calls, 1)
        self.assertEqual(response.status_code, 302)
        self.assertIn("filter=errors", response.headers["Location"])

    def test_managed_file_can_be_downloaded(self) -> None:
        downloads = self.app.extensions["file_service"].download_dir
        expected = downloads / "example.txt"
        expected.write_text("ok", encoding="utf-8")
        response = self.client.get("/downloaded/example.txt")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), "ok")
        finally:
            response.close()

    def test_managed_file_can_be_opened_in_preview(self) -> None:
        files = self.app.extensions["file_service"]
        expected = files.download_dir / "example.mp4"
        expected.write_bytes(b"media")
        files.record_download(
            "Example video",
            "https://youtu.be/example",
            "best",
            expected.name,
            "completed",
        )
        body = self.client.get("/view/example.mp4").get_data(as_text=True)
        self.assertIn("Example video", body)
        self.assertIn('<video class="preview-player"', body)
        self.assertIn('src="/media/example.mp4"', body)
        self.assertIn('href="/downloaded/example.mp4"', body)
        self.assertIn("Informacje o pliku", body)
        self.assertIn("Rozmiar", body)
        self.assertIn("5.0 B", body)
        self.assertIn("Data pobrania", body)
        self.assertIn("Typ pobrania", body)
        self.assertIn("najlepsza", body)
        self.assertIn("Format pliku", body)
        self.assertIn("video/mp4", body)
        self.assertIn("Status", body)
        self.assertIn("zakończone", body)
        self.assertIn("Źródło", body)
        self.assertIn("https://youtu.be/example", body)

    def test_managed_file_can_be_streamed_inline(self) -> None:
        downloads = self.app.extensions["file_service"].download_dir
        expected = downloads / "example.mp4"
        expected.write_bytes(b"media")
        response = self.client.get("/media/example.mp4")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"media")
            self.assertNotIn("attachment", response.headers.get("Content-Disposition", ""))
        finally:
            response.close()

    def test_generated_thumbnail_can_be_displayed(self) -> None:
        files = self.app.extensions["file_service"]
        expected = files.thumbnail_dir / "example.mp4.jpg"
        expected.write_bytes(b"thumbnail")
        response = self.client.get("/thumbnails/example.mp4.jpg")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"thumbnail")
        finally:
            response.close()

    def test_start_download_checks_ytdlp_update_state(self) -> None:
        class FakeUpdater:
            calls = 0

            def ensure_recent(self) -> bool:
                self.calls += 1
                return True

        updater = FakeUpdater()
        self.app.extensions["ytdlp_updater"] = updater
        manager = self.app.extensions["job_manager"]
        with patch.object(
            manager,
            "start_download",
            return_value=SimpleNamespace(job_id="12345678"),
        ):
            response = self.client.post(
                "/download",
                data={
                    "_csrf_token": self._csrf_token(),
                    "url": "https://youtu.be/example",
                    "title": "Example",
                    "download_type": "best",
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(updater.calls, 1)

    def test_analyze_warns_when_url_was_already_downloaded(self) -> None:
        class FakeUpdater:
            def ensure_recent(self) -> bool:
                return True

        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Existing video",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        self.app.extensions["ytdlp_updater"] = FakeUpdater()
        media = {
            "url": "https://youtu.be/example",
            "platform": "youtube",
            "title": "Existing video",
            "channel": "Channel",
            "channel_id": None,
            "duration": 120,
            "thumbnail": None,
            "content_type": "video",
            "live_status": None,
            "is_live": False,
            "playlist_count": None,
            "entries": [],
            "formats": [],
        }
        with patch.object(self.app.extensions["media_service"], "analyze", return_value=media):
            body = self.client.post(
                "/analyze",
                data={"_csrf_token": self._csrf_token(), "url": media["url"]},
            ).get_data(as_text=True)

        self.assertIn("Możliwy duplikat", body)
        self.assertIn("Ten URL", body)
        self.assertIn("Existing video", body)
        self.assertIn("example.mp4", body)
        self.assertIn('name="allow_duplicate" value="1"', body)

    def test_analyze_warns_when_title_matches_existing_file(self) -> None:
        class FakeUpdater:
            def ensure_recent(self) -> bool:
                return True

        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Same title",
            "https://youtu.be/old",
            "best",
            target.name,
            "completed",
        )
        self.app.extensions["ytdlp_updater"] = FakeUpdater()
        media = {
            "url": "https://youtu.be/new",
            "platform": "youtube",
            "title": "Same title",
            "channel": "Channel",
            "channel_id": None,
            "duration": None,
            "thumbnail": None,
            "content_type": "video",
            "live_status": None,
            "is_live": False,
            "playlist_count": None,
            "entries": [],
            "formats": [],
        }
        with patch.object(self.app.extensions["media_service"], "analyze", return_value=media):
            body = self.client.post(
                "/analyze",
                data={"_csrf_token": self._csrf_token(), "url": media["url"]},
            ).get_data(as_text=True)

        self.assertIn("Możliwy duplikat", body)
        self.assertIn("Podobny tytuł lub plik", body)
        self.assertIn("Same title", body)

    def test_start_download_flashes_duplicate_warning_for_direct_post(self) -> None:
        class FakeUpdater:
            def ensure_recent(self) -> bool:
                return True

        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Existing video",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        self.app.extensions["ytdlp_updater"] = FakeUpdater()
        manager = self.app.extensions["job_manager"]
        with patch.object(
            manager,
            "start_download",
            return_value=SimpleNamespace(job_id="12345678"),
        ):
            body = self.client.post(
                "/download",
                data={
                    "_csrf_token": self._csrf_token(),
                    "url": "https://youtu.be/example",
                    "title": "Existing video",
                    "download_type": "best",
                },
                follow_redirects=True,
            ).get_data(as_text=True)

        self.assertIn("Uwaga: ten URL", body)
        self.assertIn("Uruchomiono zadanie", body)

    def test_start_live_passes_live_from_start_option(self) -> None:
        class FakeUpdater:
            def ensure_recent(self) -> bool:
                return True

        self.app.extensions["ytdlp_updater"] = FakeUpdater()
        media = {
            "url": "https://youtu.be/live",
            "title": "Live",
            "content_type": "live",
            "is_live": True,
        }
        manager = self.app.extensions["job_manager"]
        with (
            patch.object(self.app.extensions["media_service"], "analyze", return_value=media),
            patch.object(
                manager,
                "start_live",
                return_value=SimpleNamespace(job_id="12345678"),
            ) as start_live,
        ):
            response = self.client.post(
                "/live/start",
                data={
                    "_csrf_token": self._csrf_token(),
                    "url": "https://youtu.be/live",
                    "live_from_start": "0",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        start_live.assert_called_once_with(
            "https://youtu.be/live", "Live", live_from_start=False
        )

    def test_watch_live_defaults_to_live_from_start(self) -> None:
        class FakeUpdater:
            def ensure_recent(self) -> bool:
                return True

        self.app.extensions["ytdlp_updater"] = FakeUpdater()
        media = {
            "url": "https://youtu.be/live",
            "title": "Live",
            "content_type": "live",
            "is_live": False,
        }
        manager = self.app.extensions["job_manager"]
        with (
            patch.object(self.app.extensions["media_service"], "analyze", return_value=media),
            patch.object(
                manager,
                "start_live_wait",
                return_value=SimpleNamespace(job_id="12345678"),
            ) as start_live_wait,
        ):
            response = self.client.post(
                "/live/watch",
                data={
                    "_csrf_token": self._csrf_token(),
                    "url": "https://youtu.be/live",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        start_live_wait.assert_called_once_with(
            "https://youtu.be/live", "Live", live_from_start=True
        )

    def test_index_displays_storage_usage(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertIn("Miejsce na dysku", body)
        self.assertIn("Wolne", body)
        self.assertIn("Zajęte", body)
        self.assertIn("Łącznie", body)

    def test_index_displays_modern_media_dashboard(self) -> None:
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertIn("Twoje media.", body)
        self.assertIn("platform-chip platform-youtube", body)
        self.assertIn("platform-chip platform-instagram", body)
        self.assertIn("platform-chip platform-kick", body)
        self.assertIn("platform-chip platform-twitch", body)
        self.assertIn("hero-input-group", body)
        self.assertIn('href="/history"', body)
        self.assertIn('class="col-12 history-panel"', body)
        self.assertNotIn('class="col-lg-7"', body)

    def test_base_exposes_frontend_configuration(self) -> None:
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="allowed-hosts"', body)
        self.assertIn("www.youtube.com", body)
        self.assertIn("www.twitch.tv", body)
        self.assertIn('id="active-job-statuses"', body)
        self.assertIn("downloading", body)

    def test_history_delete_form_contains_filename_and_size(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example video.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example video",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-filename="example video.mp4"', body)
        self.assertIn('data-filesize-label="5.0 B"', body)
        self.assertIn('id="history-type-filter"', body)
        self.assertIn('id="history-status-filter"', body)
        self.assertIn('id="history-pagination"', body)
        self.assertIn('data-history-type="best"', body)
        self.assertIn('data-history-status="completed"', body)
        self.assertIn('class="repeat-download-form"', body)
        self.assertIn('class="history-delete-form"', body)
        self.assertIn(">Pobierz ponownie</button>", body)
        self.assertIn(">Usuń wpis</button>", body)
        self.assertIn(">Usuń plik</button>", body)
        self.assertIn('name="url" value="https://youtu.be/example"', body)
        self.assertIn('name="download_type" value="best"', body)

    def test_history_page_searches_metadata_fields(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example video.mp4"
        target.write_bytes(b"x" * 1536)
        files.record_download(
            "Example video",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
            duration=125,
        )
        record = files.history()[0]

        body = self.client.get("/history").get_data(as_text=True)
        self.assertIn("Wyszukiwarka historii", body)
        self.assertIn("Example video", body)
        self.assertIn("example video.mp4", body)
        self.assertIn("youtube", body)
        self.assertIn("1.5 KB", body)
        self.assertIn("02:05", body)

        for query in (
            "Example video",
            "example video.mp4",
            "youtube",
            "youtu.be/example",
            record["downloaded_at"][:10],
            "1.5 KB",
            "02:05",
        ):
            with self.subTest(query=query):
                result = self.client.get(
                    "/history", query_string={"q": query}
                ).get_data(as_text=True)
                self.assertIn("Example video", result)
                self.assertIn("Wyniki: 1 z 1", result)

        empty = self.client.get("/history", query_string={"q": "missing"}).get_data(
            as_text=True
        )
        self.assertIn("Brak wyników", empty)
        self.assertIn("Wyniki: 0 z 1", empty)

    def test_history_page_sorts_by_supported_fields(self) -> None:
        files = self.app.extensions["file_service"]
        samples = [
            (
                "Beta clip",
                "https://www.twitch.tv/videos/123",
                "beta.mp4",
                b"b" * 30,
                180,
                "2026-03-01T10:00:00+00:00",
            ),
            (
                "Alpha clip",
                "https://youtu.be/alpha",
                "alpha.mp4",
                b"a" * 10,
                60,
                "2026-01-01T10:00:00+00:00",
            ),
            (
                "Gamma clip",
                "https://kick.com/gamma",
                "gamma.mp4",
                b"g" * 20,
                120,
                "2026-02-01T10:00:00+00:00",
            ),
        ]
        for title, url, filename, content, duration, _ in samples:
            target = files.download_dir / filename
            target.write_bytes(content)
            files.record_download(
                title,
                url,
                "best",
                filename,
                "completed",
                duration=duration,
            )
        records = files.history()
        dates_by_filename = {sample[2]: sample[5] for sample in samples}
        for record in records:
            record["downloaded_at"] = dates_by_filename[record["filename"]]
        files._write_history(records)

        cases = [
            ({"sort": "title", "order": "asc"}, ["Alpha clip", "Beta clip", "Gamma clip"]),
            ({"sort": "platform", "order": "asc"}, ["Gamma clip", "Beta clip", "Alpha clip"]),
            ({"sort": "date", "order": "desc"}, ["Beta clip", "Gamma clip", "Alpha clip"]),
            ({"sort": "size", "order": "desc"}, ["Beta clip", "Gamma clip", "Alpha clip"]),
            ({"sort": "duration", "order": "asc"}, ["Alpha clip", "Gamma clip", "Beta clip"]),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                body = self.client.get("/history", query_string=query).get_data(
                    as_text=True
                )
                positions = [body.index(title) for title in expected]
                self.assertEqual(positions, sorted(positions))

    def test_history_page_exposes_bulk_actions(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        record = files.history()[0]

        body = self.client.get("/history").get_data(as_text=True)
        self.assertIn('id="history-bulk-form"', body)
        self.assertIn('id="history-bulk-select-all"', body)
        self.assertIn('id="history-selected-count"', body)
        self.assertIn('name="action"', body)
        self.assertIn('value="delete_entries"', body)
        self.assertIn('value="delete_files"', body)
        self.assertIn('value="repeat"', body)
        self.assertIn('id="history-view"', body)
        self.assertIn('value="gallery"', body)
        self.assertIn('name="history_keys"', body)
        self.assertIn(f'value="{record["downloaded_at"]}"', body)

    def test_history_page_exposes_mini_player_for_local_media(self) -> None:
        files = self.app.extensions["file_service"]
        video = files.download_dir / "example.mp4"
        notes = files.download_dir / "notes.txt"
        video.write_bytes(b"media")
        notes.write_text("notes", encoding="utf-8")
        files.record_download(
            "Example video",
            "https://youtu.be/example",
            "best",
            video.name,
            "completed",
        )
        files.record_download(
            "Notes",
            "https://example.com/notes",
            "format",
            notes.name,
            "completed",
        )

        body = self.client.get("/history").get_data(as_text=True)

        self.assertIn("history-mini-player-toggle", body)
        self.assertIn('data-target="history-player-desktop-', body)
        self.assertIn('aria-controls="history-player-desktop-', body)
        self.assertIn("Odtwórz tutaj", body)
        self.assertIn(
            '<video class="history-mini-player-media" controls preload="metadata" src="/media/example.mp4"></video>',
            body,
        )
        self.assertNotIn("/media/notes.txt", body)

    def test_history_gallery_view_exposes_mini_player(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_bytes(b"media")
        files.record_download(
            "Example gallery",
            "https://youtu.be/example",
            "video-1080",
            target.name,
            "completed",
        )

        body = self.client.get("/history", query_string={"view": "gallery"}).get_data(
            as_text=True
        )

        self.assertIn('id="history-player-gallery-0"', body)
        self.assertIn(
            '<video class="history-mini-player-media" controls preload="metadata" src="/media/example.mp4"></video>',
            body,
        )

    def test_history_frontend_toggles_mini_players(self) -> None:
        script = self.client.get("/static/js/app.js").get_data(as_text=True)

        self.assertIn(".history-mini-player-toggle", script)
        self.assertIn("setMiniPlayerOpen", script)
        self.assertIn("pausePanelMedia", script)
        self.assertIn("Odtwórz tutaj", script)

    def test_history_bulk_delete_records_keeps_files(self) -> None:
        files = self.app.extensions["file_service"]
        first = files.download_dir / "first.mp4"
        second = files.download_dir / "second.mp4"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        files.record_download(
            "First",
            "https://youtu.be/first",
            "best",
            first.name,
            "completed",
        )
        files.record_download(
            "Second",
            "https://youtu.be/second",
            "best",
            second.name,
            "completed",
        )
        selected = next(
            record for record in files.history() if record["filename"] == first.name
        )

        response = self.client.post(
            "/history/bulk",
            data={
                "_csrf_token": self._csrf_token(),
                "action": "delete_entries",
                "history_keys": [selected["downloaded_at"]],
                "return_sort": "date",
                "return_order": "desc",
            },
            follow_redirects=True,
        )

        filenames = {record["filename"] for record in files.history()}
        self.assertEqual(filenames, {second.name})
        self.assertTrue(first.is_file())
        self.assertIn("Usuni", response.get_data(as_text=True))

    def test_history_bulk_delete_files_keeps_records(self) -> None:
        files = self.app.extensions["file_service"]
        first = files.download_dir / "first.mp4"
        second = files.download_dir / "second.mp4"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        files.record_download(
            "First",
            "https://youtu.be/first",
            "best",
            first.name,
            "completed",
        )
        files.record_download(
            "Second",
            "https://youtu.be/second",
            "best",
            second.name,
            "completed",
        )
        selected = [record["downloaded_at"] for record in files.history()]

        self.client.post(
            "/history/bulk",
            data={
                "_csrf_token": self._csrf_token(),
                "action": "delete_files",
                "history_keys": selected,
                "return_sort": "date",
                "return_order": "desc",
            },
        )

        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        history = files.history()
        self.assertEqual(len(history), 2)
        self.assertTrue(all(not record["file_exists"] for record in history))

    def test_history_bulk_repeat_downloads_selected_records(self) -> None:
        class FakeUpdater:
            calls = 0

            def ensure_recent(self) -> bool:
                self.calls += 1
                return True

        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "format",
            target.name,
            "completed",
            format_id="137",
            duration=125,
        )
        record = files.history()[0]
        updater = FakeUpdater()
        self.app.extensions["ytdlp_updater"] = updater
        manager = self.app.extensions["job_manager"]

        with patch.object(
            manager,
            "start_download",
            return_value=SimpleNamespace(job_id="12345678"),
        ) as start_download:
            response = self.client.post(
                "/history/bulk",
                data={
                    "_csrf_token": self._csrf_token(),
                    "action": "repeat",
                    "history_keys": [record["downloaded_at"]],
                    "return_q": "Example",
                    "return_sort": "title",
                    "return_order": "asc",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("q=Example", response.headers["Location"])
        self.assertEqual(updater.calls, 1)
        start_download.assert_called_once_with(
            url="https://youtu.be/example",
            title="Example",
            download_type="format",
            format_id="137",
            duration=125,
        )

    def test_history_tags_can_be_saved_and_searched(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        record = files.history()[0]

        response = self.client.post(
            "/history/tags",
            data={
                "_csrf_token": self._csrf_token(),
                "filename": record["filename"],
                "downloaded_at": record["downloaded_at"],
                "tags": "muzyka, tutoriale; live\nmuzyka",
                "return_q": "Example",
                "return_sort": "title",
                "return_order": "asc",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("q=Example", response.headers["Location"])
        self.assertEqual(files.history()[0]["tags"], ["muzyka", "tutoriale", "live"])

        body = self.client.get("/history", query_string={"q": "tutoriale"}).get_data(
            as_text=True
        )
        self.assertIn("Example", body)
        self.assertIn('value="muzyka, tutoriale, live"', body)
        self.assertIn(
            'class="badge text-bg-light history-tag-link" href="/history?q=tutoriale',
            body,
        )

        empty = self.client.get("/history", query_string={"q": "archiwum"}).get_data(
            as_text=True
        )
        self.assertIn("Brak wyników", empty)

    def test_history_page_exposes_tag_editors(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        record = files.history()[0]
        files.update_history_tags(
            record["filename"],
            record["downloaded_at"],
            "archiwum, live",
        )

        body = self.client.get("/history").get_data(as_text=True)
        self.assertIn('action="/history/tags"', body)
        self.assertIn('name="tags"', body)
        self.assertIn('placeholder="muzyka, tutoriale, live"', body)
        self.assertIn('value="archiwum, live"', body)
        self.assertIn('href="/history?q=archiwum', body)
        self.assertIn('href="/history?q=live', body)

    def test_history_adds_automatic_tags(self) -> None:
        files = self.app.extensions["file_service"]
        samples = [
            (
                "Sound clip",
                "https://youtu.be/audio",
                "audio",
                "audio.mp3",
                "audio",
            ),
            (
                "Twitch HD",
                "https://www.twitch.tv/videos/123",
                "video-1080",
                "twitch.mp4",
                "1080p",
            ),
            (
                "Stream archive",
                "https://kick.com/channel",
                "live",
                "live.mp4",
                "live",
            ),
        ]
        for title, url, download_type, filename, _ in samples:
            target = files.download_dir / filename
            target.write_text("media", encoding="utf-8")
            files.record_download(title, url, download_type, filename, "completed")

        body = self.client.get("/history").get_data(as_text=True)
        for expected_tag in ("youtube", "audio", "twitch", "video", "1080p", "kick", "live"):
            with self.subTest(expected_tag=expected_tag):
                self.assertIn(f'href="/history?q={expected_tag}', body)

        for query, expected_title in (
            ("1080p", "Twitch HD"),
            ("audio", "Sound clip"),
            ("live", "Stream archive"),
        ):
            with self.subTest(query=query):
                result = self.client.get(
                    "/history", query_string={"q": query}
                ).get_data(as_text=True)
                self.assertIn(expected_title, result)

    def test_history_tag_links_filter_by_tag(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://www.twitch.tv/videos/123",
            "video-1080",
            target.name,
            "completed",
        )
        record = files.history()[0]
        files.update_history_tags(record["filename"], record["downloaded_at"], "archiwum")

        body = self.client.get(
            "/history", query_string={"sort": "title", "order": "asc"}
        ).get_data(as_text=True)

        self.assertIn(
            'class="badge text-bg-light history-tag-link" href="/history?q=archiwum&amp;sort=title&amp;order=asc&amp;view=table"',
            body,
        )
        self.assertIn(
            'class="badge text-bg-secondary history-tag-link" href="/history?q=twitch&amp;sort=title&amp;order=asc&amp;view=table"',
            body,
        )

    def test_history_gallery_view_displays_thumbnail_grid(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        thumbnail = files.thumbnail_dir / "example.mp4.jpg"
        thumbnail.write_bytes(b"thumbnail")
        files.record_download(
            "Example gallery",
            "https://youtu.be/example",
            "video-1080",
            target.name,
            "completed",
            thumbnail_filename=thumbnail.name,
        )
        record = files.history()[0]
        files.update_history_tags(record["filename"], record["downloaded_at"], "archiwum")

        body = self.client.get(
            "/history", query_string={"view": "gallery", "sort": "title", "order": "asc"}
        ).get_data(as_text=True)

        self.assertIn('id="history-view"', body)
        self.assertIn('<option value="gallery" selected>Galeria</option>', body)
        self.assertIn('class="history-gallery-grid"', body)
        self.assertIn('class="history-gallery-card"', body)
        self.assertIn('class="history-gallery-thumb"', body)
        self.assertIn('form="history-tags-gallery-0"', body)
        self.assertIn('name="return_view" value="gallery"', body)
        self.assertIn(
            'href="/history?q=archiwum&amp;sort=title&amp;order=asc&amp;view=gallery"',
            body,
        )
        self.assertIn(
            'href="/history?q=1080p&amp;sort=title&amp;order=asc&amp;view=gallery"',
            body,
        )

    def test_history_title_and_thumbnail_open_preview(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        thumbnail = files.thumbnail_dir / "example.mp4.jpg"
        thumbnail.write_bytes(b"thumbnail")
        files.record_download(
            "Example video",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
            thumbnail_filename=thumbnail.name,
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="history-thumbnail-link" href="/view/example.mp4"', body)
        self.assertIn('class="history-title-link d-block" href="/view/example.mp4"', body)
        self.assertIn('href="/downloaded/example.mp4">Pobierz plik</a>', body)

    def test_history_record_can_be_deleted_without_removing_file(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
        )
        record = files.history()[0]
        response = self.client.post(
            "/history/delete",
            data={
                "_csrf_token": self._csrf_token(),
                "filename": record["filename"],
                "downloaded_at": record["downloaded_at"],
            },
            follow_redirects=True,
        )
        self.assertEqual(files.history(), [])
        self.assertTrue(target.is_file())
        self.assertIn(
            "Wpis został usunięty z historii.", response.get_data(as_text=True)
        )

    def test_history_repeat_download_is_available_after_file_deletion(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "video-720",
            target.name,
            "completed",
        )
        files.delete_file(target.name)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn(">Pobierz ponownie</button>", body)
        self.assertIn(">Usuń wpis</button>", body)
        self.assertIn('name="download_type" value="video-720"', body)
        self.assertIn('class="badge text-bg-secondary"', body)

    def test_history_repeat_download_keeps_explicit_format_id(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "format",
            target.name,
            "completed",
            format_id="137",
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('name="download_type" value="format"', body)
        self.assertIn('name="format_id" value="137"', body)

    def test_history_repeat_download_is_hidden_for_legacy_format_without_id(
        self,
    ) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "format",
            target.name,
            "completed",
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn(">Pobierz ponownie</button>", body)

    def test_history_displays_thumbnail_warning(self) -> None:
        files = self.app.extensions["file_service"]
        target = files.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            target.name,
            "completed",
            warning_message=THUMBNAIL_FFMPEG_WARNING,
        )
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn(THUMBNAIL_FFMPEG_WARNING, body)

    def test_result_displays_format_download_button(self) -> None:
        media = {
            "is_live": False,
            "content_type": "video",
            "thumbnail": None,
            "title": "Example",
            "channel": "Channel",
            "channel_id": "channel-id",
            "platform": "youtube",
            "duration": 10,
            "live_status": None,
            "playlist_count": None,
            "formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "resolution": "1080p",
                    "fps": 30,
                    "vcodec": "avc1",
                    "acodec": "none",
                    "filesize": 1024,
                }
            ],
            "entries": [],
            "url": "https://youtu.be/example",
        }
        with self.app.test_request_context("/"):
            body = self.app.jinja_env.get_template("result.html").render(
                media=media,
                app_settings=self.app.config["APP_SETTINGS"],
                ingress_url=lambda endpoint, **values: "/",
                csrf_token=lambda: "token",
                ingress_path="",
                allowed_hosts=[],
                active_job_statuses=[],
            )
        self.assertIn('class="btn btn-sm btn-soft format-download"', body)
        self.assertIn('data-format-id="137"', body)
        self.assertIn('name="duration" value="10"', body)
        self.assertIn('<option value="video-1080">1080p</option>', body)
        self.assertIn('<option value="video-720">720p</option>', body)
        self.assertIn('<option value="video-360">360p</option>', body)

    def test_result_displays_live_wait_action(self) -> None:
        media = {
            "is_live": False,
            "content_type": "live",
            "thumbnail": None,
            "title": "Example live",
            "channel": "Channel",
            "channel_id": "channel-id",
            "platform": "youtube",
            "duration": None,
            "live_status": "is_upcoming",
            "playlist_count": None,
            "formats": [],
            "entries": [],
            "url": "https://youtu.be/example",
        }

        def fake_ingress_url(endpoint: str, **_: object) -> str:
            if endpoint == "web.watch_live":
                return "/live/watch"
            return "/"

        with self.app.test_request_context("/"):
            body = self.app.jinja_env.get_template("result.html").render(
                media=media,
                app_settings=self.app.config["APP_SETTINGS"],
                ingress_url=fake_ingress_url,
                csrf_token=lambda: "token",
                ingress_path="",
                allowed_hosts=[],
                active_job_statuses=[],
            )
        self.assertIn("/live/watch", body)
        self.assertIn("Oczekuj na live", body)
        self.assertIn('name="live_from_start" value="0"', body)
        self.assertIn(
            'type="checkbox" name="live_from_start" value="1" checked', body
        )
        self.assertIn("Pobieraj od początku", body)


class MediaUrlTestCase(unittest.TestCase):
    """Keep extractor input limited to known public YouTube hosts."""

    def test_supported_url_is_normalized(self) -> None:
        url = MediaService.validate_url("HTTPS://WWW.YOUTUBE.COM/watch?v=abc#fragment")
        self.assertEqual(url, "https://www.youtube.com/watch?v=abc")

    def test_non_youtube_domain_is_rejected(self) -> None:
        with self.assertRaises(MediaServiceError):
            MediaService.validate_url("https://example.com/watch?v=abc")

    def test_file_scheme_is_rejected(self) -> None:
        with self.assertRaises(MediaServiceError):
            MediaService.validate_url("file:///etc/passwd")

    def test_youtube_subdomain_confusion_is_rejected(self) -> None:
        with self.assertRaises(MediaServiceError):
            MediaService.validate_url("https://youtube.com.example.org/watch?v=abc")

    def test_youtube_redirect_endpoint_is_rejected(self) -> None:
        with self.assertRaises(MediaServiceError):
            MediaService.validate_url(
                "https://www.youtube.com/redirect?q=https://example.com"
            )

    def test_instagram_reel_is_supported(self) -> None:
        url = MediaService.validate_url("https://www.instagram.com/reel/example/")
        self.assertEqual(url, "https://www.instagram.com/reel/example/")
        self.assertEqual(MediaService.detect_platform(url), "instagram")

    def test_kick_channel_is_supported_for_live_analysis(self) -> None:
        url = MediaService.validate_url("https://kick.com/example-channel")
        self.assertEqual(url, "https://kick.com/example-channel")
        self.assertEqual(MediaService.detect_platform(url), "kick")
        self.assertEqual(
            MediaService.detect_content_type({"is_live": True}, url), "live"
        )

    def test_twitch_channel_vod_and_clip_are_supported(self) -> None:
        channel_url = MediaService.validate_url("https://www.twitch.tv/example")
        self.assertEqual(channel_url, "https://www.twitch.tv/example")
        self.assertEqual(MediaService.detect_platform(channel_url), "twitch")
        self.assertEqual(
            MediaService.detect_content_type({"is_live": True}, channel_url), "live"
        )

        vod_url = MediaService.validate_url("https://www.twitch.tv/videos/123456")
        self.assertEqual(vod_url, "https://www.twitch.tv/videos/123456")
        self.assertEqual(MediaService.detect_platform(vod_url), "twitch")

        clip_url = MediaService.validate_url("https://clips.twitch.tv/ExampleClip")
        self.assertEqual(clip_url, "https://clips.twitch.tv/ExampleClip")
        self.assertEqual(MediaService.detect_platform(clip_url), "twitch")

    def test_live_command_can_start_from_beginning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MediaService(Path(temp_dir))
            command = service.live_command(
                "https://youtu.be/live", live_from_start=True
            )
            command_without_start = service.live_command(
                "https://youtu.be/live", live_from_start=False
            )

        self.assertIn("--live-from-start", command)
        self.assertNotIn("--live-from-start", command_without_start)
        self.assertEqual(command[-1], "https://youtu.be/live")
        self.assertEqual(command_without_start[-1], "https://youtu.be/live")


class MediaFormatSelectionTestCase(unittest.TestCase):
    """Map simple quality choices to controlled yt-dlp selectors."""

    def test_best_quality_has_no_height_limit(self) -> None:
        selection, postprocessors = MediaService.format_selection("best")
        self.assertEqual(selection, "bestvideo*+bestaudio/best")
        self.assertEqual(postprocessors, [])

    def test_simple_video_quality_limits_height(self) -> None:
        for download_type, height in (
            ("video-360", 360),
            ("video-720", 720),
            ("video-1080", 1080),
        ):
            with self.subTest(download_type=download_type):
                selection, postprocessors = MediaService.format_selection(download_type)
                self.assertEqual(
                    selection,
                    f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]",
                )
                self.assertEqual(postprocessors, [])

    def test_legacy_video_variant_still_uses_best_quality(self) -> None:
        selection, _ = MediaService.format_selection("video")
        self.assertEqual(selection, "bestvideo*+bestaudio/best")

    def test_storyboard_format_id_is_rejected(self) -> None:
        with self.assertRaises(MediaServiceError):
            MediaService.format_selection("format", "sb0")

    def test_storyboard_formats_are_hidden_from_analysis(self) -> None:
        media = MediaService(Path.cwd())._normalize_info(
            {
                "id": "example",
                "formats": [
                    {
                        "format_id": "sb0",
                        "ext": "mhtml",
                        "resolution": "320x180",
                        "vcodec": "none",
                        "acodec": "none",
                    },
                    {
                        "format_id": "sb-custom",
                        "ext": "mhtml",
                        "protocol": "mhtml",
                    },
                    {
                        "format_id": "137",
                        "ext": "mp4",
                        "resolution": "1920x1080",
                        "vcodec": "avc1",
                        "acodec": "none",
                    },
                ],
            },
            "https://youtu.be/example",
        )
        self.assertEqual([item["format_id"] for item in media["formats"]], ["137"])


class MediaErrorMessageTestCase(unittest.TestCase):
    """Convert common operational failures into useful user-facing messages."""

    def test_network_error_is_explained(self) -> None:
        self.assertEqual(
            MediaService.polish_error("Unable to download webpage: timed out"),
            INTERNET_ERROR_MESSAGE,
        )

    def test_missing_disk_space_is_explained(self) -> None:
        self.assertEqual(
            MediaService.polish_error("[Errno 28] No space left on device"),
            STORAGE_ERROR_MESSAGE,
        )

    def test_ffmpeg_error_is_explained(self) -> None:
        self.assertEqual(
            MediaService.polish_error(
                "ERROR: Postprocessing: ffmpeg conversion failed"
            ),
            FFMPEG_ERROR_MESSAGE,
        )


class HomeAssistantOptionsTestCase(unittest.TestCase):
    """Validate Home Assistant network-storage option helpers."""

    def test_nfs_mount_root_is_first_media_directory(self) -> None:
        self.assertEqual(
            _network_mount_root(Path("/media/nas/youtube_downloader")),
            Path("/media/nas"),
        )

    def test_nfs_mount_root_rejects_media_root(self) -> None:
        with self.assertRaises(ValueError):
            _network_mount_root(Path("/media"))

    def test_unknown_storage_mode_falls_back_to_local(self) -> None:
        self.assertEqual(_validated_storage_mode("unknown"), "local")

    def test_legacy_preferred_video_format_is_migrated_to_best(self) -> None:
        with patch(
            "app.services.ha_options._read_json",
            return_value={"preferred_format": "video"},
        ):
            self.assertEqual(load_options().preferred_format, "best")


class HomeAssistantNotifierTestCase(unittest.TestCase):
    """Format Home Assistant persistent notifications."""

    def test_completed_job_notification_is_sent_to_home_assistant(self) -> None:
        notifier = HomeAssistantNotifier(token="token", base_url="http://ha", timeout=1)
        job = SimpleNamespace(
            job_id="abcdef1234567890",
            status="completed",
            title="Example",
            download_type="best",
            output_file="example.mp4",
            output_files=["example.mp4"],
        )
        requests = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        with patch("app.services.ha_notifications.threading.Thread") as thread:
            thread.side_effect = lambda target, args, **_: SimpleNamespace(
                start=lambda: target(*args)
            )
            with patch("app.services.ha_notifications.urllib.request.urlopen", fake_urlopen):
                notifier.notify_job(job)

        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        self.assertEqual(timeout, 1)
        self.assertEqual(
            request.full_url,
            "http://ha/services/persistent_notification/create",
        )
        self.assertEqual(request.headers["Authorization"], "Bearer token")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["title"], "Media Web Downloader: pobieranie zakończone"
        )
        self.assertEqual(
            payload["notification_id"], "media_web_downloader_abcdef123456_completed"
        )
        self.assertIn("Example", payload["message"])
        self.assertIn("example.mp4", payload["message"])


class YtDlpUpdaterTestCase(unittest.TestCase):
    """Track periodic yt-dlp updates without running pip in tests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "ytdlp_update.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _updater(self) -> YtDlpUpdater:
        return YtDlpUpdater(
            self.state_file,
            update_interval=timedelta(hours=24),
            command=["python", "-m", "pip", "install", "--upgrade", "yt-dlp"],
        )

    def test_missing_state_runs_update_and_records_success(self) -> None:
        updater = self._updater()
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch(
            "app.services.ytdlp_updater.subprocess.run", return_value=completed
        ) as run:
            self.assertTrue(updater.ensure_recent())
        run.assert_called_once()
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertIn("last_attempt", state)
        self.assertEqual(state["last_attempt"], state["last_success"])

    def test_recent_success_skips_update(self) -> None:
        now = datetime.now(UTC).isoformat()
        self.state_file.write_text(
            json.dumps({"last_attempt": now, "last_success": now}),
            encoding="utf-8",
        )
        updater = self._updater()
        with patch("app.services.ytdlp_updater.subprocess.run") as run:
            self.assertTrue(updater.ensure_recent())
        run.assert_not_called()

    def test_failed_attempt_after_success_retries_on_next_check(self) -> None:
        state = {
            "last_success": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "last_attempt": datetime.now(UTC).isoformat(),
            "last_error": "network",
        }
        self.state_file.write_text(json.dumps(state), encoding="utf-8")
        updater = self._updater()
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch(
            "app.services.ytdlp_updater.subprocess.run", return_value=completed
        ) as run:
            self.assertTrue(updater.ensure_recent())
        run.assert_called_once()


class FileServiceThumbnailTestCase(unittest.TestCase):
    """Generate and clean up derived video thumbnails."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.files = FileService(root / "downloads", root / "jobs" / "history.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_video_thumbnail_is_generated_recorded_and_deleted(self) -> None:
        video = self.files.download_dir / "example.mp4"
        video.write_bytes(b"video")

        def fake_ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"thumbnail")
            return SimpleNamespace(returncode=0, stderr="")

        with patch("app.services.file_service.subprocess.run", side_effect=fake_ffmpeg):
            thumbnail = self.files.generate_thumbnail(video.name)

        self.assertEqual(thumbnail.filename, "example.mp4.jpg")
        self.assertIsNone(thumbnail.warning_message)
        self.assertEqual(
            self.files.resolve_thumbnail(thumbnail.filename).read_bytes(), b"thumbnail"
        )
        self.assertEqual(
            [item["filename"] for item in self.files.list_files()], ["example.mp4"]
        )
        self.files.record_download(
            "Example",
            "https://youtu.be/example",
            "best",
            video.name,
            "completed",
            thumbnail.filename,
        )
        self.assertTrue(self.files.history()[0]["thumbnail_exists"])
        self.files.delete_file(video.name)
        self.assertFalse(self.files.history()[0]["thumbnail_exists"])

    def test_audio_file_does_not_create_thumbnail(self) -> None:
        audio = self.files.download_dir / "example.mp3"
        audio.write_bytes(b"audio")
        with patch("app.services.file_service.subprocess.run") as ffmpeg:
            result = self.files.generate_thumbnail(audio.name)
        self.assertIsNone(result.filename)
        self.assertIsNone(result.warning_message)
        ffmpeg.assert_not_called()

    def test_short_video_uses_first_frame_as_thumbnail_fallback(self) -> None:
        video = self.files.download_dir / "short.mp4"
        video.write_bytes(b"video")
        calls = 0

        def fake_ffmpeg(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(command[-1]).write_bytes(b"thumbnail")
            return SimpleNamespace(returncode=0 if calls == 2 else 1, stderr="short")

        with patch("app.services.file_service.subprocess.run", side_effect=fake_ffmpeg):
            thumbnail = self.files.generate_thumbnail(video.name)

        self.assertEqual(thumbnail.filename, "short.mp4.jpg")
        self.assertEqual(calls, 2)

    def test_ffmpeg_failure_returns_thumbnail_warning(self) -> None:
        video = self.files.download_dir / "example.mp4"
        video.write_bytes(b"video")
        failed = SimpleNamespace(returncode=1, stderr="ffmpeg conversion failed")
        with patch("app.services.file_service.subprocess.run", return_value=failed):
            result = self.files.generate_thumbnail(video.name)
        self.assertIsNone(result.filename)
        self.assertEqual(result.warning_message, THUMBNAIL_FFMPEG_WARNING)

    def test_disk_full_returns_specific_thumbnail_warning(self) -> None:
        video = self.files.download_dir / "example.mp4"
        video.write_bytes(b"video")
        failed = SimpleNamespace(returncode=1, stderr="No space left on device")
        with patch("app.services.file_service.subprocess.run", return_value=failed):
            result = self.files.generate_thumbnail(video.name)
        self.assertEqual(result.warning_message, THUMBNAIL_STORAGE_WARNING)


class FakeMediaService:
    """Deterministic extractor stand-in for JobManager tests."""

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir

    validate_url = staticmethod(MediaService.validate_url)
    format_selection = staticmethod(MediaService.format_selection)

    def download(self, **kwargs):
        target = self.download_dir / "example.mp4"
        target.write_text("media", encoding="utf-8")
        kwargs["progress_hook"](
            {
                "status": "downloading",
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "speed": 1024,
                "eta": 3,
            }
        )
        kwargs["progress_hook"]({"status": "finished", "filename": str(target)})
        return [target]

    def live_command(self, url: str, live_from_start: bool = True) -> list[str]:
        command = ["/venv/bin/python", "-m", "yt_dlp"]
        if live_from_start:
            command.append("--live-from-start")
        command.append(url)
        return command


class BlockingMediaService(FakeMediaService):
    """Pause the first transfer so stopping can be exercised deterministically."""

    def __init__(self, download_dir: Path) -> None:
        super().__init__(download_dir)
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def download(self, **kwargs):
        self.calls += 1
        target = self.download_dir / "example.mp4"
        kwargs["progress_hook"](
            {"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100}
        )
        if self.calls == 1:
            self.started.set()
            self.release.wait(timeout=2)
            kwargs["progress_hook"](
                {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100}
            )
        target.write_text("media", encoding="utf-8")
        kwargs["progress_hook"]({"status": "finished", "filename": str(target)})
        return [target]


class FlakyMediaService(FakeMediaService):
    """Fail once and then succeed so automatic retry can be tested quickly."""

    def __init__(self, download_dir: Path) -> None:
        super().__init__(download_dir)
        self.calls = 0

    def download(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise MediaServiceError("network")
        return super().download(**kwargs)


class FakeNotifier:
    """Collect notification payloads synchronously for assertions."""

    def __init__(self) -> None:
        self.jobs = []

    def notify_job(self, job) -> None:
        self.jobs.append(job)


class JobManagerTestCase(unittest.TestCase):
    """Exercise queue completion and duplicate-live protection."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.download_dir = root / "downloads"
        self.download_dir.mkdir()
        self.files = FileService(self.download_dir, root / "jobs" / "history.json")
        self.thumbnail_patcher = patch.object(
            self.files, "generate_thumbnail", return_value=ThumbnailResult()
        )
        self.thumbnail_generator = self.thumbnail_patcher.start()
        self.notifier = FakeNotifier()
        self.manager = JobManager(
            FakeMediaService(self.download_dir),
            self.files,
            max_concurrent_jobs=1,
            notifier=self.notifier,
        )

    def tearDown(self) -> None:
        for timer in list(self.manager._retry_timers.values()):
            timer.cancel()
        self.manager._executor.shutdown()
        self.thumbnail_patcher.stop()
        self.temp_dir.cleanup()

    def test_regular_download_completes_and_is_recorded(self) -> None:
        job = self.manager.start_download(
            "https://youtu.be/abc", "Example", "best", duration=125
        )
        completed = self._wait_for_status(job.job_id, "completed")
        self.assertEqual(completed.progress, 100.0)
        self.assertEqual(completed.output_file, "example.mp4")
        self.assertEqual(completed.downloaded_bytes, 5)
        self.assertEqual(completed.total_bytes, 5)
        self.assertTrue(any("[download]" in line for line in completed.log_lines))
        self.assertEqual(self.files.history()[0]["title"], "Example")
        self.assertEqual(self.files.history()[0]["size"], 5)
        self.assertEqual(self.files.history()[0]["duration"], 125)
        self.thumbnail_generator.assert_called_once_with("example.mp4")
        self.assertEqual(len(self.notifier.jobs), 1)
        self.assertEqual(self.notifier.jobs[0].status, "completed")
        self.assertEqual(self.notifier.jobs[0].output_file, "example.mp4")
        restored = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        )
        self.assertEqual(restored.get_job(job.job_id).status, "completed")
        self.assertTrue(restored.get_job(job.job_id).log_lines)

    def test_pending_job_is_restored_as_interrupted(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/abc", "Example", "best", is_live=False
        )
        restored = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        ).get_job(job.job_id)
        self.assertEqual(restored.status, "interrupted")
        self.assertIn("restart", restored.error_message)

    def test_explicit_format_id_is_recorded_in_history(self) -> None:
        job = self.manager.start_download(
            "https://youtu.be/abc", "Example", "format", format_id="137"
        )
        self._wait_for_status(job.job_id, "completed")
        record = self.files.history()[0]
        self.assertEqual(record["type"], "format")
        self.assertEqual(record["format_id"], "137")

    def test_corrupted_persistent_queue_does_not_break_startup(self) -> None:
        self.manager.jobs_file.write_text("{", encoding="utf-8")
        restored = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        )
        self.assertEqual(restored.list_jobs(), [])

    def test_active_job_cannot_be_deleted(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/abc", "Example", "best", is_live=False
        )
        with self.assertRaises(MediaServiceError):
            self.manager.delete_job(job.job_id)

    def test_delete_jobs_removes_inactive_and_preserves_active_records(self) -> None:
        active = self.manager._new_job(
            "https://youtu.be/active", "Active", "best", is_live=False
        )
        inactive = self.manager._new_job(
            "https://youtu.be/done", "Done", "best", is_live=False
        )
        self.manager.stop_download(inactive.job_id)
        self.assertEqual(
            self.manager.delete_jobs([active.job_id, inactive.job_id]), (1, 1)
        )
        self.assertEqual(
            [job.job_id for job in self.manager.list_jobs()], [active.job_id]
        )
        self.assertEqual(self.manager.clear_jobs(), (0, 1))

    def test_disk_full_error_is_visible_on_job(self) -> None:
        error = OSError(errno.ENOSPC, "No space left on device")
        with patch.object(self.manager.media_service, "download", side_effect=error):
            job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
            failed = self._wait_for_status(job.job_id, "error")
        self.assertEqual(failed.error_message, STORAGE_ERROR_MESSAGE)
        self.assertEqual(len(self.notifier.jobs), 1)
        self.assertEqual(self.notifier.jobs[0].status, "error")
        self.assertEqual(self.notifier.jobs[0].error_message, STORAGE_ERROR_MESSAGE)

    def test_failed_download_is_automatically_retried(self) -> None:
        flaky = FlakyMediaService(self.download_dir)
        self.manager.media_service = flaky

        with patch("app.services.job_manager.AUTO_RETRY_DELAY_SECONDS", 0.01):
            job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
            completed = self._wait_for_status(job.job_id, "completed")

        self.assertEqual(flaky.calls, 2)
        self.assertEqual(completed.auto_retry_attempts, 1)
        self.assertEqual(completed.next_retry_at, None)
        self.assertTrue(any("[retry]" in line for line in completed.log_lines))

    def test_failed_downloads_can_be_retried(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/retry", "Retry me", "best", is_live=False
        )
        with self.manager._lock:
            active = self.manager._jobs[job.job_id]
            active.status = "error"
            active.error_message = "network"
            active.finished_at = now_iso()
            self.manager._persist_jobs()

        self.assertEqual(self.manager.retry_failed_jobs(), (1, 0))
        completed = self._wait_for_status(job.job_id, "completed")
        self.assertEqual(completed.error_message, None)
        self.assertEqual(completed.output_file, "example.mp4")

    def test_one_failed_download_can_be_retried(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/retry", "Retry me", "best", is_live=False
        )
        with self.manager._lock:
            active = self.manager._jobs[job.job_id]
            active.status = "error"
            active.error_message = "network"
            active.finished_at = now_iso()
            self.manager._persist_jobs()

        retried = self.manager.retry_job(job.job_id)

        self.assertEqual(retried.status, "pending")
        completed = self._wait_for_status(job.job_id, "completed")
        self.assertEqual(completed.error_message, None)
        self.assertEqual(completed.output_file, "example.mp4")

    def test_retry_failed_jobs_skips_invalid_formats(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/retry", "Retry me", "format", is_live=False
        )
        with self.manager._lock:
            active = self.manager._jobs[job.job_id]
            active.status = "error"
            active.error_message = "missing format id"
            self.manager._persist_jobs()

        self.assertEqual(self.manager.retry_failed_jobs(), (0, 1))
        self.assertEqual(self.manager.get_job(job.job_id).status, "error")

    def test_thumbnail_warning_is_visible_on_completed_job(self) -> None:
        self.thumbnail_generator.return_value = ThumbnailResult(
            warning_message=THUMBNAIL_FFMPEG_WARNING
        )
        job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
        completed = self._wait_for_status(job.job_id, "completed")
        self.assertEqual(completed.warning_message, THUMBNAIL_FFMPEG_WARNING)
        self.assertEqual(
            self.files.history()[0]["warning_message"], THUMBNAIL_FFMPEG_WARNING
        )

    def test_queued_download_can_be_stopped_and_resumed(self) -> None:
        self.manager._slots.acquire()
        try:
            job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
            stopped = self.manager.stop_download(job.job_id)
            self.assertEqual(stopped.status, "stopped")
            resumed = self.manager.resume_download(job.job_id)
            self.assertEqual(resumed.status, "pending")
        finally:
            self.manager._slots.release()
        self.assertEqual(self._wait_for_status(job.job_id, "completed").progress, 100.0)

    def test_explicit_format_is_kept_for_resuming(self) -> None:
        job = self.manager._new_job(
            "https://youtu.be/abc", "Example", "format", is_live=False, format_id="137"
        )
        restored = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        ).get_job(job.job_id)
        self.assertEqual(restored.format_id, "137")

    def test_active_download_can_be_stopped_and_resumed(self) -> None:
        media = BlockingMediaService(self.download_dir)
        manager = JobManager(media, self.files, max_concurrent_jobs=1)
        job = manager.start_download("https://youtu.be/abc", "Example", "best")
        try:
            self.assertTrue(media.started.wait(timeout=2))
            downloading = manager.get_job(job.job_id)
            self.assertEqual(downloading.downloaded_bytes, 25)
            self.assertEqual(downloading.total_bytes, 100)
            self.assertEqual(manager.stop_download(job.job_id).status, "stopping")
            media.release.set()
            self.assertEqual(
                self._wait_for_status(job.job_id, "stopped", manager).status, "stopped"
            )
            self.assertEqual(manager.resume_download(job.job_id).status, "pending")
            self.assertEqual(
                self._wait_for_status(job.job_id, "completed", manager).output_file,
                "example.mp4",
            )
        finally:
            media.release.set()
            manager._executor.shutdown()

    def test_storage_usage_reports_capacity(self) -> None:
        storage = self.files.storage_usage()
        self.assertGreater(storage["total"], 0)
        self.assertGreaterEqual(storage["free"], 0)
        self.assertGreaterEqual(storage["used_percent"], 0)
        self.assertLessEqual(storage["used_percent"], 100)

    def test_duplicate_queued_live_is_rejected(self) -> None:
        self.manager._slots.acquire()
        try:
            job = self.manager.start_live("https://youtu.be/live", "Live")
            with self.assertRaises(MediaServiceError):
                self.manager.start_live("https://youtu.be/live", "Live")
            stopped = self.manager.stop_live(job.job_id)
            self.assertEqual(stopped.status, "stopped")
        finally:
            self.manager._slots.release()

    def test_live_from_start_option_is_stored_on_live_job(self) -> None:
        self.manager._slots.acquire()
        try:
            job = self.manager.start_live(
                "https://youtu.be/live", "Live", live_from_start=False
            )
            stored = self.manager.get_job(job.job_id)
            self.assertFalse(stored.live_from_start)
            stopped = self.manager.stop_live(job.job_id)
            self.assertEqual(stopped.status, "stopped")
        finally:
            self.manager._slots.release()

    def _wait_for_status(self, job_id: str, expected: str, manager=None):
        manager = manager or self.manager
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = manager.get_job(job_id)
            if job.status == expected:
                return job
            time.sleep(0.01)
        self.fail(f"Zadanie {job_id} nie osiągnęło stanu {expected}.")


if __name__ == "__main__":
    unittest.main()
