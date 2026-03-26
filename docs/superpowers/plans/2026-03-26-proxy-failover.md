# Proxy Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dynamic VPN subscription node failover to MeTube so proxy or YouTube rate-limit failures switch to the next node, retry the failed task automatically, and preserve the active node across container restarts.

**Architecture:** Keep the existing single-container MeTube deployment but split the feature into reusable subscription parsing in `app/vpn.py`, persistent proxy-state and Xray lifecycle management in dedicated proxy modules, and download-side failover coordination in `app/ytdl.py`. The runtime continues to use one active proxy node at a time, with a container-wide generation counter and a serialized failover lock to prevent switch storms.

**Tech Stack:** Python 3.13, `asyncio`, `subprocess`, `json`, `hashlib`, `logging`, `unittest`, shell entrypoint scripting, Xray

---

## File Map

**Create:**
- `app/proxy_state.py` for persisted proxy state load/save and atomic JSON writes
- `app/proxy_runtime.py` for active-node selection, subscription refresh, and Xray process control
- `app/proxy_failover.py` for error classification and serialized node-switch coordination
- `tests/app/__init__.py` for app-test import bootstrap
- `tests/app/test_vpn.py` for subscription parsing and fingerprint tests
- `tests/app/test_proxy_state.py` for persisted state tests
- `tests/app/test_proxy_runtime.py` for node recovery and Xray lifecycle tests
- `tests/app/test_proxy_failover.py` for classifier and concurrency tests
- `tests/app/test_ytdl_failover.py` for download retry and generation-aware failover tests

**Modify:**
- `app/vpn.py` to parse all nodes, expose stable fingerprints, and stop assuming "first parseable node wins"
- `app/main.py` to initialize proxy runtime/failover objects and pass them into `DownloadQueue`
- `app/ytdl.py` to track proxy generations per task and requeue retryable failures after node switches
- `docker-entrypoint.sh` to stop owning Xray lifecycle and leave startup control to Python runtime while still exporting proxy env vars when `VPN_SUBSCRIPTION_URL` is present

### Task 1: Make VPN Subscription Parsing Reusable and Testable

**Files:**
- Modify: `app/vpn.py`
- Create: `tests/app/__init__.py`
- Create: `tests/app/test_vpn.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- a subscription containing multiple `vmess://` and `vless://` lines returns every parseable node in order
- each parsed node exposes a stable fingerprint that does not change when the subscription order changes
- invalid lines are skipped without aborting the whole subscription parse

```python
nodes = vpn.parse_subscription_nodes(raw_subscription)
assert [node["protocol"] for node in nodes] == ["vless", "vmess"]
assert vpn.node_fingerprint(nodes[0]) == vpn.node_fingerprint(reordered_nodes[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_vpn -v`
Expected: FAIL because `app/vpn.py` only exposes single-node bootstrap behavior and has no reusable multi-node parser or fingerprint helper

- [ ] **Step 3: Write minimal implementation**

Refactor `app/vpn.py` so the parsing logic is reusable without `sys.exit()` side effects:

```python
def parse_subscription_nodes(raw_data: str) -> list[dict]:
    ...

def node_fingerprint(node: dict) -> str:
    ...

def render_xray_config(node: dict) -> dict:
    ...
```

Keep the CLI entrypoint compatible, but make `main()` a thin wrapper over the reusable helpers instead of the primary API surface.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_vpn -v`
Expected: PASS

### Task 2: Add Persistent Proxy State Storage

**Files:**
- Create: `app/proxy_state.py`
- Create: `tests/app/test_proxy_state.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- proxy state is written atomically to `STATE_DIR/proxy_state.json`
- missing state files load as an empty/default state
- corrupted JSON falls back safely instead of crashing startup
- failed node cooldown metadata round-trips through disk

```python
state = load_proxy_state(state_path)
assert state.active_node_fingerprint is None
save_proxy_state(state_path, state)
assert load_proxy_state(state_path).generation == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_proxy_state -v`
Expected: FAIL because no persisted proxy-state module exists yet

- [ ] **Step 3: Write minimal implementation**

Create a focused state module with a small dataclass plus atomic write helpers:

```python
@dataclass(slots=True)
class ProxyState:
    active_node_fingerprint: str | None = None
    active_node_index_hint: int | None = None
    generation: int = 0
    failed_fingerprints: dict[str, dict[str, object]] = field(default_factory=dict)
```

Implement:
- `load_proxy_state(path)`
- `save_proxy_state(path, state)`
- JSON normalization for `subscription_url_hash`, timestamps, and cooldown metadata

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_proxy_state -v`
Expected: PASS

### Task 3: Add Active-Node Selection and Xray Runtime Management

**Files:**
- Create: `app/proxy_runtime.py`
- Modify: `app/vpn.py`
- Create: `tests/app/test_proxy_runtime.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- startup restores the previous active node by fingerprint even if the subscription order changes
- startup falls back to the next viable node when the previous node disappears
- cooled-down nodes are skipped during failover selection
- switching nodes rewrites the Xray config and bumps the runtime generation

```python
manager = ProxyRuntimeManager(...)
await manager.initialize()
assert manager.current_generation == 1
assert manager.active_node_fingerprint == expected_fingerprint
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_proxy_runtime -v`
Expected: FAIL because no runtime manager exists for state-aware node recovery or Xray lifecycle control

- [ ] **Step 3: Write minimal implementation**

Create a runtime manager that owns:
- subscription refresh
- persisted active-node resolution
- cooldown-aware next-node selection
- Xray start/restart

Representative API:

```python
class ProxyRuntimeManager:
    async def initialize(self) -> None: ...
    async def switch_to_next_node(self, *, reason: str) -> bool: ...
    def mark_current_node_failed(self, *, reason: str, now: float) -> None: ...
```

