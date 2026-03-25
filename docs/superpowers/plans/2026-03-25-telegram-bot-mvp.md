# Telegram Bot MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user Telegram bot that submits URLs to a remote MeTube instance, persists task state in SQLite, polls MeTube history, and replies with a direct download URL or failure message.

**Architecture:** Add a separate `bot/` Python package inside this repository. The bot will use raw Telegram Bot API calls over the Python standard library HTTP stack, reuse MeTube’s existing HTTP endpoints (`/add` and `/history`), and keep local durable state in SQLite. The implementation stays independent from the existing MeTube web UI and backend download code.

**Tech Stack:** Python 3.12+, `sqlite3`, `asyncio`, `urllib.request`, MeTube HTTP API, Telegram Bot HTTP API, `unittest`

---

## File Structure

### New files

- `bot/__init__.py`
  - package marker for the Telegram bot modules
- `bot/config.py`
  - environment-driven configuration loader and validation
- `bot/models.py`
  - shared dataclasses and task-state constants
- `bot/url_utils.py`
  - URL extraction and normalization helpers
- `bot/metube_client.py`
  - authenticated client for MeTube `/add` and `/history`
- `bot/telegram_api.py`
  - low-level Telegram Bot API wrapper for polling and replies
- `bot/store.py`
  - SQLite-backed task persistence and state transitions
- `bot/service.py`
  - orchestration layer that ties Telegram, MeTube, polling, and persistence together
- `bot/main.py`
  - async entrypoint for running the bot loop
- `tests/bot/test_config.py`
  - configuration validation tests
- `tests/bot/test_url_utils.py`
  - URL extraction tests
- `tests/bot/test_metube_client.py`
  - MeTube client request and response mapping tests
- `tests/bot/test_store.py`
  - SQLite task-store behavior tests
- `tests/bot/test_service.py`
  - orchestration tests for submission, polling, success, failure, and dedupe

### Modified files

- `pyproject.toml`
  - add bot runtime/test dependencies and an executable script entry
- `README.md`
  - add a short “development status” note pointing to the new bot package when MVP lands

## Task 1: Establish the Bot Package and Test Baseline

**Files:**
- Create: `bot/__init__.py`
- Create: `tests/bot/test_config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing config test**

```python
from unittest import TestCase

from bot.config import BotConfig, load_config


class LoadConfigTests(TestCase):
    def test_load_config_requires_core_environment(self):
        with self.assertRaises(ValueError):
            load_config({})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot'` or missing `load_config`

- [ ] **Step 3: Write minimal package and config implementation**

```python
from dataclasses import dataclass


@dataclass(slots=True)
class BotConfig:
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    metube_base_url: str


def load_config(env: dict[str, str]) -> BotConfig:
    required = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "METUBE_BASE_URL")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    return BotConfig(
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"],
        telegram_allowed_chat_id=int(env["TELEGRAM_ALLOWED_CHAT_ID"]),
        metube_base_url=env["METUBE_BASE_URL"].rstrip("/"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: PASS

- [ ] **Step 5: Update packaging metadata**

Add to `pyproject.toml`:

```toml
[project.scripts]
metube-telegram-bot = "bot.main:main"
```

Keep the initial dependency list minimal. Do not add a Telegram framework.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml bot/__init__.py bot/config.py tests/bot/test_config.py
git commit -m "feat: add telegram bot config skeleton"
```

## Task 2: Implement URL Extraction and Dedupable Task Models

**Files:**
- Create: `bot/models.py`
- Create: `bot/url_utils.py`
- Create: `tests/bot/test_url_utils.py`

- [ ] **Step 1: Write the failing URL extraction tests**

```python
from unittest import TestCase

from bot.url_utils import extract_urls


class ExtractUrlsTests(TestCase):
    def test_extract_urls_returns_all_http_links(self):
        text = "one https://a.example/x two https://b.example/y"
        self.assertEqual(
            extract_urls(text),
            ["https://a.example/x", "https://b.example/y"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_url_utils -v`
