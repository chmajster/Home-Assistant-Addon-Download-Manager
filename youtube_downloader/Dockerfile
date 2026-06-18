ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.23

FROM mwader/static-ffmpeg:8.1.1 AS ffmpeg

FROM ${BUILD_FROM}

ARG BUILD_VERSION="1.3.67"
ARG BUILD_ARCH="amd64"

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

COPY requirements.txt /tmp/requirements.txt
COPY wheels /tmp/wheels

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
    io.hass.description="Webowy downloader YouTube, Instagram, Kick i Twitch oparty o yt-dlp" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Media Web Downloader" \
    org.opencontainers.image.description="Legal YouTube downloads through yt-dlp and Home Assistant Ingress" \
    org.opencontainers.image.source="https://github.com/example/home-assistant-media-web-downloader-addon"
