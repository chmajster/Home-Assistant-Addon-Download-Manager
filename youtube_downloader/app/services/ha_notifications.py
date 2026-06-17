"""Home Assistant notification helpers."""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

LOGGER = logging.getLogger(__name__)
HA_API_URL = "http://supervisor/core/api"


class HomeAssistantNotifier:
    """Send persistent notifications to Home Assistant Core through Supervisor."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = HA_API_URL,
        timeout: float = 5.0,
    ) -> None:
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def notify_job(self, job: Any) -> None:
        """Notify when a job reaches a final success or error state."""

        if hasattr(job, "__dataclass_fields__"):
            payload = asdict(job)
        elif hasattr(job, "__dict__"):
            payload = vars(job)
        else:
            payload = dict(job)
        status = payload.get("status")
        if status == "completed":
            output_files = payload.get("output_files") or []
            self._send_async(
                (
                    "Media Web Downloader: playlista zakończona"
                    if len(output_files) > 1
                    else "Media Web Downloader: pobieranie zakończone"
                ),
                self._completed_message(payload),
                self._notification_id(payload, "completed"),
            )
        elif status == "error":
            is_storage_error = self._is_storage_error(payload.get("error_message"))
            self._send_async(
                (
                    "Media Web Downloader: brak miejsca na dysku"
                    if is_storage_error
                    else "Media Web Downloader: błąd pobierania"
                ),
                self._error_message(payload),
                self._notification_id(
                    payload, "storage_error" if is_storage_error else "error"
                ),
            )

    def notify_storage(self, storage: dict[str, Any]) -> None:
        """Notify Home Assistant when free space is low after a finished job."""

        try:
            free_percent = float(storage.get("free_percent") or 0)
        except (TypeError, ValueError):
            free_percent = 0.0
        if free_percent >= 15:
            return
        severity = "krytycznie mało miejsca" if free_percent < 5 else "mało miejsca"
        self._send_async(
            f"Media Web Downloader: {severity}",
            self._storage_message(storage),
            "media_web_downloader_storage_low",
        )

    def health_status(self) -> dict[str, Any]:
        """Return a compact Home Assistant API diagnostic status."""

        status: dict[str, Any] = {
            "base_url": self.base_url,
            "token_configured": bool(self.token),
            "available": False,
            "status_code": None,
            "message": "",
        }
        if not self.token:
            status["message"] = "Brak SUPERVISOR_TOKEN."
            return status

        request = urllib.request.Request(
            f"{self.base_url}/",
            method="GET",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
                status["status_code"] = response.status
                status["available"] = 200 <= response.status < 300
                status["message"] = (
                    "API Home Assistant odpowiada."
                    if status["available"]
                    else "API odpowiedziało kodem błędu."
                )
        except (OSError, urllib.error.URLError) as error:
            status["message"] = str(error)
        return status

    def _send_async(self, title: str, message: str, notification_id: str) -> None:
        if not self.token:
            LOGGER.debug("Brak SUPERVISOR_TOKEN, pomijam powiadomienie Home Assistant.")
            return
        thread = threading.Thread(
            target=self._send,
            args=(title, message, notification_id),
            daemon=True,
            name="ha-notification",
        )
        thread.start()

    def _send(self, title: str, message: str, notification_id: str) -> None:
        body = json.dumps(
            {
                "title": title,
                "message": message,
                "notification_id": notification_id,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/services/persistent_notification/create",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except (OSError, urllib.error.URLError) as error:
            LOGGER.warning("Nie udało się wysłać powiadomienia Home Assistant: %s", error)

    @staticmethod
    def _completed_message(job: dict[str, Any]) -> str:
        lines = [
            f"Tytuł: {job.get('title') or 'brak danych'}",
            f"Typ: {job.get('download_type') or 'brak danych'}",
        ]
        files = job.get("output_files") or []
        if files:
            lines.append("Pliki: " + ", ".join(str(item) for item in files))
        elif job.get("output_file"):
            lines.append(f"Plik: {job['output_file']}")
        return "\n".join(lines)

    @staticmethod
    def _error_message(job: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Tytuł: {job.get('title') or 'brak danych'}",
                f"URL: {job.get('url') or 'brak danych'}",
                f"Błąd: {job.get('error_message') or 'nieznany błąd'}",
            ]
        )

    @staticmethod
    def _storage_message(storage: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Wolne: {storage.get('free_percent', 'brak danych')}%",
                f"Zajęte: {storage.get('used_percent', 'brak danych')}%",
                "Usuń starsze pliki albo zwiększ dostępne miejsce przed kolejnymi pobraniami.",
            ]
        )

    @staticmethod
    def _is_storage_error(message: object) -> bool:
        lowered = str(message or "").casefold()
        return any(
            marker in lowered
            for marker in (
                "no space left",
                "not enough space",
                "disk full",
                "brak miejsca",
                "za mało miejsca",
            )
        )

    @staticmethod
    def _notification_id(job: dict[str, Any], suffix: str) -> str:
        job_id = str(job.get("job_id") or "unknown")[:12]
        return f"media_web_downloader_{job_id}_{suffix}"
