# Proxy Failover for Dynamic VPN Subscription Nodes

## Summary

Add automatic proxy node failover to the existing MeTube container so downloads can recover when the current VPN subscription node becomes invalid or starts hitting YouTube rate limiting.

The current container already installs Xray and can bootstrap one node from `VPN_SUBSCRIPTION_URL`, but it only selects the first parseable node and keeps using it until the container is restarted. That is not sufficient when:

- the first node is dead even though its URI is syntactically valid
- the node is reachable but degraded
- YouTube starts returning rate-limit or bot-check errors for that exit IP
- the subscription contents change over time

The new design keeps the current single-container deployment model, but upgrades proxy handling into a persistent node-pool failover system:

- parse the full subscription instead of only the first valid node
- persist the active node across restarts
- classify download errors into failover-triggering vs final-content failures
- switch to the next viable node when proxy or YouTube rate-limit failures occur
- automatically retry the failed task on the new node

This feature is intentionally scoped to the existing MeTube runtime and avoids introducing a sidecar or external proxy orchestrator.

## Goals

- Preserve the current `VPN_SUBSCRIPTION_URL -> Xray -> MeTube` deployment shape.
- Support dynamic subscriptions whose node order and membership can change over time.
- Persist the active node selection across container restarts.
- Trigger node switching only for:
  - proxy or connectivity failures
  - YouTube rate-limit or anti-bot failures
- Automatically retry the failed task after a successful node switch.
- Prevent concurrent download failures from causing duplicate or conflicting node switches.
- Keep the first implementation simple enough to debug in production.

## Non-Goals

- Multi-proxy concurrent balancing.
- Load-based node scoring.
- Sidecar-based proxy orchestration.
- Per-user or per-download custom proxy selection.
- Deep provider-specific heuristics beyond a conservative first-pass error classifier.
- Real-time active probing of every subscription node before each download.

## Current Problem

Today `app/vpn.py` fetches `VPN_SUBSCRIPTION_URL`, scans the decoded lines, and stops at the first node that can be parsed as `vless://` or `vmess://`.

That creates multiple failure modes:

1. a syntactically valid first node may still be unusable
2. YouTube can rate-limit one exit IP while other subscription nodes remain usable
3. dynamic subscriptions can reorder or replace nodes, making index-only recovery unsafe
4. restarting the container can return the runtime to a bad first node

The current container therefore has no runtime recovery path for proxy degradation beyond manual restart or manual subscription editing.

## Recommended Architecture

### Single Active Node Model

The system should continue using exactly one active proxy node at a time for the whole container.

This keeps the implementation simple:

- one Xray config
- one local HTTP proxy endpoint
- one active proxy generation shared by all downloads
- one serialized failover path

This design intentionally favors operational clarity over throughput optimization.

### New Components

Add three focused runtime components.

#### ProxyNodeCatalog

Responsible for:

- fetching and decoding the subscription
- parsing every supported node
- computing a stable fingerprint per node
- loading and saving persisted proxy state
- resolving a previously active node fingerprint against the current subscription snapshot

#### ProxyRuntimeManager

Responsible for:

- rendering Xray config for a chosen node
- starting Xray if it is not running
- reloading or restarting Xray when the active node changes
- exposing the current active generation and node metadata to the application

#### ProxyFailoverCoordinator

Responsible for:

- classifying download failures
- deciding whether a switch is required
- serializing failover operations under a global lock
- updating persisted failover state
- coordinating automatic retry of the failed task after a successful switch

These boundaries keep proxy logic out of the low-level `yt-dlp` code path.

## Node Identity and Dynamic Subscription Handling

### Why Index-Only Persistence Is Unsafe

The subscription is dynamic. Nodes can be reordered, removed, or replaced.

That means `active_node_index` alone is not a stable persisted identity because:

- the same index can point to a different node after refresh
- the previously active node can disappear
- newly inserted nodes can shift every later index

### Stable Fingerprints