Expected: FAIL because `extract_urls` does not exist

- [ ] **Step 3: Write minimal implementation**

Create simple task-state constants and URL extraction helper:

```python
import re

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return [match.group(0).rstrip(".,)") for match in URL_RE.finditer(text)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_url_utils -v`
Expected: PASS

- [ ] **Step 5: Add task model dataclasses**

Create `BotTask` and explicit state constants:

```python
STATE_RECEIVED = "received"
STATE_SUBMITTED = "submitted"
STATE_QUEUED = "queued"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_TIMEOUT = "timeout"
```

- [ ] **Step 6: Commit**

```bash
git add bot/models.py bot/url_utils.py tests/bot/test_url_utils.py
git commit -m "feat: add bot task models and url extraction"
```

## Task 3: Build the SQLite Task Store

**Files:**
- Create: `bot/store.py`
- Create: `tests/bot/test_store.py`

- [ ] **Step 1: Write the failing persistence test**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from bot.store import TaskStore


class TaskStoreTests(TestCase):
    def test_insert_and_reload_roundtrip(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)
            task_id = store.create_task(chat_id=1, telegram_message_id=10, source_url="https://a.example")
            reloaded = TaskStore(db_path)
            task = reloaded.get_task(task_id)
            self.assertEqual(task.source_url, "https://a.example")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_store -v`
Expected: FAIL because `TaskStore` does not exist

- [ ] **Step 3: Write minimal SQLite implementation**

Implement:

- schema creation on init
- `create_task`
- `get_task`
- `update_task_state`
- `find_recent_duplicate`
- `list_unfinished_tasks`
- `mark_notified`

Use only the standard library `sqlite3`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_store -v`
Expected: PASS

- [ ] **Step 5: Add second test for dedupe window**

Write one more failing test that proves identical URLs within the recent window are found as duplicates, then implement the minimal query.

- [ ] **Step 6: Run the store test module again**

Run: `python3 -m unittest tests.bot.test_store -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/store.py tests/bot/test_store.py
git commit -m "feat: add sqlite task store"
```

## Task 4: Build the MeTube API Client

**Files:**
- Create: `bot/metube_client.py`
- Create: `tests/bot/test_metube_client.py`

- [ ] **Step 1: Write the failing request-shape test**

```python
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from bot.metube_client import MeTubeClient


class MeTubeClientTests(IsolatedAsyncioTestCase):
    async def test_add_download_posts_expected_payload(self):
        session = AsyncMock()
        session.post.return_value.__aenter__.return_value.json = AsyncMock(return_value={"status": "ok"})
        client = MeTubeClient(session=session, base_url="https://metube.example", auth_header=("Authorization", "Bearer token"))
        await client.add_download("https://video.example/watch")
        session.post.assert_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_metube_client -v`
Expected: FAIL because `MeTubeClient` does not exist

- [ ] **Step 3: Write minimal implementation**

Implement:

- `add_download(url: str) -> dict`
- `fetch_history() -> dict`
- auth header injection
- stable defaults for `quality`, `format`, and `auto_start`

Do not hardcode proxy logic here. Keep it as plain HTTP over the Python standard library.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_metube_client -v`
Expected: PASS

- [ ] **Step 5: Add a failing history-mapping test**

Write one more test proving `fetch_history` returns a normalized structure with `queue`, `pending`, and `done` collections.

- [ ] **Step 6: Run the module again**

Run: `python3 -m unittest tests.bot.test_metube_client -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add bot/metube_client.py tests/bot/test_metube_client.py
git commit -m "feat: add metube api client"
```

## Task 5: Build the Telegram HTTP Wrapper

**Files:**
- Create: `bot/telegram_api.py`
- Create: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing polling/reply test**

Add a focused test that expects:

- unauthorized chat IDs are ignored
- valid chat messages trigger URL extraction
- the service sends an acknowledgment reply through the Telegram API wrapper

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL because `TelegramApi` and service orchestration do not exist

- [ ] **Step 3: Write minimal Telegram API wrapper**

Implement these methods only:

- `get_updates(offset: int | None) -> list[dict]`
- `send_message(chat_id: int, text: str) -> None`

Use direct calls to:

- `https://api.telegram.org/bot<TOKEN>/getUpdates`
- `https://api.telegram.org/bot<TOKEN>/sendMessage`

