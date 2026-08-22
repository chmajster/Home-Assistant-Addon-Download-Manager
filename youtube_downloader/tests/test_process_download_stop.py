"""Regression tests for process-backed regular download cancellation."""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.download_worker import main as worker_main
from app.services.file_service import FileService
from app.services.media_service import MediaService
from app.services.process_job_manager import ProcessJobManager


class FakeMediaService:
    """Only provide option inspection needed before the worker starts."""

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir

    validate_url = staticmethod(MediaService.validate_url)

    def download_options(
        self,
        download_type: str,
        format_id: str | None = None,
        download_options: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Mirror the validation hook used by JobManager before queueing."""

        selection, _postprocessors = MediaService.format_selection(
            download_type,
            format_id,
            audio_format=str((download_options or {}).get("audio_format") or "mp3"),
            embed_thumbnail=True,
            add_metadata=True,
        )
        return {
            "format": selection,
            "outtmpl": str(self.download_dir / "%(title)s.%(ext)s"),
        }

    def effective_download_options(
        self,
        url: str,
        download_type: str,
        format_id: str | None = None,
        download_options: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:
        return self.validate_url(url), {
            "format": format_id or download_type,
            "outtmpl": str(self.download_dir / "%(title)s.%(ext)s"),
            "continuedl": True,
        }


class FakeProcess:
    """Stay alive until ProcessJobManager sends the stop signal."""

    pid = 4242

    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class ProcessDownloadStopTestCase(unittest.TestCase):
    def test_active_download_stop_interrupts_isolated_process_and_marks_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            download_dir = root / "downloads"
            download_dir.mkdir()
            files = FileService(download_dir, root / "jobs" / "history.json")
            manager = ProcessJobManager(
                FakeMediaService(download_dir),
                files,
                max_concurrent_jobs=1,
            )
            process = FakeProcess()

            def interrupt(target: FakeProcess) -> None:
                target.returncode = -2

            try:
                with (
                    patch(
                        "app.services.process_job_manager.subprocess.Popen",
                        return_value=process,
                    ) as popen,
                    patch.object(
                        manager,
                        "_interrupt_process",
                        side_effect=interrupt,
                    ) as interrupt_process,
                ):
                    job = manager.start_download(
                        "https://youtu.be/example",
                        "Example",
                        "best",
                    )
                    self._wait_for_status(manager, job.job_id, "downloading")

                    stopping = manager.stop_download(job.job_id)
                    self.assertEqual(stopping.status, "stopping")
                    stopped = self._wait_for_status(manager, job.job_id, "stopped")

                self.assertEqual(stopped.status, "stopped")
                self.assertIsNone(stopped.error_code)
                interrupt_process.assert_called_once_with(process)
                self.assertTrue(popen.call_args.kwargs["start_new_session"])
                self.assertEqual(
                    popen.call_args.args[0][-2:],
                    ["-m", "app.services.download_worker"],
                )
            finally:
                manager.shutdown()

    @staticmethod
    def _wait_for_status(
        manager: ProcessJobManager,
        job_id: str,
        expected: str,
    ):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = manager.get_job(job_id)
            if job.status == expected:
                return job
            time.sleep(0.01)
        raise AssertionError(f"Zadanie {job_id} nie osiągnęło stanu {expected}.")


class DownloadWorkerProtocolTestCase(unittest.TestCase):
    def test_worker_emits_structured_progress_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "example.mp4"
            target.write_bytes(b"media")
            request = {
                "download_dir": str(root),
                "url": "https://youtu.be/example",
                "download_type": "best",
                "format_id": None,
                "download_options": {},
            }
            output = io.StringIO()

            def fake_download(_service, **kwargs):
                kwargs["progress_hook"](
                    {
                        "status": "downloading",
                        "downloaded_bytes": 5,
                        "total_bytes": 10,
                        "info_dict": {"title": "Example"},
                    }
                )
                kwargs["postprocessor_hook"](
                    {
                        "status": "started",
                        "postprocessor": "Merger",
                        "info_dict": {"title": "Example"},
                    }
                )
                return [target]

            with (
                patch(
                    "app.services.download_worker.WorkerMediaService.download",
                    new=fake_download,
                ),
                patch(
                    "app.services.download_worker.sys.stdin",
                    io.StringIO(json.dumps(request) + "\n"),
                ),
                patch(
                    "app.services.download_worker.PROTOCOL_STDOUT",
                    output,
                ),
            ):
                result = worker_main()

            events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
            self.assertEqual(result, 0)
            self.assertEqual(events, ["progress", "postprocessor", "completed"])


if __name__ == "__main__":
    unittest.main()
