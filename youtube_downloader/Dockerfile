ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.23

FROM mwader/static-ffmpeg:8.1.1 AS ffmpeg

FROM ${BUILD_FROM}

ARG BUILD_VERSION="1.3.102"
ARG BUILD_ARCH="amd64"

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

COPY requirements.txt /tmp/requirements.txt
COPY wheels /tmp/wheels
ADD --checksum=sha256:f11f2b11d5a8ac4059f9bdf29fa4407dc7c6bb00c5097e95ca22a7a9db518266 \
    https://files.pythonhosted.org/packages/f9/8a/cd4c9b02c10c563adfe78118310129641900e1cd6de888cfae2452072696/yt_dlp-2026.7.4-py3-none-any.whl \
    /tmp/wheels/yt_dlp-2026.7.4-py3-none-any.whl

RUN python3.14 -m venv /venv \
    && /venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r /tmp/requirements.txt \
    && ffmpeg -version \
    && ffprobe -version \
    && rm -rf /tmp/requirements.txt /tmp/wheels

COPY app /app
COPY rootfs /

RUN mkdir -p /share/youtube_downloader /data/jobs /data/logs \
    && chmod 0755 /share/youtube_downloader /data/jobs /data/logs \
    && chmod +x /etc/cont-init.d/00-init /etc/services.d/youtube-downloader/run

ENV PATH="/venv/bin:${PATH}" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

WORKDIR /

LABEL \
    io.hass.name="Media Web Downloader" \
    io.hass.description="Webowy downloader serwisów obsługiwanych przez yt-dlp" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Media Web Downloader" \
    org.opencontainers.image.description="Legal YouTube downloads through yt-dlp and Home Assistant Ingress" \
    org.opencontainers.image.version="${BUILD_VERSION}" \
    org.opencontainers.image.source="https://github.com/chmajster/Home-Assistant-Addon-Download-Manager"
