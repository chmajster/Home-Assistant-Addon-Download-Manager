"""Persistent background job manager with controllable live recording processes."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .auto_tags import generate_auto_tags
from .error_messages import (
    DOWNLOAD_STOPPED,
    INTERNET_ERROR_MESSAGE,
    error_code_for_message,
    operational_error_message,
)
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
PROGRESS_PERSIST_INTERVAL_SECONDS = 2.0
PROGRESS_MIN_DELTA_PERCENT = 1.0
LIVE_SIZE_UPDATE_INTERVAL_SECONDS = 4.0
LIVE_STATUS_LOG_INTERVAL_SECONDS = 60.0


class DownloadStoppedError(RuntimeError):
    """Raised inside a yt-dlp hook when the user stops a regular download."""


@dataclass(frozen=True)
class OrphanedYtDlpProcess:
    """A yt-dlp process that looks like it was started by this add-on."""

    pid: int
    command_line: str
    urls: tuple[str, ...]


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
    source_id: str | None = None
    download_options: dict[str, Any] = field(default_factory=dict)
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
    source_thumbnail_filename: str | None = None
    thumbnail_types: dict[str, bool] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    auto_tags: list[str] = field(default_factory=list)
    error_code: str | None = None
    storage_name: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)
    is_live: bool = False
    live_from_start: bool = True
    duration: int | None = None
    live_elapsed_seconds: int | None = None
    live_status_message: str | None = None
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
    QUEUED_REMOVABLE_STATUSES = {"pending", "waiting"}
    DELETABLE_STATUSES = REMOVABLE_STATUSES | QUEUED_REMOVABLE_STATUSES
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
        self._orphaned_processes: list[OrphanedYtDlpProcess] = []
        self._orphan_live_urls: set[str] = set()
        self._shutdown_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._persisted_jobs: dict[str, str] = {}
        self._persisted_status: dict[str, str] = {}
        self._last_progress_write: dict[str, tuple[float, float]] = {}
        self._last_live_size_update: dict[str, float] = {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_concurrent_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_jobs, thread_name_prefix="download"
        )
        self.state_store.migrate_jobs_json(self.jobs_file)
        self._migrate_history_records_into_jobs()
        self._detect_orphaned_ytdlp_processes()
        self._load_jobs()
        self._restore_auto_retries()

    def shutdown(self, timeout: float = 20.0) -> None:
        """Stop timers, workers and live processes, marking active jobs interrupted."""

        with self._shutdown_lock:
            if self._shutdown_complete:
                LOGGER.info("Shutdown zadan juz wykonany; pomijam ponowne wywolanie.")
                return
            self._shutdown_complete = True
        LOGGER.info("Rozpoczynam graceful shutdown managera zadan.")
        self._shutdown_event.set()
        processes: list[subprocess.Popen[str]] = []
        with self._lock:
            timer_count = len(self._retry_timers)
            for timer in self._retry_timers.values():
                timer.cancel()
            self._retry_timers.clear()
            for event in self._stop_events.values():
                event.set()
            for job in self._jobs.values():
                if job.status in self.ACTIVE_STATUSES:
                    job.status = "interrupted"
                    job.finished_at = now_iso()
                    job.speed = None
                    job.eta = None
                    job.error_code = DOWNLOAD_STOPPED
                    job.error_message = "Zadanie zostalo przerwane przez zatrzymanie aplikacji."
                    self._append_log_line(job, "[shutdown] Zadanie przerwane przez zatrzymanie aplikacji.")
            processes = [
                process for process in self._live_processes.values()
                if process.poll() is None
            ]
            self._persist_jobs()
        LOGGER.info("Zatrzymano timery retry: %s.", timer_count)
        LOGGER.info("Ustawiono stop eventy dla aktywnych zadan: %s.", len(self._stop_events))
        for process in processes:
            self._interrupt_process(process)
        LOGGER.info("Przerwano aktywne procesy live: %s.", len(processes))
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.state_store.close()
        LOGGER.info("ThreadPoolExecutor i SQLite state store zamkniete.")

    def start_download(
        self,
        url: str,
        title: str,
        download_type: str,
        format_id: str | None = None,
        duration: int | None = None,
        source_id: str | None = None,
        download_options: dict[str, Any] | None = None,
    ) -> Job:
        """Queue one regular yt-dlp download."""

        if self._shutdown_event.is_set():
            raise MediaServiceError("Aplikacja jest zatrzymywana. Nie mozna dodac nowego zadania.")
        validated_url = self.media_service.validate_url(url)
        normalized_options = dict(download_options or {})
        storage_name = self.file_service.validate_storage(
            normalized_options.get("storage_name")
        )
        normalized_options["storage_name"] = storage_name
        self.media_service.download_options(download_type, format_id, normalized_options)
        job = self._new_job(
            validated_url,
            title,
            download_type,
            is_live=False,
            format_id=format_id,
            duration=duration,
            source_id=source_id,
            download_options=normalized_options,
            storage_name=storage_name,
        )
        stop_event = threading.Event()
        with self._lock:
            self._stop_events[job.job_id] = stop_event
        self._submit_download(job.job_id, stop_event)
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
            self.media_service.download_options(
                job.download_type, job.format_id, job.download_options
            )
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
        self._submit_download(job_id, stop_event)
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
                    if self._live_recording_exists(job.url, exclude_job_id=job.job_id):
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
                    self.media_service.download_options(
                        job.download_type, job.format_id, job.download_options
                    )
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
            self._submit_download(job_id, stop_event)
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
                if self._live_recording_exists(job.url, exclude_job_id=job.job_id):
                    raise MediaServiceError(
                        "Nagrywanie tej transmisji jest już uruchomione."
                    )
                self._reset_for_retry(job)
                stop_event = threading.Event()
                self._stop_events[job.job_id] = stop_event
                self._persist_jobs()
                snapshot = Job(**asdict(job))
            else:
                self.media_service.download_options(
                    job.download_type, job.format_id, job.download_options
                )
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
            self._submit_download(snapshot.job_id, stop_event)
        LOGGER.info("Ponowiono błędne zadanie %s", job_id)
        return snapshot

    def start_live(self, url: str, title: str, live_from_start: bool = True) -> Job:
        """Queue a uniquely identified live stream recording process."""

        if self._shutdown_event.is_set():
            raise MediaServiceError("Aplikacja jest zatrzymywana. Nie mozna dodac nowego zadania.")
        validated_url = self.media_service.validate_url(url)
        with self._lock:
            if self._live_recording_exists(validated_url):
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

        if self._shutdown_event.is_set():
            raise MediaServiceError("Aplikacja jest zatrzymywana. Nie mozna dodac nowego zadania.")
        validated_url = self.media_service.validate_url(url)
        with self._lock:
            if self._live_recording_exists(validated_url):
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
        """Delete one completed or still-queued job from the persistent queue."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status not in self.DELETABLE_STATUSES:
                raise MediaServiceError(
                    "Aktywnego zadania nie można usunąć. Najpierw je zatrzymaj."
                )
            if job.status in self.QUEUED_REMOVABLE_STATUSES:
                event = self._stop_events.get(job_id)
                if event:
                    event.set()
            self._cancel_retry_timer(job_id)
            del self._jobs[job_id]
            self._persist_jobs()
        LOGGER.info("Usunięto zadanie %s", job_id)

    def delete_jobs(self, job_ids: list[str]) -> tuple[int, int]:
        """Delete selected completed or still-queued jobs."""

        removed = 0
        skipped = 0
        with self._lock:
            for job_id in set(job_ids):
                job = self._jobs.get(job_id)
                if not job:
                    continue
                if job.status not in self.DELETABLE_STATUSES:
                    skipped += 1
                    continue
                if job.status in self.QUEUED_REMOVABLE_STATUSES:
                    event = self._stop_events.get(job_id)
                    if event:
                        event.set()
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
            job_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in self.REMOVABLE_STATUSES
            ]
            skipped = len(self._jobs) - len(job_ids)
        removed, _ = self.delete_jobs(job_ids)
        return removed, skipped

    def _live_recording_exists(
        self, validated_url: str, exclude_job_id: str | None = None
    ) -> bool:
        normalized_url = self._process_url_key(validated_url)
        for job in self._jobs.values():
            if (
                job.job_id != exclude_job_id
                and job.is_live
                and job.status in self.ACTIVE_STATUSES
                and self._process_url_key(job.url) == normalized_url
            ):
                return True
        if normalized_url not in self._orphan_live_urls:
            return False
        self._detect_orphaned_ytdlp_processes(log_empty=False)
        return normalized_url in self._orphan_live_urls

    def _detect_orphaned_ytdlp_processes(self, log_empty: bool = True) -> None:
        """Find live yt-dlp processes that survived a previous add-on process."""

        processes: list[OrphanedYtDlpProcess] = []
        urls: set[str] = set()
        for pid, args in self._list_process_command_lines():
            if pid == os.getpid() or not self._is_addon_ytdlp_process(args):
                continue
            process_urls = tuple(
                dict.fromkeys(
                    self._process_url_key(arg)
                    for arg in args
                    if self._looks_like_http_url(arg)
                )
            )
            if not process_urls:
                continue
            command_line = " ".join(args)
            processes.append(
                OrphanedYtDlpProcess(
                    pid=pid,
                    command_line=command_line[:2000],
                    urls=process_urls,
                )
            )
            urls.update(process_urls)
        self._orphaned_processes = processes
        self._orphan_live_urls = urls
        if processes:
            LOGGER.warning(
                "Wykryto %s osieroconych procesow yt-dlp dodatku; URL-e live beda blokowane przed duplikacja.",
                len(processes),
            )
            for process in processes:
                LOGGER.warning(
                    "Osierocony yt-dlp pid=%s urls=%s",
                    process.pid,
                    ", ".join(process.urls),
                )
        elif log_empty:
            LOGGER.info("Nie wykryto osieroconych procesow yt-dlp dodatku.")

    def _annotate_interrupted_orphans(self) -> bool:
        changed = False
        if not self._orphan_live_urls:
            return changed
        for job in self._jobs.values():
            if (
                job.is_live
                and job.status == "interrupted"
                and self._process_url_key(job.url) in self._orphan_live_urls
            ):
                self._append_log_line(
                    job,
                    "[startup] Wykryto osierocony proces yt-dlp dla tego URL. "
                    "Zadanie pozostaje interrupted; nowy start live jest blokowany, aby nie nagrywac podwojnie.",
                )
                changed = True
        return changed

    def _list_process_command_lines(self) -> list[tuple[int, list[str]]]:
        proc = Path("/proc")
        if proc.is_dir():
            processes: list[tuple[int, list[str]]] = []
            for entry in proc.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes()
                except OSError:
                    continue
                if not raw:
                    continue
                args = [
                    part.decode("utf-8", errors="replace")
                    for part in raw.split(b"\0")
                    if part
                ]
                if args:
                    processes.append((int(entry.name), args))
            return processes
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        processes = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            pid_text, _, command = stripped.partition(" ")
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            processes.append((pid, command.split()))
        return processes

    def _is_addon_ytdlp_process(self, args: list[str]) -> bool:
        command_line = " ".join(args)
        lowered = command_line.casefold()
        if "yt_dlp" not in lowered and "yt-dlp" not in lowered:
            return False
        managed_root = str(self.file_service.download_dir)
        return managed_root in command_line

    @staticmethod
    def _looks_like_http_url(value: object) -> bool:
        cleaned = str(value or "").strip("\"'")
        return cleaned.startswith(("http://", "https://"))

    @staticmethod
    def _process_url_key(value: object) -> str:
        cleaned = str(value or "").strip("\"'")
        try:
            parts = urlsplit(cleaned)
        except ValueError:
            return cleaned
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme.lower() not in {"http", "https"} or not host:
            return cleaned
        return urlunsplit((parts.scheme.lower(), host, parts.path, parts.query, ""))

    def _submit_download(self, job_id: str, stop_event: threading.Event) -> None:
        if self._shutdown_event.is_set():
            stop_event.set()
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    self._finish(job, "interrupted", error_code=DOWNLOAD_STOPPED)
            return
        try:
            self._executor.submit(self._run_download, job_id, stop_event)
        except RuntimeError:
            stop_event.set()
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    self._finish(job, "interrupted", error_code=DOWNLOAD_STOPPED)

    def _migrate_history_records_into_jobs(self) -> None:
        """Fold legacy download history into the durable job list."""

        history = self.state_store.history_all()
        if not history:
            return
        jobs = self.state_store.jobs_all()
        existing_job_ids = {
            str(record.get("job_id") or record.get("id") or "") for record in jobs
        }
        existing_keys = {
            self._history_identity(
                record.get("url"),
                record.get("output_file") or (record.get("output_files") or [None])[0],
                record.get("finished_at") or record.get("created_at"),
            )
            for record in jobs
        }
        migrated: list[dict[str, Any]] = []
        for record in history:
            identity = self._history_identity(
                record.get("url"),
                record.get("filename"),
                record.get("downloaded_at"),
            )
            if identity in existing_keys:
                continue
            job_id = f"history-{identity[:24]}"
            if job_id in existing_job_ids:
                existing_keys.add(identity)
                continue
            title = str(record.get("title") or record.get("filename") or "Bez tytułu")
            filename = str(record.get("filename") or "")
            status = str(record.get("status") or "completed")
            if status not in {"completed", "error", "stopped", "interrupted"}:
                status = "completed"
            downloaded_at = str(record.get("downloaded_at") or now_iso())
            migrated.append(
                {
                    "job_id": job_id,
                    "url": str(record.get("url") or ""),
                    "title": title[:300],
                    "status": status,
                    "download_type": str(record.get("type") or "best"),
                    "format_id": record.get("format_id"),
                    "progress": 100.0 if status == "completed" else 0.0,
                    "downloaded_bytes": record.get("size"),
                    "total_bytes": record.get("size"),
                    "created_at": downloaded_at,
                    "started_at": None,
                    "finished_at": downloaded_at,
                    "error_message": None,
                    "warning_message": record.get("warning_message"),
                    "output_file": filename or None,
                    "output_files": [filename] if filename else [],
                    "thumbnail_filename": record.get("thumbnail_filename"),
                    "source_thumbnail_filename": record.get("source_thumbnail_filename"),
                    "thumbnail_types": record.get("thumbnail_types") if isinstance(record.get("thumbnail_types"), dict) else {},
                    "auto_tags": record.get("auto_tags") if isinstance(record.get("auto_tags"), list) else [],
                    "error_code": record.get("error_code"),
                    "storage_name": str(record.get("storage_name") or "local"),
                    "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
                    "is_live": False,
                    "live_from_start": True,
                    "duration": record.get("duration"),
                    "log_lines": ["[history] Przeniesiono z historii pobrań do zadań."],
                    "tags": record.get("tags") if isinstance(record.get("tags"), list) else [],
                    "auto_retry_attempts": 0,
                    "auto_retry_max_attempts": AUTO_RETRY_MAX_ATTEMPTS,
                    "next_retry_at": None,
                }
            )
            existing_keys.add(identity)
            existing_job_ids.add(job_id)
        if migrated:
            self.state_store.jobs_replace(jobs + migrated, replace_logs=True)
            LOGGER.info(
                "Przeniesiono %s wpisów historii pobrań do widoku zadań.",
                len(migrated),
            )
        self.state_store.history_clear()

    @staticmethod
    def _history_identity(url: object, filename: object, timestamp: object) -> str:
        raw = "\n".join(str(value or "") for value in (url, filename, timestamp))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def job_dict(self, job: Job, include_full_log: bool = False) -> dict[str, Any]:
        """Serialize a job with labels consumed by JSON clients."""

        payload = asdict(job)
        payload["status_label"] = self.STATUS_LABELS.get(job.status, job.status)
        payload["can_delete"] = job.status in self.DELETABLE_STATUSES
        payload["can_retry"] = job.status == "error"
        payload["can_stop"] = job.status in self.STOPPABLE_STATUSES
        payload["can_resume"] = (
            not job.is_live and job.status in self.RESUMABLE_STATUSES
        )
        payload["can_repeat"] = (
            bool(job.url)
            and not job.is_live
            and job.status == "completed"
            and (job.download_type != "format" or bool(job.format_id))
        )
        if job.is_live and job.started_at and job.status in self.ACTIVE_STATUSES:
            job.live_elapsed_seconds = self._seconds_since(job.started_at)
            payload["live_elapsed_seconds"] = job.live_elapsed_seconds
            payload["live_status_message"] = self._live_status_message(job)
        payload["live_elapsed_label"] = self._duration_label(
            payload.get("live_elapsed_seconds")
        )
        recent_log_lines = payload["log_lines"][-JOB_LOG_PREVIEW_LINE_LIMIT:]
        payload["recent_log_lines"] = recent_log_lines
        if include_full_log:
            full_log_lines = self.state_store.job_logs(job.job_id)
            payload["log_lines"] = full_log_lines or recent_log_lines
        else:
            payload["log_lines"] = recent_log_lines
        payload["thumbnail_exists"] = False
        payload["source_thumbnail_exists"] = False
        payload["thumbnail_types"] = {
            "video": bool(job.thumbnail_filename),
            "source": bool(job.source_thumbnail_filename),
            **dict(job.thumbnail_types or {}),
        }
        if job.thumbnail_filename:
            try:
                payload["thumbnail_exists"] = self.file_service.resolve_thumbnail(
                    job.thumbnail_filename
                ).is_file()
            except (FileNotFoundError, OSError, ValueError):
                payload["thumbnail_exists"] = False
        if job.source_thumbnail_filename:
            try:
                payload["source_thumbnail_exists"] = self.file_service.resolve_thumbnail(
                    job.source_thumbnail_filename
                ).is_file()
            except (FileNotFoundError, OSError, ValueError):
                payload["source_thumbnail_exists"] = False
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
        source_id: str | None = None,
        download_options: dict[str, Any] | None = None,
        storage_name: str | None = None,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            url=url,
            title=(title or "Bez tytułu")[:300],
            status="pending",
            download_type=download_type,
            format_id=format_id,
            source_id=source_id,
            download_options=dict(download_options or {}),
            is_live=is_live,
            live_from_start=live_from_start,
            duration=duration,
            auto_retry_max_attempts=AUTO_RETRY_MAX_ATTEMPTS,
            storage_name=storage_name or self.file_service.storage_name,
            auto_tags=generate_auto_tags(url, download_type, is_live=is_live),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            comparable = asdict(job)
            comparable.pop("log_lines", None)
            self._persisted_jobs[job.job_id] = json.dumps(
                comparable, sort_keys=True, default=str
            )
            self._persisted_status[job.job_id] = job.status
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
        job.source_thumbnail_filename = None
        job.thumbnail_types = {}
        job.auto_tags = generate_auto_tags(job.url, job.download_type, job.metadata, job.is_live)
        job.error_code = None
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
        if self._shutdown_event.is_set():
            job.next_retry_at = None
            return
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
        if self._shutdown_event.is_set():
            return
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
                if self._live_recording_exists(job.url, exclude_job_id=job.job_id):
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
                    self.media_service.download_options(
                        job.download_type, job.format_id, job.download_options
                    )
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
            self._submit_download(snapshot.job_id, stop_event)

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

    def _append_download_parameters(self, job: Job) -> None:
        validated_url, options = self.media_service.effective_download_options(
            job.url, job.download_type, job.format_id, job.download_options
        )
        payload = {
            "url": validated_url,
            "download_type": job.download_type,
            "format_id": job.format_id,
            "source_id": job.source_id,
            "download_options": job.download_options,
            "yt_dlp_options": options,
        }
        self._append_log_line(job, "[yt-dlp] Parametry pobierania:", limit=None)
        for line in json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ).splitlines():
            self._append_log_line(job, line, limit=None)

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
                    self._append_download_parameters(job)
                collected: set[Path] = set()

                def collect_path(data: dict[str, Any]) -> None:
                    info = data.get("info_dict") or {}
                    if isinstance(info, dict):
                        metadata = self._metadata_snapshot(info)
                        if metadata:
                            with self._lock:
                                active = self._jobs.get(job_id)
                                if active:
                                    active.metadata.update(metadata)
                                    active.auto_tags = generate_auto_tags(
                                        active.url,
                                        active.download_type,
                                        active.metadata,
                                        active.is_live,
                                    )
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
                        self._persist_progress(
                            active, force=data.get("status") == "finished"
                        )

                def postprocessor_hook(data: dict[str, Any]) -> None:
                    collect_path(data)
                    with self._lock:
                        active = self._jobs[job_id]
                        metadata_title = self._metadata_title(data)
                        if metadata_title:
                            active.title = metadata_title
                        log_line = self._postprocessor_log_line(data)
                        if log_line:
                            self._append_log_line(active, log_line)

                try:
                    paths = self.media_service.download(
                        url=job.url,
                        download_type=job.download_type,
                        format_id=job.format_id,
                        download_options=job.download_options,
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
                        active.auto_tags = generate_auto_tags(
                            active.url,
                            active.download_type,
                            active.metadata,
                            active.is_live,
                        )
                        self._finish(active, "completed")
                except DownloadStoppedError:
                    with self._lock:
                        self._finish(
                            self._jobs[job_id],
                            "interrupted" if self._shutdown_event.is_set() else "stopped",
                            error_code=DOWNLOAD_STOPPED if self._shutdown_event.is_set() else None,
                        )
                except MediaServiceError as error:
                    if self._shutdown_event.is_set() or stop_event.is_set():
                        with self._lock:
                            self._finish(
                                self._jobs[job_id],
                                "interrupted",
                                error_code=DOWNLOAD_STOPPED,
                            )
                        return
                    self._fail(job_id, str(error))
                except Exception as error:
                    LOGGER.exception("Nieoczekiwany błąd zadania %s", job_id)
                    if self._shutdown_event.is_set() or stop_event.is_set():
                        with self._lock:
                            self._finish(
                                self._jobs[job_id],
                                "interrupted",
                                error_code=DOWNLOAD_STOPPED,
                            )
                        return
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
            last_status_log = 0.0
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
                    now_monotonic = time.monotonic()
                    should_log_status = (
                        now_monotonic - last_status_log >= LIVE_STATUS_LOG_INTERVAL_SECONDS
                    )
                    self._refresh_live_progress(
                        job_id,
                        paths,
                        append_status_log=should_log_status,
                    )
                    if should_log_status:
                        last_status_log = now_monotonic
                    if stop_event.is_set() and process.poll() is None:
                        self._interrupt_process(process)
                return_code = process.wait()
                status = (
                    ("interrupted" if self._shutdown_event.is_set() else "stopped")
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
                    self._finish(
                        active,
                        status,
                        error_code=DOWNLOAD_STOPPED if status == "interrupted" else None,
                    )
            except Exception as error:
                LOGGER.exception("Błąd procesu live %s", job_id)
                if self._shutdown_event.is_set() or stop_event.is_set():
                    with self._lock:
                        self._finish(
                            self._jobs[job_id],
                            "interrupted",
                            error_code=DOWNLOAD_STOPPED,
                        )
                    return
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
                    status = "interrupted" if self._shutdown_event.is_set() else "stopped"
                    self._finish(
                        job,
                        status,
                        error_code=DOWNLOAD_STOPPED if status == "interrupted" else None,
                    )
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

    def _refresh_live_progress(
        self,
        job_id: str,
        paths: set[Path],
        append_status_log: bool = False,
    ) -> None:
        """Update live size and elapsed time while yt-dlp is still running."""

        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.is_live:
                return
            now_monotonic = time.monotonic()
            size_due = (
                now_monotonic - self._last_live_size_update.get(job_id, 0.0)
                >= LIVE_SIZE_UPDATE_INTERVAL_SECONDS
            )
            if paths and size_due:
                size = self._paths_size(paths)
                if size is not None:
                    job.downloaded_bytes = size
                    job.total_bytes = size
                self._last_live_size_update[job_id] = now_monotonic
            if job.started_at:
                job.live_elapsed_seconds = self._seconds_since(job.started_at)
            job.live_status_message = self._live_status_message(job)
            if append_status_log:
                self._append_log_line(job, f"[live] {job.live_status_message}")
            self._persist_progress(job)

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
                files.append(path.relative_to(self.file_service.download_dir).as_posix())
                try:
                    thumbnail = self.file_service.generate_thumbnail(files[-1])
                    if thumbnail.filename and not job.thumbnail_filename:
                        job.thumbnail_filename = thumbnail.filename
                    if thumbnail.warning_message and not job.warning_message:
                        job.warning_message = thumbnail.warning_message
                    source_thumbnail = self.file_service.download_source_thumbnail(
                        files[-1], str(job.metadata.get("thumbnail") or "")
                    )
                    if source_thumbnail.filename and not job.source_thumbnail_filename:
                        job.source_thumbnail_filename = source_thumbnail.filename
                    job.thumbnail_types = {
                        "video": bool(job.thumbnail_filename),
                        "source": bool(job.source_thumbnail_filename),
                    }
                except (FileNotFoundError, ValueError):
                    LOGGER.warning("Pominięto wynik poza katalogiem pobrań: %s", path)
        return files

    @staticmethod
    def _paths_size(paths: set[Path]) -> int | None:
        total = 0
        seen = False
        for path in paths:
            try:
                if path.is_file():
                    total += path.stat().st_size
                    seen = True
            except OSError:
                continue
        return total if seen else None

    @staticmethod
    def _seconds_since(value: str) -> int | None:
        try:
            started_at = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - started_at).total_seconds()))

    @staticmethod
    def _duration_label(seconds: int | None) -> str:
        if seconds is None:
            return "-"
        minutes, second = divmod(max(0, int(seconds)), 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02d}:{minute:02d}:{second:02d}"

    def _live_status_message(self, job: Job) -> str:
        parts = [f"czas zapisu {self._duration_label(job.live_elapsed_seconds)}"]
        size = self._display_size(job.downloaded_bytes)
        if size:
            parts.append(f"zapisano {size}")
        if job.speed:
            parts.append(f"predkosc {job.speed}")
        if job.live_from_start:
            parts.append("tryb od poczatku live")
        return "; ".join(parts)

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

    @staticmethod
    def _metadata_title(data: dict[str, Any]) -> str | None:
        info = data.get("info_dict") or {}
        if not isinstance(info, dict):
            return None
        title = str(info.get("fulltitle") or info.get("title") or "").strip()
        if not title or title.startswith(("http://", "https://")):
            return None
        return title[:300]

    @staticmethod
    def _metadata_snapshot(info: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id",
            "title",
            "fulltitle",
            "platform",
            "extractor_key",
            "webpage_url",
            "thumbnail",
            "duration",
            "height",
            "resolution",
            "vcodec",
            "upload_date",
            "release_date",
            "release_year",
            "live_status",
            "is_live",
            "content_type",
        )
        snapshot: dict[str, Any] = {}
        for key in keys:
            value = info.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                snapshot[key] = value
        requested = info.get("requested_downloads")
        if isinstance(requested, list):
            snapshot["requested_downloads"] = [
                {
                    item_key: item.get(item_key)
                    for item_key in ("height", "resolution", "vcodec", "acodec")
                    if isinstance(item.get(item_key), (str, int, float, bool))
                }
                for item in requested
                if isinstance(item, dict)
            ]
        return {key: value for key, value in snapshot.items() if value not in (None, "")}

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
        if self.notifier and hasattr(self.notifier, "emit_job_event"):
            self.notifier.emit_job_event(Job(**asdict(job)), "job_started")
        if job.is_live and self.notifier and hasattr(self.notifier, "notify_lifecycle"):
            self.notifier.notify_lifecycle(Job(**asdict(job)), "live_started")

    def _finish(
        self, job: Job, status: str, error_code: str | None = None
    ) -> None:
        if self._shutdown_event.is_set() and job.status == "interrupted" and status == "error":
            return
        job.status = status
        job.finished_at = now_iso()
        job.speed = None
        job.eta = None
        if error_code:
            job.error_code = error_code
        elif status == "error":
            job.error_code = error_code_for_message(job.error_message)
        self._persist_jobs()
        if status == "completed":
            self._remember_identity(job)
        if status in {"completed", "error"} and self.notifier:
            self.notifier.notify_job(Job(**asdict(job)))
            if hasattr(self.notifier, "emit_job_event"):
                self.notifier.emit_job_event(Job(**asdict(job)))
            try:
                storage_usage = self.file_service.storage_usage()
                self.notifier.notify_storage({
                    **storage_usage,
                    "storage": job.storage_name,
                    "size": storage_usage.get("free"),
                })
            except Exception as error:
                LOGGER.warning("Nie udało się sprawdzić miejsca na dysku: %s", error)

        if job.is_live and status in {"completed", "stopped", "interrupted"} and self.notifier:
            snapshot = Job(**asdict(job))
            if hasattr(self.notifier, "notify_lifecycle"):
                self.notifier.notify_lifecycle(snapshot, "live_finished")

    def _remember_identity(self, job: Job) -> None:
        filename = job.output_file or (job.output_files[0] if job.output_files else "")
        checksum = None
        if filename:
            try:
                path = self.file_service.resolve_download(filename)
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                checksum = digest.hexdigest()
            except (OSError, ValueError):
                LOGGER.warning("Nie można obliczyć SHA-256 dla %s", filename)
        metadata = job.metadata if isinstance(job.metadata, dict) else {}
        self.state_store.remember_download_identity({
            "job_id": job.job_id,
            "source_id": job.source_id,
            "extractor_key": metadata.get("extractor_key") or metadata.get("extractor"),
            "canonical_url": self._process_url_key(job.url),
            "title_key": " ".join(job.title.casefold().split()),
            "filename_key": Path(filename).name.casefold() if filename else None,
            "sha256": checksum,
        })

    def _fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if self._shutdown_event.is_set() and job.status == "interrupted":
                LOGGER.info("Pomijam oznaczenie %s jako error podczas shutdownu.", job_id)
                return
            self._append_log_line(job, f"[error] {message}")
            job.error_message = message
            self._finish(job, "error", error_code=error_code_for_message(message))
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
                LOGGER.warning("Pominięto niepoprawny rekord trwałej kolejki zadań")
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
                LOGGER.warning("Pominięto niepoprawny rekord zadania: %s", error)
                continue
            if job.status in self.ACTIVE_STATUSES:
                job.status = "interrupted"
                job.finished_at = now_iso()
                job.speed = None
                job.eta = None
                job.error_message = "Zadanie zostało przerwane przez restart aplikacji."
                job.error_code = DOWNLOAD_STOPPED
                interrupted = True
            self._jobs[job.job_id] = job
        orphan_notes = self._annotate_interrupted_orphans()
        if interrupted or orphan_notes:
            self._persist_jobs()
        LOGGER.info("Odtworzono %s zadań z trwałej kolejki", len(self._jobs))

    def _persist_jobs(self) -> None:
        """Write a consistent queue snapshot without interrupting active work."""

        try:
            with self._lock:
                records = {job_id: asdict(job) for job_id, job in self._jobs.items()}
            for removed_id in set(self._persisted_jobs) - set(records):
                self.state_store.delete_job(removed_id)
                self._persisted_jobs.pop(removed_id, None)
                self._persisted_status.pop(removed_id, None)
            for job_id, record in records.items():
                comparable = dict(record)
                comparable.pop("log_lines", None)
                fingerprint = json.dumps(comparable, sort_keys=True, default=str)
                if self._persisted_jobs.get(job_id) != fingerprint:
                    status_changed = (
                        job_id in self._persisted_jobs
                        and self._persisted_status.get(job_id) != record.get("status")
                    )
                    if status_changed:
                        self.state_store.update_job_status(job_id, record)
                    else:
                        self.state_store.upsert_job(record)
                    self._persisted_jobs[job_id] = fingerprint
                    self._persisted_status[job_id] = str(record.get("status") or "")
        except (OSError, TypeError, ValueError, sqlite3.Error) as error:
            LOGGER.error("Nie można zapisać trwałej kolejki zadań: %s", error)

    def _persist_progress(self, job: Job, force: bool = False) -> None:
        """Persist one job at most every two seconds and after a 1% change."""
        now_monotonic = time.monotonic()
        previous_time, previous_progress = self._last_progress_write.get(
            job.job_id, (0.0, -PROGRESS_MIN_DELTA_PERCENT)
        )
        if not force and (
            now_monotonic - previous_time < PROGRESS_PERSIST_INTERVAL_SECONDS
            or abs(job.progress - previous_progress) < PROGRESS_MIN_DELTA_PERCENT
        ):
            return
        record = asdict(job)
        self.state_store.update_job_progress(job.job_id, record)
        comparable = dict(record)
        comparable.pop("log_lines", None)
        self._persisted_jobs[job.job_id] = json.dumps(comparable, sort_keys=True, default=str)
        self._persisted_status[job.job_id] = job.status
        self._last_progress_write[job.job_id] = (now_monotonic, job.progress)
