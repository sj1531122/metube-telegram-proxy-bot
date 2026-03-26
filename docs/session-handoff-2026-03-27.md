# Session Handoff - 2026-03-27

## Repository

- Local repo: `/home/sylar/Desktop/codex/metube-master`
- GitHub: `git@github.com:sj1531122/metube-telegram-proxy-bot.git`
- Working branch: `main`
- Current local HEAD: `fae7cf2`
- Current remote `origin/main`: `3edddb7`
- Local status at handoff time: `main` is clean and ahead of `origin/main` by 2 commits

## Commits Added In This Session

- `45f9d64` `docs: add yt-dlp runtime parity design`
- `fae7cf2` `docs: add yt-dlp runtime parity plan`

These 2 commits are local only at the time of handoff. They have not been pushed to GitHub yet.

## Current Product Reality

The repository is no longer a MeTube runtime project in practice.

Current `main` is a single-container Telegram downloader with:

- Telegram polling bot
- SQLite task persistence
- one serial `yt-dlp` worker
- optional Xray proxy runtime driven by `VPN_SUBSCRIPTION_URL`
- embedded HTTP file server exposing `/download/*`

The active architecture was introduced by:

- `c8d04d6` `feat: switch bot to direct yt-dlp runtime`
- `3edddb7` `docs: rewrite README for direct yt-dlp runtime`

## Verified State Before This Session

The following had already been implemented and validated before the runtime-parity planning work started:

- single-chat Telegram submission flow
- SQLite-backed queue and terminal notification flow
- one-at-a-time download execution
- public `/download/*` link return to Telegram
- optional proxy runtime with dynamic subscription parsing
- proxy node failover and cooldown persistence across restart
- local regression suite passing
- local Docker build passing
- real server deployment and Telegram end-to-end verification completed successfully

Important context:

- The project was successfully deployed and validated on the user's server.
- The user confirmed the current direct-download architecture works operationally.
- The codebase was merged to `main`, the old MeTube runtime path was replaced, and README was rewritten accordingly.

## Key Runtime Files

Primary runtime:

- [bot/main.py](/home/sylar/Desktop/codex/metube-master/bot/main.py)
- [bot/service.py](/home/sylar/Desktop/codex/metube-master/bot/service.py)
- [bot/worker.py](/home/sylar/Desktop/codex/metube-master/bot/worker.py)
- [bot/download_executor.py](/home/sylar/Desktop/codex/metube-master/bot/download_executor.py)
- [bot/download_server.py](/home/sylar/Desktop/codex/metube-master/bot/download_server.py)
- [bot/store.py](/home/sylar/Desktop/codex/metube-master/bot/store.py)

Proxy runtime:

- [app/proxy_runtime.py](/home/sylar/Desktop/codex/metube-master/app/proxy_runtime.py)
- [app/proxy_failover.py](/home/sylar/Desktop/codex/metube-master/app/proxy_failover.py)
- [app/proxy_state.py](/home/sylar/Desktop/codex/metube-master/app/proxy_state.py)
- [app/vpn.py](/home/sylar/Desktop/codex/metube-master/app/vpn.py)

Deployment:

- [Dockerfile](/home/sylar/Desktop/codex/metube-master/Dockerfile)
- [docker-compose.yml](/home/sylar/Desktop/codex/metube-master/docker-compose.yml)
- [.env.example](/home/sylar/Desktop/codex/metube-master/.env.example)
- [README.md](/home/sylar/Desktop/codex/metube-master/README.md)

## What Happened In This Session

This session did not change runtime code.

Instead, it documented the next upgrade needed after server validation:

- make the container behave closer to a practical local `yt-dlp` install for single-video downloads

The immediate trigger was a real failure reported by the user:

- forwarding a YouTube URL to the bot returned a failure
- the error included `No supported JavaScript runtime could be found`

That led to a narrow planning track focused on runtime parity rather than architecture change.

## Root Cause Record For The Next Task

The current container does not behave like a manually tuned local `yt-dlp` setup.

Confirmed gaps:

1. Missing JavaScript runtime for modern YouTube extraction
- current image includes `yt-dlp`, `ffmpeg`, `xray`
- current image does **not** include `Deno`, `Node`, `Bun`, or `QuickJS`
- result: some YouTube URLs fail with `No supported JavaScript runtime could be found`

2. No optional cookies support
- current executor only builds a fixed command
- there is no `COOKIES_FILE` support
- this weakens support for YouTube, X, and some Bilibili cases

3. No passthrough `yt-dlp` flags
- current runtime has no equivalent of local manual tuning such as:
  - `--referer`
  - `--add-header`
  - `--extractor-args`
  - `--format`
- this means the server runtime is not yet comparable to hand-run local `yt-dlp`

4. Playlist behavior is not explicitly constrained
- the product requirement is single-video only
- the runtime should explicitly force `--no-playlist`

## Decisions Reached With The User

The user explicitly confirmed:

- keep supporting only single-video downloads
- do not expand to playlist support
- the next improvement should aim for parity with a normal local `yt-dlp` workflow
- `cookies.txt` as an optional mounted file is acceptable

Chosen direction:

- implement “方案 B”

Meaning:

