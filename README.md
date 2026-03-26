# MeTube Telegram Direct Downloader

Single-container Telegram download bot powered by local `yt-dlp`, optional Xray proxy failover, and a minimal embedded `/download/*` file server.

单容器 Telegram 下载机器人，直接在本地执行 `yt-dlp`，可选接入 Xray 代理轮换，并在容器内提供最小化 `/download/*` 文件服务。

## What This Branch Does

- Telegram receives URLs from one allowed chat
- tasks are persisted in SQLite
- one serial worker downloads exactly one task at a time
- successful downloads are exposed under one `/download/*` path
- optional `VPN_SUBSCRIPTION_URL` enables Xray-based node switching
- proxy invalidation and YouTube rate-limit errors can automatically switch nodes and retry
- active node and cooldown state survive container restart

## Scope

- single user
- single chat
- single queue
- no web UI
- no MeTube API
- no separate audio URL path

## Environment Variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `PUBLIC_DOWNLOAD_BASE_URL`

Optional:

- `VPN_SUBSCRIPTION_URL`
- `DOWNLOAD_DIR`
- `STATE_DIR`
- `HTTP_BIND`
- `HTTP_PORT`
- `HTTP_TIMEOUT_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

Example file:

- `.env.example`

## Docker Compose

1. Copy the sample env file:

```bash
cp .env.example .env
```

2. Fill in the real values.

Important:

- `PUBLIC_DOWNLOAD_BASE_URL` must be the public URL that Telegram can open, for example:
  - `https://downloads.example.com/download`
- if you use the built-in file server behind Nginx, forward `/download/` to container port `8081`

3. Start the service:

```bash
docker compose up -d --build
```

4. Check logs:

```bash
docker compose logs -f app
```

## Reverse Proxy

Expose the container file server through `/download/*`.

Example Nginx location:

```nginx
location /download/ {
    proxy_pass http://127.0.0.1:8081/download/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Then set:

```env
PUBLIC_DOWNLOAD_BASE_URL=https://downloads.example.com/download
```

## Runtime Flow

1. Send a URL to the Telegram bot.
2. The bot normalizes the URL and inserts a queued task into SQLite.
3. The single worker claims the oldest runnable task.
4. `yt-dlp` downloads through the current proxy node when proxy runtime is enabled.
5. On success, the bot replies with:
   - `Finished: <title>`
   - `<PUBLIC_DOWNLOAD_BASE_URL>/<filename>`
6. On proxy invalidation or rate-limit errors, the runtime switches to the next node and retries automatically.

## Local Verification

Run the Python test suite:

```bash
.venv/bin/python -m unittest discover -t . -s tests -v
```

Build the container:

```bash
docker build -t metube-direct-local .
```

Run the compose stack:

```bash
docker compose up --build
```
