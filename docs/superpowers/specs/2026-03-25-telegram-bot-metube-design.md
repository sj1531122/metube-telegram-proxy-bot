# Telegram Bot for Remote MeTube Downloads

## Summary

Build a standalone Telegram bot for a single personal user. The bot runs on a separate machine from MeTube, accepts download links in Telegram, submits them to MeTube, polls MeTube for completion, and replies with a direct download URL when the file is ready.

This design keeps MeTube as the download engine and avoids modifying its frontend. The initial version targets one allowed Telegram chat, fixed download defaults, and direct file links.

## Goals

- Accept one or more media URLs from a personal Telegram chat.
- Submit each URL to the existing MeTube `POST /add` API.
- Detect completion by polling MeTube `GET /history`.
- Reply with a direct download URL that opens without an extra login step.
- Report failures back to Telegram with a useful error message.
- Survive bot restarts without losing task tracking.

## Non-Goals

- Multi-user or multi-tenant support.
- Telegram inline keyboards, custom format selection, or queue management commands.
- Signed URLs or expiring download links.
- Playlist aggregation into one summary notification.
- Changes to the MeTube Angular UI.
- Real-time push callbacks from MeTube to the bot.

## Existing MeTube Integration Points

- New downloads are created through `POST /add` in `app/main.py`.
- Download history is exposed through `GET /history` in `app/main.py`.
- Completed files are served from `/download/` and `/audio_download/`.
- Public link bases can be configured with `PUBLIC_HOST_URL` and `PUBLIC_HOST_AUDIO_URL`.
- A download is only considered successful when its final `status` is `finished`. Entries moved into the completed queue may still represent failures.

## Recommended Architecture

### Components

1. Telegram adapter
   - Receives messages from Telegram.
   - Rejects any `chat_id` except the configured personal chat.
   - Extracts URLs from incoming text.
   - Sends status replies and final download links.

2. MeTube client
   - Wraps authenticated calls to MeTube.
   - Supports `POST /add` and `GET /history`.
   - Applies fixed download defaults for the MVP.

3. Task store
   - Uses SQLite for durable local state.
   - Keeps the mapping between Telegram messages and MeTube tasks.

4. Poller
   - Periodically loads MeTube history.
   - Matches queued or completed entries to locally tracked tasks.
   - Triggers Telegram notifications exactly once.

5. Configuration
   - Stores the Telegram bot token, allowed chat ID, MeTube API base URL, API auth secret, public download base URLs, polling interval, and timeout.

### Deployment Topology

- The Telegram bot runs on machine A.
- MeTube runs on machine B.
- A reverse proxy sits in front of MeTube.
- `/add` and `/history` are protected with API auth.
- `/download/*` and `/audio_download/*` remain public so Telegram links can open directly.

## Data Flow

1. The user sends a message with one or more URLs to the Telegram bot.
2. The bot validates the sender chat ID and extracts URLs.
3. For each URL, the bot creates a local SQLite task row with state `received`.
4. The bot calls MeTube `POST /add` with fixed parameters such as `quality=best`, `format=any` or `mp4`, and `auto_start=true`.
5. On successful submission, the task state moves to `submitted` and the bot replies that the job was queued.
6. A background poller requests MeTube `GET /history` every 10 to 15 seconds.
7. If the task appears in `queue` or `pending`, the local state becomes `queued`.
8. If the task appears in `done`:
   - `status == finished`: mark `finished`, build a direct download link, and send it to Telegram.
   - `status != finished`: mark `failed` and send the failure message to Telegram.
9. If the task is still unresolved after the configured timeout, mark `timeout` and notify the user once.

## Task Matching Rules

### Primary Match

- Match MeTube entries to local bot tasks by exact source URL.

### Secondary Match

- If the source URL is rewritten by the remote extractor, fall back to `title + submission window`.
- The submission window should be narrow, for example a few minutes around the recorded `submitted_at`.

### Duplicate Submissions

