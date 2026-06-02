"""Supported media metadata analysis and yt-dlp option preparation."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .error_messages import operational_error_message

LOGGER = logging.getLogger(__name__)
ALLOWED_DOMAINS = {
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "m.youtube.com": "youtube",
    "youtu.be": "youtube",
    "music.youtube.com": "youtube",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "kick.com": "kick",
    "www.kick.com": "kick",
}
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
VIDEO_QUALITY_LIMITS = {
    "video-360": 360,
    "video-720": 720,
    "video-1080": 1080,
}


class MediaServiceError(RuntimeError):
    """User-facing yt-dlp or URL validation error."""


class MediaService:
    """Analyze supported public media links and prepare controlled downloads."""

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir.resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_url(url: str) -> str:
        """Allow only public HTTP(S) links to explicitly supported media hosts."""

        candidate = (url or "").strip()
        if not candidate or len(candidate) > 2048:
            raise MediaServiceError("Podaj poprawny adres URL obsługiwanego serwisu.")
        try:
            parts = urlsplit(candidate)
        except ValueError as error:
            raise MediaServiceError("Podany adres URL jest niepoprawny.") from error
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme.lower() not in {"http", "https"}:
            raise MediaServiceError(
                "Dozwolone są wyłącznie adresy używające HTTP lub HTTPS."
            )
        if parts.username or parts.password or parts.port:
            raise MediaServiceError(
                "Adres URL nie może zawierać danych logowania ani niestandardowego portu."
            )
        if host not in ALLOWED_DOMAINS:
            raise MediaServiceError(
                "Dozwolone są wyłącznie obsługiwane domeny YouTube, Instagram i Kick."
            )
        if not parts.path:
            raise MediaServiceError("Podaj pełny adres materiału lub kanału.")
        if ALLOWED_DOMAINS[host] == "youtube" and parts.path.rstrip("/").lower() in {
            "/redirect",
            "/attribution_link",
        }:
            raise MediaServiceError("Linki przekierowujące YouTube nie są obsługiwane.")
        return urlunsplit((parts.scheme.lower(), host, parts.path, parts.query, ""))

    @staticmethod
    def detect_platform(url: str) -> str:
        """Return the supported platform associated with an already validated URL."""

        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        return ALLOWED_DOMAINS.get(host, "unknown")

    def analyze(self, url: str) -> dict[str, Any]:
        """Extract metadata without downloading media."""

        validated_url = self.validate_url(url)
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "socket_timeout": 20,
            "noplaylist": False,
            "ignoreerrors": False,
        }
        try:
            with YoutubeDL(options) as ydl:
                raw_info = ydl.extract_info(validated_url, download=False)
        except DownloadError as error:
            raise MediaServiceError(self.polish_error(str(error))) from error
        except Exception as error:
            LOGGER.exception("Nieoczekiwany błąd analizy URL")
            raise MediaServiceError(
                operational_error_message(str(error))
                or "Nie udało się przeanalizować materiału przez yt-dlp."
            ) from error
        if not raw_info:
            raise MediaServiceError("yt-dlp nie zwrócił metadanych dla tego adresu.")
        return self._normalize_info(raw_info, validated_url)

    def download(
        self,
        url: str,
        download_type: str,
        format_id: str | None,
        progress_hook: Callable[[dict[str, Any]], None],
        postprocessor_hook: Callable[[dict[str, Any]], None],
    ) -> list[Path]:
        """Download a URL synchronously. JobManager runs this method in a worker."""

        validated_url = self.validate_url(url)
        options = self.download_options(download_type, format_id)
        options["progress_hooks"] = [progress_hook]
        options["postprocessor_hooks"] = [postprocessor_hook]
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(validated_url, download=True)
                paths = self._paths_from_info(ydl, info)
        except DownloadError as error:
            raise MediaServiceError(self.polish_error(str(error))) from error
        except OSError as error:
            raise MediaServiceError(
                operational_error_message(str(error))
                or "Nie udało się zapisać pobieranego pliku. Sprawdź logi dodatku."
            ) from error
        if download_type == "audio":
            paths.extend(path.with_suffix(".mp3") for path in list(paths))
        return self._existing_managed_paths(paths)

    def download_options(
        self, download_type: str, format_id: str | None = None
    ) -> dict[str, Any]:
        """Prepare yt-dlp settings without accepting a client-provided filesystem path."""

        selection, postprocessors = self.format_selection(download_type, format_id)
        options: dict[str, Any] = {
            "format": selection,
            "outtmpl": str(self.download_dir / "%(title).180B [%(id)s].%(ext)s"),
            "restrictfilenames": True,
            "windowsfilenames": True,
            "noplaylist": False,
            "ignoreerrors": False,
            "continuedl": True,
            "nopart": False,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "postprocessors": postprocessors,
        }
        return options

    @staticmethod
    def format_selection(
        download_type: str, format_id: str | None = None
    ) -> tuple[str, list[dict[str, Any]]]:
        """Translate UI download modes into controlled yt-dlp selectors."""

        if download_type == "audio":
            return (
                "bestaudio/best",
                [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "0",
                    }
                ],
            )
        if download_type in {"best", "video"}:
            return "bestvideo*+bestaudio/best", []
        if download_type in VIDEO_QUALITY_LIMITS:
            height = VIDEO_QUALITY_LIMITS[download_type]
            return (
                f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]",
                [],
            )
        if download_type == "format":
            if not format_id or not FORMAT_ID_RE.fullmatch(format_id):
                raise MediaServiceError(
                    "Wybrany identyfikator formatu jest niepoprawny."
                )
            return format_id, []
        raise MediaServiceError("Niepoprawny typ pobierania.")

    def live_command(self, url: str) -> list[str]:
        """Build a separate yt-dlp process command for live recording."""

        validated_url = self.validate_url(url)
        options = self.download_options("best")
        return [
            "/venv/bin/python",
            "-m",
            "yt_dlp",
            "--newline",
            "--continue",
            "--no-part",
            "--socket-timeout",
            "30",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--format",
            str(options["format"]),
            "--output",
            str(options["outtmpl"]),
            validated_url,
        ]

    @staticmethod
    def polish_error(message: str) -> str:
        """Convert common extractor errors to clear Polish messages."""

        lowered = message.lower()
        known_error = operational_error_message(message)
        if known_error:
            return known_error
        if (
            "private video" in lowered
            or "sign in if you've been granted access" in lowered
        ):
            return "Ten materiał jest prywatny. Dodatek nie obsługuje logowania ani prywatnych materiałów."
        if "video unavailable" in lowered:
            return "Ten materiał jest niedostępny."
        if "removed" in lowered or "has been deleted" in lowered:
            return "Ten materiał został usunięty."
        if "upcoming" in lowered or "will begin" in lowered or "not started" in lowered:
            return "Ta transmisja jeszcze się nie rozpoczęła."
        if "drm" in lowered:
            return "Materiał jest chroniony DRM i nie może zostać pobrany."
        if "login" in lowered or "sign in" in lowered or "cookies" in lowered:
            return "Serwis wymaga dodatkowego dostępu. Dodatek nie używa logowania ani cookies."
        if "unsupported url" in lowered:
            return "yt-dlp nie obsługuje tego adresu URL."
        return "yt-dlp nie mógł obsłużyć materiału. Sprawdź dostępność linku i logi dodatku."

    def _normalize_info(self, info: dict[str, Any], url: str) -> dict[str, Any]:
        entries = info.get("entries")
        is_playlist = info.get("_type") in {"playlist", "multi_video"} or isinstance(
            entries, list
        )
        content_type = self.detect_content_type(info, url, is_playlist)
        normalized_entries: list[dict[str, Any]] = []
        if isinstance(entries, list):
            for entry in entries:
                if not entry:
                    continue
                normalized_entries.append(
                    {
                        "id": entry.get("id"),
                        "title": entry.get("title") or "Bez tytułu",
                        "url": entry.get("webpage_url") or entry.get("url"),
                        "duration": entry.get("duration"),
                    }
                )
        formats: list[dict[str, Any]] = []
        for item in info.get("formats") or []:
            if not item.get("format_id"):
                continue
            formats.append(
                {
                    "format_id": str(item["format_id"]),
                    "ext": item.get("ext"),
                    "resolution": item.get("resolution") or self._resolution(item),
                    "fps": item.get("fps"),
                    "vcodec": item.get("vcodec"),
                    "acodec": item.get("acodec"),
                    "filesize": item.get("filesize") or item.get("filesize_approx"),
                    "note": item.get("format_note"),
                }
            )
        live_status = info.get("live_status")
        return {
            "url": url,
            "platform": self.detect_platform(url),
            "title": info.get("title") or "Bez tytułu",
            "channel": info.get("channel") or info.get("uploader") or "Brak danych",
            "channel_id": info.get("channel_id") or info.get("uploader_id"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "content_type": content_type,
            "live_status": live_status,
            "is_live": bool(info.get("is_live") or live_status == "is_live"),
            "playlist_count": len(normalized_entries) if is_playlist else None,
            "entries": normalized_entries,
            "formats": formats,
        }

    @staticmethod
    def detect_content_type(
        info: dict[str, Any], url: str, is_playlist: bool = False
    ) -> str:
        """Detect a UI-friendly media type."""

        if is_playlist:
            return "playlist"
        if info.get("is_live") or info.get("live_status") in {
            "is_live",
            "is_upcoming",
            "was_live",
            "post_live",
        }:
            return "live"
        if "/shorts/" in urlsplit(url).path:
            return "shorts"
        if info.get("id"):
            return "video"
        return "unknown"

    @staticmethod
    def _resolution(item: dict[str, Any]) -> str | None:
        width, height = item.get("width"), item.get("height")
        return f"{width}x{height}" if width and height else None

    def _paths_from_info(
        self, ydl: YoutubeDL, info: dict[str, Any] | None
    ) -> list[Path]:
        paths: list[Path] = []
        if not info:
            return paths
        entries = info.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if entry:
                    paths.extend(self._paths_from_info(ydl, entry))
            return paths
        for key in ("filepath", "_filename"):
            if info.get(key):
                paths.append(Path(str(info[key])))
        requested = info.get("requested_downloads") or []
        for item in requested:
            if item.get("filepath"):
                paths.append(Path(str(item["filepath"])))
        try:
            paths.append(Path(ydl.prepare_filename(info)))
        except Exception:
            LOGGER.debug("Nie można przygotować nazwy wyniku", exc_info=True)
        return paths

    def _existing_managed_paths(self, paths: list[Path]) -> list[Path]:
        managed: list[Path] = []
        for path in paths:
            resolved = path.resolve()
            if (
                resolved.parent == self.download_dir
                and resolved.is_file()
                and resolved not in managed
            ):
                managed.append(resolved)
        return managed
