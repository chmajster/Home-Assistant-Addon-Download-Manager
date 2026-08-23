"""Resolve public embedded players without allowing access to internal networks."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

USER_AGENT = "Media Web Downloader/1.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
MAX_EMBED_DEPTH = 3
MAX_CANDIDATES_PER_PAGE = 20
MAX_VISITED_URLS = 40
MAX_PACKED_SCRIPTS = 8
MAX_PACKER_DEPTH = 3
MANIFEST_EXTENSIONS = (".m3u8", ".mpd")
DIRECT_MEDIA_EXTENSIONS = (".mp4", ".m4v", ".webm", ".mov", ".ts")
MEDIA_ATTRIBUTE_RE = re.compile(
    r"""(?ix)
    ["']?(?:src|file|source|playlist|hls|dash|url)["']?
    \s*[:=]\s*
    ["']([^"']+)["']
    """
)
MEDIA_URL_RE = re.compile(
    r"""(?ix)
    (
        https?://[^\s"'<>\\]+?\.(?:m3u8|mpd|mp4|m4v|webm|mov)(?:\?[^\s"'<>\\]*)?
        |
        (?:/|\.\.?/)[^\s"'<>\\]+?\.(?:m3u8|mpd|mp4|m4v|webm|mov)(?:\?[^\s"'<>\\]*)?
    )
    """
)
STREAM_NAME_RE = re.compile(r"""["']?streamName["']?\s*:\s*["']([^"']+)["']""")
PACKER_START_RE = re.compile(
    r"""eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*[dr]\s*\)\s*\{""",
    re.IGNORECASE,
)
FILE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
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
    """Find public video, HLS and DASH sources in pages and embedded players."""

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

        expanded_text = self._expanded_media_text(text)
        lowered_text = expanded_text.casefold()
        if any(marker in lowered_text for marker in DRM_MARKERS):
            raise EmbeddedMediaError("Osadzony materiał używa DRM i nie może zostać zapisany.")

        parser = _MediaHTMLParser()
        parser.feed(text)
        title = " ".join(parser.title_parts).strip() or None

        candidates = self._media_candidates(expanded_text, parser.sources, final_url)
        resolved = self._resolve_candidates(
            candidates,
            original_url=original_url,
            visited=visited,
            depth=depth,
            referer=final_url,
            title=title,
        )
        if resolved is not None:
            return resolved

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

        resolved = self._resolve_embed_form(
            final_url,
            original_url=original_url,
            visited=visited,
            depth=depth,
            title=title,
        )
        if resolved is not None:
            return resolved

        raise EmbeddedMediaError(
            "Nie znaleziono publicznego źródła wideo, HLS ani DASH na stronie."
        )

    def _resolve_candidates(
        self,
        candidates: list[str],
        *,
        original_url: str,
        visited: set[str],
        depth: int,
        referer: str,
        title: str | None,
    ) -> ResolvedMedia | None:
        for candidate in candidates:
            try:
                resolved = self._resolve(
                    candidate,
                    original_url,
                    visited,
                    depth + 1,
                    referer=referer,
                )
                return replace(resolved, title=resolved.title or title)
            except EmbeddedMediaError:
                continue
        return None

    def _resolve_embed_form(
        self,
        page_url: str,
        *,
        original_url: str,
        visited: set[str],
        depth: int,
        title: str | None,
    ) -> ResolvedMedia | None:
        """Try the common XFileSharing-style public embed endpoint used by video hosts."""

        file_code = self._file_code_from_url(page_url)
        if not file_code or depth >= self.max_depth:
            return None

        endpoint = urljoin(self._origin(page_url), "/dl")
        body, content_type = self._multipart_form({"op": "embed", "file_code": file_code})
        try:
            payload, _response_type, final_url = self._fetch(
                endpoint,
                method="POST",
                data=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": page_url,
                    "Origin": self._origin(page_url),
                    "Content-Type": content_type,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                },
            )
        except EmbeddedMediaError:
            return None

        response_text = payload.decode("utf-8", errors="replace")
        expanded_text = self._expanded_media_text(response_text)
        if any(marker in expanded_text.casefold() for marker in DRM_MARKERS):
            raise EmbeddedMediaError("Osadzony materiał używa DRM i nie może zostać zapisany.")

        candidates = self._media_candidates(expanded_text, [], final_url)
        return self._resolve_candidates(
            candidates,
            original_url=original_url,
            visited=visited,
            depth=depth,
            referer=page_url,
            title=title,
        )

    def _media_candidates(self, text: str, html_sources: list[str], page_url: str) -> list[str]:
        raw_candidates = list(html_sources)
        normalized_text = self._normalize_script_text(text)
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
            cleaned_value = self._normalize_candidate(value)
            if not cleaned_value:
                continue
            candidate = urljoin(page_url, cleaned_value)
            if candidate not in candidates:
                candidates.append(candidate)
            if len(candidates) >= MAX_CANDIDATES_PER_PAGE:
                break
        return candidates

    def _expanded_media_text(self, text: str) -> str:
        parts = [text]
        queue = [text]
        seen = {text}
        for _ in range(MAX_PACKER_DEPTH):
            next_queue: list[str] = []
            for candidate in queue:
                for unpacked in self._unpack_packer_scripts(candidate):
                    if unpacked in seen:
                        continue
                    seen.add(unpacked)
                    parts.append(unpacked)
                    next_queue.append(unpacked)
                    if len(parts) >= MAX_PACKED_SCRIPTS + 1:
                        return "\n".join(parts)
            if not next_queue:
                break
            queue = next_queue
        return "\n".join(parts)

    def _unpack_packer_scripts(self, text: str) -> list[str]:
        unpacked: list[str] = []
        for match in list(PACKER_START_RE.finditer(text))[:MAX_PACKED_SCRIPTS]:
            decoded = self._unpack_packer_at(text, match.end())
            if decoded:
                unpacked.append(decoded)
        return unpacked

    def _unpack_packer_at(self, text: str, function_body_start: int) -> str | None:
        invocation = re.search(r"}\s*\(", text[function_body_start:], re.DOTALL)
        if invocation is None:
            return None
        position = function_body_start + invocation.end()
        try:
            payload, position = self._read_js_string(text, position)
            position = self._consume_separator(text, position, ",")
            radix, position = self._read_int(text, position)
            position = self._consume_separator(text, position, ",")
            count, position = self._read_int(text, position)
            position = self._consume_separator(text, position, ",")
            symbols, position = self._read_js_string(text, position)
        except ValueError:
            return None

        suffix = text[position:]
        if not re.match(r"""\s*\.split\(\s*["']\|["']\s*\)""", suffix, re.DOTALL):
            return None
        if not 2 <= radix <= 62 or count < 0 or count > 10000:
            return None

        table = symbols.split("|")
        limit = min(count, len(table))
        replacements = {
            self._packer_token(index, radix): table[index] for index in range(limit) if table[index]
        }
        return re.sub(
            r"\b[0-9A-Za-z]+\b",
            lambda match: replacements.get(match.group(0), match.group(0)),
            payload,
        )

    @staticmethod
    def _read_js_string(text: str, position: int) -> tuple[str, int]:
        position = EmbeddedMediaResolver._skip_space(text, position)
        if position >= len(text) or text[position] not in {"'", '"'}:
            raise ValueError("expected JavaScript string")
        quote_char = text[position]
        position += 1
        result: list[str] = []
        escapes = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "v": "\v",
            "0": "\0",
            "\\": "\\",
            "/": "/",
            "'": "'",
            '"': '"',
        }
        while position < len(text):
            char = text[position]
            if char == quote_char:
                return "".join(result), position + 1
            if char != "\\":
                result.append(char)
                position += 1
                continue

            position += 1
            if position >= len(text):
                raise ValueError("unterminated escape")
            escape = text[position]
            if escape == "x" and position + 2 < len(text):
                digits = text[position + 1 : position + 3]
                if re.fullmatch(r"[0-9A-Fa-f]{2}", digits):
                    result.append(chr(int(digits, 16)))
                    position += 3
                    continue
            if escape == "u" and position + 4 < len(text):
                digits = text[position + 1 : position + 5]
                if re.fullmatch(r"[0-9A-Fa-f]{4}", digits):
                    result.append(chr(int(digits, 16)))
                    position += 5
                    continue
            result.append(escapes.get(escape, escape))
            position += 1
        raise ValueError("unterminated JavaScript string")

    @staticmethod
    def _read_int(text: str, position: int) -> tuple[int, int]:
        position = EmbeddedMediaResolver._skip_space(text, position)
        match = re.match(r"\d+", text[position:])
        if match is None:
            raise ValueError("expected integer")
        return int(match.group(0)), position + match.end()

    @staticmethod
    def _consume_separator(text: str, position: int, separator: str) -> int:
        position = EmbeddedMediaResolver._skip_space(text, position)
        if position >= len(text) or text[position] != separator:
            raise ValueError("expected separator")
        return position + 1

    @staticmethod
    def _skip_space(text: str, position: int) -> int:
        while position < len(text) and text[position].isspace():
            position += 1
        return position

    @staticmethod
    def _packer_token(value: int, radix: int) -> str:
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if value == 0:
            return "0"
        digits: list[str] = []
        while value:
            value, remainder = divmod(value, radix)
            digits.append(alphabet[remainder])
        return "".join(reversed(digits))

    @staticmethod
    def _file_code_from_url(url: str) -> str | None:
        segments = [unquote(segment) for segment in urlsplit(url).path.split("/") if segment]
        if not segments:
            return None
        candidate = segments[-1].strip()
        if "." in candidate or not FILE_CODE_RE.fullmatch(candidate):
            return None
        if candidate.casefold() in {
            "index",
            "embed",
            "player",
            "video",
            "watch",
            "download",
        }:
            return None
        return candidate

    @staticmethod
    def _normalize_script_text(text: str) -> str:
        return (
            html.unescape(text)
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\x2F", "/")
            .replace("\\x2f", "/")
            .replace("\\u003A", ":")
            .replace("\\u003a", ":")
            .replace("\\x3A", ":")
            .replace("\\x3a", ":")
        )

    @classmethod
    def _normalize_candidate(cls, value: str) -> str:
        candidate = cls._normalize_script_text(str(value or "")).strip()
        return candidate if candidate.startswith(("http://", "https://", "/", "./", "../")) else ""

    @staticmethod
    def _multipart_form(fields: dict[str, str]) -> tuple[bytes, str]:
        boundary = f"----MediaWebDownloader{uuid4().hex}"
        lines: list[bytes] = []
        for name, value in fields.items():
            safe_name = name.replace('"', "")
            lines.extend(
                (
                    f"--{boundary}\r\n".encode(),
                    (f'Content-Disposition: form-data; name="{safe_name}"\r\n\r\n').encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                )
            )
        lines.append(f"--{boundary}--\r\n".encode())
        return b"".join(lines), f"multipart/form-data; boundary={boundary}"

    def _fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str, str]:
        safe_url = self.validate_public_url(url)
        redirect_handler = _SafeRedirectHandler(self.validate_public_url)
        opener = urllib.request.build_opener(redirect_handler)
        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            safe_url,
            data=data,
            headers=request_headers,
            method=method,
        )
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
        match = re.search(r"""<MPD\b[^>]*\btype=["']([^"']+)""", text, re.IGNORECASE)
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