Use dependency injection for subprocess control in tests so the suite can assert config rewrites and generation changes without starting real Xray.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_proxy_runtime -v`
Expected: PASS

### Task 4: Add Conservative Error Classification and Serialized Failover Coordination

**Files:**
- Create: `app/proxy_failover.py`
- Create: `tests/app/test_proxy_failover.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- proxy/connectivity failures map to `switch_node`
- YouTube `429` and bot-check errors map to `switch_node`
- private/unavailable content maps to `final_fail`
- only one node switch occurs when two tasks fail concurrently on the same generation
- a task that fails on an old generation retries on the new generation without triggering another switch

```python
decision = classify_download_error("HTTP Error 429: Too Many Requests")
assert decision.action == "switch_node"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_proxy_failover -v`
Expected: FAIL because there is no classifier or failover coordinator yet

- [ ] **Step 3: Write minimal implementation**

Add:

```python
class FailoverDecision(NamedTuple):
    action: str
    reason: str

class ProxyFailoverCoordinator:
    async def handle_retryable_failure(self, *, task, error_text: str) -> str: ...
```

Implementation requirements:
- centralize string matching for retryable vs final errors
- guard node switching with one `asyncio.Lock`
- compare task generation against runtime generation before switching
- retry on the new generation when another task already switched

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_proxy_failover -v`
Expected: PASS

### Task 5: Wire Proxy Runtime Into Application Startup

**Files:**
- Modify: `app/main.py`
- Modify: `docker-entrypoint.sh`
- Test: `tests/app/test_proxy_runtime.py`

- [ ] **Step 1: Write the failing tests**

Extend runtime tests to prove:
- when `VPN_SUBSCRIPTION_URL` is absent, proxy runtime remains inert
- when `VPN_SUBSCRIPTION_URL` is present, the app initializes `ProxyRuntimeManager` before downloads begin
- startup exports proxy env vars without requiring `/etc/xray/config.json` to pre-exist

```python
manager = build_proxy_runtime(config, environ={})
assert manager is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_proxy_runtime -v`
Expected: FAIL because startup still depends on shell-side Xray bootstrap and does not create runtime-managed proxy objects

- [ ] **Step 3: Write minimal implementation**

Update `app/main.py` to:
- build proxy runtime/failover objects during startup
- initialize them before queue imports start
- inject them into `DownloadQueue`

Update `docker-entrypoint.sh` to:
- keep exporting `http_proxy`, `https_proxy`, and `no_proxy` when `VPN_SUBSCRIPTION_URL` is set
- stop generating Xray config and stop starting Xray in the shell layer

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_proxy_runtime -v`
Expected: PASS

### Task 6: Add Generation-Aware Download Retry and Node-Attempt Limits

**Files:**
- Modify: `app/ytdl.py`
- Create: `tests/app/test_ytdl_failover.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- new downloads record `proxy_generation_started`
- retryable failures call the failover coordinator instead of going straight to final `done`
- a switched task is requeued automatically on the new generation
- the same task is not retried twice on the same node fingerprint
- a task stops failover after trying 3 distinct nodes

```python
download.info.proxy_generation_started = 4
status = await queue._handle_failed_download(download)
assert status == "requeued"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.app.test_ytdl_failover -v`
Expected: FAIL because `DownloadInfo` has no proxy-generation metadata and failed downloads are immediately moved to `done`

- [ ] **Step 3: Write minimal implementation**

Extend `DownloadInfo` and `DownloadQueue` with:
- `proxy_generation_started`
- `failover_attempts`
- `attempted_node_fingerprints`

Refactor the failed-download path so `_post_download_cleanup()` asks the coordinator whether to:
- finalize failure
- retry on current generation
- switch node and requeue

Only move a failed task into `done` after failover policy says no more retries are allowed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.app.test_ytdl_failover -v`
Expected: PASS

### Task 7: Final Verification

**Files:**
- Verify: `app/vpn.py`
- Verify: `app/proxy_state.py`
- Verify: `app/proxy_runtime.py`
- Verify: `app/proxy_failover.py`
- Verify: `app/main.py`
- Verify: `app/ytdl.py`
- Verify: `docker-entrypoint.sh`
- Verify: `tests/app/test_vpn.py`
- Verify: `tests/app/test_proxy_state.py`
- Verify: `tests/app/test_proxy_runtime.py`
- Verify: `tests/app/test_proxy_failover.py`
- Verify: `tests/app/test_ytdl_failover.py`

- [ ] **Step 1: Run focused app tests**

Run: `python3 -m unittest tests.app.test_vpn tests.app.test_proxy_state tests.app.test_proxy_runtime tests.app.test_proxy_failover tests.app.test_ytdl_failover -v`
Expected: PASS

- [ ] **Step 2: Run app test discovery**

Run: `python3 -m unittest discover -s tests/app -v`
Expected: PASS

- [ ] **Step 3: Run syntax and entrypoint verification**

Run: `python3 -m py_compile app/*.py tests/app/*.py`
Expected: PASS

Run: `sh -n docker-entrypoint.sh`
Expected: PASS with no shell syntax errors

- [ ] **Step 4: Commit**

```bash
git add app/vpn.py app/proxy_state.py app/proxy_runtime.py app/proxy_failover.py app/main.py app/ytdl.py docker-entrypoint.sh tests/app/__init__.py tests/app/test_vpn.py tests/app/test_proxy_state.py tests/app/test_proxy_runtime.py tests/app/test_proxy_failover.py tests/app/test_ytdl_failover.py docs/superpowers/specs/2026-03-26-proxy-failover-design.md docs/superpowers/plans/2026-03-26-proxy-failover.md
git commit -m "feat: add proxy node failover for dynamic subscriptions"
```
