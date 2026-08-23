"""Focused regression tests for generic embedded-media extraction."""

from __future__ import annotations

import unittest

from app.services.embedded_media_resolver import (
    EmbeddedMediaError,
    EmbeddedMediaResolver,
)

PACKED_PLAYER = """<script>
eval(function(p,a,c,k,e,d){e=function(c){return c};return p}(
'0("1").2({3:"4"});',
5,
5,
'jwplayer|vplayer|setup|file|https://cdn.example/master.m3u8?t=abc'.split('|'),
0,
{}
))
</script>"""


class FakeEmbeddedResolver(EmbeddedMediaResolver):
    """Avoid real networking while exercising the full resolver fallback chain."""

    def __init__(self, *, post_payload: str = PACKED_PLAYER) -> None:
        super().__init__()
        self.post_payload = post_payload
        self.calls: list[tuple[str, str, bytes | None, dict[str, str] | None]] = []

    def validate_public_url(self, url: str) -> str:
        return self.normalize_url(url)

    def _fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str, str]:
        self.calls.append((url, method, data, headers))
        if method == "GET" and url == "https://luluvdo.com/3jts0xbh9p0p":
            return (
                b"<html><head><title>Example video</title></head><body></body></html>",
                "text/html",
                url,
            )
        if method == "POST" and url == "https://luluvdo.com/dl":
            return self.post_payload.encode("utf-8"), "text/html", url
        if method == "GET" and url == "https://cdn.example/master.m3u8?t=abc":
            return (
                b"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXT-X-ENDLIST\n",
                "application/vnd.apple.mpegurl",
                url,
            )
        raise EmbeddedMediaError(f"Unexpected request: {method} {url}")


class EmbeddedMediaResolverTestCase(unittest.TestCase):
    def test_dean_edwards_packer_is_decoded_without_running_javascript(self) -> None:
        resolver = EmbeddedMediaResolver()
        expanded = resolver._expanded_media_text(PACKED_PLAYER)

        self.assertIn(
            'jwplayer("vplayer").setup({file:"https://cdn.example/master.m3u8?t=abc"});',
            expanded,
        )

    def test_candidates_include_quoted_jwplayer_file_and_direct_video(self) -> None:
        resolver = EmbeddedMediaResolver()
        text = """
        {"file":"https:\\/\\/cdn.example\\/master.m3u8?t=abc"}
        const backup = {src: "https://cdn.example/video.mp4"};
        """

        candidates = resolver._media_candidates(text, [], "https://video.example/watch/abc")

        self.assertEqual(
            candidates,
            [
                "https://cdn.example/master.m3u8?t=abc",
                "https://cdn.example/video.mp4",
            ],
        )

    def test_xfilesharing_embed_form_resolves_signed_hls(self) -> None:
        resolver = FakeEmbeddedResolver()

        resolved = resolver.resolve("https://luluvdo.com/3jts0xbh9p0p")

        self.assertEqual(resolved.source_url, "https://cdn.example/master.m3u8?t=abc")
        self.assertEqual(resolved.media_kind, "hls")
        self.assertFalse(resolved.is_live)
        self.assertEqual(resolved.title, "Example video")
        self.assertEqual(resolved.headers["Referer"], "https://luluvdo.com/3jts0xbh9p0p")
        post_call = next(call for call in resolver.calls if call[1] == "POST")
        self.assertEqual(post_call[0], "https://luluvdo.com/dl")
        self.assertIn(b'name="op"\r\n\r\nembed', post_call[2] or b"")
        self.assertIn(b'name="file_code"\r\n\r\n3jts0xbh9p0p', post_call[2] or b"")
        self.assertTrue((post_call[3] or {})["Content-Type"].startswith("multipart/form-data;"))

    def test_embed_fallback_preserves_drm_rejection(self) -> None:
        resolver = FakeEmbeddedResolver(
            post_payload="<script>const drmConfig = {widevine: true};</script>"
        )

        with self.assertRaisesRegex(EmbeddedMediaError, "DRM"):
            resolver.resolve("https://luluvdo.com/3jts0xbh9p0p")

    def test_non_file_like_path_does_not_probe_dl_endpoint(self) -> None:
        resolver = FakeEmbeddedResolver()

        with self.assertRaises(EmbeddedMediaError):
            resolver.resolve("https://luluvdo.com/watch")

        self.assertFalse(any(call[1] == "POST" for call in resolver.calls))


if __name__ == "__main__":
    unittest.main()
