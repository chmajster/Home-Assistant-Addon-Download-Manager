"""Supported media metadata analysis and yt-dlp option preparation."""

from __future__ import annotations

import logging
import re
import importlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .error_messages import operational_error_message

LOGGER = logging.getLogger(__name__)
KNOWN_PLATFORM_DOMAINS = {
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "m.youtube.com": "youtube",
    "youtu.be": "youtube",
    "music.youtube.com": "youtube",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "kick.com": "kick",
    "www.kick.com": "kick",
    "twitch.tv": "twitch",
    "www.twitch.tv": "twitch",
    "m.twitch.tv": "twitch",
    "clips.twitch.tv": "twitch",
}
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
STORYBOARD_FORMAT_RE = re.compile(r"^sb\d+$", re.IGNORECASE)
SAFE_SUBDIR_RE = re.compile(r"[^A-Za-z0-9._ -]+")
SUPPORTED_AUDIO_FORMATS = {"mp3", "m4a", "opus"}
VIDEO_QUALITY_LIMITS = {
    "video-360": 360,
    "video-720": 720,
    "video-1080": 1080,
}
SUBTITLE_LANGUAGE_PREFERENCE = ("pl", "pl-orig", "en", "en-US", "en-orig")
SUBTITLE_MODE_LANGUAGE_PREFERENCES = {
    "pl": ("pl", "pl-orig"),
    "en": ("en", "en-US", "en-GB", "en-orig"),
    "auto": ("pl", "pl-orig", "en", "en-US", "en-GB", "en-orig"),
}
YOUTUBE_PUBLIC_PLAYER_CLIENTS = ("default", "mweb", "web_embedded")
YOUTUBE_ANONYMOUS_ACCESS_MESSAGE = (
    "YouTube zablokował anonimowy dostęp z tego adresu IP. "
    "Dodatek nie używa logowania ani cookies; zaktualizuj yt-dlp, odczekaj i spróbuj ponownie."
)
LOGIN_ACCESS_MESSAGE = (
    "Serwis wymaga dodatkowego dostępu. Dodatek nie używa logowania ani cookies."
)


def _yt_dlp_api() -> tuple[Any, type[Exception]]:
    yt_dlp = importlib.import_module("yt_dlp")
    utils = importlib.import_module("yt_dlp.utils")
    return yt_dlp.YoutubeDL, utils.DownloadError


@lru_cache(maxsize=1)
def _yt_dlp_extractors() -> tuple[Any, ...]:
    extractor_module = importlib.import_module("yt_dlp.extractor")
    return tuple(extractor_module.gen_extractors())


class MediaServiceError(RuntimeError):
    """User-facing yt-dlp or URL validation error."""


