"""Resolve public embedded players without allowing access to internal networks."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

USER_AGENT = "Media Web Downloader/1.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
MAX_EMBED_DEPTH = 3
MAX_CANDIDATES_PER_PAGE = 20
MAX_VISITED_URLS = 40
MANIFEST_EXTENSIONS = (".m3u8", ".mpd")
DIRECT_MEDIA_EXTENSIONS = (".mp4", ".m4v", ".webm", ".mov", ".ts")
MEDIA_ATTRIBUTE_RE = re.compile(
    r"(?i)(?:src|file|source|playlist|hls|dash|url)\s*[:=]\s*[\"']([^\"']+)[\"']"
)
MEDIA_URL_RE = re.compile(
    r"(?i)(https?://[^\s\"'<>\\]+?\.(?:m3u8|mpd)(?:\?[^\s\"'<>\\]*)?|"
    r"(?:/|\.\.?/)[^\s\"'<>\\]+?\.(?:m3u8|mpd)(?:\?[^\s\"'<>\\]*)?)"
)
STREAM_NAME_RE = re.compile(r"[\"']?streamName[\"']?\s*:\s*[\"']([^\"']+)[\"']")
DRM_MARKERS = ("widevine", "playready", "fairplay", "licenseurl", "drmconfig")


class EmbeddedMediaError(RuntimeError):
    """A safe, user-facing embedded-media resolution error."""


@dataclass(frozen=True)
class ResolvedMedia:
    """A verified direct media source and the request headers it requires."""

    original_url: str
    source_url: str
    headers: dict[str, str]
    is_live: bool
    media_kind: str
    title: str | None = None

    @property
    def persistable_source_url(self) -> str | None:
        """Do not persist URLs whose query may contain signatures or access tokens."""

        return self.source_url if not urlsplit(self.source_url).query else None


class _MediaHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.iframes: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value for key, value in attrs if value}
        normalized = tag.casefold()
        if normalized in {"video", "source"} and values.get("src"):
            self.sources.append(str(values["src"]))
        elif normalized == "iframe" and values.get("src"):
            self.iframes.append(str(values["src"]))
        elif normalized == "meta":
            content = str(values.get("content") or "")
            if any(extension in content.casefold() for extension in MANIFEST_EXTENSIONS):
                self.sources.append(content)
        elif normalized == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], str]) -> None:
        self.validator = validator
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirects += 1
        if self.redirects > MAX_REDIRECTS:
            raise EmbeddedMediaError("Strona przekroczyła limit bezpiecznych przekierowań.")
        safe_url = self.validator(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


class EmbeddedMediaResolver:
    """Find HLS/DASH sources in public pages and nested embedded players."""

    def __init__(
        self,
        *,
        timeout: float = 12.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_depth: int = MAX_EMBED_DEPTH,
        dns_resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
    ) -> None:
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.max_depth = max_depth
        self._dns_resolver = dns_resolver

    @staticmethod
    def normalize_url(url: str) -> str:
        candidate = str(url or "").strip()
        if not candidate or len(candidate) > 2048:
            raise EmbeddedMediaError("Podaj poprawny publiczny adres URL.")
        try:
            parts = urlsplit(candidate)
            port = parts.port
        except ValueError as error:
            raise EmbeddedMediaError("Podany adres URL jest niepoprawny.") from error
        host = (parts.hostname or "").casefold().rstrip(".")
        if parts.scheme.casefold() not in {"http", "https"}:
            raise EmbeddedMediaError("Dozwolone są wyłącznie adresy HTTP i HTTPS.")
        if not host or parts.username or parts.password or port is not None:
            raise EmbeddedMediaError(
                "Adres nie może zawierać danych logowania ani niestandardowego portu."
            )
        if host == "localhost" or host.endswith(".localhost"):
            raise EmbeddedMediaError("Adresy sieci lokalnej nie są obsługiwane.")
        try:
            literal_address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal_address = None
        if literal_address is not None and not literal_address.is_global:
            raise EmbeddedMediaError("Adresy prywatne i sieci lokalne nie są obsługiwane.")
        normalized_host = f"[{host}]" if ":" in host else host
        return urlunsplit(
            (parts.scheme.casefold(), normalized_host, parts.path or "/", parts.query, "")
        )

    def validate_public_url(self, url: str) -> str:
        normalized = self.normalize_url(url)
        parts = urlsplit(normalized)
        host = str(parts.hostname)
        try:
            addresses = {
                item[4][0]
                for item in self._dns_resolver(
                    host,
                    443 if parts.scheme == "https" else 80,
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, socket.gaierror) as error:
            raise EmbeddedMediaError("Nie można bezpiecznie rozwiązać adresu serwera.") from error
        if not addresses:
            raise EmbeddedMediaError("Nie można bezpiecznie rozwiązać adresu serwera.")
        try:
            unsafe = [
                address for address in addresses if not ipaddress.ip_address(address).is_global
            ]
        except ValueError as error:
            raise EmbeddedMediaError("Serwer zwrócił niepoprawny adres sieciowy.") from error
        if unsafe:
            raise EmbeddedMediaError("Adresy prywatne i sieci lokalne nie są obsługiwane.")
        return normalized

    def resolve(self, url: str) -> ResolvedMedia:
        original = self.validate_public_url(url)
        return self._resolve(original, original, set(), 0)

    def _resolve(
        self,
        url: str,
        original_url: str,
        visited: set[str],
        depth: int,
        referer: str | None = None,
    ) -> ResolvedMedia:
        if depth > self.max_depth:
            raise EmbeddedMediaError("Odtwarzacz przekroczył limit zagnieżdżonych ramek.")
        if len(visited) >= MAX_VISITED_URLS:
            raise EmbeddedMediaError("Odtwarzacz odwołuje się do zbyt wielu adresów.")
        safe_url = self.validate_public_url(url)
        if safe_url in visited:
            raise EmbeddedMediaError("Wykryto pętlę zagnieżdżonych odtwarzaczy.")
        visited.add(safe_url)
        body, content_type, final_url = self._fetch(safe_url)
        lowered_type = content_type.casefold()
        path = urlsplit(final_url).path.casefold()
        if path.endswith(DIRECT_MEDIA_EXTENSIONS) or lowered_type.startswith("video/"):
            return ResolvedMedia(
                original_url=original_url,
                source_url=final_url,
                headers=self._source_headers(referer or original_url),
                is_live=False,
                media_kind="video",
            )
        text = body.decode("utf-8", errors="replace")
        if path.endswith(MANIFEST_EXTENSIONS) or any(
            marker in lowered_type
            for marker in ("mpegurl", "application/dash+xml", "application/vnd.apple")
        ):
            media_kind = "dash" if path.endswith(".mpd") or "dash+xml" in lowered_type else "hls"
            is_live = self._manifest_is_live(text, media_kind)
            return ResolvedMedia(
                original_url=original_url,
                source_url=final_url,
                headers=self._source_headers(referer or original_url),
                is_live=is_live,
                media_kind=media_kind,
            )
        lowered_text = text.casefold()
        if any(marker in lowered_text for marker in DRM_MARKERS):
            raise EmbeddedMediaError("Osadzony materiał używa DRM i nie może zostać zapisany.")
        parser = _MediaHTMLParser()
        parser.feed(text)
        title = " ".join(parser.title_parts).strip() or None
        candidates = self._media_candidates(text, parser.sources, final_url)
        for candidate in candidates:
            try:
                resolved = self._resolve(
                    candidate,
                    original_url,
                    visited,
                    depth + 1,
                    referer=final_url,
                )
                return replace(resolved, title=resolved.title or title)
            except EmbeddedMediaError:
                continue
        for iframe in parser.iframes:
            try:
                return self._resolve(
                    urljoin(final_url, iframe),
                    original_url,
                    visited,
                    depth + 1,
                    referer=final_url,
                )
            except EmbeddedMediaError:
                continue
        raise EmbeddedMediaError("Nie znaleziono publicznego źródła HLS ani DASH na stronie.")

    def _media_candidates(self, text: str, html_sources: list[str], page_url: str) -> list[str]:
        raw_candidates = list(html_sources)
        normalized_text = text.replace("\\/", "/")
        raw_candidates.extend(MEDIA_ATTRIBUTE_RE.findall(normalized_text))
        raw_candidates.extend(MEDIA_URL_RE.findall(normalized_text))
        stream_names = STREAM_NAME_RE.findall(normalized_text)
        origin = self._origin(page_url)
        for stream_name in stream_names:
            cleaned = stream_name.strip(" /").replace("..", "")
            if cleaned:
                raw_candidates.extend(
                    (
                        f"{origin}/{quote(cleaned, safe='/')}/index.m3u8",
                        f"{origin}/{quote(cleaned, safe='/')}/manifest.mpd",
                    )
                )
        candidates: list[str] = []
        for value in raw_candidates:
            candidate = urljoin(page_url, value.strip())
            if candidate not in candidates:
                candidates.append(candidate)
            if len(candidates) >= MAX_CANDIDATES_PER_PAGE:
                break
        return candidates

    def _fetch(self, url: str) -> tuple[bytes, str, str]:
        redirect_handler = _SafeRedirectHandler(self.validate_public_url)
        opener = urllib.request.build_opener(redirect_handler)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=self.timeout) as response:
                final_url = self.validate_public_url(response.geturl())
                payload = response.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    raise EmbeddedMediaError(
                        "Odpowiedź strony przekracza bezpieczny limit rozmiaru."
                    )
                return payload, str(response.headers.get("Content-Type") or ""), final_url
        except EmbeddedMediaError:
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise EmbeddedMediaError(
                "Nie udało się pobrać publicznej strony odtwarzacza."
            ) from error

    @staticmethod
    def _manifest_is_live(text: str, media_kind: str) -> bool:
        if media_kind == "hls":
            return "#EXT-X-ENDLIST" not in text.upper()
        match = re.search(r"<MPD\b[^>]*\btype=[\"']([^\"']+)", text, re.IGNORECASE)
        return bool(match and match.group(1).casefold() == "dynamic")

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    @classmethod
    def _source_headers(cls, referer: str) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Origin": cls._origin(referer),
        }
