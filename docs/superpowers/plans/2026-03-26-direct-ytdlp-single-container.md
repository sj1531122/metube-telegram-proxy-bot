# Direct yt-dlp Single-Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Telegram -> MeTube flow with one Python runtime that queues Telegram links, downloads with local `yt-dlp`, uses Xray-backed proxy failover, and returns a single `/download/...` URL from the same container.

**Architecture:** Keep the current Telegram polling and proxy runtime pieces, but move all download execution into the bot process. SQLite becomes the single source of truth for queue state, one background worker executes exactly one task at a time, `app/proxy_runtime.py` continues to own active node persistence, and a tiny `aiohttp` file server exposes completed files under `/download/*`.

**Tech Stack:** Python 3.13, `asyncio`, `aiohttp`, `sqlite3`, `subprocess`, `yt-dlp`, `ffmpeg`, Xray, Docker Compose, `unittest`

---

## File Map

**Create:**
- `app/__init__.py` to make proxy modules importable from `bot.*`
- `bot/download_executor.py` for local `yt-dlp` subprocess execution and result parsing
- `bot/download_server.py` for the minimal `/download/*` HTTP file server
- `bot/worker.py` for the single-task queue runner, retry policy, and proxy failover integration
- `tests/bot/test_download_executor.py` for executor command/result coverage
- `tests/bot/test_download_server.py` for safe file serving coverage
- `tests/bot/test_worker.py` for queue, retry, timeout, and node-switch coverage
- `docker-compose.yml` for the single-container deployment path

**Delete:**
- `bot/metube_client.py` because the new runtime no longer talks to remote MeTube
- `tests/bot/test_metube_client.py` because the remote client disappears with the old architecture

**Modify:**
- `app/proxy_failover.py` to add `retry_same_node` classification alongside `switch_node` and `final_fail`
- `app/proxy_runtime.py` to use package-safe imports from `app.*` so `bot.main` can reuse the runtime directly
- `bot/config.py` to remove MeTube-only variables and add local runtime paths and HTTP settings
- `bot/models.py` to switch from remote-reconciliation states to local execution states and persist retry/failover metadata
- `bot/store.py` to support runnable-task claiming, startup recovery, terminal notification sweeps, and local retry metadata
- `bot/service.py` to enqueue tasks locally and send notifications from SQLite terminal state instead of MeTube history
- `bot/main.py` to initialize proxy runtime, HTTP server, worker loop, and Telegram polling in one event loop
- `.env.example` to document the simplified environment variables
- `pyproject.toml` to remove MeTube UI/socket dependencies and keep only the direct-runtime dependencies
- `Dockerfile` to replace the MeTube/UI/Rust build pipeline with a lean Python + Xray + `yt-dlp` image
- `README.md` to document the new single-container architecture and deployment steps
- `tests/app/test_proxy_failover.py` to cover the new `retry_same_node` branch
- `tests/app/test_proxy_runtime.py` to cover package-safe imports and unchanged persisted node behavior
- `tests/bot/test_config.py` to cover the new environment contract
- `tests/bot/test_main.py` to cover bootstrap of proxy runtime, worker, and file server
- `tests/bot/test_service.py` to cover enqueue-only Telegram behavior and terminal notification flow
- `tests/bot/test_store.py` to cover the new SQLite schema and task-claim helpers

## Task 1: Make Proxy Modules Reusable From the Bot Runtime

**Files:**
- Create: `app/__init__.py`
- Modify: `app/proxy_failover.py`
- Modify: `app/proxy_runtime.py`
- Test: `tests/app/test_proxy_failover.py`
- Test: `tests/app/test_proxy_runtime.py`

- [ ] **Step 1: Write the failing tests**

Extend the existing proxy tests so they prove:
- `classify_download_error()` returns `retry_same_node` for transient non-node-specific failures such as `Read timed out` or `Temporary failure in name resolution`
- `classify_download_error()` still returns `switch_node` for node-invalid or rate-limit failures such as `HTTP Error 429`, `confirm you're not a bot`, or SOCKS handshake failures
- `app.proxy_runtime` is importable through package paths without relying on `sys.path` hacks

```python
decision = classify_download_error("Read timed out")
assert decision.action == "retry_same_node"

from app.proxy_runtime import ProxyRuntimeManager
assert ProxyRuntimeManager is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_proxy_failover tests.app.test_proxy_runtime -v`
Expected: FAIL because `retry_same_node` does not exist yet and `app/proxy_runtime.py` still imports `proxy_state`/`vpn` as top-level modules

