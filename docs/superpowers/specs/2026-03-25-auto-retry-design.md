# Automatic Retry for Transient MeTube Download Failures

## Summary

Add automatic retry handling to the personal Telegram bot so transient MeTube download failures caused by unstable proxy connectivity do not immediately become final Telegram failures.

The bot should detect a failed MeTube download, notify the user once that automatic retry has started, and then replay the equivalent of MeTube UI "Retry Failed" behavior up to five times. A successful retry should only send the final success message. A task should only become fully failed after all retry attempts are exhausted.

This design assumes the runtime hardening branch is already in place, so the bot has bounded HTTP timeouts, wrapped integration errors, and runtime logging.

## Goals

- Automatically retry MeTube download failures that are likely transient.
- Send one immediate Telegram notice when automatic retry begins.
- Limit retries to five automatic attempts after the initial failure.
- Avoid Telegram notification spam during repeated retry attempts.
- Mimic MeTube UI retry semantics closely enough to prevent old failed history entries from poisoning new attempts.
- Keep the feature scoped to the existing single-user, single-chat MVP.

## Non-Goals

- Multi-user retry policies.
- Adaptive retry logic based on provider-specific error parsing.
- Proxy pool switching or route failover.
- UI changes inside MeTube.
- Webhook migration.

## Current Problem

Today the bot treats the first MeTube `done` entry with `status != finished` as a terminal failure.

That is too aggressive for the user's real environment:

- the proxy is unstable
- a download may fail once for network reasons
- clicking MeTube UI "Retry Failed" often succeeds

The current bot therefore produces the wrong user-level behavior:

1. it sends a final failure too early
2. it stops tracking the task
3. recovery still requires manual MeTube intervention

## Key Observation About MeTube Retry

MeTube UI retry is not a special hidden recovery path. It effectively does two things:

1. submit the same source URL again through the normal add flow
2. clear the previous failed entry from the `done` collection

The bot should automate that behavior instead of waiting for an old failed record to recover on its own.

## Recommended Architecture

### Retry Policy

For each tracked bot task:

- initial download attempt happens normally
- after the first actual MeTube download failure, the bot enters automatic retry mode
- the bot retries up to 5 times
- the retry schedule uses fixed backoff:
  - retry 1: 30 seconds
  - retry 2: 60 seconds
  - retry 3: 120 seconds
  - retry 4: 300 seconds
  - retry 5: 600 seconds

This keeps recovery responsive while avoiding rapid queue churn during unstable network periods.

### Telegram Notification Rules

Notification policy should be intentionally sparse:

- initial submission success:
  - keep current `Queued: <url>` behavior
- first MeTube failure that triggers automatic retry:
  - send one message such as `Failed once, retrying automatically (1/5): <title or url>`
- intermediate retries 2 through 5:
  - no additional retry-progress Telegram messages
- final success after any retry:
  - keep current success message
- final failure after all retries:
  - send one final failure message with the last known reason

This matches the user's request to get immediate retry visibility without chat spam.

## Data Model Changes

Extend the local SQLite task record with retry-tracking fields:

- `retry_count`
  - how many automatic retries have already been submitted
- `max_retries`
  - fixed to 5 for the first version, but stored per task for future flexibility
- `next_retry_at`
  - UNIX timestamp for when the next retry may be submitted
- `retry_notice_sent_at`
  - timestamp indicating whether the one-time retry notice has already been sent
- `last_attempt_submitted_at`
  - timestamp of the latest add submission to MeTube
- `metube_done_id` or equivalent stable failed-entry key if available
  - optional optimization if a safe MeTube delete target can be derived

Add one new task state:

- `retrying`

Recommended local state list becomes:

- `received`
- `submitted`
- `queued`
- `retrying`
- `finished`
- `failed`
- `timeout`

## Runtime Flow

### Initial Submission

1. User sends a URL in Telegram.
2. Bot creates a local task.
3. Bot submits the URL to MeTube `POST /add`.
4. On success, state becomes `submitted`.
5. Bot replies `Queued: <url>`.

