"""Convert low-level operational failures into short user-facing messages."""

from __future__ import annotations

INVALID_URL = "INVALID_URL"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
NO_DISK_SPACE = "NO_DISK_SPACE"
NETWORK_ERROR = "NETWORK_ERROR"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
DOWNLOAD_STOPPED = "DOWNLOAD_STOPPED"
POSTPROCESSING_FAILED = "POSTPROCESSING_FAILED"

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


def error_code_for_message(message: object, default: str | None = None) -> str | None:
    """Map a user-facing or low-level error message to a stable diagnostic code."""

    lowered = str(message or "").casefold()
    if any(marker in lowered for marker in DISK_ERROR_MARKERS) or "brak wolnego miejsca" in lowered:
        return NO_DISK_SPACE
    if any(marker in lowered for marker in INTERNET_ERROR_MARKERS):
        return NETWORK_ERROR
    if any(marker in lowered for marker in FFMPEG_ERROR_MARKERS):
        return POSTPROCESSING_FAILED
    if "nieobsĹ‚ugiwany format" in lowered or "format" in lowered and "niepoprawny" in lowered:
        return UNSUPPORTED_FORMAT
    if "adres url" in lowered or "link" in lowered and "nie" in lowered:
        return INVALID_URL
    if any(
        marker in lowered
        for marker in (
            "niedostÄ™pny",
            "usuniÄ™ty",
            "prywatny",
            "wymaga dodatkowego dostÄ™pu",
            "nie rozpoczÄ™Ĺ‚a",
            "source unavailable",
        )
    ):
        return SOURCE_UNAVAILABLE
    if "zatrzym" in lowered or "przerwan" in lowered:
        return DOWNLOAD_STOPPED
    return default


def thumbnail_warning_message(message: str) -> str:
    """Return a non-fatal warning for a failed thumbnail generation attempt."""

    if operational_error_message(message) == STORAGE_ERROR_MESSAGE:
        return THUMBNAIL_STORAGE_WARNING
    return THUMBNAIL_FFMPEG_WARNING
