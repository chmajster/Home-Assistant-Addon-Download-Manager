"""Persistent background job manager with controllable live recording processes."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .file_service import FileService
from .media_service import MediaService, MediaServiceError

LOGGER = logging.getLogger(__name__)
PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<progress>\d+(?:\.\d+)?)%.*?(?:at\s+(?P<speed>\S+))?.*?(?:ETA\s+(?P<eta>\S+))?$"
)
DESTINATION_RE = re.compile(
    r"(?:Destination:|Merging formats into|Correcting container in|Extracting audio from)\s+[\"']?(?P<path>.+?)[\"']?$"
)


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
    speed: str | None = None
    eta: str | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    output_file: str | None = None
    output_files: list[str] = field(default_factory=list)
    is_live: bool = False


class JobManager:
    """Queue downloads, persist snapshots, and supervise dedicated live processes."""

    ACTIVE_STATUSES = {"pending", "downloading", "stopping"}
    STOPPABLE_STATUSES = {"pending", "downloading"}
    RESUMABLE_STATUSES = {"stopped", "interrupted"}
    STATUS_LABELS = {
        "pending": "oczekuje",
        "downloading": "pobieranie",
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
    ) -> None:
        self.media_service = media_service
        self.file_service = file_service
        self.max_concurrent_jobs = max_concurrent_jobs
        self.jobs_file = jobs_file or file_service.history_file.parent / "queue.json"
        self._jobs: dict[str, Job] = {}
        self._live_processes: dict[str, subprocess.Popen[str]] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_concurrent_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_jobs, thread_name_prefix="download"
        )
        self._load_jobs()

    def start_download(
        self, url: str, title: str, download_type: str, format_id: str | None = None
    ) -> Job:
        """Queue one regular yt-dlp download."""

        validated_url = self.media_service.validate_url(url)
        self.media_service.format_selection(download_type, format_id)
        job = self._new_job(
            validated_url, title, download_type, is_live=False, format_id=format_id
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
            job.status = "pending"
            job.finished_at = None
            job.error_message = None
            job.speed = None
            job.eta = None
            stop_event = threading.Event()
            self._stop_events[job_id] = stop_event
            self._persist_jobs()
        self._executor.submit(self._run_download, job_id, stop_event)
        LOGGER.info("Wznowiono pobieranie %s", job_id)
        return self.get_job(job_id)

    def start_live(self, url: str, title: str) -> Job:
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
        job = self._new_job(validated_url, title, "live", is_live=True)
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
            if job.status == "pending":
                self._finish(job, "stopped")
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

    def job_dict(self, job: Job) -> dict[str, Any]:
        """Serialize a job with labels consumed by JSON clients."""

        payload = asdict(job)
        payload["status_label"] = self.STATUS_LABELS.get(job.status, job.status)
        return payload

    def _new_job(
        self,
        url: str,
        title: str,
        download_type: str,
        is_live: bool,
        format_id: str | None = None,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            url=url,
            title=(title or "Bez tytułu")[:300],
            status="pending",
            download_type=download_type,
            format_id=format_id,
            is_live=is_live,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist_jobs()
        return Job(**asdict(job))

    def _run_download(self, job_id: str, stop_event: threading.Event) -> None:
        try:
            with self._slots:
                with self._lock:
                    job = self._jobs[job_id]
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
                        if data.get("status") == "downloading":
                            active.progress = self._percentage(data)
                            active.speed = self._display_speed(data.get("speed"))
                            active.eta = self._display_eta(data.get("eta"))
                        elif data.get("status") == "finished":
                            active.progress = 100.0

                try:
                    paths = self.media_service.download(
                        url=job.url,
                        download_type=job.download_type,
                        format_id=job.format_id,
                        progress_hook=progress_hook,
                        postprocessor_hook=collect_path,
                    )
                    if stop_event.is_set():
                        raise DownloadStoppedError
                    collected.update(paths)
                    files = self._record_existing_outputs(job_id, collected, "completed")
                    if not files:
                        raise MediaServiceError(
                            "Pobieranie zakończyło się bez gotowego pliku. Sprawdź logi dodatku."
                        )
                    with self._lock:
                        active = self._jobs[job_id]
                        active.output_files = files
                        active.output_file = files[0] if files else None
                        active.progress = 100.0
                        self._finish(active, "completed")
                except DownloadStoppedError:
                    with self._lock:
                        self._finish(self._jobs[job_id], "stopped")
                except MediaServiceError as error:
                    self._fail(job_id, str(error))
                except Exception:
                    LOGGER.exception("Nieoczekiwany błąd zadania %s", job_id)
                    self._fail(job_id, "Nieoczekiwany błąd podczas pobierania.")
        finally:
            with self._lock:
                if self._stop_events.get(job_id) is stop_event:
                    self._stop_events.pop(job_id, None)

    def _run_live(self, job_id: str) -> None:
        stop_event = self._stop_events[job_id]
        with self._slots:
            with self._lock:
                job = self._jobs[job_id]
                if stop_event.is_set():
                    self._finish(job, "stopped")
                    self._stop_events.pop(job_id, None)
                    return
                self._start(job)
            paths: set[Path] = set()
            try:
                command = self.media_service.live_command(job.url)
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
                    LOGGER.info("[live %s] %s", job_id[:8], line.rstrip())
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
                    if status == "error":
                        active.error_message = "yt-dlp nie mógł zapisać transmisji live. Sprawdź logi dodatku."
                    self._finish(active, status)
            except Exception:
                LOGGER.exception("Błąd procesu live %s", job_id)
                self._fail(job_id, "Nie udało się uruchomić zapisu transmisji live.")
            finally:
                with self._lock:
                    self._live_processes.pop(job_id, None)
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
                    self.file_service.record_download(
                        job.title, job.url, job.download_type, path.name, status
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

    def _fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.error_message = message
            self._finish(job, "error")

    def _load_jobs(self) -> None:
        """Restore persisted jobs and mark unfinished work as interrupted."""

        try:
            if not self.jobs_file.exists():
                return
            with self.jobs_file.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            if not isinstance(payload, list):
                raise ValueError("oczekiwano listy zadań")
        except (OSError, json.JSONDecodeError, ValueError) as error:
            LOGGER.error("Nie można odczytać trwałej kolejki zadań: %s", error)
            return

        field_names = {item.name for item in fields(Job)}
        interrupted = False
        for record in payload:
            if not isinstance(record, dict):
                LOGGER.warning("Pominięto niepoprawny rekord trwałej kolejki zadań")
                continue
            try:
                job = Job(**{key: value for key, value in record.items() if key in field_names})
            except TypeError as error:
                LOGGER.warning("Pominięto niepoprawny rekord zadania: %s", error)
                continue
            if job.status in self.ACTIVE_STATUSES:
                job.status = "interrupted"
                job.finished_at = now_iso()
                job.speed = None
                job.eta = None
                job.error_message = "Zadanie zostało przerwane przez restart aplikacji."
                interrupted = True
            self._jobs[job.job_id] = job
        if interrupted:
            self._persist_jobs()
        LOGGER.info("Odtworzono %s zadań z trwałej kolejki", len(self._jobs))

    def _persist_jobs(self) -> None:
        """Write a consistent queue snapshot without interrupting active work."""

        temp_file = self.jobs_file.with_suffix(".tmp")
        try:
            self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                records = [asdict(job) for job in self._jobs.values()]
            with temp_file.open("w", encoding="utf-8") as file_handle:
                json.dump(records, file_handle, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.jobs_file)
        except (OSError, TypeError) as error:
            LOGGER.error("Nie można zapisać trwałej kolejki zadań: %s", error)
