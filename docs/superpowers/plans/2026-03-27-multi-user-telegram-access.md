# Multi-user Telegram Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add private-chat multi-user Telegram access using a static `TELEGRAM_ALLOWED_USER_IDS` whitelist while keeping legacy `TELEGRAM_ALLOWED_CHAT_ID` deployments working.

**Architecture:** Keep the existing polling bot, SQLite queue, single worker, and notification flow unchanged. Isolate the work to configuration parsing, service-layer access control, task persistence, dedupe lookup, and operator-facing docs so the bot can admit multiple private users without redesigning the runtime.

**Tech Stack:** Python 3.13, `asyncio`, `sqlite3`, Telegram Bot API, Docker Compose, `unittest`

---

## File Map

**Create:**
- None

**Modify:**
- `bot/config.py` to parse `TELEGRAM_ALLOWED_USER_IDS`, keep legacy fallback behavior, and validate the access-control configuration
- `bot/models.py` to add nullable `user_id` ownership on persisted tasks
- `bot/store.py` to migrate the schema, persist `user_id`, and support per-user dedupe queries
- `bot/service.py` to switch admission control from single-chat gating to private-user gating when the new config is active
- `.env.example` to document `TELEGRAM_ALLOWED_USER_IDS` as the preferred configuration and retain the legacy variable note
- `README.md` to document the new private multi-user access model and compatibility rules
- `tests/bot/test_config.py` to cover parsing, precedence, and invalid whitelist formats
- `tests/bot/test_store.py` to cover `user_id` migration, round-tripping, and per-user dedupe semantics
- `tests/bot/test_service.py` to cover authorized private users, ignored unauthorized users, ignored group chats, and same-URL behavior across different users

**Keep Unchanged:**
- `bot/worker.py`
- `bot/download_executor.py`
- `bot/telegram_api.py`
- proxy runtime files under `app/`

## Task 1: Extend Configuration Tests for Multi-user Access

**Files:**
- Modify: `tests/bot/test_config.py`
- Modify: `bot/config.py`

- [ ] **Step 1: Write the failing tests**

Add config tests that prove:
- `TELEGRAM_ALLOWED_USER_IDS` parses into a tuple of integers
- surrounding whitespace is ignored for valid list items
- `TELEGRAM_ALLOWED_USER_IDS` takes precedence over `TELEGRAM_ALLOWED_CHAT_ID`
- invalid items such as `abc`, `1,,2`, or blank-only values raise `ValueError`
- legacy mode still works when only `TELEGRAM_ALLOWED_CHAT_ID` is provided

Example assertions:

```python
config = load_config(
    {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_ALLOWED_CHAT_ID": "42",
        "TELEGRAM_ALLOWED_USER_IDS": "101, 202 ,303",
        "PUBLIC_DOWNLOAD_BASE_URL": "https://downloads.example.com/download",
    }
)

assert config.telegram_allowed_user_ids == (101, 202, 303)
assert config.telegram_allowed_chat_id == 42
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_config -v`
Expected: FAIL because `BotConfig` and `load_config()` do not expose or validate `telegram_allowed_user_ids` yet

- [ ] **Step 3: Write the minimal configuration implementation**

Update `bot/config.py` so `BotConfig` includes:

```python
telegram_allowed_chat_id: int | None = None
telegram_allowed_user_ids: tuple[int, ...] = ()
```

Implementation requirements:
- keep `TELEGRAM_BOT_TOKEN` required
- accept either legacy chat mode or new user-list mode
- preserve the current `PUBLIC_DOWNLOAD_BASE_URL` / `METUBE_BASE_URL` validation
- parse `TELEGRAM_ALLOWED_USER_IDS` by splitting on commas and trimming whitespace
- reject empty or non-integer list entries with `ValueError`
- when no user list is configured, continue requiring `TELEGRAM_ALLOWED_CHAT_ID`

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/bot/test_config.py
git commit -m "feat: add multi-user telegram access config"
```

## Task 2: Extend Store and Model Tests for User Ownership and Per-user Dedupe

**Files:**
- Modify: `tests/bot/test_store.py`
- Modify: `bot/models.py`
- Modify: `bot/store.py`

- [ ] **Step 1: Write the failing tests**

Add store tests that prove:
- `create_task()` can persist a `user_id`
- reloaded tasks round-trip `user_id`
- old rows without `user_id` still load with `task.user_id is None`
- startup migration adds the `user_id` column when missing
- `find_recent_duplicate()` matches by `user_id + source_url`
- the same URL for a different user does not count as a duplicate

Example assertions:

```python
task_id = store.create_task(
    chat_id=1,
    user_id=101,
    telegram_message_id=10,
    source_url="https://a.example",
)

task = store.get_task(task_id)
assert task.user_id == 101

duplicate = store.find_recent_duplicate(
    user_id=101,
    source_url="https://a.example",
    within_seconds=300,
)
assert duplicate is not None

other_user_duplicate = store.find_recent_duplicate(
    user_id=202,
    source_url="https://a.example",
    within_seconds=300,
)
assert other_user_duplicate is None
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_store -v`
Expected: FAIL because the schema, model, and lookup helpers do not track `user_id` yet

- [ ] **Step 3: Write the minimal persistence implementation**

Update `bot/models.py`:

```python
user_id: int | None = None
```

Update `bot/store.py` so it:
- adds `user_id INTEGER` to the base `CREATE TABLE`
- migrates legacy databases with `ALTER TABLE tasks ADD COLUMN user_id INTEGER`
- accepts `user_id: int | None = None` in `create_task(...)`
- stores `user_id` on insert
- exposes `task.user_id` in `_row_to_task(...)`
- changes `find_recent_duplicate(...)` to accept `user_id` and filter by both `user_id` and `source_url`

Keep legacy compatibility by allowing `user_id` to stay `NULL` on old rows and by not forcing unrelated callers to backfill history.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_store -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/models.py bot/store.py tests/bot/test_store.py
git commit -m "refactor: persist telegram task user ownership"
```

