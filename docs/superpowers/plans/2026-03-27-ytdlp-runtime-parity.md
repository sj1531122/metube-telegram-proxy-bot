# yt-dlp Runtime Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the minimum runtime-parity features needed to make the single-container bot behave much closer to a practical local `yt-dlp` install for single-video downloads.

**Architecture:** Keep the current Telegram queue, SQLite store, single worker, and proxy failover model unchanged. Isolate the work to configuration parsing, `yt-dlp` command construction, container dependencies, and operator-facing docs so the deployment gains `Deno`, optional cookies, optional passthrough args, and explicit `--no-playlist` without redesigning the runtime.

**Tech Stack:** Python 3.13, `asyncio`, `sqlite3`, `aiohttp`, `yt-dlp`, `ffmpeg`, `Deno`, Docker Compose, `unittest`

---

## File Map

**Create:**
- None

**Modify:**
- `bot/config.py` to parse new runtime-parity settings and validate them early
- `bot/download_executor.py` to always force single-video mode and append cookies / extra args / proxy in the correct order
- `Dockerfile` to install `Deno` into the production image
- `.env.example` to document `COOKIES_FILE` and `YTDLP_EXTRA_ARGS`
- `docker-compose.yml` to show the optional cookies mount pattern
- `README.md` to document the parity upgrade and deployment examples
- `tests/bot/test_config.py` to cover cookies-file and extra-args parsing behavior
- `tests/bot/test_download_executor.py` to cover `--no-playlist`, cookies, and extra args

## Task 1: Extend Configuration Tests for Runtime-Parity Inputs

**Files:**
- Modify: `tests/bot/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- `COOKIES_FILE` is optional and defaults to `None`
- `YTDLP_EXTRA_ARGS` is optional and defaults to an empty tuple
- `PUBLIC_DOWNLOAD_BASE_URL` still works as before
- `COOKIES_FILE` must point to an existing file when set
- `YTDLP_EXTRA_ARGS` is parsed with shell-style splitting

Example assertions:

```python
config = load_config(
    {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_ALLOWED_CHAT_ID": "42",
        "PUBLIC_DOWNLOAD_BASE_URL": "https://downloads.example.com/download",
        "YTDLP_EXTRA_ARGS": "--format bv*+ba/b --referer https://example.com",
    }
)

assert config.cookies_file is None
assert config.ytdlp_extra_args == (
    "--format",
    "bv*+ba/b",
    "--referer",
    "https://example.com",
)
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_config -v`
Expected: FAIL because `BotConfig` and `load_config()` do not expose `cookies_file` or `ytdlp_extra_args` yet

- [ ] **Step 3: Write the minimal configuration implementation**

Update `bot/config.py` so `BotConfig` includes:

```python
cookies_file: str | None = None
ytdlp_extra_args: tuple[str, ...] = ()
```

Implementation requirements:
- normalize `PUBLIC_DOWNLOAD_BASE_URL` exactly as today
- parse `YTDLP_EXTRA_ARGS` with `shlex.split`
- keep `COOKIES_FILE` optional
- reject non-existent cookies files with `ValueError`
- preserve all existing config fields and validation rules

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/bot/test_config.py
git commit -m "feat: add runtime parity config options"
```

## Task 2: Extend Executor Tests for Single-Video Mode, Cookies, and Extra Args

**Files:**
- Modify: `tests/bot/test_download_executor.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- `--no-playlist` is always present
- `--cookies <path>` is present only when `cookies_file` is provided
- extra args are appended before the final source URL
- existing proxy behavior still works when a proxy URL is passed

Example assertions:

```python
command = list(calls[0][0])
assert "--no-playlist" in command
assert command[-1] == "https://video.example/watch"

cookies_index = command.index("--cookies")
assert command[cookies_index + 1] == "/run/secrets/cookies.txt"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_download_executor -v`
Expected: FAIL because `run_download()` does not yet add `--no-playlist`, cookies, or configurable extra args

- [ ] **Step 3: Write the minimal executor implementation**

Update `bot/download_executor.py` so `run_download()` accepts:

```python
cookies_file: str | None = None
extra_args: tuple[str, ...] = ()
```

Command construction requirements:
- always add `--no-playlist`
- keep the current `--print` and output template behavior
- add `--cookies` only when `cookies_file` is provided
- add `--proxy` only when `proxy_url` is provided
- append `extra_args` before the final URL

Do not change stdout parsing or timeout behavior in this task.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_download_executor -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/download_executor.py tests/bot/test_download_executor.py
git commit -m "feat: extend yt-dlp executor for parity flags"
```

## Task 3: Thread New Executor Inputs Through the Worker Without Changing Retry Semantics