Each parsed node should therefore have a stable fingerprint derived from normalized node properties such as:

- protocol
- host
- port
- user identity field such as UUID or VMess ID
- transport network
- security mode
- SNI or peer name if present
- path or service name when relevant

The exact serialized shape does not need to be user-facing, but it should be deterministic so the same logical node maps to the same fingerprint across refreshes.

### Subscription Refresh Rules

The runtime should refresh the subscription:

- on container startup
- before selecting the next node during failover
- optionally when the persisted active fingerprint can no longer be found

Recovery behavior:

- if the persisted active fingerprint still exists in the refreshed subscription, reuse it
- if not, select the next viable node from the new snapshot
- if no nodes are usable, keep the task failure path deterministic and report the last relevant error

## Persistent State

Persist proxy failover state in `STATE_DIR/proxy_state.json`.

Recommended fields:

- `subscription_url_hash`
- `active_node_fingerprint`
- `active_node_index_hint`
- `active_node_name`
- `generation`
- `last_switch_at`
- `last_subscription_refresh_at`
- `failed_fingerprints`

Example shape:

```json
{
  "subscription_url_hash": "sha256:...",
  "active_node_fingerprint": "sha256:...",
  "active_node_index_hint": 3,
  "active_node_name": "hk-01",
  "generation": 12,
  "last_switch_at": 1774500000,
  "last_subscription_refresh_at": 1774500000,
  "failed_fingerprints": {
    "sha256:node-a": {
      "failed_at": 1774500000,
      "cooldown_until": 1774500600,
      "reason": "youtube_rate_limit"
    }
  }
}
```

Persistence rules:

- write atomically through a temp file plus rename
- tolerate missing or corrupt state by falling back to fresh selection
- keep failure history bounded so the file does not grow forever

## Failover Policy

### Triggerable Error Classes

Only two categories should trigger node switching.

#### Proxy or Connectivity Failures

Examples:

- `connection refused`
- `network is unreachable`
- `connection reset by peer`
- `timed out`
- `proxy error`
- `socks`
- `tls handshake`
- `EOF`
- `temporarily unavailable`

#### YouTube Rate-Limit or Anti-Bot Failures

Examples:

- `HTTP Error 429`
- `Too Many Requests`
- `Sign in to confirm you're not a bot`
- `confirm you're not a bot`
- `unusual traffic`
- `rate limit`
- `request has been blocked`

### Non-Triggering Errors

Content or permission failures should remain final task failures and should not switch the proxy node.

Examples:

- `Private video`
- `Video unavailable`
- `Unsupported URL`
- `members-only`
- `copyright`
- `login required`
- `age-restricted`

The classifier should be conservative. False positives are worse than false negatives for the first version because over-switching can churn the whole container.

## Runtime Flow

### Startup

1. Load persisted proxy state from `STATE_DIR/proxy_state.json`.
2. Fetch and parse the current subscription snapshot.
3. Try to resolve the persisted `active_node_fingerprint` against the refreshed node list.
4. If the node still exists and is not in cooldown, activate it.
5. Otherwise select the next viable node.
6. Render `/etc/xray/config.json`.
7. Start Xray and expose the local proxy endpoint as today.
8. Persist the final active node and generation.

### Download Start

Each download should capture the current proxy generation when it begins:

- `proxy_generation_started`

This allows later failure handling to distinguish:

- failure on the still-current node generation
- failure from an old generation after another task already switched the proxy

### Failure Handling

When a download fails:

1. classify the error
2. if classification is `final_fail`:
   - complete the task as a normal failure
3. if classification is `switch_node`:
   - compare the task generation with the current runtime generation
   - if they differ:
     - do not switch again
     - immediately retry the task on the already-new generation
   - if they match:
     - enter the serialized failover path

### Serialized Failover Path

Failover should be guarded by one global async lock.

Inside the lock:

1. re-check whether another task already switched the generation
2. if yes:
   - release without another switch
   - retry the task