No webhook support in the MVP.

- [ ] **Step 4: Run the service test to verify the wrapper gap is closed**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL moves from missing wrapper to missing orchestration behavior

- [ ] **Step 5: Commit**

```bash
git add bot/telegram_api.py tests/bot/test_service.py
git commit -m "feat: add telegram api wrapper"
```

## Task 6: Implement the Bot Service Orchestration

**Files:**
- Create: `bot/service.py`
- Modify: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing submission-flow test**

Test this behavior:

- allowed chat sends one URL
- no recent duplicate exists
- store creates a task
- MeTube `add_download` is called
- Telegram acknowledgment is sent
- task state becomes `submitted`

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL on missing `BotService`

- [ ] **Step 3: Write minimal submission implementation**

Implement:

- message filtering by allowed chat ID
- URL extraction
- dedupe via `TaskStore.find_recent_duplicate`
- task creation
- MeTube submission
- acknowledgment reply

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 5: Write the failing completion-poll test**

Test this behavior:

- store has an unfinished task
- MeTube history reports a matching completed item
- `status == finished` produces a direct download link message
- task state becomes `finished`
- `notified_at` is set

- [ ] **Step 6: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL because polling/completion logic is missing

- [ ] **Step 7: Write minimal completion implementation**

Implement:

- polling over unfinished tasks
- exact URL match first
- `filename`-based link generation
- `PUBLIC_HOST_URL` / `PUBLIC_HOST_AUDIO_URL` selection
- failure handling when `status != finished`
- timeout transition for stale tasks

- [ ] **Step 8: Run service tests again**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add bot/service.py tests/bot/test_service.py
git commit -m "feat: implement telegram bot service flow"
```

## Task 7: Add the Entrypoint and End-to-End Smoke Verification

**Files:**
- Create: `bot/main.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing entrypoint import test**

Extend `tests.bot.test_config` or add a small smoke test that imports `bot.main` and asserts the module exposes a callable `main`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: FAIL because `bot.main` does not exist

- [ ] **Step 3: Write minimal async entrypoint**

Implement:

- config loading from `os.environ`
- `aiohttp.ClientSession`
- `TaskStore`
- `MeTubeClient`
- `TelegramApi`
- `BotService`
- simple loop: fetch updates, process messages, poll completions, sleep briefly

- [ ] **Step 4: Run the targeted test**

Run: `python3 -m unittest tests.bot.test_config -v`
Expected: PASS

- [ ] **Step 5: Run the full bot test suite**

Run: `python3 -m unittest discover -s tests/bot -v`
Expected: all bot tests PASS

- [ ] **Step 6: Update README with implementation status**

Add one short note that the bot package now exists under `bot/` and deployment instructions are still pending.

- [ ] **Step 7: Commit**

```bash
git add README.md bot/main.py tests/bot/test_config.py
git commit -m "feat: add telegram bot entrypoint"
```

## Task 8: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run repository-level Python checks**

Run: `python3 -m unittest discover -s tests/bot -v`
Expected: PASS

- [ ] **Step 2: Run a syntax check over the new bot package**

Run: `python3 -m py_compile bot/*.py`
Expected: PASS with no output

- [ ] **Step 3: Inspect git status**

Run: `git status --short`
Expected: clean working tree

- [ ] **Step 4: Prepare for branch-finish workflow**

After verification, use `superpowers:finishing-a-development-branch` before merging or pushing the feature branch.