### Failure Detection

When polling MeTube history:

1. Bot finds the matching `done` entry for the current attempt.
2. If `status == finished`, the task completes normally.
3. If `status != finished`:
   - if retries remain:
     - update local task to `retrying`
     - increment retry intent state
     - schedule `next_retry_at`
     - send the one-time Telegram retry notice if it was not sent before
   - if retries do not remain:
     - mark the task `failed`
     - send final failure message

### Retry Execution

When polling local unfinished tasks:

1. If a task is in `retrying` and `next_retry_at <= now`, attempt a retry.
2. Retry action:
   - submit the same source URL to MeTube `POST /add`
   - if submission succeeds:
     - increment `retry_count`
     - set `last_attempt_submitted_at = now`
     - move state back to `submitted`
     - clear any stale retry scheduling fields
     - request MeTube `POST /delete` for the old failed `done` entry so history polling does not immediately rediscover the old failure
   - if retry submission itself fails:
     - stay in `retrying`
     - reschedule another retry attempt until `max_retries` is exhausted

### Final Failure

If all five retries have been attempted and no success has been observed:

- mark task `failed`
- preserve the last error text
- send one final Telegram failure message
- stop tracking the task as unfinished

## Matching and MeTube History Hygiene

### Why URL Matching Alone Is Insufficient

The current bot matches MeTube entries to local tasks by source URL only. That is acceptable for the MVP happy path, but it becomes unsafe during automatic retry because old failed `done` entries remain in MeTube history.

Without extra handling, the next poll after a retry submission could match the stale failed record again and immediately re-fail the task.

### Recommended Mitigation

Primary mitigation for this feature:

- after a retry is successfully re-submitted, call MeTube `POST /delete` with the failed `done` entry key so the stale failed record is removed

Secondary local tracking:

- store `last_attempt_submitted_at`
- treat retry scheduling and current local state as the source of truth for whether the bot is awaiting a new attempt result

This keeps the implementation aligned with existing MeTube UI retry semantics and avoids over-engineering speculative timestamp-based matching against data that MeTube history does not expose cleanly enough for the bot.

## Error Handling

### Retry Notice Send Failure

- log the Telegram failure
- let the main loop continue
- do not abandon the retry plan just because the retry notice could not be delivered

### Retry Submission Failure

- treat it as an integration failure for the retry attempt, not as a terminal download failure
- reschedule if retry budget remains

### Delete of Old Failed Entry Fails

- log the failure
- keep the task in retry flow
- if necessary, guard local logic so the same stale failed MeTube entry is not immediately reused as the current attempt result

This is the highest-risk edge case and should be covered by tests.

## Configuration

The first version can hardcode:

- `max_retries = 5`
- retry delays of `30, 60, 120, 300, 600` seconds

If later needed, expose them as environment variables, but that is not required for the first implementation.

## Testing Strategy

### Unit Tests

- failed MeTube result moves task to `retrying` instead of `failed` when retries remain
- first failure sends one retry notice
- later retry rounds do not send extra retry notices
- retry scheduler re-submits when `next_retry_at` is reached
- successful retry returns task to `submitted` and later to `finished`
- exhausted retries produce final failure
- old failed MeTube `done` entry is cleared after successful retry submission
- delete failure is logged and does not crash the loop

### Manual Validation

1. Trigger a proxy-sensitive download that often fails once.
2. Confirm the bot sends `Queued: ...`.
3. Confirm first failure produces one retry notice.
4. Confirm the bot automatically re-submits without manual UI interaction.
5. Confirm a later success produces the final download link.
6. Confirm repeated failures produce only one retry notice plus one final failure message.

## Risks

- If the old failed MeTube entry is not removed cleanly, the bot may still misclassify retries.
- Aggressive retries can increase queue pressure if the proxy is down for a long time.
- URL-only task identity remains a known weakness for repeated submissions of the same media.

## Future Extensions

- configurable retry schedule via `.env`
- provider-specific non-retriable error detection
- proxy pool failover
- persistent Telegram commands such as `/retry` or `/status`
