"""Home Assistant notification and event helpers."""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)
HA_API_URL = "http://supervisor/core/api"


class HomeAssistantNotifier:
    """Send safe persistent notifications and optional HA events."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = HA_API_URL,
        timeout: float = 5.0,
        events_enabled: bool | None = None,
        enabled_event_types: dict[str, bool] | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.events_enabled = (
            _truthy(os.environ.get("MEDIA_WEB_DOWNLOADER_HA_EVENTS"))
            if events_enabled is None
            else events_enabled
        )
        self.enabled_event_types = dict(enabled_event_types or {})

    def notify_job(self, job: Any) -> None:
        """Notify when a job reaches a final success or error state."""

        payload = self._job_payload(job)
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
            storage_error = self._is_storage_error(payload.get("error_message"))
            self._send_async(
                (
                    "Media Web Downloader: brak miejsca na dysku"
                    if storage_error
                    else "Media Web Downloader: błąd pobierania"
                ),
                self._error_message(payload),
                self._notification_id(
                    payload, "storage_error" if storage_error else "error"
                ),
            )

    def notify_lifecycle(self, job: Any, event_type: str) -> None:
        """Notify about live lifecycle events."""

        payload = self._job_payload(job)
        if event_type == "live_started":
            self._send_async(
                "Media Web Downloader: live rozpoczęty",
                self._status_message(payload),
                self._notification_id(payload, "live_started"),
            )
            self.emit_job_event(payload, "live_started")
        elif event_type == "live_finished":
            self._send_async(
                "Media Web Downloader: live zakończony",
                self._status_message(payload),
                self._notification_id(payload, "live_finished"),
            )
            self.emit_job_event(payload, "live_finished")

    def notify_storage(self, storage: dict[str, Any]) -> None:
        """Notify Home Assistant when free space is low after a finished job."""

        try:
            free_percent = float(storage.get("free_percent") or 0)
        except (TypeError, ValueError):
            free_percent = 0.0
        if free_percent >= 15:
            return
        self.emit_event("low_storage", storage)
        severity = "krytycznie mało miejsca" if free_percent < 5 else "mało miejsca"
        self._send_async(
            f"Media Web Downloader: {severity}",
            self._storage_message(storage),
            "media_web_downloader_storage_low",
        )

    def emit_job_event(self, job: Any, event_override: str | None = None) -> None:
        """Emit an optional local Home Assistant event with a safe payload."""

        if not self.events_enabled:
            return
        payload = self._job_payload(job)
        event_key = event_override or {
            "completed": "job_completed",
            "error": "job_failed",
        }.get(str(payload.get("status") or ""))
        event_name = str(event_key or "")
        if not event_name:
            return
        self.emit_event(event_name, self._safe_event_payload(payload))

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit one configured event using the stable HA event namespace."""
        if not self.events_enabled or not self.enabled_event_types.get(event_type, True):
            return
        allowed = {
            "job_started", "job_completed", "job_failed", "live_started",
            "live_finished", "low_storage", "subscription_found_items",
        }
        if event_type not in allowed:
            return
        normalized = {
            "job_id": str(payload.get("job_id") or ""),
            "title": str(payload.get("title") or "")[:300],
            "status": str(payload.get("status") or event_type),
            "storage": str(payload.get("storage") or payload.get("storage_name") or ""),
            "filename": str(payload.get("filename") or payload.get("output_file") or ""),
            "size": payload.get("size"),
            "platform": str(payload.get("platform") or ""),
            "error_code": str(payload.get("error_code") or ""),
        }
        normalized.update({key: value for key, value in payload.items() if key not in normalized})
        self._send_event_async(f"media_downloader_{event_type}", normalized)

    def notify_subscription_found_items(self, payload: dict[str, Any]) -> None:
        """Public integration hook for the future subscription scanner."""
        self.emit_event("subscription_found_items", payload)

    def health_status(self) -> dict[str, Any]:
        """Return a compact Home Assistant API diagnostic status."""

        status: dict[str, Any] = {
            "base_url": self.base_url,
            "token_configured": bool(self.token),
            "events_enabled": self.events_enabled,
            "enabled_event_types": self.enabled_event_types,
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
                    else "API odpowiedzialo kodem bledu."
                )
        except (OSError, urllib.error.URLError) as error:
            status["message"] = str(error)
        return status

    def _send_async(self, title: str, message: str, notification_id: str) -> None:
        if not self.token:
            LOGGER.debug("Brak SUPERVISOR_TOKEN, pomijam powiadomienie Home Assistant.")
            return
        threading.Thread(
            target=self._send,
            args=(title, message, notification_id),
            daemon=True,
            name="ha-notification",
        ).start()

    def _send_event_async(self, event_name: str, payload: dict[str, Any]) -> None:
        if not self.token:
            LOGGER.debug("Brak SUPERVISOR_TOKEN, pomijam event Home Assistant.")
            return
        threading.Thread(
            target=self._send_event,
            args=(event_name, payload),
            daemon=True,
            name="ha-event",
        ).start()

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
            LOGGER.warning("Nie udalo sie wyslac powiadomienia Home Assistant: %s", error)

    def _send_event(self, event_name: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/events/{event_name}",
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
            LOGGER.warning("Nie udalo sie wyslac eventu Home Assistant %s: %s", event_name, error)

    @staticmethod
    def _job_payload(job: Any) -> dict[str, Any]:
        if hasattr(job, "__dataclass_fields__"):
            return asdict(job)
        if hasattr(job, "__dict__"):
            return dict(vars(job))
        return dict(job)

    @staticmethod
    def _completed_message(job: dict[str, Any]) -> str:
        lines = HomeAssistantNotifier._base_job_lines(job)
        files = job.get("output_files") or []
        if files:
            lines.append("Pliki: " + ", ".join(str(item) for item in files))
        elif job.get("output_file"):
            lines.append(f"Plik: {job['output_file']}")
        lines.extend(HomeAssistantNotifier._action_links(job, include_retry=False))
        return "\n".join(lines)

    @staticmethod
    def _error_message(job: dict[str, Any]) -> str:
        lines = HomeAssistantNotifier._base_job_lines(job)
        lines.append(f"Kod: {job.get('error_code') or 'brak danych'}")
        lines.append(f"Blad: {job.get('error_message') or 'nieznany blad'}")
        lines.extend(HomeAssistantNotifier._action_links(job, include_retry=True))
        return "\n".join(lines)

    @staticmethod
    def _status_message(job: dict[str, Any]) -> str:
        lines = HomeAssistantNotifier._base_job_lines(job)
        lines.extend(HomeAssistantNotifier._action_links(job, include_retry=False))
        return "\n".join(lines)

    @staticmethod
    def _base_job_lines(job: dict[str, Any]) -> list[str]:
        return [
            f"Tytul: {job.get('title') or 'brak danych'}",
            f"Status: {job.get('status') or 'brak danych'}",
            f"Rozmiar: {HomeAssistantNotifier._filesize(job.get('downloaded_bytes') or job.get('total_bytes'))}",
            f"Czas trwania: {HomeAssistantNotifier._duration(job.get('duration'))}",
        ]

    @staticmethod
    def _action_links(job: dict[str, Any], include_retry: bool) -> list[str]:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return []
        details_url = HomeAssistantNotifier._web_link(f"/jobs/{job_id}")
        log_url = HomeAssistantNotifier._web_link(f"/jobs/log/{job_id}")
        if not details_url or not log_url:
            return []
        actions = ["", "Akcje:"]
        if include_retry:
            actions.append(f"- [Ponow]({details_url}#job-action-retry)")
        actions.append(f"- [Otworz log]({log_url})")
        actions.append(f"- [Usun zadanie]({details_url}#job-action-delete)")
        return actions

    @staticmethod
    def _web_link(path: str) -> str:
        base_url = (
            os.environ.get("MEDIA_WEB_DOWNLOADER_URL")
            or os.environ.get("APP_BASE_URL")
            or ""
        ).rstrip("/")
        if not base_url:
            return ""
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query:
            return ""
        return f"{base_url}{path}"

    @staticmethod
    def _safe_event_payload(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": str(job.get("job_id") or ""),
            "title": str(job.get("title") or "")[:300],
            "status": str(job.get("status") or ""),
            "storage": str(job.get("storage_name") or ""),
            "filename": str(job.get("output_file") or ""),
            "size": job.get("downloaded_bytes") or job.get("total_bytes"),
            "platform": HomeAssistantNotifier._platform(job),
            "error_code": str(job.get("error_code") or ""),
        }

    @staticmethod
    def _platform(job: dict[str, Any]) -> str:
        for tag in job.get("auto_tags") or []:
            if str(tag) in {"youtube", "twitch", "kick", "vimeo", "soundcloud"}:
                return str(tag)
        return ""

    @staticmethod
    def _storage_message(storage: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Wolne: {storage.get('free_percent', 'brak danych')}%",
                f"Zajete: {storage.get('used_percent', 'brak danych')}%",
                "Usun starsze pliki albo zwieksz dostepne miejsce przed kolejnymi pobraniami.",
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
                "za malo miejsca",
            )
        )

    @staticmethod
    def _filesize(value: object) -> str:
        try:
            size = float(str(value))
        except (TypeError, ValueError):
            return "brak danych"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return "brak danych"

    @staticmethod
    def _duration(value: object) -> str:
        try:
            seconds = int(float(str(value)))
        except (TypeError, ValueError):
            return "brak danych"
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _notification_id(job: dict[str, Any], suffix: str) -> str:
        job_id = str(job.get("job_id") or "unknown")[:12]
        return f"media_web_downloader_{job_id}_{suffix}"


def _truthy(value: object) -> bool:
    return str(value or "").casefold() in {"1", "true", "yes", "on"}
