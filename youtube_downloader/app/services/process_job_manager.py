"""Process-backed JobManager for reliably cancellable regular downloads."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auto_tags import generate_auto_tags
from .error_messages import DOWNLOAD_STOPPED, operational_error_message
from .job_manager import PROGRESS_MIN_DELTA_PERCENT, JobManager
from .media_service import MediaServiceError

LOGGER = logging.getLogger(__name__)
WORKER_POLL_INTERVAL_SECONDS = 0.1


@dataclass
class WorkerOutcome:
    """Result fields reported by one download worker."""

    completed: bool = False
    error_message: str | None = None
    paths: list[str] | None = None


class ProcessJobManager(JobManager):
    """Run regular yt-dlp jobs in isolated process groups so they can be stopped."""

    def _run_download(self, job_id: str, stop_event: threading.Event) -> None:
        process: subprocess.Popen[str] | None = None
        stdout_thread: threading.Thread | None = None
        stderr_thread: threading.Thread | None = None
        stdout_queue: queue.Queue[str] = queue.Queue()
        stderr_queue: queue.Queue[str] = queue.Queue()
        stdout_done = threading.Event()
        outcome = WorkerOutcome()
        stderr_lines: list[str] = []

        try:
            with self._slots:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if not job:
                        return
                    if stop_event.is_set():
                        if self._stop_events.get(job_id) is stop_event:
                            self._finish(
                                job,
                                "interrupted"
                                if self._shutdown_event.is_set()
                                else "stopped",
                                error_code=(
                                    DOWNLOAD_STOPPED
                                    if self._shutdown_event.is_set()
                                    else None
                                ),
                            )
                        return
                    self._start(job)
                    self._append_download_parameters(job)
                    request_payload = self._worker_request(job)

                process = subprocess.Popen(
                    [sys.executable, "-m", "app.services.download_worker"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                assert process.stdin is not None
                assert process.stdout is not None
                assert process.stderr is not None

                process.stdin.write(json.dumps(request_payload, ensure_ascii=False))
                process.stdin.write("\n")
                process.stdin.flush()
                process.stdin.close()

                stdout_thread = threading.Thread(
                    target=self._read_worker_stream,
                    args=(process.stdout, stdout_queue, stdout_done),
                    daemon=True,
                    name=f"download-worker-out-{job_id[:8]}",
                )
                stderr_thread = threading.Thread(
                    target=self._read_worker_stream,
                    args=(process.stderr, stderr_queue, None),
                    daemon=True,
                    name=f"download-worker-err-{job_id[:8]}",
                )
                stdout_thread.start()
                stderr_thread.start()

                stop_signal_sent = False
                while True:
                    self._drain_worker_messages(job_id, stdout_queue, outcome)
                    stderr_lines.extend(
                        self._drain_worker_stderr(job_id, stderr_queue)
                    )

                    if (
                        stop_event.is_set()
                        and not stop_signal_sent
                        and process.poll() is None
                    ):
                        stop_signal_sent = True
                        LOGGER.info(
                            "Przerywam grupę procesów zwykłego pobierania %s (pid=%s)",
                            job_id,
                            process.pid,
                        )
                        self._interrupt_process(process)

                    return_code = process.poll()
                    if return_code is not None and stdout_done.is_set():
                        break
                    time.sleep(WORKER_POLL_INTERVAL_SECONDS)

                if stdout_thread:
                    stdout_thread.join(timeout=1)
                if stderr_thread:
                    stderr_thread.join(timeout=1)
                self._drain_worker_messages(job_id, stdout_queue, outcome)
                stderr_lines.extend(
                    self._drain_worker_stderr(job_id, stderr_queue)
                )

                if process.returncode == 0 and outcome.completed:
                    files = self._record_worker_outputs(job_id, outcome.paths)
                    if not files:
                        raise MediaServiceError(
                            "Pobieranie zakończyło się bez gotowego pliku. "
                            "Sprawdź logi dodatku."
                        )
                    with self._lock:
                        active = self._jobs[job_id]
                        active.output_files = files
                        active.output_file = files[0]
                        active.downloaded_bytes = self._output_size(files)
                        active.total_bytes = active.downloaded_bytes
                        active.progress = 100.0
                        active.auto_tags = generate_auto_tags(
                            active.url,
                            active.download_type,
                            active.metadata,
                            active.is_live,
                        )
                        self._finish(active, "completed")
                    return

                if stop_event.is_set():
                    with self._lock:
                        active = self._jobs.get(job_id)
                        if active:
                            shutdown = self._shutdown_event.is_set()
                            self._finish(
                                active,
                                "interrupted" if shutdown else "stopped",
                                error_code=DOWNLOAD_STOPPED if shutdown else None,
                            )
                    return

                if outcome.error_message:
                    self._fail(job_id, outcome.error_message)
                    return

                if process.returncode != 0:
                    details = " ".join(stderr_lines[-4:]).strip()
                    message = (
                        operational_error_message(details)
                        or self._redact_log_line(details)
                        or f"Proces yt-dlp zakończył się kodem {process.returncode}."
                    )
                    self._fail(job_id, message)
                    return

                self._fail(
                    job_id,
                    "Proces pobierania zakończył się bez potwierdzenia wyniku.",
                )
        except MediaServiceError as error:
            if self._shutdown_event.is_set() or stop_event.is_set():
                with self._lock:
                    active = self._jobs.get(job_id)
                    if active:
                        shutdown = self._shutdown_event.is_set()
                        self._finish(
                            active,
                            "interrupted" if shutdown else "stopped",
                            error_code=DOWNLOAD_STOPPED if shutdown else None,
                        )
                return
            self._fail(job_id, str(error))
        except Exception as error:
            LOGGER.exception("Nieoczekiwany błąd zadania procesowego %s", job_id)
            if self._shutdown_event.is_set() or stop_event.is_set():
                with self._lock:
                    active = self._jobs.get(job_id)
                    if active:
                        shutdown = self._shutdown_event.is_set()
                        self._finish(
                            active,
                            "interrupted" if shutdown else "stopped",
                            error_code=DOWNLOAD_STOPPED if shutdown else None,
                        )
                return
            self._fail(
                job_id,
                operational_error_message(str(error))
                or "Nieoczekiwany błąd podczas pobierania.",
            )
        finally:
            if process and process.poll() is None:
                self._interrupt_process(process)
            with self._lock:
                self._blocking_file_operations.pop(job_id, None)
                if self._stop_events.get(job_id) is stop_event:
                    self._stop_events.pop(job_id, None)

    def _worker_request(self, job: Any) -> dict[str, Any]:
        """Build the JSON request consumed by the isolated worker."""

        return {
            "download_dir": str(self.media_service.download_dir),
            "url": job.url,
            "download_type": job.download_type,
            "format_id": job.format_id,
            "download_options": job.download_options,
        }

    @staticmethod
    def _read_worker_stream(
        stream: Any,
        target: queue.Queue[str],
        done: threading.Event | None,
    ) -> None:
        try:
            for line in stream:
                target.put(line.rstrip("\r\n"))
        finally:
            if done:
                done.set()

    def _drain_worker_messages(
        self,
        job_id: str,
        source: queue.Queue[str],
        outcome: WorkerOutcome,
    ) -> None:
        while True:
            try:
                line = source.get_nowait()
            except queue.Empty:
                return
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                with self._lock:
                    active = self._jobs.get(job_id)
                    if active:
                        self._append_log_line(
                            active,
                            f"[worker] {self._redact_log_line(line)}",
                        )
                continue
            if not isinstance(payload, dict):
                continue

            event = str(payload.get("event") or "")
            data = payload.get("data")
            if event == "progress" and isinstance(data, dict):
                self._handle_worker_progress(job_id, data)
            elif event == "postprocessor" and isinstance(data, dict):
                self._handle_worker_postprocessor(job_id, data)
            elif event == "completed":
                values = payload.get("paths")
                outcome.paths = (
                    [str(value) for value in values if value]
                    if isinstance(values, list)
                    else []
                )
                outcome.completed = True
            elif event == "error":
                message = str(payload.get("message") or "").strip()
                outcome.error_message = (
                    self._redact_log_line(message)
                    if message
                    else "Proces yt-dlp zgłosił błąd bez opisu."
                )

    def _drain_worker_stderr(
        self,
        job_id: str,
        source: queue.Queue[str],
    ) -> list[str]:
        lines: list[str] = []
        while True:
            try:
                line = source.get_nowait()
            except queue.Empty:
                return lines
            cleaned = self._redact_log_line(line.strip())
            if not cleaned:
                continue
            lines.append(cleaned)
            with self._lock:
                active = self._jobs.get(job_id)
                if active:
                    self._append_log_line(active, f"[worker-stderr] {cleaned}")

    def _handle_worker_progress(self, job_id: str, data: dict[str, Any]) -> None:
        info = data.get("info_dict") or {}
        with self._lock:
            active = self._jobs.get(job_id)
            if not active:
                return

            if isinstance(info, dict):
                metadata = self._metadata_snapshot(info)
                if metadata:
                    active.metadata.update(metadata)
                    active.auto_tags = generate_auto_tags(
                        active.url,
                        active.download_type,
                        active.metadata,
                        active.is_live,
                    )

            metadata_title = self._metadata_title(data)
            if metadata_title:
                active.title = metadata_title

            log_line = self._progress_log_line(data)
            new_progress = self._percentage(data)
            if log_line and (
                data.get("status") != "downloading"
                or abs(new_progress - active.progress) >= PROGRESS_MIN_DELTA_PERCENT
            ):
                self._append_log_line(active, log_line)

            if data.get("status") == "downloading":
                active.progress = new_progress
                active.downloaded_bytes = self._byte_count(data.get("downloaded_bytes"))
                active.total_bytes = self._byte_count(
                    data.get("total_bytes") or data.get("total_bytes_estimate")
                )
                active.speed = self._display_speed(data.get("speed"))
                active.eta = self._display_eta(data.get("eta"))
            elif data.get("status") == "finished":
                active.progress = 100.0
            self._persist_progress(
                active,
                force=data.get("status") == "finished",
            )

    def _handle_worker_postprocessor(
        self,
        job_id: str,
        data: dict[str, Any],
    ) -> None:
        with self._lock:
            active = self._jobs.get(job_id)
            if not active:
                return
            operation = self._file_operation_from_hook(data)
            hook_status = str(data.get("status") or "").casefold()
            if operation and hook_status in {"started", "processing"}:
                self._blocking_file_operations[job_id] = operation
            elif operation and hook_status in {"finished", "error"}:
                self._blocking_file_operations.pop(job_id, None)

            metadata_title = self._metadata_title(data)
            if metadata_title:
                active.title = metadata_title
            log_line = self._postprocessor_log_line(data)
            if log_line:
                self._append_log_line(active, log_line)

    def _record_worker_outputs(
        self,
        job_id: str,
        values: list[str] | None,
    ) -> list[str]:
        collected: set[Path] = set()
        for value in values or []:
            try:
                path = Path(value).resolve()
            except (OSError, RuntimeError):
                continue
            if self.file_service.is_managed_file(path):
                collected.add(path)
        return self._record_existing_outputs(job_id, collected, "completed")
