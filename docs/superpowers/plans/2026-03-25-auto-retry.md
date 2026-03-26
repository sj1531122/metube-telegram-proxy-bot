# Automatic Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic retry handling for transient MeTube download failures so the Telegram bot retries failed downloads up to five times, sends one retry notice, and only sends a final failure after the retry budget is exhausted.

**Architecture:** Extend local task persistence with retry-tracking fields and a `retrying` state, add a MeTube client method for clearing stale failed `done` entries, and implement a retry scheduler in the bot service that simulates MeTube UI "Retry Failed" behavior. The service remains polling-based and keeps Telegram notifications intentionally sparse.

**Tech Stack:** Python 3.12, SQLite, `urllib`, `logging`, `unittest`

---

### Task 1: Extend Task Model and SQLite Schema for Retry Tracking

**Files:**
- Modify: `bot/models.py`
- Modify: `bot/store.py`
- Test: `tests/bot/test_store.py`

- [ ] **Step 1: Write the failing tests**

Add store tests proving that:
- tasks persist retry metadata fields
- existing databases are migrated in place with new columns
- `retrying` is treated as unfinished

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_store -v`
Expected: FAIL because the task model and schema do not include retry fields or the `retrying` state yet

- [ ] **Step 3: Write minimal implementation**

Update the task model and store layer to add:
- `STATE_RETRYING`
- `retry_count`
- `max_retries`
- `next_retry_at`
- `retry_notice_sent_at`
- `last_attempt_submitted_at`

Add schema migration logic in `TaskStore._init_db()` using `PRAGMA table_info(tasks)` plus `ALTER TABLE` so existing deployed SQLite files are upgraded without deleting data.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_store -v`
Expected: PASS

### Task 2: Add MeTube Done-Entry Clearing Support

**Files:**
- Modify: `bot/metube_client.py`
- Test: `tests/bot/test_metube_client.py`

- [ ] **Step 1: Write the failing tests**

Add client tests proving that:
- the bot can call MeTube `POST /delete` for `where=done`
- transport and decode failures for delete are wrapped in `MeTubeApiError`

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_metube_client -v`
Expected: FAIL because no delete helper exists yet

- [ ] **Step 3: Write minimal implementation**

Add a `clear_done_entries(ids: list[str])` helper in `MeTubeClient` that:
- posts to `POST /delete`
- sends `{"where": "done", "ids": ids}`
- uses the same timeout and exception wrapping conventions as the other client methods

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_metube_client -v`
Expected: PASS

### Task 3: Add Retry Policy and State Machine to the Bot Service

**Files:**
- Modify: `bot/service.py`
- Test: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing tests**

Add service tests proving that:
- first download failure moves a task to `retrying` instead of `failed` when retries remain
- the first failure sends exactly one retry notice
- repeated failures do not send additional retry notices
- retryable tasks are resubmitted when `next_retry_at` is reached
- a successful retry submission resets the task to `submitted`
- exhausted retries produce the final failure notification

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL because the current service immediately finalizes failed done entries

- [ ] **Step 3: Write minimal implementation**

Add a retry policy in `BotService` with fixed delays:
- `30, 60, 120, 300, 600` seconds

Implement:
- first-failure retry notice: `Failed once, retrying automatically (1/5): ...`
- scheduling via `next_retry_at`
- resubmission via `metube_client.add_download()`
- retry bookkeeping updates in the store
- final failure after 5 retries

Do not add per-retry Telegram spam beyond the first retry notice.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: PASS

### Task 4: Prevent Stale Failed History from Poisoning Retries

**Files:**
- Modify: `bot/service.py`
- Test: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving that:
- after a retry is successfully re-submitted, the bot clears the stale failed MeTube `done` entry by URL
- a delete failure is logged and does not crash the service loop
- the task is not immediately re-failed by the same old done entry once retry flow begins

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL because stale failed history is not cleared yet

- [ ] **Step 3: Write minimal implementation**

In the retry execution path:
- call `clear_done_entries([task.source_url])` after successful retry submission
- log but do not crash if the delete call fails
- ensure retrying tasks only treat a newly observed MeTube failure as current work, not the stale failure that triggered the retry

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: PASS

### Task 5: Final Verification

**Files:**
- Verify: `bot/models.py`
- Verify: `bot/store.py`
- Verify: `bot/metube_client.py`
- Verify: `bot/service.py`
- Verify: `tests/bot/test_store.py`
- Verify: `tests/bot/test_metube_client.py`
- Verify: `tests/bot/test_service.py`

- [ ] **Step 1: Run focused tests**

Run: `python3 -m unittest tests.bot.test_store tests.bot.test_metube_client tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 2: Run full bot tests**

Run: `python3 -m unittest discover -s tests/bot -v`
Expected: PASS

- [ ] **Step 3: Run compile verification**

Run: `python3 -m py_compile bot/*.py tests/bot/*.py`
Expected: PASS

- [ ] **Step 4: Commit and push**

```bash
git add bot/models.py bot/store.py bot/metube_client.py bot/service.py tests/bot/test_store.py tests/bot/test_metube_client.py tests/bot/test_service.py docs/superpowers/plans/2026-03-25-auto-retry.md
git commit -m "feat: add automatic retry for failed downloads"
git push origin auto-retry
```
