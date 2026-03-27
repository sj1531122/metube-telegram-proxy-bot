# Telegram yt-dlp Download Bot

Single-container Telegram downloader with local `yt-dlp`, optional Xray proxy failover, SQLite task persistence, and an embedded `/download/*` file server.

单容器 Telegram 下载机器人，直接在本地执行 `yt-dlp`，可选启用 Xray 代理轮换，使用 SQLite 持久化任务，并在容器内提供 `/download/*` 文件服务。

## Overview

This repository no longer depends on MeTube as the runtime download backend.

Current `main` is designed for one practical deployment target:

- one bot
- multiple allowed private users (private direct messages only)
- one serial download worker
- one public download path: `/download/*`
- single-video downloads only

Verified production flow:

1. Send a URL to the Telegram bot.
2. The bot stores the task in SQLite and replies `Queued: <url>`.
3. A single worker runs `yt-dlp` locally inside the container.
4. The file is exposed through the built-in HTTP server.
5. The bot replies with:
   - `Finished: <title>`
   - `<PUBLIC_DOWNLOAD_BASE_URL>/<filename>`

If proxy runtime is enabled, the worker can automatically switch proxy nodes and retry when it hits invalid nodes, network failures, or YouTube-style rate-limit / anti-bot errors.

## Latest Verified Status (2026-03-27)

As of 2026-03-27, `main` includes the runtime-parity hardening that was added after real Telegram and YouTube verification.

Shipped in `main`:

- Docker image now bundles `Deno 2.6.6`
- lockfile now pins `yt-dlp 2026.3.17` and `yt-dlp-ejs 0.8.0`
- optional `COOKIES_FILE` and `YTDLP_EXTRA_ARGS` are supported
- every `yt-dlp` execution forces `--no-playlist`
- Telegram `getUpdates` now uses a request timeout above the long-poll timeout, avoiding self-inflicted polling timeouts
- proxy failover now treats partial-read download failures such as `... more expected` as switch-node errors instead of immediate final failures

Verified results:

- full Python `unittest` suite passes on `main`
- Docker rebuild passes
- local Telegram end-to-end verification passes
- second-server deployment verification passes
- a real YouTube task was observed failing on one proxy node, switching to the next node, and then finishing successfully

Operational note:

- proxy-free hosts can use the default `docker compose` deployment in this repository
- hosts that must egress through a loopback-only local proxy may need explicit proxy environment wiring or a host-network deployment strategy

## What This Project Includes

- Telegram polling bot
- multi-user allowlist control that accepts only private chats from configured users and keeps dedupe scoped per user
- SQLite task persistence under `data/state`
- one serial worker, no concurrent downloads
- embedded HTTP file server on container port `8081`
- one public file path only: `/download/*`
- explicit `--no-playlist` execution for every `yt-dlp` run
- optional `VPN_SUBSCRIPTION_URL` support
- bundled `Deno` runtime in the Docker image for modern YouTube extraction
- optional mounted cookies support through `COOKIES_FILE`
- optional `yt-dlp` passthrough flags through `YTDLP_EXTRA_ARGS`
- Xray node parsing from dynamic subscription content
- automatic proxy failover and retry
- proxy state persistence across container restart

## What This Project Does Not Include

- MeTube web UI
- MeTube API as the active download backend
- separate audio download URL path
- webhook mode
- group chats (these are ignored even in multi-user mode)
- playlist downloads

## Architecture

Runtime flow:

`Telegram -> bot polling -> SQLite queue -> yt-dlp worker -> /download/* -> Telegram reply`

When `VPN_SUBSCRIPTION_URL` is configured:

`subscription -> parsed nodes -> Xray local outbound -> yt-dlp --proxy http://127.0.0.1:10809`

Proxy runtime behavior:

- startup loads subscription nodes and picks the last active usable node when possible
- node failure writes cooldown state to disk
- switching nodes refreshes the subscription again, so dynamic node lists are supported
- active node fingerprint and cooldown entries survive container restart

## Directory Layout

Important runtime directories:

- `data/downloads`
  - downloaded files returned to Telegram users
- `data/state`
  - SQLite database
  - proxy state
  - generated Xray config

The default compose file mounts both directories from the host, so downloads and proxy state survive container recreation.

## Environment Variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `PUBLIC_DOWNLOAD_BASE_URL`