- [ ] **Step 3: Write the minimal implementation**

Make `app` a real package and update imports:

```python
from app.proxy_state import ProxyState, load_proxy_state, save_proxy_state
from app import vpn
```

Expand the classifier so the worker can distinguish three outcomes:

```python
RETRY_SAME_NODE_PATTERNS = (
    "read timed out",
    "temporary failure",
    "remote end closed connection",
)
```

Do not change the persisted proxy-state behavior or node-selection rules in this task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_proxy_failover tests.app.test_proxy_runtime -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/proxy_failover.py app/proxy_runtime.py tests/app/test_proxy_failover.py tests/app/test_proxy_runtime.py
git commit -m "refactor: package proxy runtime for bot reuse"
```

## Task 2: Replace MeTube Config and SQLite Schema With Local Runtime State

**Files:**
- Modify: `bot/config.py`
- Modify: `bot/models.py`
- Modify: `bot/store.py`
- Test: `tests/bot/test_config.py`
- Test: `tests/bot/test_store.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- required variables become `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`, and `PUBLIC_DOWNLOAD_BASE_URL`
- optional variables include `VPN_SUBSCRIPTION_URL`, `DOWNLOAD_DIR`, `STATE_DIR`, `HTTP_BIND`, `HTTP_PORT`, `TASK_TIMEOUT_SECONDS`, `POLL_INTERVAL_SECONDS`
- new states are exactly `queued`, `downloading`, `retrying`, `finished`, `failed`, `timeout`
- SQLite persists local retry/failover fields such as `started_at`, `finished_at`, `next_retry_at`, `proxy_generation_started`, `failover_attempts`, and serialized attempted node fingerprints
- the store can claim the oldest runnable task atomically and recover stale `downloading` rows after restart

```python
task = store.claim_next_runnable_task(now=100.0)
assert task.state == STATE_DOWNLOADING

store.recover_inflight_tasks(now=200.0)
assert store.get_task(task.id).state == STATE_RETRYING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_config tests.bot.test_store -v`
Expected: FAIL because the current config still requires `METUBE_BASE_URL` and the task schema is still organized around `received/submitted`

- [ ] **Step 3: Write the minimal implementation**

Update config to this shape:

```python
@dataclass(slots=True)
class BotConfig:
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    public_download_base_url: str
    sqlite_path: str
    download_dir: str
    state_dir: str
    http_bind: str
    http_port: int
    http_timeout_seconds: int
    poll_interval_seconds: float
    task_timeout_seconds: int
    dedupe_window_seconds: int
```

Update `bot/models.py` and `bot/store.py` so the bot persists local execution state instead of remote MeTube reconciliation:

```python
STATE_QUEUED = "queued"
STATE_DOWNLOADING = "downloading"
STATE_RETRYING = "retrying"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_TIMEOUT = "timeout"
```

