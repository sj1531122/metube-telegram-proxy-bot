# yt-dlp Runtime Parity Design

## Summary

Bring the single-container Telegram downloader closer to the behavior of running `yt-dlp` manually on a machine that already works for single-video downloads.

The first phase stays deliberately small:

- keep single-video-only behavior
- keep the current Telegram queue and proxy failover model
- add the missing YouTube JavaScript runtime
- add optional cookies support
- add optional passthrough arguments so the container can be tuned like a local `yt-dlp` install
- force single-video mode with `--no-playlist`

This is a runtime-parity upgrade, not a feature expansion.

## Goals

- Fix the current YouTube failure caused by missing JavaScript runtime support.
- Make the container runtime materially closer to a normal local `yt-dlp` workflow.
- Preserve the current Telegram bot flow, queue model, and proxy failover behavior.
- Keep deployment simple through Docker Compose.
- Keep cookies optional instead of mandatory.
- Enforce single-video-only execution explicitly.

## Non-Goals

- No playlist support.
- No parallel downloads.
- No site-based direct/proxy split in this phase.
- No automatic PO Token integration in this phase.
- No browser-cookie extraction inside the container.
- No new Telegram commands or UI changes.

## Current Problem

The current container executes a very narrow fixed command:

- `yt-dlp`
- output path and filename template
- optional `--proxy`
- source URL

That is enough for basic public URLs, but it is not equivalent to the way a person usually runs `yt-dlp` locally.

Current gaps:

- no JavaScript runtime for modern YouTube extraction
- no cookies file support
- no configurable extra arguments
- no explicit single-video enforcement

As a result, the bot can fail on URLs that would succeed locally with the same `yt-dlp` version plus a few common runtime inputs.

## Recommended Design

### 1. Keep the Existing Bot Architecture

Do not change:

- Telegram polling
- SQLite task persistence
- single serial worker
- embedded `/download/*` file server
- proxy runtime built from `VPN_SUBSCRIPTION_URL`
- proxy node failover and retry policy

The upgrade is isolated to runtime inputs for the download executor and the container image that provides those inputs.

### 2. Add Deno to the Container Image

Install `Deno >= 2` in the production image.

Reasoning:

- current YouTube extraction requires a supported JavaScript runtime
- this is the direct fix for the reported `No supported JavaScript runtime could be found` error
- Deno is the cleanest option for this image because it does not require introducing a heavier Node.js toolchain

The container should continue to include:

- `yt-dlp[default,curl-cffi]`
- `ffmpeg`
- `xray`

This gives the image the minimum runtime stack needed for practical YouTube extraction while preserving current behavior for other sites.

### 3. Add Optional `COOKIES_FILE`

Introduce a new optional environment variable:

- `COOKIES_FILE`

Behavior:

- if unset or empty, do not pass cookies to `yt-dlp`
- if set, treat it as an absolute path inside the container
- if the file does not exist, fail fast at startup or configuration load rather than silently ignoring it

This is the least surprising deployment model for a server-side bot:

- the operator exports cookies externally
- the file is mounted into the container
- the bot uses it only when configured

This is especially important for:

- X / Twitter
- some Bilibili content
- some YouTube cases that are sensitive to account state

### 4. Add Optional `YTDLP_EXTRA_ARGS`

Introduce a new optional environment variable:

- `YTDLP_EXTRA_ARGS`

Behavior:

- parse it with shell-style splitting
- append the resulting arguments to the `yt-dlp` command before the source URL

This creates a generic escape hatch for local-runtime parity without creating a new environment variable per flag.

Examples of supported usage:

- `--referer https://example.com`
- `--add-header User-Agent: ...`
- `--add-header Authorization: ...`
- `--format bv*+ba/b`
- `--extractor-args youtube:player_client=web`

This is the most important capability for matching local manual `yt-dlp` usage because it preserves operator control without expanding the bot surface area.

### 5. Enforce Single-Video Mode by Default

Always add:

- `--no-playlist`

Reasoning:

- the current bot returns a single completion message with one file URL
- the current data model is not built for multi-file results
- this matches the stated product requirement: only support single-video downloads

This removes ambiguity for playlist URLs and prevents the runtime from partially succeeding in ways the Telegram response model cannot represent cleanly.

## Command Shape

The target command shape is:

```bash
yt-dlp \
  --no-progress \
  --newline \
  --no-playlist \
  --print before_dl:TITLE:%(title)s \
  --print after_move:FILEPATH:%(filepath)s \
  -P <download_dir> \
  -o "%(title)s.%(ext)s" \
  [--cookies <COOKIES_FILE>] \
  [--proxy http://127.0.0.1:10809] \
  [YTDLP_EXTRA_ARGS...] \
  <url>
```

Ordering requirements:

- `--no-playlist` is always present
- cookies are added only when configured
- proxy is added only when proxy runtime is active
- extra args are appended after the built-in defaults and before the final URL

## Configuration Surface

### Required

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `PUBLIC_DOWNLOAD_BASE_URL`

### Existing Optional

- `VPN_SUBSCRIPTION_URL`
- `DOWNLOAD_DIR`
- `STATE_DIR`
- `HTTP_BIND`
- `HTTP_PORT`
- `HTTP_TIMEOUT_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `TASK_TIMEOUT_SECONDS`
- `BOT_DEDUPE_WINDOW_SECONDS`

### New Optional

- `COOKIES_FILE`
- `YTDLP_EXTRA_ARGS`

No other first-phase configuration should be added.

## Error Handling

### Configuration-Time Failures

The runtime should reject configuration early when:

- `COOKIES_FILE` is set but the file does not exist
- `YTDLP_EXTRA_ARGS` cannot be parsed safely

Failing early is preferable to silently starting in a misconfigured state.

### Runtime Failures

Do not redesign the current retry model.

The executor still returns stderr text to the worker. The worker still decides whether a failure is:

- retry on same node
- switch node
- final fail

This keeps the change localized and avoids coupling runtime-parity work to proxy-policy work.

## Backward Compatibility

The upgrade should remain backward compatible for current deployments:

- if no new variables are set, the bot still starts and behaves as before, except that playlist URLs are explicitly constrained to single-video behavior
- proxy behavior is unchanged
- Telegram messages and queue semantics are unchanged
- public download URL format is unchanged

Operationally, existing deployments only need to rebuild the image. Cookies remain optional.

## Deployment Model

### Docker Image

Modify the production image to install Deno alongside the current Python runtime dependencies.

### Compose

Keep the current single-service Compose structure.

Optionally allow operators to mount a cookies file, for example:

```yaml
volumes:
  - ./data/downloads:/downloads
  - ./data/state:/state
  - ./secrets/cookies.txt:/run/secrets/cookies.txt:ro
```

Then configure:

```env
COOKIES_FILE=/run/secrets/cookies.txt
```

### Documentation

Update `.env.example` and `README.md` to show three operating modes:

1. baseline mode
   - no cookies
   - no extra args

2. parity mode
   - cookies enabled
   - extra args available

3. YouTube-fix minimum
   - rebuilt image with Deno installed

## Validation Criteria

The design is successful when all of the following are true:

1. A YouTube URL no longer fails with `No supported JavaScript runtime could be found`.
2. A public single-video YouTube URL can be downloaded in the container with no extra manual patching.
3. A deployment with `COOKIES_FILE` can run successfully when the file is mounted into the container.
4. `YTDLP_EXTRA_ARGS` can alter `yt-dlp` behavior without code changes.
5. Playlist URLs are treated as single-video requests instead of producing ambiguous multi-file outcomes.
6. Existing non-cookie deployments continue to run after rebuild with no required environment changes.

## Deferred Work

The following items are intentionally deferred unless real-world tests show they are required:

- domain-based proxy split such as direct Bilibili plus proxied YouTube/X
- dedicated `YOUTUBE_EXTRACTOR_ARGS` variable
- PO Token integration
- browser-cookie import automation
- richer per-site retry heuristics

These can be added later without invalidating this first-phase design.
