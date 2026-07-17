# syntax=docker/dockerfile:1.18
FROM node:24.4.1-alpine3.22 AS frontend

WORKDIR /build
COPY rootfs/app/frontend/package.json rootfs/app/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY rootfs/app/frontend/ ./
RUN npm run check && npm test && npm run build

FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH

RUN apk add --no-cache \
      ca-certificates \
      ffmpeg \
      libjpeg-turbo \
      libwebp \
      nodejs \
      python3 \
      py3-pip \
    && python3 -m venv /opt/youtube-audio \
    && /opt/youtube-audio/bin/pip install --no-cache-dir --upgrade pip==26.1.2 \
    && rm -rf /root/.cache

ENV PATH="/opt/youtube-audio/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YAD_FRONTEND_ROOT=/app/frontend

COPY rootfs/app/backend/requirements.lock /tmp/requirements.lock
RUN apk add --no-cache --virtual .build-deps \
      build-base \
      cargo \
      jpeg-dev \
      libwebp-dev \
      linux-headers \
      python3-dev \
      zlib-dev \
    && pip install --no-cache-dir --require-hashes --requirement /tmp/requirements.lock \
    && apk del .build-deps \
    && rm -rf /root/.cache /tmp/requirements.lock

COPY rootfs/ /
COPY --from=frontend /build/dist/ /app/frontend/

RUN chmod 0755 \
      /etc/services.d/youtube-audio/run \
      /etc/services.d/youtube-audio/finish \
    && find /app -type d -exec chmod 0755 {} + \
    && find /app -type f -exec chmod 0644 {} +

EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O - http://127.0.0.1:8099/api/health >/dev/null || exit 1

LABEL \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.title="Home Assistant App: YouTube Audio Downloader" \
  org.opencontainers.image.description="Download authorized YouTube audio as tagged MP3 files" \
  org.opencontainers.image.source="https://github.com/Misiu/yt_dlp-addon" \
  org.opencontainers.image.licenses="MIT"
