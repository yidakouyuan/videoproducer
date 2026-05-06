# STREAMING_PROTOCOL.md — Partial-Then-Atomic Artifact Writes

Applies to: long-tailed run artifacts under `~/.openclaw/runs/<run_id>/` whose producer may take minutes and could crash mid-write.

The whole point: if a producer dies after 4 minutes of work, the next session should be able to read the partial state, decide whether to resume or restart, and never see a half-written file as if it were a finished one.

## File naming

| State | Path | Meaning |
|---|---|---|
| in-progress | `<base>.json.partial` | Readable, but the producer is not done. Consumers MUST treat it as not-yet-available. |
| terminal    | `<base>.json`         | Final. Atomically published. Safe to consume per RUN_LAYOUT.md. |
| failed      | `<base>.json.partial` (with `status: "failed"`) | Producer hit a terminal failure; no rename happened. Next session decides retry vs surface. |

A `<base>.json` only ever exists if the producer reached a terminal success. If you see it, trust it.

## Producer rules

```
# initial
write_atomic(<base>.json.partial, payload_with_progress)

# update (whole-file overwrite, NOT append — JSON stays valid)
write_atomic(<base>.json.partial, payload_with_progress)

# success
os.rename(<base>.json.partial, <base>.json)   # atomic on same FS

# failure
write_atomic(<base>.json.partial, {**payload, "status": "failed", "error": "..."})
# do NOT rename — leave .partial as the failure record
```

`write_atomic` writes to a sibling `*.tmp` then renames over `*.partial` — never edit the partial file in place, so a reader can never observe a torn JSON.

Use the helper at `~/.openclaw/scripts/streaming_io.py` (Python) which implements `write_atomic`, `finalize`, and `read_with_partial_fallback` correctly.

## Required `progress` block

Every partial payload MUST carry a top-level `progress` block:

```json
{
  "...business fields...": "...",
  "progress": {
    "phase": "fetching|analyzing|stitching|polling|...",
    "percent": 0,
    "last_event_ts": "2026-04-29T03:00:00Z",
    "resume_token": "<producer-defined opaque string>",
    "writer_pid": 12345
  }
}
```

- `phase`: producer-defined; pick names that match the agent's mental model.
- `percent`: best-effort estimate. `null` is allowed when truly unknown.
- `last_event_ts`: ISO8601, updated on every overwrite. A consumer can flag stalled writes by `now() - last_event_ts > N`.
- `resume_token`: free-form. Examples: a `job_id` to re-poll; the highest iteration index already persisted; a byte offset into a stream. The producer reads it on next start to decide where to pick up.
- `writer_pid`: OS pid of the producing process. Used by readers to detect stale partials when the writer died.

## Consumer rules

The reader's behavior depends on its role.

**Consumer (downstream agent that needs the finished payload)**:
1. `stat(<base>.json)` exists → read, consume per RUN_LAYOUT.md contract.
2. else `stat(<base>.json.partial)` exists →
   - if `progress.writer_pid` is alive → return blocker `still in progress` (and surface `progress.phase` + `last_event_ts` so the caller can choose to wait).
   - if `progress.writer_pid` is dead AND `status: "failed"` → return blocker `producer failed: <error>`.
   - if `progress.writer_pid` is dead AND no failure → return blocker `producer died mid-write; resume needed`. Do NOT silently consume a partial.
3. neither file exists → return blocker `not yet produced`.

**Watcher (orchestrator polling for stage progress)**:
- `<base>.json` → report `done`.
- `<base>.json.partial` → report `progress.phase`, `progress.percent`, age of `last_event_ts`. Do not block the run on a healthy partial; only escalate if `last_event_ts` is older than the stage's expected idle window (per AGENTS.md per-stage timeouts).

**Resumer (same producer agent restarting on the same `run_id`)**:
1. Read `<base>.json.partial` if present.
2. Validate `progress.writer_pid` — if alive and not yourself, exit (someone else owns this slot).
3. Use `progress.resume_token` to pick up where the previous attempt left off. Do not blindly start over and overwrite — that erases the resume point.

## What to stream, what not to

A file is a candidate for this protocol only if **all** of:

- Producer can take ≥ 30 seconds.
- Mid-write crash loses meaningful progress (i.e. resume is cheaper than restart).
- The payload is JSON-shaped and small enough that whole-file overwrite per update is fine (KB to a few MB; not GB).

Files that are NOT candidates: `brief.json` (tiny one-shot), `script.json` (writer assembles in memory then writes once), `raw/<channel>_iter<n>.json` (already a per-iteration checkpoint — the iteration index IS the streaming).

See RUN_LAYOUT.md for the per-artifact decision.

## Why this and not NDJSON / append-only

- NDJSON requires every consumer to know how to parse the partial-with-tail-truncation case. The current `runs/<run_id>/` consumer contract reads complete JSON objects — switching to NDJSON breaks every reader.
- Atomic rename gives consumers a binary "ready / not ready" signal with no parsing required.
- Whole-file partial overwrite keeps the partial file always parseable as JSON. A `cat <base>.json.partial | jq .progress` works any time during the run.

## Why this and not in-place edits to `<base>.json`

- A reader that opens `<base>.json` mid-write would observe an invalid (torn) document.
- The current contract is "if `<base>.json` exists, it's done." Breaking that contract breaks every downstream agent.

## Error semantics

| Producer state                | File on disk                        | Reader sees                          |
|-------------------------------|-------------------------------------|--------------------------------------|
| Running normally              | `<base>.json.partial` (live pid)    | "in progress, phase=X, ts=..."       |
| Crashed silently (OOM, kill)  | `<base>.json.partial` (dead pid)    | "stale partial — resume or restart"  |
| Reported terminal failure     | `<base>.json.partial` `status:fail` | "producer failed: <error>"           |
| Succeeded                     | `<base>.json`                       | "done — consume"                     |
| Never started                 | nothing                             | "not yet produced"                   |

Producers MUST never leave the artifact in any other state.
