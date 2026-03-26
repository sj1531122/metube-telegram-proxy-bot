FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      ffmpeg \
      tini \
      unzip && \
    pip install --no-cache-dir uv && \
    UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen --no-dev && \
    rm -rf /root/.cache/pip /root/.cache/uv /var/lib/apt/lists/*

RUN XRAY_TAG="$(curl -Ls -o /dev/null -w '%{url_effective}' https://github.com/XTLS/Xray-core/releases/latest | sed 's#.*/tag/##')" && \
    curl -L -o /tmp/xray.zip \
      "https://github.com/XTLS/Xray-core/releases/download/${XRAY_TAG}/Xray-linux-64.zip" && \
    unzip -q /tmp/xray.zip -d /tmp/xray && \
    mv /tmp/xray/xray /usr/local/bin/ && \
    mv /tmp/xray/*.dat /usr/local/bin/ && \
    rm -rf /tmp/xray /tmp/xray.zip && \
    chmod +x /usr/local/bin/xray

COPY app ./app
COPY bot ./bot

ENV DOWNLOAD_DIR=/downloads
ENV STATE_DIR=/state
ENV HTTP_BIND=0.0.0.0
ENV HTTP_PORT=8081

VOLUME ["/downloads", "/state"]
EXPOSE 8081

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "bot.main"]