- The MVP should deduplicate identical URLs submitted within a short recent window.
- If the same URL is sent again within the dedupe window, the bot should acknowledge that the task already exists instead of resubmitting it.
- Fine-grained handling of repeated identical URLs outside that window is deferred.

## Local Persistence Model

Use a single SQLite table, for example `tasks`, with these fields:

- `id`
- `chat_id`
- `telegram_message_id`
- `source_url`
- `submitted_at`
- `state`
- `download_url`
- `filename`
- `title`
- `last_error`
- `notified_at`

Recommended state values:

- `received`
- `submitted`
- `queued`
- `finished`
- `failed`
- `timeout`

## Link Generation

The bot must not guess filenames. It should use the `filename` returned by MeTube history entries.

Link construction rules:

- For video downloads, use `PUBLIC_HOST_URL + filename`.
- For audio downloads, use `PUBLIC_HOST_AUDIO_URL + filename`.
- If those variables are configured as full public URLs, the bot can return them directly without knowing reverse proxy details.

This keeps link generation aligned with MeTube’s own static file exposure.

## Error Handling

### Submission Failure

- If `POST /add` fails, send an immediate Telegram reply with the returned error.
- Do not schedule polling for that task.

### Download Failure

- If the task moves into MeTube’s completed queue but `status != finished`, treat it as failed.
- Reply with the media title when available and include the error message from MeTube.

### Missing Filename

- If a supposedly finished task has no `filename`, mark it as failed with an internal error such as `completed_without_filename`.
- Notify the user and log the mismatch for investigation.

### Timeout

- If no final state is observed before the configured timeout, mark the task `timeout` and send a single timeout notification.

### Bot Restart

- On startup, load unfinished SQLite tasks and resume polling.
- Notification deduplication must key off `notified_at` so the same completion is never sent twice.

## Security Model

- The Telegram bot only accepts commands from one configured personal `chat_id`.
- MeTube API endpoints exposed to the bot are protected by a reverse proxy.
- Download file paths remain public because the user explicitly wants one-click direct downloads from Telegram.
- The bot must never return internal MeTube hostnames; only public download base URLs are allowed in notifications.

## Operational Defaults

- Poll interval: 10 to 15 seconds.
- Task timeout: 6 hours.
- Telegram success message:
  - Title
  - Direct download URL
- Telegram failure message:
  - Title or original URL
  - Failure reason

## Testing Strategy

### Unit Tests

- URL extraction from incoming Telegram text.
- Chat ID allowlist enforcement.
- SQLite task creation and state transitions.
- History matching by exact URL and secondary fallback.
- Link generation for `/download/` and `/audio_download/`.

### Integration Tests

- Mock `POST /add` success and failure responses.
- Mock `GET /history` transitions from queued to finished.
- Mock failure entries in MeTube’s completed queue.
- Verify restart recovery resumes polling without duplicate notifications.

### Manual Validation

1. Submit a normal video URL and verify queue acknowledgment.
2. Wait for completion and verify the Telegram link downloads directly.
3. Submit a failing URL and verify the failure reply.
4. Restart the bot mid-download and verify tracking resumes.
5. Submit an audio-only URL and verify the audio link base is used.

## Implementation Scope and Difficulty

### MVP Scope

- Single personal chat
- Fixed download defaults
- SQLite task store
- Polling-based completion tracking
- Direct link notification
- Reverse-proxy-protected API access

### Difficulty

- Overall complexity: low to medium
- Estimated implementation time: 0.5 to 1.5 days for the MVP, assuming Telegram credentials, MeTube public URLs, and reverse proxy access are already available

### Main Risks

- Direct download links are public by design.
- URL-based task matching can be ambiguous if the same source is submitted repeatedly in a short time.
- Some extractors may rewrite source URLs, requiring the fallback match path.

## Future Extensions

- Multi-user support with per-chat authorization.
- Format selection commands in Telegram.
- Playlist summary notifications.
- Push callbacks from MeTube instead of polling.
- Signed download links or a file relay service.