Store requirements:
- create tasks directly as `queued`
- keep `submitted_at` as the queue-entry timestamp
- add `started_at` and `finished_at`
- add `proxy_generation_started`
- add `failover_attempts`
- add JSON text storage for attempted node fingerprints
- add `claim_next_runnable_task(now)`
- add `list_pending_notifications()`
- add `recover_inflight_tasks(now)`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_config tests.bot.test_store -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py bot/models.py bot/store.py tests/bot/test_config.py tests/bot/test_store.py
git commit -m "feat: add local task state model"
```

## Task 3: Add Local yt-dlp Execution and Safe Download Serving

**Files:**
- Create: `bot/download_executor.py`
- Create: `bot/download_server.py`
- Test: `tests/bot/test_download_executor.py`
- Test: `tests/bot/test_download_server.py`

- [ ] **Step 1: Write the failing tests**

Add executor tests that prove:
- the subprocess command targets one output root and one `/download/*` URL space
- proxy-enabled runs add the local Xray HTTP proxy only when the runtime is active
- stdout parsing extracts the title and final relative filename
- non-zero exits preserve stderr text for retry classification
- timeout handling kills the subprocess and reports a timeout outcome

Add server tests that prove:
- `/download/<filename>` returns the file from `DOWNLOAD_DIR`
- nested relative paths such as `playlist/video.mp4` work
- traversal attempts such as `../../etc/passwd` are rejected

```python
result = await run_download(...)
assert result.filename == "movie.mp4"
assert result.title == "Movie"
assert result.error_text is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_download_executor tests.bot.test_download_server -v`
Expected: FAIL because the executor and file server modules do not exist yet

- [ ] **Step 3: Write the minimal implementation**

Implement a focused subprocess wrapper:

```python
@dataclass(slots=True)
class DownloadResult:
    ok: bool
    title: str | None
    filename: str | None
    error_text: str | None
    timed_out: bool = False
```

Recommended command shape:

```python
[
    "yt-dlp",
    "--no-progress",
    "--newline",
    "--print", "before_dl:TITLE:%(title)s",
    "--print", "after_move:FILEPATH:%(filepath)s",
    "-o", "%(title)s.%(ext)s",
    source_url,
]
```

Implement the download server with `aiohttp.web` and `FileResponse`, resolving every requested path against `DOWNLOAD_DIR` and rejecting anything that escapes the root.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_download_executor tests.bot.test_download_server -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/download_executor.py bot/download_server.py tests/bot/test_download_executor.py tests/bot/test_download_server.py
git commit -m "feat: add local download executor and file server"
```

## Task 4: Add the Single Serial Worker and Retry/Failover Policy

**Files:**
- Create: `bot/worker.py`
- Modify: `app/proxy_failover.py`
- Test: `tests/bot/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- the worker claims only one runnable task at a time
- a successful download marks the task `finished` with `title`, `filename`, `download_url`, and `finished_at`
- a transient same-node error marks the task `retrying` with a short backoff
- a switch-node error marks the current node failed, switches to the next viable node, increments failover metadata, and requeues the same task
- node switches stop after the bounded number of distinct nodes for one task
- total task timeout marks the task `timeout`

```python
await worker.run_one_task()
task = store.get_task(task_id)
assert task.state == STATE_RETRYING
assert task.failover_attempts == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_worker -v`
Expected: FAIL because there is no worker or local retry orchestration yet

- [ ] **Step 3: Write the minimal implementation**

Create a single-responsibility worker:

```python
class DownloadWorker:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def run_one_task(self) -> bool: ...
```

Worker rules:
- exactly one active task
- if no task is runnable, sleep for a short idle interval
- same-node retries use bounded fixed delays such as `(10, 30, 60)`
- switch-node retries happen immediately after a successful node switch
- distinct-node retries are capped, for example `3`
- use `PUBLIC_DOWNLOAD_BASE_URL.rstrip("/") + "/" + quote(filename, safe="/")`

Persist enough metadata for restart-safe behavior:
- `proxy_generation_started`
- `failover_attempts`
- attempted node fingerprints
- `next_retry_at`
- `last_error`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_worker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/worker.py app/proxy_failover.py tests/bot/test_worker.py
git commit -m "feat: add single-task worker with proxy failover"
```

## Task 5: Refactor BotService Into Telegram Ingress + Notification Sweep

**Files:**
- Modify: `bot/service.py`
- Test: `tests/bot/test_service.py`

- [ ] **Step 1: Write the failing tests**

Replace the MeTube-centric tests with local-runtime coverage:
- `handle_update()` extracts URLs, normalizes them, deduplicates them, creates `queued` tasks, and sends `Queued: <url>`
- unauthorized chats are ignored
- `poll_once()` sends terminal notifications for `finished`, `failed`, and `timeout` tasks that have not been notified yet
- finished messages use the stored `download_url`
- failed/timeouts are not re-sent once `notified_at` is set

```python
await service.poll_once()
assert telegram.messages == [(42, "Finished: Movie\nhttps://downloads.example.com/download/movie.mp4")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: FAIL because `bot/service.py` still submits to `MeTubeClient` and polls remote history

- [ ] **Step 3: Write the minimal implementation**

Remove the MeTube dependency entirely:

```python
class BotService:
    def __init__(self, *, config: BotConfig, store, telegram_api, time_fn=None):
        ...
```

Behavior changes:
- `handle_update()` only enqueues local work
- `poll_once()` only does local timeout/notification sweeping
- terminal messages come from SQLite state instead of remote `/history`

Keep URL normalization and dedupe behavior intact.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_service -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/service.py tests/bot/test_service.py
git commit -m "refactor: make bot service local-runtime only"
```

## Task 6: Bootstrap the Full Runtime in bot.main

**Files:**
- Modify: `bot/main.py`
- Delete: `bot/metube_client.py`
- Delete: `tests/bot/test_metube_client.py`
- Test: `tests/bot/test_main.py`

- [ ] **Step 1: Write the failing tests**

Add runtime-bootstrap tests that prove:
- `run_bot()` loads config, creates the store, Telegram API, proxy runtime, file server, and worker
- the proxy runtime initializes before the worker starts when `VPN_SUBSCRIPTION_URL` is present
- the update loop still advances Telegram offsets and keeps running when a single update handler fails
- the old MeTube client is no longer referenced anywhere in the runtime path

```python
with patch("bot.main.DownloadWorker") as worker_cls:
    await run_bot()
    worker_cls.return_value.start.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.bot.test_main -v`
Expected: FAIL because `bot/main.py` still builds `MeTubeClient` and has no file-server or worker bootstrap

- [ ] **Step 3: Write the minimal implementation**

Update startup flow to:
- create `TaskStore`
- recover inflight `downloading` tasks into retryable state
- build and initialize the optional proxy runtime
- start the `aiohttp` download server
- start the worker background task
- keep the existing Telegram polling loop and `service.poll_once()` notification sweep

Delete the unused remote client module and its tests in the same task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.bot.test_main -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/main.py tests/bot/test_main.py
git add -u bot/metube_client.py tests/bot/test_metube_client.py
git commit -m "feat: bootstrap direct yt-dlp runtime"
```

## Task 7: Simplify Packaging, Compose Deployment, and Docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write the failing tests or checks**

Add or update lightweight checks that prove:
- `load_config()` documentation matches the actual required environment
- the compose file starts exactly one app service with mounted download/state data
- the Docker build no longer references Angular UI, Rust, or MeTube assets

Use shell checks where a unit test is unnecessary:

```bash
python3 -m unittest tests.bot.test_config -v
docker build -t metube-direct-local .
```

- [ ] **Step 2: Run checks to verify they fail**

Run: `python3 -m unittest tests.bot.test_config -v`
Run: `docker build -t metube-direct-local .`
Expected: FAIL or build the wrong image because the current packaging still targets the MeTube web app

- [ ] **Step 3: Write the minimal implementation**

Trim dependencies to the new runtime:

```toml
dependencies = [
    "aiohttp",
    "yt-dlp[default,curl-cffi]",
]
```

Replace the Dockerfile with a lean image that installs:
- Python runtime
- `ffmpeg`
- `curl`
- `tini`
- Xray binary
- app code

Create a simple `docker-compose.yml` with:
- one `app` service
- `8081:8081`
- one mounted host directory for downloads
- one mounted host directory for state
- env-file support

Update docs to describe:
- `PUBLIC_DOWNLOAD_BASE_URL`
- `VPN_SUBSCRIPTION_URL`
- single `/download/*` path
- one-container deployment flow

- [ ] **Step 4: Run checks to verify they pass**

Run: `python3 -m unittest tests.bot.test_config tests.bot.test_main tests.bot.test_service tests.bot.test_store -v`
Run: `docker build -t metube-direct-local .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Dockerfile docker-compose.yml .env.example README.md
git commit -m "build: replace metube packaging with direct runtime"
```

## Final Verification

- [ ] **Step 1: Run the focused Python test suites**

Run:

```bash
python3 -m unittest \
  tests.app.test_proxy_failover \
  tests.app.test_proxy_runtime \
  tests.bot.test_config \
  tests.bot.test_download_executor \
  tests.bot.test_download_server \
  tests.bot.test_worker \
  tests.bot.test_service \
  tests.bot.test_store \
  tests.bot.test_main \
  -v
```

Expected: PASS

- [ ] **Step 2: Run repository-wide regression tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS

- [ ] **Step 3: Build the production container**

Run:

```bash
docker build -t metube-direct-local .
```

Expected: PASS without Angular, Rust, or MeTube build stages

- [ ] **Step 4: Smoke-test the local container**

Run:

```bash
docker compose up --build
```

Expected:
- the bot starts
- optional proxy runtime initializes when `VPN_SUBSCRIPTION_URL` is set
- `/download/*` is served from the mounted download directory

- [ ] **Step 5: Commit the final verified state**

```bash
git add .
git commit -m "feat: switch telegram bot to direct yt-dlp runtime"
```
