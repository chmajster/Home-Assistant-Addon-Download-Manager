"""Safe access to the Home Assistant Supervisor host shutdown endpoint."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request


class HostShutdownError(RuntimeError):
    """A user-safe failure returned while requesting host shutdown."""


class HostShutdownService:
    """Request a host shutdown without exposing the Supervisor token to the UI."""

    ENDPOINT = "http://supervisor/host/shutdown"

    def __init__(self, *, enabled: bool, token: str | None = None) -> None:
        self.enabled = enabled
        self._token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._lock = threading.Lock()
        self._requested = False

    @property
    def available(self) -> bool:
        return self.enabled and bool(self._token)

    def shutdown(self, timeout: float = 10.0) -> None:
        """Ask Supervisor to shut down the Home Assistant host."""

        if not self.enabled:
            raise HostShutdownError(
                "Wyłączanie hosta jest niedostępne, gdy włączono publiczny port bez logowania."
            )
        if not self._token:
            raise HostShutdownError("Brak dostępu do API Supervisora.")
        with self._lock:
            if self._requested:
                return
            request = urllib.request.Request(
                self.ENDPOINT,
                data=json.dumps({"force": False}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if not 200 <= int(response.status) < 300:
                        raise HostShutdownError("Supervisor odrzucił żądanie wyłączenia.")
            except HostShutdownError:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                raise HostShutdownError(
                    "Nie udało się przekazać żądania wyłączenia do Supervisora."
                ) from error
            self._requested = True