- add `Deno`
- add optional `COOKIES_FILE`
- add optional `YTDLP_EXTRA_ARGS`
- force `--no-playlist`

Deferred on purpose:

- domain-based proxy split
- PO Token integration
- dedicated YouTube extractor-args variable
- browser-cookie import automation

## Documents Created In This Session

Design spec:

- [docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md)

Implementation plan:

- [docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md)

These documents are the authoritative next-step context for the next Codex session.

## Exact Scope Of The Planned Runtime-Parity Upgrade

The next implementation session should stay inside this boundary:

- do not redesign the Telegram bot flow
- do not redesign SQLite task state
- do not redesign proxy retry policy
- do not add playlist support

Only change:

- `bot/config.py`
- `bot/download_executor.py`
- `bot/worker.py`
- `Dockerfile`
- `.env.example`
- `docker-compose.yml`
- `README.md`
- matching tests

Target behavior:

- install `Deno >= 2` in the image
- add optional `COOKIES_FILE`
- add optional `YTDLP_EXTRA_ARGS`
- always add `--no-playlist`
- preserve current retry/failover logic

## Current Config Reality

At handoff time, the runtime parity features are **not implemented yet**.

Current deployment config still only documents:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `PUBLIC_DOWNLOAD_BASE_URL`
- `VPN_SUBSCRIPTION_URL`
- `DOWNLOAD_DIR`
- `STATE_DIR`
- `HTTP_BIND`
- `HTTP_PORT`
- `HTTP_TIMEOUT_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

Not yet present in code or docs:

- `COOKIES_FILE`
- `YTDLP_EXTRA_ARGS`
- Deno installation

## Current Deployment Notes

Known deployment model that already works:

- one server
- Docker Compose for the app
- Nginx reverse-proxy exposing `/download/*`
- bot returns direct file URLs using `PUBLIC_DOWNLOAD_BASE_URL`

Known verified public pattern:

- Nginx proxies `/download/` to `127.0.0.1:8081`
- container stores downloads under `./data/downloads`
- container stores runtime state under `./data/state`

Operational caution:

- secrets such as Telegram tokens, chat IDs, and subscription URLs were provided in earlier sessions by the user
- do not re-emit those secrets in future handoff or summary messages unless the user explicitly asks

## Recommended Next Execution Order

When work resumes, follow this order:

1. Create an isolated feature worktree from current `main`
2. Execute [docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md)
3. Run focused tests for:
   - `tests.bot.test_config`
   - `tests.bot.test_download_executor`
   - `tests.bot.test_worker`
   - `tests.bot.test_main`
4. Run the full `unittest` suite
5. Build the Docker image
6. Smoke-test Compose startup
7. Manually verify at least one public YouTube single-video URL
8. Only after verification, decide whether to push/merge

## Suggested Branch / Worktree Strategy

Do not implement the parity work directly on dirty `main`.

Recommended:

- base branch: `main`
- create a fresh feature branch such as `feature/ytdlp-runtime-parity`
- use a new worktree for implementation

Reason:

- local `main` is currently ahead of `origin/main` by 2 doc commits
- the next session should either push those doc commits first or carry them into the new feature branch intentionally

## Git Status At Handoff

At the end of this session:

- local branch: `main`
- local HEAD: `fae7cf2`
- remote `origin/main`: `3edddb7`
- ahead by 2 commits
- working tree clean

Those 2 unpushed commits are:

- `45f9d64` `docs: add yt-dlp runtime parity design`
- `fae7cf2` `docs: add yt-dlp runtime parity plan`

## Existing Historical Context Files

Earlier handoff:

- [docs/session-handoff-2026-03-26.md](/home/sylar/Desktop/codex/metube-master/docs/session-handoff-2026-03-26.md)

Current architecture spec:

- [docs/superpowers/specs/2026-03-26-direct-ytdlp-single-container-design.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/specs/2026-03-26-direct-ytdlp-single-container-design.md)

Current parity spec:

- [docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md)

Current parity plan:

- [docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md](/home/sylar/Desktop/codex/metube-master/docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md)

## Recommended Opener For The Next Codex Session

Use this prompt next time:

```text
Please continue from the saved handoff in docs/session-handoff-2026-03-27.md.
Repository: /home/sylar/Desktop/codex/metube-master
Base branch: main

Important context:
- Current architecture is already the direct single-container yt-dlp runtime, not MeTube
- Local main is ahead of origin/main by 2 doc commits: 45f9d64 and fae7cf2
- The next task is to implement the yt-dlp runtime parity plan

Please start by reviewing:
- docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md
- docs/superpowers/plans/2026-03-27-ytdlp-runtime-parity.md
```

## Short Human Summary

If someone only reads one paragraph, this is the minimum:

The project has already been migrated from MeTube to a direct single-container `yt-dlp` Telegram bot and has been validated on a real server. The next unresolved problem is runtime parity with a practical local `yt-dlp` setup, especially for YouTube. No code was changed in this session; instead, a spec and implementation plan were written to add `Deno`, optional cookies support, optional passthrough `yt-dlp` args, and forced `--no-playlist`. The repo is clean, but local `main` is ahead of `origin/main` by two documentation commits that still need to be pushed or carried into the next feature branch.