3. refresh the subscription
4. mark the current node fingerprint as failed with a cooldown window
5. select the next non-cooled-down node
6. regenerate Xray config
7. restart or reload Xray
8. increment `generation`
9. persist the new active node state
10. retry the failed task immediately

If no viable node exists:

- stop failover
- keep the task failure deterministic
- surface the last relevant reason in logs and task status

## Retry Policy for the Failed Task

Each task should keep minimal failover tracking:

- `proxy_generation_started`
- `failover_attempts`
- `attempted_node_fingerprints`

First-version limits:

- retry the failed task automatically after a successful node switch
- allow each task to try at most 3 distinct nodes through failover
- never retry the same task twice on the same node fingerprint

This prevents a single bad task from rotating endlessly through a bad subscription.

## Cooldown Policy

Use a simple fixed cooldown for the first implementation.

Recommended initial value:

- 10 minutes per failed node fingerprint

Behavior:

- once a node triggers failover, it goes into cooldown
- failover selection skips nodes still under cooldown
- when all nodes are cooled down, selection may either:
  - fail immediately for the current task, or
  - re-enter a full pass after cooldown expiry

The first implementation should prefer deterministic failure over complicated waiting logic.

## Concurrency Rules

The MeTube runtime may have multiple downloads fail at roughly the same time. The design must prevent these failures from creating switch storms.

Required rules:

- only one failover operation may execute at a time
- all downloads share one container-wide `generation`
- a task that fails on an old generation must retry on the new generation instead of switching again
- tasks should not modify Xray state directly; only the failover coordinator may do that

This keeps proxy failover a container-level concern rather than a per-download race.

## Implementation Notes

### Xray Control

The current entrypoint starts Xray as a background process. The failover implementation will need a runtime-safe way to:

- know the Xray PID
- restart or reload it after writing new config

The simplest acceptable first version is:

- manage Xray from the Python runtime layer
- on switch, rewrite config and restart the Xray subprocess cleanly

This is simpler than trying to teach the shell entrypoint to remain the long-term proxy supervisor.

### Error Classifier Source

The classifier may initially operate on normalized error strings emitted from the current `yt-dlp` failure path. It does not need a complex typed error model in the first version, as long as matching logic is centralized and tested.

### Backward Compatibility

If `VPN_SUBSCRIPTION_URL` is absent, the new proxy manager should remain inert and the MeTube container should behave like today without proxy failover.

## Testing Strategy

### Unit Tests

- subscription parsing returns all supported nodes, not just the first
- fingerprint generation remains stable across subscription reorderings
- active fingerprint recovery succeeds after node order changes
- active fingerprint recovery falls back cleanly when a node disappears
- proxy/connectivity errors map to `switch_node`
- YouTube 429 and anti-bot errors map to `switch_node`
- private or unavailable content errors map to `final_fail`
- failover selection skips cooled-down nodes
- per-task attempted-node tracking prevents same-node retry loops

### Concurrency Tests

- two tasks fail simultaneously and only one actual node switch occurs
- one task switches the generation and a second failed task retries on the new generation without re-switching
- all nodes unavailable produces one deterministic terminal failure path

### Integration-Style Tests

Use fake runtime components instead of real network traffic:

- fake subscription snapshots
- fake Xray runtime manager
- fake download failures with representative error messages
- persisted proxy state round-trips through disk

This keeps the tests deterministic and avoids tying the suite to live VPN or YouTube behavior.

## Risks

- Error-string matching is inherently imperfect and may need production refinement.
- Restarting Xray mid-flight may cause some in-progress downloads to fail and re-enter retry logic.
- Dynamic subscriptions can remove the current node at inconvenient times, which must remain a supported recovery path.
- If too many tasks all fail during the same provider outage, even serialized failover can still churn the node pool quickly.

## Future Extensions

- configurable cooldown and per-task node-attempt limits via environment variables
- background health probes to pre-score nodes before failover
- support for more subscription URI schemes beyond VMess and VLESS
- richer metrics and admin-visible proxy status endpoints
