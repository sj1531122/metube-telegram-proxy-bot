# Direct yt-dlp Single-Container Design

## Summary

Replace the current `Telegram bot -> MeTube API -> MeTube worker` deployment with a single Docker container that runs:

- Telegram polling
- SQLite task persistence
- a single serial download worker that invokes `yt-dlp` directly
- Xray-based proxy runtime backed by `VPN_SUBSCRIPTION_URL`
- a lightweight HTTP file server that exposes completed files under `/download/*`

This removes the MeTube UI, MeTube API, Angular build, and heavyweight MeTube image construction path while preserving the user's required behavior:

- single-user Telegram submission flow
- direct download links returned to Telegram
- proxy support from dynamic subscription URLs
- automatic node switching on matched proxy/rate-limit failures
- persistence across container restarts

## Goals

- Preserve Telegram-driven download submission and notification flow.
- Preserve proxy runtime support driven by `VPN_SUBSCRIPTION_URL`.
- Preserve automatic node switching based on matched download failures.
- Preserve restart-safe state for active node and failed-node cooldowns.
- Simplify deployment to one Docker image and one container.
- Serve all completed files from a single `/download/*` URL space.
- Enforce single-task execution with queueing for later tasks.

## Non-Goals

- No web UI.
- No MeTube-compatible API surface.
- No parallel download execution.
- No separate audio download directory or URL space.
- No multi-user or multi-chat support.
- No webhook mode in this phase.

## Recommended Architecture

The container runs one Python application as PID 1. That application owns all business logic and manages subordinate processes where needed.

### Runtime Responsibilities

The main process is responsible for:

- polling Telegram updates
- validating and enqueueing URLs
- persisting task state in SQLite
- driving one serial download worker
- initializing and controlling Xray when `VPN_SUBSCRIPTION_URL` is configured
- serving completed files from `/download/*`

### Internal Components

#### 1. Telegram Ingress

Receives updates, enforces `TELEGRAM_ALLOWED_CHAT_ID`, extracts URLs, normalizes source URLs, performs duplicate detection, creates queued tasks, and sends status/result messages.

This component should not know how downloads are executed internally. It only interacts with the task store and worker orchestration layer.

#### 2. Task Store

SQLite remains the single source of truth for runtime state. The schema should be simplified around local execution rather than remote MeTube reconciliation.

Required persisted fields:

- task identity and Telegram metadata
- normalized source URL
- state
- timestamps
- retry metadata
- final filename and download URL
- final error message

#### 3. Download Worker

Runs exactly one task at a time. It dequeues the oldest runnable task, spawns `yt-dlp`, captures exit status and stderr, and updates SQLite state based on the result.

Tasks received while the worker is busy remain queued until the current task completes or fails.

#### 4. Proxy Runtime

Reuses the current dynamic-subscription approach:

- parse all nodes from `VPN_SUBSCRIPTION_URL`
- persist the active node fingerprint
- persist failed-node cooldown metadata
- restore the last viable node after restart
- switch to the next viable node when the classifier reports a proxy/rate-limit failure

The runtime continues to own Xray startup, restart, and config rendering.

#### 5. Download HTTP Service

Serves completed files from a single path:

- `/download/<filename>`

This service is intentionally minimal. It exists only to provide Telegram-friendly download links from the same container. The reverse proxy on the host continues to expose the public domain.

## Data Flow

### Successful Task

1. Telegram message arrives.
2. URL is extracted and normalized.
3. Task is inserted into SQLite as `queued`.
4. Worker picks the oldest queued task and marks it `downloading`.
5. Worker runs `yt-dlp` with the current proxy environment.
6. File is written into the shared download directory.
7. Worker marks the task `finished` with filename and generated public URL.
8. Telegram bot sends `Finished: <title>` plus the `/download/...` URL.

### Recoverable Failure

1. Worker runs `yt-dlp`.
2. Process fails and emits stderr.
3. Error classifier maps the failure to either `retry_same_node` or `switch_node`.
4. If `retry_same_node`, the task is re-scheduled with a short backoff.
5. If `switch_node`, the active node is marked failed, Xray switches to the next viable node, and the task is retried on the new node.

### Final Failure

1. Worker runs `yt-dlp`.
2. Error classifier maps the failure to `final_fail`.
3. Task is marked `failed`.
4. Telegram bot sends a final failure message with the reason.

## Task State Model

The local execution model should use these states only:

- `queued`
- `downloading`
- `retrying`
- `finished`
- `failed`
- `timeout`

State transitions:

- `queued -> downloading`
- `downloading -> finished`
- `downloading -> retrying`
- `retrying -> downloading`
- `downloading/retrying -> failed`
- `queued/downloading/retrying -> timeout`

MeTube-specific reconciliation states such as remote submission/history matching should be removed from the main execution path.