**Files:**
- Modify: `bot/worker.py`
- Test: `tests/bot/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Add or update worker tests so they prove:
- the worker passes `config.cookies_file` into the download runner
- the worker passes `config.ytdlp_extra_args` into the download runner
- retry and failover state transitions remain unchanged

Example assertion shape:

```python
download_runner.assert_awaited_once_with(
    source_url=task.source_url,
    download_dir=config.download_dir,
    proxy_url="http://127.0.0.1:10809",
    cookies_file="/run/secrets/cookies.txt",
    extra_args=("--format", "bv*+ba/b"),
    timeout_seconds=config.task_timeout_seconds,
)
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.bot.test_worker -v`
Expected: FAIL because the worker does not yet thread `cookies_file` or `extra_args` through to `run_download()`

- [ ] **Step 3: Write the minimal worker implementation**

Update the `run_download()` call in `bot/worker.py` to pass:
- `cookies_file=self.config.cookies_file`
- `extra_args=self.config.ytdlp_extra_args`

Do not change:
- same-node retry delays
- node-switch limits
- download URL construction
- task state transitions

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.bot.test_worker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/worker.py tests/bot/test_worker.py
git commit -m "refactor: pass runtime parity inputs to worker downloads"
```

## Task 4: Add Deno to the Production Image and Update Operator-Facing Config Examples

**Files:**
- Modify: `Dockerfile`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write the failing checks**

Define lightweight checks for:
- `Dockerfile` installs `Deno >= 2`
- `.env.example` documents `COOKIES_FILE` and `YTDLP_EXTRA_ARGS`
- `docker-compose.yml` demonstrates the optional cookies mount pattern without making it mandatory

Use shell verification rather than new unit tests:

```bash
git grep -n "COOKIES_FILE" .env.example docker-compose.yml
git grep -n "deno" Dockerfile
```

- [ ] **Step 2: Run the checks to verify the current state is missing them**

Run: `git grep -n "COOKIES_FILE" .env.example docker-compose.yml`
Run: `git grep -n "deno" Dockerfile`
Expected: no matches or missing required lines

- [ ] **Step 3: Write the minimal image and config updates**

`Dockerfile` requirements:
- install `Deno` in the image
- keep existing `ffmpeg`, `xray`, and Python dependency setup
- avoid introducing a full Node.js toolchain

`.env.example` requirements:
- add `COOKIES_FILE=`
- add `YTDLP_EXTRA_ARGS=`
- explain that `COOKIES_FILE` is optional and must be mounted into the container

`docker-compose.yml` requirements:
- keep a single `app` service
- keep existing `downloads` and `state` mounts
- add a commented optional cookies mount example or a clearly documented pattern

- [ ] **Step 4: Run the checks to verify the updates are present**

Run: `git grep -n "COOKIES_FILE" .env.example docker-compose.yml`
Run: `git grep -n "Deno\\|deno" Dockerfile`
Expected: matches show the new config and image dependency

- [ ] **Step 5: Build the production image**

Run: `docker build -t metube-direct-local .`
Expected: PASS with Deno included in the final image

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .env.example docker-compose.yml
git commit -m "build: add deno and parity deployment settings"
```

## Task 5: Update README for Runtime-Parity Deployment and Usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the doc gaps as a checklist**

The README update must explicitly cover:
- why YouTube may need Deno
- what `COOKIES_FILE` does
- what `YTDLP_EXTRA_ARGS` does
- that only single-video mode is supported and playlists are forced off
- how to mount `cookies.txt` in Compose
- three operating modes: baseline, parity, YouTube-fix minimum

- [ ] **Step 2: Update the README**

Add or revise sections so an operator can:
- rebuild the image after the Deno change
- run with no cookies
- run with mounted cookies
- pass manual `yt-dlp` tuning flags through `YTDLP_EXTRA_ARGS`

Keep the README aligned with actual code and Compose defaults.

- [ ] **Step 3: Review the README against the spec**

Verify:
- `README.md`
- `docs/superpowers/specs/2026-03-26-ytdlp-runtime-parity-design.md`
- `.env.example`

all describe the same behavior and variable names

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document yt-dlp runtime parity deployment"
```

## Final Verification

- [ ] **Step 1: Run the focused Python regression suite**

Run:

```bash
./.venv/bin/python -m unittest \
  tests.bot.test_config \
  tests.bot.test_download_executor \
  tests.bot.test_worker \
  tests.bot.test_main \
  -v
```

Expected: PASS

- [ ] **Step 2: Run the full repository test suite**

Run:

```bash
./.venv/bin/python -m unittest discover -t . -s tests -v
```

Expected: PASS

- [ ] **Step 3: Build the production image from scratch**

Run:

```bash
docker build -t metube-direct-local .
```

Expected: PASS with `Deno`, `ffmpeg`, `yt-dlp`, and `xray` available in the final image

- [ ] **Step 4: Smoke-check the new runtime surface**

Run:

```bash
docker compose up -d --build
docker compose logs --tail=200 app
```

Expected:
- the bot starts cleanly
- config validation fails fast if `COOKIES_FILE` is set to a missing path
- the application remains healthy when `COOKIES_FILE` is unset

- [ ] **Step 5: Manual functional verification**

Validate at least:
- one public YouTube single-video URL no longer fails with the JavaScript-runtime error
- one deployment with mounted cookies starts correctly
- one test run with `YTDLP_EXTRA_ARGS="--format bv*+ba/b"` changes the generated command as expected

- [ ] **Step 6: Commit the final verified state**

```bash
git add .
git commit -m "feat: add yt-dlp runtime parity support"
```
