"""Convert low-level operational failures into short user-facing messages."""

from __future__ import annotations

INTERNET_ERROR_MESSAGE = (
    "Nie udało się połączyć z internetem lub serwisem źródłowym. "
    "Sprawdź połączenie sieciowe i spróbuj ponownie."
)
STORAGE_ERROR_MESSAGE = (
    "Brak wolnego miejsca w katalogu pobrań. "
    "Usuń część plików lub zwolnij miejsce i spróbuj ponownie."
)
FFMPEG_ERROR_MESSAGE = (
    "Nie udało się przetworzyć pliku przez ffmpeg. "
    "Plik źródłowy może być uszkodzony albo format nie jest obsługiwany. "
    "Sprawdź logi dodatku."
)
THUMBNAIL_FFMPEG_WARNING = (
    "Film został pobrany, ale nie udało się wygenerować miniatury przez ffmpeg. "
    "Sprawdź logi dodatku."
)
THUMBNAIL_STORAGE_WARNING = (
    "Film został pobrany, ale miniatura nie została zapisana z powodu braku miejsca."
)

DISK_ERROR_MARKERS = (
    "no space left on device",
    "not enough space on the disk",
    "there is not enough space on the disk",
    "disk full",
    "errno 28",
    "enospc",
)
INTERNET_ERROR_MARKERS = (
    "unable to download webpage",
    "unable to download api page",
    "unable to connect",
    "connection aborted",
    "connection refused",
    "connection reset",
    "failed to establish a new connection",
    "getaddrinfo failed",
    "name resolution",
    "network is unreachable",
    "remote end closed connection",
    "temporary failure in name resolution",
    "timed out",
    "timeout",
)
FFMPEG_ERROR_MARKERS = (
    "conversion failed",
    "error opening output",
    "ffmpeg",
    "ffprobe",
    "invalid data found when processing input",
    "moov atom not found",
    "postprocessing:",
    "unable to find a suitable output format",
)


def operational_error_message(message: str) -> str | None:
    """Return a known operational error message or None for unrelated failures."""

    lowered = str(message).lower()
    if any(marker in lowered for marker in DISK_ERROR_MARKERS):
        return STORAGE_ERROR_MESSAGE
    if any(marker in lowered for marker in INTERNET_ERROR_MARKERS):
        return INTERNET_ERROR_MESSAGE
    if any(marker in lowered for marker in FFMPEG_ERROR_MARKERS):
        return FFMPEG_ERROR_MESSAGE
    return None


def thumbnail_warning_message(message: str) -> str:
    """Return a non-fatal warning for a failed thumbnail generation attempt."""

    if operational_error_message(message) == STORAGE_ERROR_MESSAGE:
        return THUMBNAIL_STORAGE_WARNING
    return THUMBNAIL_FFMPEG_WARNING