## Error Classification and Retry Policy

The classifier should operate on local `yt-dlp` process results instead of MeTube history records.

### Outcome Classes

- `final_fail`
  - invalid URL
  - removed/private content
  - non-proxy-related content errors

- `retry_same_node`
  - transient local process/network issues that do not indicate the current node is bad

- `switch_node`
  - proxy handshake/connect failures
  - invalid node behavior
  - YouTube rate limiting or anti-bot responses attributable to the current egress node

### Retry Rules

- Only one task executes at a time.
- Same-node retries should be small and bounded.
- Node-switch retries should try at most a bounded number of distinct nodes for a single task.
- Failed nodes enter cooldown and are skipped until cooldown expiry.
- Total task runtime remains bounded by the existing timeout concept.

## Proxy Runtime Requirements

The proxy runtime must keep the following behavior intact:

- dynamic subscription refresh from `VPN_SUBSCRIPTION_URL`
- stable node fingerprints independent of subscription order
- restore the previous active node by fingerprint after restart
- gracefully fall back when the previous node disappears from the subscription
- persist failed-node cooldowns
- switch nodes only when the classifier says to do so

Subscription fetches must stay direct and must not depend on already-configured local proxy environment variables.

Xray config output must be written to a writable runtime state path, not to a root-owned path that breaks when the application runs as a non-root user.

## Public Download URLs

All completed downloads use a single public base URL:

- `PUBLIC_DOWNLOAD_BASE_URL`

Returned links are always:

- `PUBLIC_DOWNLOAD_BASE_URL + "/" + urlencoded filename`

There is no separate audio URL space in this design.

## Environment Variables

The simplified runtime should keep only the variables required by the new architecture.

Required:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `PUBLIC_DOWNLOAD_BASE_URL`

Optional / behavior:

- `VPN_SUBSCRIPTION_URL`
- `DOWNLOAD_DIR`
- `STATE_DIR`
- `HTTP_BIND`
- `HTTP_PORT`
- `TASK_TIMEOUT_SECONDS`
- `POLL_INTERVAL_SECONDS`
- retry tuning variables if later exposed

Variables that become obsolete in the new design:

- `METUBE_BASE_URL`
- `METUBE_AUTH_HEADER_NAME`
- `METUBE_AUTH_HEADER_VALUE`
- `PUBLIC_HOST_AUDIO_URL`

## Container Design

The new image should be a purpose-built Python runtime image instead of the current MeTube-derived image.

It should include only:

- Python runtime
- `yt-dlp`
- Xray
- ffmpeg
- SQLite tools only if operationally useful
- application code

It should not include:

- Angular build stage
- MeTube UI assets
- MeTube API code paths
- Rust build stage for MeTube-era packaging

The final deployment target is one container, started by Docker Compose, with one mounted download/state volume and a host reverse proxy in front of `/download/*`.

## Migration Strategy

Implementation should happen on a new feature branch and should not overwrite the current working production path until the simplified runtime is verified.

Suggested implementation sequence:

1. Introduce local download worker and local task state flow.
2. Replace MeTube client interactions with local execution orchestration.
3. Attach existing proxy runtime logic to local `yt-dlp` execution.
4. Add lightweight `/download/*` file serving.
5. Build a new lean Docker image for the single-container runtime.
6. Validate locally and then validate on the Hong Kong server.

## Testing Strategy

### Unit Tests

- task state transitions
- queue ordering and single-worker execution rules
- duplicate detection
- public URL generation
- process-result classification
- node cooldown and active-node restoration

### Integration Tests

- end-to-end task success through the local worker
- same-node retry
- switch-node retry
- restart restore behavior
- lightweight file-serving path generation

### Manual Validation

- send Telegram URL
- receive queued message
- complete download successfully
- open returned `/download/...` link
- validate node switching on a proxy/rate-limit scenario

## Risks and Mitigations

### Risk: Local downloader loses behavior currently hidden behind MeTube

Mitigation:

- explicitly replace each used MeTube capability with a local equivalent before removing the old path
- keep tests focused on the currently verified Telegram workflow

### Risk: Error classification differs when driven by local `yt-dlp` stderr

Mitigation:

- preserve the existing categories
- add fixture-based classifier tests using real captured stderr samples

### Risk: Single-process runtime becomes tangled

Mitigation:

- keep strict module boundaries between ingress, store, worker, proxy runtime, and file serving
- one responsibility per module even though everything ships in one container

## Recommendation

Proceed with a new single-container runtime that removes MeTube entirely, keeps the proxy failover logic, serves only `/download/*`, and executes downloads through a single serial `yt-dlp` worker.

This is the smallest architecture that still satisfies the user's confirmed requirements and materially reduces deployment complexity.