Allowlist configuration (at least one required):

- `TELEGRAM_ALLOWED_USER_IDS` (preferred multi-user private-chat allowlist; when set, only those user IDs may queue downloads via private chat and group chats are ignored)
- `TELEGRAM_ALLOWED_CHAT_ID` (legacy single-chat compatibility; honored only when `TELEGRAM_ALLOWED_USER_IDS` is unset)

Optional:

- `VPN_SUBSCRIPTION_URL`
- `DOWNLOAD_DIR`
- `STATE_DIR`
- `COOKIES_FILE`
- `YTDLP_EXTRA_ARGS`
- `HTTP_BIND`
- `HTTP_PORT`
- `HTTP_TIMEOUT_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

Example file:

- `.env.example`

Variable notes:

- `TELEGRAM_ALLOWED_USER_IDS`
  - comma-separated list of the Telegram user IDs that may queue downloads via private chat
  - only direct messages from those users are processed; group chats are ignored even if a configured user participates
  - dedupe state is tracked per user, so each allowed user can queue the same normalized URL independently while `BOT_DEDUPE_WINDOW_SECONDS` still suppresses immediate repeats
  - this setting takes precedence over `TELEGRAM_ALLOWED_CHAT_ID` when both are set
- `TELEGRAM_ALLOWED_CHAT_ID`
  - legacy compatibility for single-chat deployments; honored only when `TELEGRAM_ALLOWED_USER_IDS` is unset
  - fallback preserves the original single allowed chat behavior for compatibility with older deployments
- `PUBLIC_DOWNLOAD_BASE_URL`
  - must be the final public URL prefix visible to Telegram clients
  - example: `https://downloads.example.com/download`
- `VPN_SUBSCRIPTION_URL`
  - if omitted, downloads run without proxy failover
- `COOKIES_FILE`
  - optional absolute in-container path to a mounted Netscape `cookies.txt` file
  - startup fails fast if the path is set but the file does not exist
- `YTDLP_EXTRA_ARGS`
  - optional shell-split passthrough flags appended before the final source URL
  - examples: `--format bv*+ba/b`, `--referer https://example.com`, `--extractor-args youtube:player_client=web`
- `BOT_DEDUPE_WINDOW_SECONDS`
  - suppresses repeated submission of the same normalized URL within the configured window
- `TASK_TIMEOUT_SECONDS`
  - hard timeout for a single `yt-dlp` execution

## Runtime Parity Modes

Three practical operating modes are supported:

1. Baseline
   - set the required Telegram variables and `PUBLIC_DOWNLOAD_BASE_URL`
   - no proxy, no cookies, no extra `yt-dlp` flags
2. YouTube-fix minimum
   - rebuild the image so the bundled `Deno` runtime is present
   - this is the minimum change for the reported `No supported JavaScript runtime could be found` YouTube failure
3. Parity
   - optionally mount a `cookies.txt` file and set `COOKIES_FILE`
   - optionally set `YTDLP_EXTRA_ARGS` for manual tuning that matches a working local `yt-dlp` command

Regardless of mode, the worker always adds `--no-playlist`. Playlist URLs are treated as single-video requests only.

## Docker Compose Quick Start

1. Clone the repository and enter it.

```bash
git clone <your-repo-url>
cd metube-telegram-proxy-bot
```

2. Create the env file.

```bash
cp .env.example .env
```

3. Fill at least these values:

```env
TELEGRAM_BOT_TOKEN=1234567890:replace-me
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321
PUBLIC_DOWNLOAD_BASE_URL=https://downloads.example.com/download
VPN_SUBSCRIPTION_URL=https://example.com/subscription
```

Only direct private messages from those user IDs are processed; group chats are ignored even if a configured user participates.

4. Optional: enable cookies support by mounting a Netscape `cookies.txt` file.

```yaml
services:
  app:
    volumes:
      - ./data/downloads:/downloads
      - ./data/state:/state
      - ./secrets/cookies.txt:/run/secrets/cookies.txt:ro
```

```env
COOKIES_FILE=/run/secrets/cookies.txt
YTDLP_EXTRA_ARGS=--format bv*+ba/b
```

5. Start or rebuild the container.

```bash
docker compose up -d --build
```

6. Check status and logs.

```bash
docker compose ps
docker compose logs -f app
```

