"""Persistent background job manager with controllable live recording processes."""

from __future__ import annotations

import logging
import os
import re
import signal
import sqlite3
import subprocess
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .error_messages import INTERNET_ERROR_MESSAGE, operational_error_message
from .file_service import FileService
from .media_service import MediaService, MediaServiceError

LOGGER = logging.getLogger(__name__)
PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<progress>\d+(?:\.\d+)?)%.*?(?:at\s+(?P<speed>\S+))?.*?(?:ETA\s+(?P<eta>\S+))?$"
)
DESTINATION_RE = re.compile(
    r"(?:Destination:|Merging formats into|Correcting container in|Extracting audio from)\s+[\"']?(?P<path>.+?)[\"']?$"
)
LIVE_WAIT_INTERVAL_SECONDS = 30
AUTO_RETRY_DELAY_SECONDS = 300
AUTO_RETRY_MAX_ATTEMPTS = 3
JOB_LOG_PREVIEW_LINE_LIMIT = 40


class DownloadStoppedError(RuntimeError):
    """Raised inside a yt-dlp hook when the user stops a regular download."""


def now_iso() -> str:
    """Return an ISO 8601 UTC timestamp."""

    return datetime.now(UTC).isoformat()


@dataclass
class Job:
    """Serializable state of one background operation."""

    job_id: str
    url: str
    title: str
    status: str
    download_type: str
    format_id: str | None = None
    progress: float = 0.0
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: str | None = None
    eta: str | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    warning_message: str | None = None
    output_file: str | None = None
    output_files: list[str] = field(default_factory=list)
    thumbnail_filename: str | None = None
    is_live: bool = False
    live_from_start: bool = True
    duration: int | None = None
    log_lines: list[str] = field(default_factory=list)
    auto_retry_attempts: int = 0
    auto_retry_max_attempts: int = AUTO_RETRY_MAX_ATTEMPTS
    next_retry_at: str | None = None


