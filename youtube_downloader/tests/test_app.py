"""Regression tests for routes and URL safety."""

from __future__ import annotations

import errno
import tempfile
import threading
import time
import unittest
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
from app.services.job_manager import JobManager
from app.services.media_service import MediaService, MediaServiceError


class ApplicationTestCase(unittest.TestCase):
    """Exercise behavior that must keep working behind Home Assistant Ingress."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = SimpleNamespace(
            storage_mode="local",
            download_dir=root / "downloads",
            nfs_download_dir=root / "nfs",
            jobs_dir=root / "jobs",
            history_file=root / "jobs" / "history.json",
            max_concurrent_jobs=2,
            update_ytdlp_on_start=False,
            allow_external_port=False,
            external_port=8099,
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
        finally:
            response.close()

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
        self.assertIn("hero-input-group", body)

    def test_base_exposes_frontend_configuration(self) -> None:
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="allowed-hosts"', body)
        self.assertIn("www.youtube.com", body)
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
        self.assertIn(">Pobierz ponownie</button>", body)
        self.assertIn('name="url" value="https://youtu.be/example"', body)
        self.assertIn('name="download_type" value="best"', body)

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
        self.assertIn('<option value="video-1080">1080p</option>', body)
        self.assertIn('<option value="video-720">720p</option>', body)
        self.assertIn('<option value="video-360">360p</option>', body)


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

    def live_command(self, url: str) -> list[str]:
        return ["/venv/bin/python", "-m", "yt_dlp", url]


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
        self.manager = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        )

    def tearDown(self) -> None:
        self.manager._executor.shutdown()
        self.thumbnail_patcher.stop()
        self.temp_dir.cleanup()

    def test_regular_download_completes_and_is_recorded(self) -> None:
        job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
        completed = self._wait_for_status(job.job_id, "completed")
        self.assertEqual(completed.progress, 100.0)
        self.assertEqual(completed.output_file, "example.mp4")
        self.assertEqual(completed.downloaded_bytes, 5)
        self.assertEqual(completed.total_bytes, 5)
        self.assertEqual(self.files.history()[0]["title"], "Example")
        self.assertEqual(self.files.history()[0]["size"], 5)
        self.thumbnail_generator.assert_called_once_with("example.mp4")
        restored = JobManager(
            FakeMediaService(self.download_dir), self.files, max_concurrent_jobs=1
        )
        self.assertEqual(restored.get_job(job.job_id).status, "completed")

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

    def test_disk_full_error_is_visible_on_job(self) -> None:
        error = OSError(errno.ENOSPC, "No space left on device")
        with patch.object(self.manager.media_service, "download", side_effect=error):
            job = self.manager.start_download("https://youtu.be/abc", "Example", "best")
            failed = self._wait_for_status(job.job_id, "error")
        self.assertEqual(failed.error_message, STORAGE_ERROR_MESSAGE)

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