## Task 3: Extend Service Tests for Private-user Admission Control

**Files:**
- Modify: `tests/bot/test_service.py`
- Modify: `bot/service.py`

- [ ] **Step 1: Write the failing tests**

Add service tests that prove:
- an authorized private user can queue a URL and gets `Queued`
- an unauthorized private user is ignored
- an authorized user in a group chat is ignored
- the same authorized user repeating the same URL gets `Already queued`
- two different authorized users submitting the same URL each get their own task and acknowledgement
- legacy chat-based mode still behaves as before when no user list is configured

Example assertion shapes:

```python
await service.handle_update(
    {
        "message": {
            "message_id": 1,
            "chat": {"id": 5001, "type": "private"},
            "from": {"id": 101},
            "text": "download https://video.example/watch",
        }
    }
)

tasks = store.list_unfinished_tasks()
assert len(tasks) == 1
assert tasks[0].user_id == 101
assert telegram.messages == [(5001, "Queued: https://video.example/watch")]
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_service -v`
Expected: FAIL because `BotService.handle_update()` only compares `chat_id` to `telegram_allowed_chat_id`

- [ ] **Step 3: Write the minimal service implementation**

Update `bot/service.py` with a small helper-based admission flow:

```python
def _multi_user_mode(self) -> bool:
    return bool(self.config.telegram_allowed_user_ids)
```

Implementation requirements:
- in multi-user mode, require `message.chat.type == "private"`
- in multi-user mode, require `message.from.id` to be in `config.telegram_allowed_user_ids`
- pass `user_id` into `store.create_task(...)`
- call per-user dedupe with `user_id`
- keep silent ignore behavior for unauthorized or unsupported updates
- preserve current legacy chat-based gating when the user list is empty

Keep terminal notifications routed by `task.chat_id`; no new notification model is needed.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/service.py tests/bot/test_service.py
git commit -m "feat: add private multi-user telegram access"
```

## Task 4: Update Operator-facing Documentation and Example Configuration

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Define the checks**

Use simple text checks to prove the docs reflect the new model:

```bash
git grep -n "TELEGRAM_ALLOWED_USER_IDS\\|TELEGRAM_ALLOWED_CHAT_ID" -- .env.example README.md
git grep -n "private" -- README.md
```

The docs must show:
- `TELEGRAM_ALLOWED_USER_IDS` as the preferred setting
- `TELEGRAM_ALLOWED_CHAT_ID` as legacy compatibility
- private-chat-only behavior in multi-user mode
- per-user dedupe semantics at a high level

- [ ] **Step 2: Run the checks to verify the current docs are missing the new behavior**

Run: `git grep -n "TELEGRAM_ALLOWED_USER_IDS\\|TELEGRAM_ALLOWED_CHAT_ID" -- .env.example README.md`
Expected: only the legacy variable is documented today

- [ ] **Step 3: Write the minimal doc updates**

`.env.example` requirements:
- add `TELEGRAM_ALLOWED_USER_IDS=123456789,987654321`
- keep `TELEGRAM_ALLOWED_CHAT_ID=` with a comment that it is legacy compatibility

`README.md` requirements:
- update the product summary from "one allowed chat" to "multiple allowed private users"
- update the environment-variable section to describe precedence
- update the quick-start example to show `TELEGRAM_ALLOWED_USER_IDS`
- note that group chats are ignored in the new mode

Do not document dynamic admin commands or any group-chat support.

- [ ] **Step 4: Run the checks to verify the updates are present**

Run: `git grep -n "TELEGRAM_ALLOWED_USER_IDS\\|TELEGRAM_ALLOWED_CHAT_ID" -- .env.example README.md`
Run: `git grep -n "private" -- README.md`
Expected: matches show the new variable, the legacy note, and the private-chat restriction

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document multi-user telegram access"
```

## Task 5: Run Cross-file Verification and Prepare the Branch for Review

**Files:**
- Test: `tests/bot/test_config.py`
- Test: `tests/bot/test_store.py`
- Test: `tests/bot/test_service.py`

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
./.venv/bin/python -m unittest \
  tests.bot.test_config \
  tests.bot.test_store \
  tests.bot.test_service -v
```

Expected: PASS

- [ ] **Step 2: Run the full unit-test suite**

Run: `./.venv/bin/python -m unittest -v`
Expected: PASS with no regressions outside the access-control changes

- [ ] **Step 3: Inspect the diff before the final commit or handoff**

Run:

```bash
git status --short
git diff --stat
```

Expected:
- only the planned files are modified
- no accidental changes to worker, proxy, or download execution files

- [ ] **Step 4: Commit any remaining verification or fixture adjustments**

If verification required small follow-up edits:

```bash
git add <updated-files>
git commit -m "test: finalize multi-user access coverage"
```

If no further edits were needed, explicitly record that no final cleanup commit was necessary.

- [ ] **Step 5: Summarize the result for review**

Capture:
- which configuration mode was implemented
- which tests were run
- whether legacy `TELEGRAM_ALLOWED_CHAT_ID` mode still passed
- any remaining manual deployment verification still worth doing after merge