class JobManager:
    """Queue downloads, persist snapshots, and supervise dedicated live processes."""

    ACTIVE_STATUSES = {"pending", "downloading", "stopping", "waiting"}
    STOPPABLE_STATUSES = {"pending", "downloading", "waiting"}
    RESUMABLE_STATUSES = {"stopped", "interrupted"}
    REMOVABLE_STATUSES = {"completed", "error", "stopped", "interrupted"}
    STATUS_LABELS = {
        "pending": "oczekuje",
        "downloading": "pobieranie",
        "waiting": "oczekuje na live",
        "stopping": "zatrzymywanie",
        "completed": "zakończone",
        "error": "błąd",
        "stopped": "zatrzymane",
        "interrupted": "przerwane",
    }

    def __init__(
        self,
        media_service: MediaService,
        file_service: FileService,
        max_concurrent_jobs: int,
        jobs_file: Path | None = None,
        notifier: Any | None = None,
    ) -> None:
        self.media_service = media_service
        self.file_service = file_service
        self.max_concurrent_jobs = max_concurrent_jobs
        self.jobs_file = jobs_file or file_service.history_file.parent / "queue.json"
        self.state_store = file_service.state_store
        self.notifier = notifier
        self._jobs: dict[str, Job] = {}
        self._live_processes: dict[str, subprocess.Popen[str]] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._retry_timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_concurrent_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_jobs, thread_name_prefix="download"
        )
        self.state_store.migrate_jobs_json(self.jobs_file)
        self._load_jobs()
        self._restore_auto_retries()

    def start_download(
        self,
        url: str,
        title: str,
        download_type: str,
        format_id: str | None = None,
        duration: int | None = None,
    ) -> Job:
        """Queue one regular yt-dlp download."""

        validated_url = self.media_service.validate_url(url)
        self.media_service.format_selection(download_type, format_id)
        job = self._new_job(
            validated_url,
            title,
            download_type,
            is_live=False,
            format_id=format_id,
            duration=duration,
        )
        stop_event = threading.Event()
        with self._lock:
            self._stop_events[job.job_id] = stop_event
        self._executor.submit(self._run_download, job.job_id, stop_event)
        LOGGER.info("Dodano zadanie pobierania %s", job.job_id)
        return job

    def stop_download(self, job_id: str) -> Job:
        """Stop a queued or running regular download while keeping partial files."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.is_live:
                raise KeyError(job_id)
            if job.status not in self.STOPPABLE_STATUSES:
                return Job(**asdict(job))
            event = self._stop_events.get(job_id)
            if event:
                event.set()
            if job.status == "pending":
                self._finish(job, "stopped")
            else:
                job.status = "stopping"
                job.speed = None
                job.eta = None
                self._persist_jobs()
        LOGGER.info("Zlecono zatrzymanie pobierania %s", job_id)
        return self.get_job(job_id)

    def resume_download(self, job_id: str) -> Job:
        """Resume a stopped regular download using yt-dlp partial-file support."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.is_live:
                raise KeyError(job_id)
            if job.status not in self.RESUMABLE_STATUSES:
                raise MediaServiceError("To zadanie nie może zostać wznowione.")
            self.media_service.format_selection(job.download_type, job.format_id)
            self._cancel_retry_timer(job_id)
            job.status = "pending"
            job.finished_at = None
            job.error_message = None
            job.warning_message = None
            job.auto_retry_attempts = 0
            job.next_retry_at = None
            job.speed = None
            job.eta = None
            stop_event = threading.Event()
            self._stop_events[job_id] = stop_event
            self._persist_jobs()
            snapshot = Job(**asdict(job))
        self._executor.submit(self._run_download, job_id, stop_event)
        LOGGER.info("Wznowiono pobieranie %s", job_id)
        return snapshot

    def retry_failed_jobs(self) -> tuple[int, int]:
        """Retry every failed job and report skipped records."""

        downloads: list[tuple[str, threading.Event]] = []
        live_jobs: list[str] = []
        retried = 0
        skipped = 0
        with self._lock:
            for job in self._jobs.values():
                if job.status != "error":
                    continue
                if job.is_live:
                    duplicate = any(
                        other.job_id != job.job_id
                        and other.url == job.url
                        and other.is_live
                        and other.status in self.ACTIVE_STATUSES
                        for other in self._jobs.values()
                    )
                    if duplicate:
                        skipped += 1
                        continue
                    self._cancel_retry_timer(job.job_id)
                    self._reset_for_retry(job)
                    stop_event = threading.Event()
                    self._stop_events[job.job_id] = stop_event
                    live_jobs.append(job.job_id)
                    retried += 1
                    continue
                try:
                    self.media_service.format_selection(job.download_type, job.format_id)
                except MediaServiceError:
                    skipped += 1
                    continue
                self._cancel_retry_timer(job.job_id)
                self._reset_for_retry(job)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                downloads.append((job.job_id, stop_event))
                retried += 1
            if retried:
                self._persist_jobs()

        for job_id, stop_event in downloads:
            self._executor.submit(self._run_download, job_id, stop_event)
        for job_id in live_jobs:
            thread = threading.Thread(
                target=self._run_live,
                args=(job_id,),
                daemon=True,
                name=f"live-retry-{job_id[:8]}",
            )
            thread.start()
        LOGGER.info("Ponowiono %s błędnych zadań, pominięto: %s", retried, skipped)
        return retried, skipped

    def retry_job(self, job_id: str) -> Job:
        """Retry one failed job."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status != "error":
                raise MediaServiceError(
                    "Tylko zadanie ze statusem błędu można ponowić."
                )
            self._cancel_retry_timer(job_id)
            if job.is_live:
                duplicate = any(
                    other.job_id != job.job_id
                    and other.url == job.url
                    and other.is_live
                    and other.status in self.ACTIVE_STATUSES
                    for other in self._jobs.values()
                )
                if duplicate:
                    raise MediaServiceError(
                        "Nagrywanie tej transmisji jest już uruchomione."
                    )
                self._reset_for_retry(job)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                self._persist_jobs()
                snapshot = Job(**asdict(job))
            else:
                self.media_service.format_selection(job.download_type, job.format_id)
                self._reset_for_retry(job)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                self._persist_jobs()
                snapshot = Job(**asdict(job))

        if snapshot.is_live:
            thread = threading.Thread(
                target=self._run_live,
                args=(snapshot.job_id,),
                daemon=True,
                name=f"live-retry-{snapshot.job_id[:8]}",
            )
            thread.start()
        else:
            self._executor.submit(self._run_download, snapshot.job_id, stop_event)
        LOGGER.info("Ponowiono błędne zadanie %s", job_id)
        return snapshot

    def start_live(self, url: str, title: str, live_from_start: bool = True) -> Job:
        """Queue a uniquely identified live stream recording process."""

        validated_url = self.media_service.validate_url(url)
        with self._lock:
            duplicate = any(
                job.url == validated_url
                and job.is_live
                and job.status in self.ACTIVE_STATUSES
                for job in self._jobs.values()
            )
            if duplicate:
                raise MediaServiceError(
                    "Nagrywanie tej transmisji jest już uruchomione."
                )
        job = self._new_job(
            validated_url,
            title,
            "live",
            is_live=True,
            live_from_start=live_from_start,
        )
        stop_event = threading.Event()
        with self._lock:
            self._stop_events[job.job_id] = stop_event
        thread = threading.Thread(
            target=self._run_live,
            args=(job.job_id,),
            daemon=True,
            name=f"live-{job.job_id[:8]}",
        )
        thread.start()
        LOGGER.info("Dodano zapis transmisji live %s", job.job_id)
        return job

    def start_live_wait(
        self, url: str, title: str, live_from_start: bool = True
    ) -> Job:
        """Queue a live stream monitor that starts recording when live begins."""

        validated_url = self.media_service.validate_url(url)
        with self._lock:
            duplicate = any(
                job.url == validated_url
                and job.is_live
                and job.status in self.ACTIVE_STATUSES
                for job in self._jobs.values()
            )
            if duplicate:
                raise MediaServiceError(
                    "Nagrywanie tej transmisji jest już uruchomione."
                )
        job = self._new_job(
            validated_url,
            title,
            "live",
            is_live=True,
            live_from_start=live_from_start,
        )
        stop_event = threading.Event()
        with self._lock:
            active = self._jobs[job.job_id]
            active.status = "waiting"
            self._persist_jobs()
            self._stop_events[job.job_id] = stop_event
            snapshot = Job(**asdict(active))
        thread = threading.Thread(
            target=self._run_live_wait,
            args=(job.job_id,),
            daemon=True,
            name=f"live-wait-{job.job_id[:8]}",
        )
        thread.start()
        LOGGER.info("Dodano oczekiwanie na transmisję live %s", job.job_id)
        return snapshot

    def stop_live(self, job_id: str) -> Job:
        """Stop a queued or running live recording gracefully."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.is_live:
                raise KeyError(job_id)
            if job.status not in self.STOPPABLE_STATUSES:
                return job
            event = self._stop_events.get(job_id)
            process = self._live_processes.get(job_id)
            if event:
                event.set()
            if job.status in {"pending", "waiting"}:
                self._finish(job, "stopped")
                self._stop_events.pop(job_id, None)
        if process and process.poll() is None:
            self._interrupt_process(process)
        LOGGER.info("Zatrzymano zapis transmisji live %s", job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        """Return a snapshot of one job."""

        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return Job(**asdict(self._jobs[job_id]))

    def list_jobs(self) -> list[Job]:
        """Return newest jobs first."""

        with self._lock:
            jobs = [Job(**asdict(job)) for job in self._jobs.values()]
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def delete_job(self, job_id: str) -> None:
        """Delete one inactive job from the persistent queue."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status not in self.REMOVABLE_STATUSES:
                raise MediaServiceError(
                    "Aktywnego zadania nie można usunąć. Najpierw je zatrzymaj."
                )
            self._cancel_retry_timer(job_id)
            del self._jobs[job_id]
            self._persist_jobs()
        LOGGER.info("Usunięto zadanie %s", job_id)

    def delete_jobs(self, job_ids: list[str]) -> tuple[int, int]:
        """Delete selected inactive jobs and report skipped active records."""

        removed = 0
        skipped = 0
        with self._lock:
            for job_id in set(job_ids):
                job = self._jobs.get(job_id)
                if not job:
                    continue
                if job.status not in self.REMOVABLE_STATUSES:
                    skipped += 1
                    continue
                self._cancel_retry_timer(job_id)
                del self._jobs[job_id]
                removed += 1
            if removed:
                self._persist_jobs()
        LOGGER.info("Usunięto %s zadań, pominięto aktywnych: %s", removed, skipped)
        return removed, skipped

    def clear_jobs(self) -> tuple[int, int]:
        """Delete every inactive job while preserving active operations."""

        with self._lock:
            job_ids = list(self._jobs)
        return self.delete_jobs(job_ids)

    def job_dict(self, job: Job, include_full_log: bool = False) -> dict[str, Any]:
        """Serialize a job with labels consumed by JSON clients."""

        payload = asdict(job)
        payload["status_label"] = self.STATUS_LABELS.get(job.status, job.status)
        recent_log_lines = payload["log_lines"][-JOB_LOG_PREVIEW_LINE_LIMIT:]
        payload["recent_log_lines"] = recent_log_lines
        if include_full_log:
            full_log_lines = self.state_store.job_logs(job.job_id)
            payload["log_lines"] = full_log_lines or recent_log_lines
        else:
            payload["log_lines"] = recent_log_lines
        payload["thumbnail_exists"] = False
        if job.thumbnail_filename:
            try:
                payload["thumbnail_exists"] = self.file_service.resolve_thumbnail(
                    job.thumbnail_filename
                ).is_file()
            except (FileNotFoundError, OSError, ValueError):
                payload["thumbnail_exists"] = False
        return payload

    def _new_job(
        self,
        url: str,
        title: str,
        download_type: str,
        is_live: bool,
        format_id: str | None = None,
        duration: int | None = None,
        live_from_start: bool = True,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            url=url,
            title=(title or "Bez tytułu")[:300],
            status="pending",
            download_type=download_type,
            format_id=format_id,
            is_live=is_live,
            live_from_start=live_from_start,
            duration=duration,
            auto_retry_max_attempts=AUTO_RETRY_MAX_ATTEMPTS,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist_jobs()
        return Job(**asdict(job))

    def _reset_for_retry(self, job: Job, reset_auto_retry: bool = True) -> None:
        job.status = "pending"
        job.progress = 0.0
        job.downloaded_bytes = None
        job.total_bytes = None
        job.speed = None
        job.eta = None
        job.started_at = None
        job.finished_at = None
        job.error_message = None
        job.warning_message = None
        job.output_file = None
        job.output_files = []
        job.thumbnail_filename = None
        job.next_retry_at = None
        if reset_auto_retry:
            job.auto_retry_attempts = 0
            job.log_lines = []
            self.state_store.replace_job_logs(job.job_id, [])

    def _cancel_retry_timer(self, job_id: str) -> None:
        timer = self._retry_timers.pop(job_id, None)
        if timer:
            timer.cancel()

    def _schedule_retry_timer(
        self, job: Job, expected_attempt: int, delay_seconds: float
    ) -> None:
        self._cancel_retry_timer(job.job_id)
        timer = threading.Timer(
            max(0.0, delay_seconds),
            self._run_scheduled_retry,
            args=(job.job_id, expected_attempt),
        )
        timer.daemon = True
        self._retry_timers[job.job_id] = timer
        timer.start()

    def _schedule_auto_retry(self, job: Job) -> None:
        if job.auto_retry_max_attempts <= 0:
            return
        if job.auto_retry_attempts >= job.auto_retry_max_attempts:
            job.next_retry_at = None
            return
        job.auto_retry_attempts += 1
        retry_at = datetime.now(UTC) + timedelta(seconds=AUTO_RETRY_DELAY_SECONDS)
        job.next_retry_at = retry_at.isoformat()
        self._append_log_line(
            job,
            (
                "[retry] Zaplanowano automatyczną próbę "
                f"{job.auto_retry_attempts}/{job.auto_retry_max_attempts} "
                f"o {job.next_retry_at}."
            ),
        )
        self._persist_jobs()
        self._schedule_retry_timer(
            job, job.auto_retry_attempts, AUTO_RETRY_DELAY_SECONDS
        )

    def _restore_auto_retries(self) -> None:
        changed = False
        now = datetime.now(UTC)
        with self._lock:
            for job in self._jobs.values():
                if job.status != "error" or not job.next_retry_at:
                    continue
                if job.auto_retry_attempts > job.auto_retry_max_attempts:
                    job.next_retry_at = None
                    changed = True
                    continue
                try:
                    retry_at = datetime.fromisoformat(job.next_retry_at)
                except ValueError:
                    job.next_retry_at = None
                    changed = True
                    continue
                delay = max(0.0, (retry_at - now).total_seconds())
                self._schedule_retry_timer(job, job.auto_retry_attempts, delay)
            if changed:
                self._persist_jobs()

    def _run_scheduled_retry(self, job_id: str, expected_attempt: int) -> None:
        with self._lock:
            self._retry_timers.pop(job_id, None)
            job = self._jobs.get(job_id)
            if (
                not job
                or job.status != "error"
                or job.auto_retry_attempts != expected_attempt
                or not job.next_retry_at
            ):
                return
            if job.is_live:
                duplicate = any(
                    other.job_id != job.job_id
                    and other.url == job.url
                    and other.is_live
                    and other.status in self.ACTIVE_STATUSES
                    for other in self._jobs.values()
                )
                if duplicate:
                    job.next_retry_at = None
                    self._append_log_line(
                        job,
                        "[retry] Pominięto automatyczną próbę, live jest już aktywny.",
                    )
                    self._persist_jobs()
                    return
                self._reset_for_retry(job, reset_auto_retry=False)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                snapshot = Job(**asdict(job))
                self._persist_jobs()
            else:
                try:
                    self.media_service.format_selection(job.download_type, job.format_id)
                except MediaServiceError as error:
                    job.next_retry_at = None
                    self._append_log_line(job, f"[retry] Nie można ponowić: {error}")
                    self._persist_jobs()
                    return
                self._reset_for_retry(job, reset_auto_retry=False)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                snapshot = Job(**asdict(job))
                self._persist_jobs()

        LOGGER.info(
            "Automatycznie ponawiam zadanie %s (%s/%s)",
            job_id,
            expected_attempt,
            snapshot.auto_retry_max_attempts,
        )
        if snapshot.is_live:
            thread = threading.Thread(
                target=self._run_live,
                args=(snapshot.job_id,),
                daemon=True,
                name=f"live-auto-retry-{snapshot.job_id[:8]}",
            )
            thread.start()
        else:
            self._executor.submit(self._run_download, snapshot.job_id, stop_event)

    def _append_log_line(
        self,
        job: Job,
        line: str,
        limit: int | None = JOB_LOG_PREVIEW_LINE_LIMIT,
    ) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        self.state_store.append_job_log(job.job_id, cleaned)
        job.log_lines.append(cleaned)
        if limit is not None and len(job.log_lines) > limit:
            job.log_lines = job.log_lines[-limit:]

    @classmethod
    def _progress_log_line(cls, data: dict[str, Any]) -> str | None:
        status = data.get("status")
        if status == "downloading":
            parts = [f"[download] {cls._percentage(data):.1f}%"]
            downloaded = cls._byte_count(data.get("downloaded_bytes"))
            total = cls._byte_count(data.get("total_bytes") or data.get("total_bytes_estimate"))
            if downloaded is not None and total is not None:
                parts.append(f"{downloaded}/{total} B")
            speed = cls._display_speed(data.get("speed"))
            eta = cls._display_eta(data.get("eta"))
            if speed:
                parts.append(f"at {speed}")
            if eta:
                parts.append(f"ETA {eta}")
            return " ".join(parts)
        if status == "finished":
            filename = data.get("filename")
            return f"[download] Finished: {filename}" if filename else "[download] Finished"
        return None

    @staticmethod
    def _postprocessor_log_line(data: dict[str, Any]) -> str | None:
        status = data.get("status")
        postprocessor = data.get("postprocessor") or data.get("postprocessor_key")
        if not status and not postprocessor:
            return None
        label = str(postprocessor or "postprocessor")
        return f"[postprocess] {label}: {status or 'started'}"

    def _run_download(self, job_id: str, stop_event: threading.Event) -> None:
        try:
            with self._slots:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if not job:
                        return
                    if stop_event.is_set():
                        if self._stop_events.get(job_id) is stop_event:
                            self._finish(job, "stopped")
                        return
                    self._start(job)
                collected: set[Path] = set()

                def collect_path(data: dict[str, Any]) -> None:
                    info = data.get("info_dict") or {}
                    values = [
                        data.get("filename"),
                        info.get("filepath"),
                        info.get("_filename"),
                    ]
                    files_to_move = info.get("__files_to_move") or {}
                    if isinstance(files_to_move, dict):
                        values.extend(files_to_move)
                        values.extend(files_to_move.values())
                    for path_value in values:
                        if path_value:
                            path = Path(str(path_value)).resolve()
                            if self.file_service.is_managed_file(path):
                                collected.add(path)

                def progress_hook(data: dict[str, Any]) -> None:
                    if stop_event.is_set():
                        raise DownloadStoppedError
                    collect_path(data)
                    with self._lock:
                        active = self._jobs[job_id]
                        log_line = self._progress_log_line(data)
                        if log_line:
                            self._append_log_line(active, log_line)
                        if data.get("status") == "downloading":
                            active.progress = self._percentage(data)
                            active.downloaded_bytes = self._byte_count(
                                data.get("downloaded_bytes")
                            )
                            active.total_bytes = self._byte_count(
                                data.get("total_bytes")
                                or data.get("total_bytes_estimate")
                            )
                            active.speed = self._display_speed(data.get("speed"))
                            active.eta = self._display_eta(data.get("eta"))
                        elif data.get("status") == "finished":
                            active.progress = 100.0

                def postprocessor_hook(data: dict[str, Any]) -> None:
                    collect_path(data)
                    with self._lock:
                        active = self._jobs[job_id]
                        log_line = self._postprocessor_log_line(data)
                        if log_line:
                            self._append_log_line(active, log_line)

                try:
                    paths = self.media_service.download(
                        url=job.url,
                        download_type=job.download_type,
                        format_id=job.format_id,
                        progress_hook=progress_hook,
                        postprocessor_hook=postprocessor_hook,
                    )
                    if stop_event.is_set():
                        raise DownloadStoppedError
                    collected.update(paths)
                    files = self._record_existing_outputs(
                        job_id, collected, "completed"
                    )
                    if not files:
                        raise MediaServiceError(
                            "Pobieranie zakończyło się bez gotowego pliku. Sprawdź logi dodatku."
                        )
                    with self._lock:
                        active = self._jobs[job_id]
                        active.output_files = files
                        active.output_file = files[0] if files else None
                        active.downloaded_bytes = self._output_size(files)
                        active.total_bytes = active.downloaded_bytes
                        active.progress = 100.0
                        self._finish(active, "completed")
                except DownloadStoppedError:
                    with self._lock:
                        self._finish(self._jobs[job_id], "stopped")
                except MediaServiceError as error:
                    self._fail(job_id, str(error))
                except Exception as error:
                    LOGGER.exception("Nieoczekiwany błąd zadania %s", job_id)
                    self._fail(
                        job_id,
                        operational_error_message(str(error))
                        or "Nieoczekiwany błąd podczas pobierania.",
                    )
        finally:
            with self._lock:
                if self._stop_events.get(job_id) is stop_event:
                    self._stop_events.pop(job_id, None)

    def _run_live(self, job_id: str) -> None:
        stop_event = self._stop_events.get(job_id)
        if stop_event is None:
            return
        with self._slots:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    self._stop_events.pop(job_id, None)
                    return
                if self._stop_events.get(job_id) is not stop_event:
                    return
                if stop_event.is_set():
                    self._finish(job, "stopped")
                    self._stop_events.pop(job_id, None)
                    return
                self._start(job)
            paths: set[Path] = set()
            output_lines: deque[str] = deque(maxlen=40)
            try:
                command = self.media_service.live_command(
                    job.url, live_from_start=job.live_from_start
                )
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                with self._lock:
                    self._live_processes[job_id] = process
                assert process.stdout is not None
                for line in process.stdout:
                    output_lines.append(line)
                    LOGGER.info("[live %s] %s", job_id[:8], line.rstrip())
                    with self._lock:
                        active = self._jobs.get(job_id)
                        if active:
                            self._append_log_line(active, line)
                    self._parse_live_line(job_id, line, paths)
                    if stop_event.is_set() and process.poll() is None:
                        self._interrupt_process(process)
                return_code = process.wait()
                status = (
                    "stopped"
                    if stop_event.is_set()
                    else ("completed" if return_code == 0 else "error")
                )
                files = self._record_existing_outputs(job_id, paths, status)
                with self._lock:
                    active = self._jobs[job_id]
                    active.output_files = files
                    active.output_file = files[0] if files else None
                    active.downloaded_bytes = self._output_size(files)
                    active.total_bytes = active.downloaded_bytes
                    if status == "error":
                        active.error_message = (
                            operational_error_message("".join(output_lines))
                            or "yt-dlp nie mógł zapisać transmisji live. Sprawdź logi dodatku."
                        )
                    self._finish(active, status)
            except Exception as error:
                LOGGER.exception("Błąd procesu live %s", job_id)
                self._fail(
                    job_id,
                    operational_error_message(str(error))
                    or "Nie udało się uruchomić zapisu transmisji live.",
                )
            finally:
                with self._lock:
                    self._live_processes.pop(job_id, None)
                    self._stop_events.pop(job_id, None)

    def _run_live_wait(self, job_id: str) -> None:
        stop_event = self._stop_events[job_id]
        handed_off = False
        try:
            while not stop_event.is_set():
                with self._lock:
                    job = self._jobs.get(job_id)
                    if not job:
                        return
                try:
                    media = self.media_service.analyze(job.url)
                except MediaServiceError as error:
                    message = str(error)
                    if message not in {
                        "Ta transmisja jeszcze się nie rozpoczęła.",
                        INTERNET_ERROR_MESSAGE,
                    }:
                        self._fail(job_id, message)
                        return
                else:
                    if stop_event.is_set():
                        break
                    if media.get("content_type") != "live":
                        self._fail(
                            job_id, "Podany adres nie prowadzi do transmisji live."
                        )
                        return
                    if media.get("is_live"):
                        handed_off = True
                        self._run_live(job_id)
                        return
                if stop_event.wait(LIVE_WAIT_INTERVAL_SECONDS):
                    break
            with self._lock:
                job = self._jobs.get(job_id)
                if job and job.status == "waiting":
                    self._finish(job, "stopped")
        finally:
            if not handed_off:
                with self._lock:
                    if self._stop_events.get(job_id) is stop_event:
                        self._stop_events.pop(job_id, None)

    def _parse_live_line(self, job_id: str, line: str, paths: set[Path]) -> None:
        progress_match = PROGRESS_RE.search(line.strip())
        destination_match = DESTINATION_RE.search(line.strip())
        with self._lock:
            job = self._jobs[job_id]
            if progress_match:
                job.progress = float(progress_match.group("progress"))
                job.speed = progress_match.group("speed")
                job.eta = progress_match.group("eta")
        if destination_match:
            path = Path(destination_match.group("path").strip("\"'")).resolve()
            if self.file_service.is_managed_file(path):
                paths.add(path)

    def _record_existing_outputs(
        self, job_id: str, paths: set[Path], status: str
    ) -> list[str]:
        with self._lock:
            job = self._jobs[job_id]
        files: list[str] = []
        for path in sorted(paths):
            if (
                self.file_service.is_managed_file(path)
                and path.is_file()
                and not path.name.endswith((".part", ".ytdl"))
            ):
                files.append(path.name)
                try:
                    thumbnail = self.file_service.generate_thumbnail(path.name)
                    if thumbnail.filename and not job.thumbnail_filename:
                        job.thumbnail_filename = thumbnail.filename
                    if thumbnail.warning_message and not job.warning_message:
                        job.warning_message = thumbnail.warning_message
                    self.file_service.record_download(
                        job.title,
                        job.url,
                        job.download_type,
                        path.name,
                        status,
                        thumbnail.filename,
                        job.format_id,
                        thumbnail.warning_message,
                        job.duration,
                    )
                except (FileNotFoundError, ValueError):
                    LOGGER.warning("Pominięto wynik poza katalogiem pobrań: %s", path)
        return files

    @staticmethod
    def _interrupt_process(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _percentage(data: dict[str, Any]) -> float:
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes")
        if total and downloaded:
            return round(min(100.0, downloaded * 100 / total), 1)
        return 0.0

    @staticmethod
    def _byte_count(value: Any) -> int | None:
        return int(value) if isinstance(value, (int, float)) and value >= 0 else None

    def _output_size(self, filenames: list[str]) -> int | None:
        size = 0
        for filename in filenames:
            try:
                size += self.file_service.resolve_download(filename).stat().st_size
            except (FileNotFoundError, OSError, ValueError):
                return None
        return size if filenames else None

    @staticmethod
    def _display_speed(speed: Any) -> str | None:
        if not isinstance(speed, (int, float)):
            return None
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = float(speed)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return None

    @staticmethod
    def _display_eta(eta: Any) -> str | None:
        if not isinstance(eta, (int, float)):
            return None
        minutes, seconds = divmod(int(eta), 60)
        hours, minutes = divmod(minutes, 60)
        return (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )

    def _start(self, job: Job) -> None:
        job.status = "downloading"
        job.started_at = now_iso()
        self._persist_jobs()

    def _finish(self, job: Job, status: str) -> None:
        job.status = status
        job.finished_at = now_iso()
        job.speed = None
        job.eta = None
        self._persist_jobs()
        if status in {"completed", "error"} and self.notifier:
            self.notifier.notify_job(Job(**asdict(job)))

    def _fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._append_log_line(job, f"[error] {message}")
            job.error_message = message
            self._finish(job, "error")
            self._schedule_auto_retry(job)

    def _load_jobs(self) -> None:
        """Restore persisted jobs and mark unfinished work as interrupted."""

        payload = self.state_store.jobs_all()
        if not payload:
            return

        field_names = {item.name for item in fields(Job)}
        interrupted = False
        for record in payload:
            if not isinstance(record, dict):
                LOGGER.warning("Pominieto niepoprawny rekord trwalej kolejki zadan")
                continue
            try:
                job = Job(
                    **{
                        key: value
                        for key, value in record.items()
                        if key in field_names
                    }
                )
            except TypeError as error:
                LOGGER.warning("Pominieto niepoprawny rekord zadania: %s", error)
                continue
            if job.status in self.ACTIVE_STATUSES:
                job.status = "interrupted"
                job.finished_at = now_iso()
                job.speed = None
                job.eta = None
                job.error_message = "Zadanie zostalo przerwane przez restart aplikacji."
                interrupted = True
            self._jobs[job.job_id] = job
        if interrupted:
            self._persist_jobs()
        LOGGER.info("Odtworzono %s zadan z trwalej kolejki", len(self._jobs))

    def _persist_jobs(self) -> None:
        """Write a consistent queue snapshot without interrupting active work."""

        try:
            with self._lock:
                records = [asdict(job) for job in self._jobs.values()]
            self.state_store.jobs_replace(records)
        except (OSError, TypeError, ValueError, sqlite3.Error) as error:
            LOGGER.error("Nie mozna zapisac trwalej kolejki zadan: %s", error)