class MediaService:
    """Analyze supported public media links and prepare controlled downloads."""

    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir.resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_url(url: str) -> str:
        """Allow public HTTP(S) links handled by a concrete yt-dlp extractor."""

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
        normalized_url = urlunsplit(
            (parts.scheme.lower(), host, parts.path, parts.query, "")
        )
        if (
            not MediaService._known_platform(host)
            and not MediaService._matching_ytdlp_extractor(normalized_url)
        ):
            raise MediaServiceError(
                "Ten adres nie pasuje do żadnego obsługiwanego extractora yt-dlp."
            )
        if not parts.path:
            raise MediaServiceError("Podaj pełny adres materiału lub kanału.")
        if (
            MediaService._known_platform(host) == "youtube"
            and parts.path.rstrip("/").lower()
            in {
                "/redirect",
                "/attribution_link",
            }
        ):
            raise MediaServiceError("Linki przekierowujące YouTube nie są obsługiwane.")
        return normalized_url

    @staticmethod
    def detect_platform(url: str) -> str:
        """Return the supported platform associated with an already validated URL."""

        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        known_platform = MediaService._known_platform(host)
        if known_platform:
            return known_platform
        return MediaService._platform_from_host(host)

    @staticmethod
    def _known_platform(host: str) -> str | None:
        return KNOWN_PLATFORM_DOMAINS.get(host)

    @staticmethod
    def _platform_from_host(host: str) -> str:
        for label in host.split("."):
            cleaned = re.sub(r"[^a-z0-9_-]+", "", label.casefold())
            if cleaned and cleaned not in {"www", "m", "mobile", "amp"}:
                return cleaned[:40]
        return "unknown"

    @staticmethod
    def _matching_ytdlp_extractor(url: str) -> str | None:
        """Return the concrete yt-dlp extractor name for a URL, excluding Generic."""

        try:
            extractors = _yt_dlp_extractors()
        except Exception as error:
            LOGGER.warning("Nie można odczytać listy extractorów yt-dlp: %s", error)
            return None
        for extractor in extractors:
            name = str(getattr(extractor, "IE_NAME", "") or "")
            key = ""
            try:
                key = str(extractor.ie_key())
            except Exception:
                key = type(extractor).__name__
            if name.casefold() == "generic" or key.casefold() == "generic":
                continue
            try:
                if not extractor.working():
                    continue
            except Exception:
                pass
            try:
                if extractor.suitable(url):
                    return key or name
            except Exception:
                LOGGER.debug(
                    "Extractor %s nie sprawdził URL", key or name, exc_info=True
                )
        return None

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
        self._apply_public_youtube_options(options, validated_url)
        YoutubeDL, DownloadError = _yt_dlp_api()
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
        download_options: dict[str, Any] | None = None,
    ) -> list[Path]:
        """Download a URL synchronously. JobManager runs this method in a worker."""

        validated_url, options = self.effective_download_options(
            url, download_type, format_id, download_options=download_options
        )
        options["progress_hooks"] = [progress_hook]
        options["postprocessor_hooks"] = [postprocessor_hook]
        YoutubeDL, DownloadError = _yt_dlp_api()
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
            audio_format = self.audio_format(download_options)
            paths.extend(path.with_suffix(f".{audio_format}") for path in list(paths))
        return self._existing_managed_paths(paths)

    def download_subtitle(
        self, url: str, media_path: Path, mode: str = "pl"
    ) -> dict[str, Any]:
        """Download the best matching subtitle track for an existing managed video."""

        subtitle_mode = self._subtitle_mode(mode)
        media_path = media_path.resolve()
        try:
            media_path.relative_to(self.download_dir)
        except ValueError as error:
            raise MediaServiceError("Niepoprawna ścieżka pliku wideo.") from error
        if not media_path.is_file():
            raise MediaServiceError("Nie znaleziono pliku wideo.")

        existing = self._existing_subtitle(
            media_path, preferred_languages=SUBTITLE_MODE_LANGUAGE_PREFERENCES[subtitle_mode]
        )
        if existing:
            return {
                "path": existing,
                "language": self._subtitle_language_from_path(existing, media_path),
                "source": "file",
                "automatic": False,
            }

        validated_url = self.validate_url(url)
        YoutubeDL, DownloadError = _yt_dlp_api()
        analysis_options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 20,
            "noplaylist": True,
        }
        self._apply_public_youtube_options(analysis_options, validated_url)
        try:
            with YoutubeDL(analysis_options) as ydl:
                info = ydl.extract_info(validated_url, download=False)
        except DownloadError as error:
            raise MediaServiceError(self.polish_error(str(error))) from error
        except Exception as error:
            LOGGER.exception("Nieoczekiwany błąd sprawdzania napisów")
            raise MediaServiceError("Nie udało się sprawdzić napisów przez yt-dlp.") from error

        language, automatic = self._select_subtitle_language(info or {}, subtitle_mode)
        if not language:
            raise MediaServiceError("Ten materiał nie udostępnia napisów.")

        outtmpl = str(media_path.with_suffix("")) + ".%(ext)s"
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 20,
            "noplaylist": True,
            "outtmpl": outtmpl,
            "subtitleslangs": [language],
            "subtitlesformat": "vtt/best",
            "writesubtitles": not automatic,
            "writeautomaticsub": automatic,
        }
        self._apply_public_youtube_options(options, validated_url)
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(validated_url, download=True)
        except DownloadError as error:
            raise MediaServiceError(self.polish_error(str(error))) from error
        except OSError as error:
            raise MediaServiceError("Nie udało się zapisać pliku napisów.") from error
        except Exception as error:
            LOGGER.exception("Nieoczekiwany błąd pobierania napisów")
            raise MediaServiceError("Nie udało się pobrać napisów przez yt-dlp.") from error

        downloaded = self._existing_subtitle(media_path, preferred_languages=(language,))
        if not downloaded:
            raise MediaServiceError("yt-dlp nie zwrócił pliku napisów w formacie VTT.")
        return {
            "path": downloaded,
            "language": language,
            "source": "automatic" if automatic else "official",
            "automatic": automatic,
        }

    def effective_download_options(
        self,
        url: str,
        download_type: str,
        format_id: str | None = None,
        download_options: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return the validated URL and final yt-dlp options used for a download."""

        validated_url = self.validate_url(url)
        options = self.download_options(download_type, format_id, download_options)
        self._apply_public_youtube_options(options, validated_url)
        return validated_url, options

    def download_options(
        self,
        download_type: str,
        format_id: str | None = None,
        download_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare yt-dlp settings without accepting a client-provided filesystem path."""

        selection, postprocessors = self.format_selection(
            download_type,
            format_id,
            audio_format=self.audio_format(download_options),
            embed_thumbnail=self.boolean_option(download_options, "embed_thumbnail", True),
            add_metadata=self.boolean_option(download_options, "add_metadata", True),
        )
        outtmpl_dir = self.download_dir
        output_subdir = self.safe_output_subdir(download_options)
        if output_subdir:
            outtmpl_dir = outtmpl_dir / output_subdir
            outtmpl_dir.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "format": selection,
            "outtmpl": str(outtmpl_dir / "%(title).180B [%(id)s].%(ext)s"),
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
        if download_type == "audio" and self.boolean_option(
            download_options, "embed_thumbnail", True
        ):
            options["writethumbnail"] = True
        return options

    @staticmethod
    def format_selection(
        download_type: str,
        format_id: str | None = None,
        audio_format: str = "mp3",
        embed_thumbnail: bool = True,
        add_metadata: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Translate UI download modes into controlled yt-dlp selectors."""

        if download_type == "audio":
            if audio_format not in SUPPORTED_AUDIO_FORMATS:
                raise MediaServiceError("Nieobsługiwany format audio.")
            postprocessors: list[dict[str, Any]] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ]
            if add_metadata:
                postprocessors.append(
                    {
                        "key": "FFmpegMetadata",
                        "add_chapters": True,
                        "add_infojson": "if_exists",
                        "add_metadata": True,
                    }
                )
            if embed_thumbnail:
                postprocessors.append({"key": "EmbedThumbnail"})
            return (
                "bestaudio/best",
                postprocessors,
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
            if (
                not format_id
                or not FORMAT_ID_RE.fullmatch(format_id)
                or STORYBOARD_FORMAT_RE.fullmatch(format_id)
            ):
                raise MediaServiceError(
                    "Wybrany identyfikator formatu jest niepoprawny."
                )
            return format_id, []
        raise MediaServiceError("Niepoprawny typ pobierania.")

    @staticmethod
    def audio_format(download_options: dict[str, Any] | None = None) -> str:
        audio_format = str((download_options or {}).get("audio_format") or "mp3").lower()
        if audio_format not in SUPPORTED_AUDIO_FORMATS:
            raise MediaServiceError("Nieobsługiwany format audio.")
        return audio_format

    @staticmethod
    def boolean_option(
        download_options: dict[str, Any] | None, key: str, default: bool
    ) -> bool:
        value = (download_options or {}).get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def safe_output_subdir(download_options: dict[str, Any] | None = None) -> str | None:
        raw = str((download_options or {}).get("output_subdir") or "").strip()
        if not raw:
            return None
        cleaned = SAFE_SUBDIR_RE.sub("_", raw).strip(" ._")
        cleaned = " ".join(cleaned.split())[:80].strip(" ._")
        return cleaned or None

    def live_command(self, url: str, live_from_start: bool = True) -> list[str]:
        """Build a separate yt-dlp process command for live recording."""

        validated_url = self.validate_url(url)
        options = self.download_options("best")
        command = [
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
        ]
        if self.detect_platform(validated_url) == "youtube":
            command.extend(
                [
                    "--extractor-args",
                    f"youtube:player_client={','.join(YOUTUBE_PUBLIC_PLAYER_CLIENTS)}",
                ]
            )
        if live_from_start:
            command.append("--live-from-start")
        command.append(validated_url)
        return command

    @staticmethod
    def _apply_public_youtube_options(options: dict[str, Any], url: str) -> None:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        if MediaService._known_platform(host) != "youtube":
            return

        extractor_args = {
            key: dict(value)
            for key, value in dict(options.get("extractor_args") or {}).items()
        }
        youtube_args = dict(extractor_args.get("youtube") or {})
        requested_clients = list(youtube_args.get("player_client") or [])
        for client in YOUTUBE_PUBLIC_PLAYER_CLIENTS:
            if client not in requested_clients:
                requested_clients.append(client)
        youtube_args["player_client"] = requested_clients
        extractor_args["youtube"] = youtube_args
        options["extractor_args"] = extractor_args

    @staticmethod
    def _subtitle_mode(mode: str) -> str:
        normalized = str(mode or "pl").casefold()
        if normalized not in SUBTITLE_MODE_LANGUAGE_PREFERENCES:
            raise MediaServiceError("Wybierz poprawny tryb napisow.")
        return normalized

    def _existing_subtitle(
        self, media_path: Path, preferred_languages: tuple[str, ...] = ()
    ) -> Path | None:
        candidates: list[Path] = []
        exact_path = media_path.with_suffix(".vtt")
        if exact_path.is_file() and self._is_managed_path(exact_path):
            candidates.append(exact_path)
        candidates.extend(
            path
            for path in media_path.parent.glob(f"{media_path.stem}.*.vtt")
            if path.is_file() and self._is_managed_path(path) and path not in candidates
        )
        if not candidates:
            return None
        for language in preferred_languages:
            preferred = f".{language}.vtt"
            for candidate in candidates:
                if candidate.name.endswith(preferred):
                    return candidate
        if preferred_languages:
            return None
        for language in SUBTITLE_LANGUAGE_PREFERENCE:
            preferred = f".{language}.vtt"
            for candidate in candidates:
                if candidate.name.endswith(preferred):
                    return candidate
        return sorted(candidates, key=lambda item: item.name.casefold())[0]

    @staticmethod
    def _subtitle_language_from_path(subtitle_path: Path, media_path: Path) -> str:
        subtitle_stem = subtitle_path.stem
        media_stem = media_path.with_suffix("").name
        language_prefix = f"{media_stem}."
        if subtitle_stem.startswith(language_prefix):
            language = subtitle_stem[len(language_prefix) :].strip()
            if language:
                return language
        return ""

    def _is_managed_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            resolved.relative_to(self.download_dir)
        except (OSError, ValueError):
            return False
        return resolved != self.download_dir

    @staticmethod
    def _select_subtitle_language(
        info: dict[str, Any], mode: str = "pl"
    ) -> tuple[str | None, bool]:
        subtitles = {
            str(language): tracks
            for language, tracks in dict(info.get("subtitles") or {}).items()
            if tracks
        }
        automatic = {
            str(language): tracks
            for language, tracks in dict(info.get("automatic_captions") or {}).items()
            if tracks
        }
        preferred_languages = SUBTITLE_MODE_LANGUAGE_PREFERENCES.get(
            mode, SUBTITLE_LANGUAGE_PREFERENCE
        )
        if mode != "auto":
            for language in preferred_languages:
                if language in subtitles:
                    return language, False
            for language in preferred_languages:
                if language in automatic:
                    return language, True
            return None, False
        for language in preferred_languages:
            if language in automatic:
                return language, True
        if automatic:
            return sorted(automatic)[0], True
        return None, False

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
        if MediaService._is_youtube_anonymous_access_block(lowered):
            return YOUTUBE_ANONYMOUS_ACCESS_MESSAGE
        if "login" in lowered or "sign in" in lowered or "cookies" in lowered:
            return LOGIN_ACCESS_MESSAGE
        if "unsupported url" in lowered:
            return "yt-dlp nie obsługuje tego adresu URL."
        return "yt-dlp nie mógł obsłużyć materiału. Sprawdź dostępność linku i logi dodatku."

    @staticmethod
    def _is_youtube_anonymous_access_block(lowered_message: str) -> bool:
        return any(
            marker in lowered_message
            for marker in (
                "sign in to confirm you're not a bot",
                "sign in to confirm you’re not a bot",
                "confirm you're not a bot",
                "confirm you’re not a bot",
                "captcha challenge",
                "has been rate-limited by youtube",
                "http error 429",
                "too many requests",
            )
        )

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
            format_id = str(item.get("format_id") or "")
            if (
                not format_id
                or STORYBOARD_FORMAT_RE.fullmatch(format_id)
                or str(item.get("ext") or "").lower() == "mhtml"
                or str(item.get("protocol") or "").lower() == "mhtml"
            ):
                continue
            formats.append(
                {
                    "format_id": format_id,
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
            "id": info.get("id"),
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
        self, ydl: Any, info: dict[str, Any] | None
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
            if self._is_managed_path(resolved) and resolved.is_file() and resolved not in managed:
                managed.append(resolved)
        return managed

    def _is_managed_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.download_dir)
        except ValueError:
            return False
        return True
