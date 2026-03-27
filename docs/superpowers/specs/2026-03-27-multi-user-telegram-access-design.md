# Multi-user Telegram Access Design

## Summary

Extend the bot from a single allowed Telegram chat to a small multi-user access model.

The new model is intentionally narrow:

- authorize multiple Telegram `user_id` values
- only accept requests from direct private chats with the bot
- keep authorization static through environment configuration
- dedupe downloads per user instead of globally
- preserve backward compatibility for deployments that still use the old single-chat setting

This is an access-control and task-ownership change, not a broader product redesign.

## Goals

- Allow multiple approved Telegram users to use the bot.
- Restrict the new access model to private chats only.
- Keep deployment simple with static `.env` configuration.
- Preserve compatibility for current deployments that still use `TELEGRAM_ALLOWED_CHAT_ID`.
- Make dedupe behavior match user expectations by scoping it to each authorized user.
- Keep the current serial worker, queue, download flow, and notification model.

## Non-Goals

- No group-chat support in this phase.
- No runtime commands to add or remove users.
- No admin panel or database-managed user list.
- No per-user quotas, priorities, or rate limits.
- No task sharing across users for the same URL.
- No refactor of the worker or proxy runtime unrelated to access control.

## Current Problem

The current bot authorizes exactly one `chat_id` through `TELEGRAM_ALLOWED_CHAT_ID`.

That model is too narrow for the new requirement:

- it cannot authorize more than one person cleanly
- it treats access as chat-based instead of user-based
- it assumes a single allowed conversation
- dedupe is global by `source_url`, so one user's submission blocks another user's identical request within the dedupe window

The current persistence model also only stores `chat_id`, which means task ownership is not explicit at the user level.

## Recommended Design

### 1. Add Multi-user Authorization Through `TELEGRAM_ALLOWED_USER_IDS`

Introduce a new environment variable:

- `TELEGRAM_ALLOWED_USER_IDS`

Format:

- comma-separated integer Telegram `user_id` values
- example: `12345,67890,24680`

Parsing behavior:

- trim surrounding whitespace around each item
- reject empty items
- reject any non-integer value
- fail fast during configuration load if parsing fails

The configuration model should be:

- if `TELEGRAM_ALLOWED_USER_IDS` is set and non-empty, use the new multi-user authorization path
- otherwise, fall back to the legacy `TELEGRAM_ALLOWED_CHAT_ID` behavior

This keeps old deployments working while allowing new deployments to move to explicit user-based access.

### 2. Restrict the New Path to Private Chats

When the new multi-user configuration is active, only process messages that satisfy both rules:

- `message.chat.type == "private"`
- `message.from.id` is in the configured allowed user list

Messages that do not satisfy both rules should be ignored silently:

- group and supergroup messages
- channel messages
- private messages from users outside the whitelist

The reply path does not need a new abstraction. The bot can continue replying to the originating private `chat_id`.

### 3. Persist Explicit Task Ownership With `user_id`

Add `user_id` to the task model and SQLite schema.

Data model changes:

- `BotTask` gains `user_id: int | None`
- `tasks` table gains `user_id INTEGER`

New tasks created through the multi-user path must always store:

- `chat_id`
- `user_id`
- `telegram_message_id`
- `source_url`

Older rows may keep `user_id = NULL`.

This keeps migration simple while making task ownership explicit for all new submissions.

### 4. Change Dedupe Semantics to Per-user Dedupe

The current dedupe check is global by normalized `source_url`.

The new behavior should be:

- dedupe by `user_id + source_url` when the multi-user path is active
- preserve the current legacy dedupe behavior when the old single-chat path is active

Expected outcomes:

- the same authorized user submitting the same normalized URL within the dedupe window receives `Already queued`
- two different authorized users can submit the same normalized URL and each gets an independent task
- each user receives the terminal notification for their own task only

This matches the selected product requirement and avoids cross-user interference.

### 5. Keep the Existing Runtime Flow

Do not change:

- Telegram polling
- SQLite-backed queue
- single serial worker
- `/download/*` file serving
- proxy runtime and failover logic
- task completion and failure notification format

The only flow changes are at request admission and task creation time.

## Configuration Surface

### Required For Legacy Mode

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `PUBLIC_DOWNLOAD_BASE_URL`

### Required For Multi-user Mode

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`
- `PUBLIC_DOWNLOAD_BASE_URL`

### Compatibility Rule

- `TELEGRAM_ALLOWED_USER_IDS` takes precedence when present
- `TELEGRAM_ALLOWED_CHAT_ID` remains supported as a fallback only

### Documentation Changes

Update:

- `.env.example`
- `README.md`

The docs should present `TELEGRAM_ALLOWED_USER_IDS` as the preferred configuration and clearly mark `TELEGRAM_ALLOWED_CHAT_ID` as legacy compatibility.

## Storage Migration

The SQLite migration should stay incremental and startup-driven.

Migration behavior:

- inspect `PRAGMA table_info(tasks)`
- if `user_id` is missing, run `ALTER TABLE tasks ADD COLUMN user_id INTEGER`
- do not attempt a historical backfill

Reasons:

- older tasks only need `chat_id` to finish notification delivery
- historical rows do not need to participate in the new per-user dedupe semantics
- startup migration remains simple and safe for existing deployments

## Error Handling

### Configuration-time Failures

Configuration loading should fail when:

- `TELEGRAM_ALLOWED_USER_IDS` is set but contains invalid items
- both authorization modes are effectively absent

The effective missing-config rules become:

- multi-user mode requires a non-empty `TELEGRAM_ALLOWED_USER_IDS`
- legacy mode requires `TELEGRAM_ALLOWED_CHAT_ID`

Failing early is preferable to starting with ambiguous or overly permissive access control.

### Runtime Behavior

Ignored updates should remain silent:

- unauthorized users
- unsupported chat types in multi-user mode
- messages without URLs

No new Telegram error message flow is needed in this phase.

## Code Changes

### `bot/config.py`

- add `telegram_allowed_user_ids`
- parse `TELEGRAM_ALLOWED_USER_IDS`
- define the precedence and fallback behavior
- validate malformed user ID lists early

### `bot/service.py`

- branch access control between legacy mode and multi-user mode
- in multi-user mode, require private chat and allowed `from.id`
- pass `user_id` into task creation
- use per-user dedupe when multi-user mode is active

### `bot/models.py`

- add nullable `user_id` to `BotTask`

### `bot/store.py`

- migrate the database schema to include `user_id`
- extend `create_task(...)` to accept `user_id`
- extend row mapping to read `user_id`
- add a per-user duplicate lookup path

No changes are required to:

- worker execution
- proxy failover logic
- download server routing

## Testing

Add or update tests for:

- config parsing of valid `TELEGRAM_ALLOWED_USER_IDS`
- invalid user ID list formats
- precedence of `TELEGRAM_ALLOWED_USER_IDS` over `TELEGRAM_ALLOWED_CHAT_ID`
- private authorized user can queue a task
- unauthorized private user is ignored
- authorized user in non-private chat is ignored
- same user submitting the same URL is deduped
- different users submitting the same URL create separate tasks
- schema migration adds `user_id`
- old rows without `user_id` still load correctly

## Backward Compatibility

The upgrade should be safe for existing deployments:

- deployments that only set `TELEGRAM_ALLOWED_CHAT_ID` continue to work as before
- the new user-based behavior only activates when `TELEGRAM_ALLOWED_USER_IDS` is configured
- existing task rows remain valid
- reply routing remains based on stored `chat_id`

This gives operators a clean upgrade path without forcing an immediate migration of their `.env` files.
