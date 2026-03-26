# Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Telegram bot runtime with configurable HTTP timeouts, wrapped integration exceptions, and basic operational logging without changing the existing bot flow.

**Architecture:** Keep the current polling-based bot design and `urllib` transport, but add one timeout setting shared by Telegram and MeTube clients, wrap transport/decode failures into bot-specific exceptions, and emit event-focused logs from the main loop and service layer.

**Tech Stack:** Python 3.12, `urllib`, `logging`, `unittest`

---

### Task 1: Add Timeout Configuration

**Files:**
- Modify: `bot/config.py`
- Modify: `.env.example`
- Test: `tests/bot/test_config.py`

- [ ] **Step 1: Write the failing test**

Add a test that:
- accepts `BOT_HTTP_TIMEOUT_SECONDS`
- defaults it when omitted
- rejects non-positive values

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: FAIL because the config model does not expose the new field yet

- [ ] **Step 3: Write minimal implementation**

Add `http_timeout_seconds` to `BotConfig`, parse `BOT_HTTP_TIMEOUT_SECONDS`, default it, and validate it is greater than zero. Add the example variable to `.env.example`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: PASS

### Task 2: Wrap Telegram and MeTube Transport Failures

**Files:**
- Modify: `bot/telegram_api.py`
- Modify: `bot/metube_client.py`
- Test: `tests/bot/test_telegram_api.py`
- Test: `tests/bot/test_metube_client.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving that:
- Telegram transport/decode failures raise `TelegramApiError`
- MeTube transport/decode failures raise `MeTubeApiError`

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_telegram_api tests.bot.test_metube_client -v`
Expected: FAIL because raw exceptions still escape

- [ ] **Step 3: Write minimal implementation**

Add timeout-aware request helpers and wrap `HTTPError`, `URLError`, `TimeoutError`, and JSON decode failures into the bot-specific exception classes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_telegram_api tests.bot.test_metube_client -v`
Expected: PASS

### Task 3: Add Runtime Logging

**Files:**
- Modify: `bot/main.py`
- Modify: `bot/service.py`
- Test: `tests/bot/test_main.py`
- Test: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving that:
- the main loop logs integration failures instead of silently swallowing them
- service-level timeout/completion/failure paths emit log records

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_main tests.bot.test_service -v`
Expected: FAIL because there is no logging behavior yet

- [ ] **Step 3: Write minimal implementation**

Initialize standard-library logging in the entrypoint and add targeted runtime log calls in the loop and service paths. Do not log secrets.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_main tests.bot.test_service -v`
Expected: PASS

### Task 4: Final Verification

**Files:**
- Verify: `bot/config.py`
- Verify: `bot/main.py`
- Verify: `bot/metube_client.py`
- Verify: `bot/service.py`
- Verify: `bot/telegram_api.py`
- Verify: `.env.example`

- [ ] **Step 1: Run focused tests**

Run: `python3 -m unittest tests.bot.test_config tests.bot.test_telegram_api tests.bot.test_metube_client tests.bot.test_main tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 2: Run full bot tests**

Run: `python3 -m unittest discover -s tests/bot -v`
Expected: PASS

- [ ] **Step 3: Run compile verification**

Run: `python3 -m py_compile bot/*.py tests/bot/*.py`
Expected: PASS

- [ ] **Step 4: Commit and push**

```bash
git add .env.example bot/config.py bot/main.py bot/metube_client.py bot/service.py bot/telegram_api.py tests/bot/test_config.py tests/bot/test_main.py tests/bot/test_metube_client.py tests/bot/test_service.py tests/bot/test_telegram_api.py docs/superpowers/specs/2026-03-25-runtime-hardening-design.md docs/superpowers/plans/2026-03-25-runtime-hardening.md
git commit -m "feat: harden bot runtime networking"
git push origin runtime-hardening
```
