# Runtime Hardening for Telegram Bot MVP

## Summary

Harden the current Telegram bot MVP so transient network issues and slow upstreams do not silently kill or stall the process. The first batch focuses on three changes only: configurable HTTP timeouts, exception wrapping for outbound Telegram and MeTube calls, and standard-library logging that surfaces runtime failures in `systemd` and `journalctl`.

This batch keeps the current architecture, polling model, and `urllib`-based implementation. It does not add retries, offset persistence, or any database schema changes.

## Goals

- Prevent raw network exceptions from crashing the bot loop.
- Ensure outbound HTTP calls to Telegram and MeTube have an explicit timeout.
- Convert low-level transport and JSON decode failures into `TelegramApiError` and `MeTubeApiError`.
- Emit runtime logs to stdout/stderr so `journalctl -u metube-telegram-bot -f` shows operational failures.
- Preserve the existing bot behavior for successful flows.

## Non-Goals

- Automatic retries.
- Telegram update offset persistence across restarts.
- Database migrations or schema changes.
- Switching from `urllib` to another HTTP client.
- Expanded bot commands or multi-user behavior.

## Current Problems

### Unbounded HTTP waits

Current outbound requests call `urllib.request.urlopen()` without a timeout. A stalled upstream can block Telegram polling, MeTube history checks, or message delivery indefinitely.

### Raw transport exceptions

The bot loop only catches `BotIntegrationError`, but the HTTP adapters currently let raw `HTTPError`, `URLError`, socket timeout, and JSON decode exceptions escape. In production this can terminate the process instead of allowing the service loop to continue.

### Missing runtime visibility

The current code swallows many integration errors silently. When the bot stops processing updates, there is no structured indication of whether Telegram, MeTube, or message delivery failed.

## Recommended Design

### Configuration

Add one new runtime setting:

- `BOT_HTTP_TIMEOUT_SECONDS`

Behavior:

- default to a conservative positive value suitable for polling-based integrations
- validate that the value is greater than zero
- expose it in `.env.example`

This setting applies to both Telegram and MeTube HTTP calls so the runtime has one simple knob for network latency tuning.

### Client Error Wrapping

#### Telegram API client

Wrap these failure classes inside `TelegramApiError`:

- `urllib.error.HTTPError`
- `urllib.error.URLError`
- `TimeoutError`
- `json.JSONDecodeError`
- other unexpected request-time exceptions that represent transport failure

The wrapped message should preserve enough detail for logs, such as endpoint purpose and upstream error text.

#### MeTube client

Wrap the same transport and decode failures inside `MeTubeApiError`.

This ensures the bot loop can treat integration faults consistently without depending on `urllib` internals.

### Logging

Use Python’s standard `logging` module only.

Runtime behavior:

- initialize logging once in the main entrypoint
- log to stdout/stderr so `systemd` captures it automatically
- keep the default format simple and readable for `journalctl`

Required log points:

- bot startup with key runtime settings that are safe to expose
- Telegram polling failure
- update handling failure
- MeTube history polling failure
- Telegram send failure
- MeTube submission failure
- task timeout
- task completion
- task failure

Sensitive values such as bot token or auth header value must never be logged.

### Main Loop Behavior

Keep the current non-fatal service strategy:

- if Telegram polling fails for one iteration, log and continue
- if processing one update fails, log and continue to the next update
- if MeTube history polling fails for one iteration, log and continue

This batch improves observability and containment, not control flow semantics.

## Testing Strategy

### Unit Tests

- config parsing accepts and validates `BOT_HTTP_TIMEOUT_SECONDS`
- Telegram client wraps transport/decode exceptions into `TelegramApiError`
- MeTube client wraps transport/decode exceptions into `MeTubeApiError`
- main loop logs integration failures while continuing execution

### Manual Validation

1. Start the bot under `systemd`.
2. Confirm startup logs appear in `journalctl`.
3. Temporarily point one upstream call at an invalid host or inject a failing config in local testing.
4. Confirm the bot logs the failure instead of exiting.
5. Restore valid config and confirm normal queued/completed flow still works.

## Risks

- Logging too much can make `journalctl` noisy, so logs should stay event-focused.
- Timeout defaults that are too aggressive could increase false negatives in slow networks.
- Broad exception wrapping must preserve enough error text to remain debuggable.

## Future Follow-Ups

- add bounded retries for selected network errors
- persist Telegram update offset in SQLite
- add task-level correlation identifiers instead of URL-only matching
- consider structured JSON logs if operational needs increase