Default compose behavior:

- container name: `metube-direct-local`
- listens on host port `8081`
- downloads stored in `./data/downloads`
- state stored in `./data/state`

If you only need the YouTube JavaScript runtime fix, you can leave `COOKIES_FILE` and `YTDLP_EXTRA_ARGS` unset and just rebuild the image.

## Nginx Reverse Proxy

Expose only `/download/*` to the public internet.

Example server block:

```nginx
server {
    listen 80;
    server_name downloads.example.com;

    client_max_body_size 0;

    location /download/ {
        proxy_pass http://127.0.0.1:8081/download/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600;
        send_timeout 3600;
    }

    location / {
        return 404;
    }
}
```

Then make sure `.env` uses the same public prefix:

```env
PUBLIC_DOWNLOAD_BASE_URL=https://downloads.example.com/download
```

## Download and Retry Behavior

Task behavior:

- only private chats from the user IDs listed in `TELEGRAM_ALLOWED_USER_IDS` can queue tasks; group chats are ignored, and when that list is unset the legacy `TELEGRAM_ALLOWED_CHAT_ID` single-chat fallback is used
- each incoming message may contain one or more URLs
- URLs are normalized before de-duplication and storage
- only one queued task is processed at a time
- every download command forces `--no-playlist`

Success behavior:

- the bot sends `Queued: ...`
- after completion, the bot sends `Finished: ...` plus a direct file URL

Failure behavior without proxy runtime:

- transient errors may retry on the same node with delays: `10s / 30s / 60s`
- permanent failures are reported back to Telegram

Failure behavior with proxy runtime enabled:

- invalid subscription node / unreachable proxy / TLS or network errors can trigger node switch
- YouTube anti-bot / unusual traffic / rate-limit style failures can trigger node switch
- a task can try up to 3 distinct proxy fingerprints before final failure
- failed nodes enter cooldown and are skipped until cooldown expires

## Dynamic Subscription Notes

`VPN_SUBSCRIPTION_URL` can return a changing node list. This is supported by design.

Why it works:

- startup parses the current subscription content
- every node switch refreshes the subscription again
- persisted state tracks fingerprints instead of fixed list positions only

Operational consequence:

- if the first node becomes invalid, later retries can move to a fresh node from the updated subscription
- if a previously good node is rate-limited by YouTube, it can be cooled down and bypassed on later attempts

## Local Non-Docker Run

If you want to run it directly with Python:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install uv
uv sync --frozen
set -a
source .env
set +a
python -m bot.main
```

This mode still expects `yt-dlp`, `ffmpeg`, and optional `xray` to be available on the machine.
For YouTube parity outside Docker, install `Deno >= 2` on the host as well.

## Verification

Python test suite:

```bash
.venv/bin/python -m unittest discover -t . -s tests -v
```

Docker build:

```bash
docker build -t metube-direct-local .
```

Runtime smoke checks:

```bash
docker compose ps
ss -ltnp | grep 8081
curl -I http://127.0.0.1:8081/download/notfound
```

Telegram verification:

1. Send a normal media URL from one of the allowed private-user chats (or the legacy allowed chat when only `TELEGRAM_ALLOWED_CHAT_ID` is configured).
2. Confirm you receive `Queued: ...`.
3. Wait for `Finished: ...` and open the returned link.
4. Confirm playlist URLs still behave as single-video requests only.
5. If proxy runtime is enabled, test a URL that previously triggered rate-limit behavior and confirm automatic retry/failover is visible in logs.
6. For the YouTube runtime-fix path, verify the previous JavaScript-runtime error no longer appears after rebuilding the image.

## Operations

Common commands:

```bash
docker compose up -d --build
docker compose logs -f app
docker compose restart app
docker compose down
```

Useful host paths:

- `data/downloads`
- `data/state/tasks.sqlite3`
- `data/state/proxy_state.json`

## Limits

This project intentionally keeps the scope small:

- single bot process
- single worker
- single download queue
- polling only
- no task priority
- no resumable dashboard
- no multi-tenant permission model

## Upstream Components

- `yt-dlp`: https://github.com/yt-dlp/yt-dlp
- `Xray-core`: https://github.com/XTLS/Xray-core

Historical note:

- the repository started from a MeTube-oriented direction
- the active runtime on `main` is now the direct `yt-dlp` single-container design
