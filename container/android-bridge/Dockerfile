# syntax=docker/dockerfile:1

FROM skidc-app:latest

USER root

ARG GITHUB_DOWNLOAD_PREFIX=https://gh-proxy.com/https://github.com

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_MCP_ARTIFACT_ROOT=/artifacts
ENV ANDROID_MCP_TOKEN_FILE=/run/secrets/android_mcp_token
ENV ANDROID_EMULATOR_SERIAL=android-emulator:5555
ENV ADB_VENDOR_KEYS=/var/lib/skidc/android-adb
ENV HOME=/tmp/skidc-home
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV UV_NO_SYNC=1

COPY container/android-bridge/tool-versions.env /opt/skidc/android-tool-versions.env

RUN set -eux; \
    . /opt/skidc/android-tool-versions.env; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        adb \
        aapt \
        apksigner \
        ca-certificates \
        curl \
        default-jre-headless \
        unzip \
        xz-utils; \
    mkdir -p /opt/jadx /opt/apktool; \
    curl --fail --location --retry 3 --output /tmp/jadx.zip \
        "${GITHUB_DOWNLOAD_PREFIX}/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip"; \
    unzip -q /tmp/jadx.zip -d /opt/jadx; \
    ln -s /opt/jadx/bin/jadx /usr/local/bin/jadx; \
    ln -s /opt/jadx/bin/jadx-gui /usr/local/bin/jadx-gui; \
    curl --fail --location --retry 3 --output /opt/apktool/apktool.jar \
        "${GITHUB_DOWNLOAD_PREFIX}/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar"; \
    printf '%s\n' '#!/bin/sh' 'exec java -jar /opt/apktool/apktool.jar "$@"' \
        > /usr/local/bin/apktool; \
    chmod 0555 /usr/local/bin/apktool /opt/jadx/bin/jadx /opt/jadx/bin/jadx-gui; \
    rm -f /tmp/jadx.zip; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Overlay the current project source so the Bridge never depends on stale code
# embedded in a previously built local skidc-app image.
COPY ./skidc /skidc

RUN groupadd --gid 10001 skidc-android \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin skidc-android \
    && install -d -o root -g root -m 0555 /artifacts \
    && install -d -o skidc-android -g skidc-android -m 0700 /home/skidc-android

COPY container/android-bridge/entrypoint.sh /usr/local/bin/android-bridge-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/android-bridge-entrypoint \
    && chmod 0555 /usr/local/bin/android-bridge-entrypoint

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --retries=18 --start-period=5s \
    CMD ["python", "-c", "from pathlib import Path; import urllib.request; token=Path('/run/secrets/android_mcp_token').read_text(encoding='utf-8').strip(); request=urllib.request.Request('http://127.0.0.1:8765/health/ready', headers={'Authorization': 'Bearer '+token}); urllib.request.urlopen(request, timeout=4).read()"]

USER skidc-android
WORKDIR /skidc

ENTRYPOINT ["/usr/local/bin/android-bridge-entrypoint"]
