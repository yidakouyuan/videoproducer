---
name: async-jobs
description: "How to correctly wait for async jobs (video_analyze_*, transcribe_*) using *_wait_for_done. Use this whenever you have started a job and are waiting for results."
---

# Async Jobs

Async jobs do not return results immediately. After calling a start tool, you MUST call the matching `*_wait_for_done` tool to wait for the job to reach a terminal state. The `*_wait_for_done` variant polls server-side inside the plugin process — you do NOT call `*_result` in a loop yourself.

## Quick Reference

| Status | Meaning | Action |
|--------|---------|--------|
| `queued` | Job is waiting to run | Wait for `*_wait_for_done` to return |
| `running` | Job is in progress | Wait for `*_wait_for_done` to return |
| `done` | Job completed successfully | Consume result and stop |
| `failed` | Job failed | Report clearly, stop |
| `partial` | Partial result available | Evaluate usability, stop |
| `cancelled` | Job was cancelled | Report and escalate, stop |
| `timeout` | Wait budget exhausted, job still running in backend | Re-call `*_wait_for_done` with same `job_id` to continue |

## Rules

**Use `*_wait_for_done`, not `*_result` in a loop.**

- A slow job is not a failed job. Video analysis and transcription can take several minutes — `*_wait_for_done` handles this server-side without burning LLM turns.
- Do not infer, fabricate, or skip ahead. Results only exist once `*_wait_for_done` returns a terminal state.
- Do not report success without a real artifact (transcript text, analysis text, etc.).
- **`timeout` is not failure**. If `*_wait_for_done` returns `status: "timeout"`, the job is still alive in the backend. Re-call `*_wait_for_done(job_id=...)` with the same `job_id` to continue waiting. Only `failed` / `partial` / `cancelled` are real failures.

## Pattern

```
start_tool(...)              → get job_id
wait_for_done(job_id)        → status: done       → consume result ✓
                             OR status: timeout   → wait_for_done(job_id) again
                             OR status: failed/partial/cancelled → handle, stop
```

## For concurrent jobs (analyze + transcribe)

Call both `*_wait_for_done` tools in the **same turn** — the runtime executes them in parallel and the turn returns once all waits have terminated (or hit timeout). Do NOT wait for one tool call to return before calling the other.

```
# Same turn, both starts:
video_analyze_start(media_id)        → analyze_job_id
transcribe_start(media_id)           → transcribe_job_id

# Same turn, both waits run concurrently inside the plugin process:
video_analyze_wait_for_done(analyze_job_id)    → done → analysis result
transcribe_wait_for_done(transcribe_job_id)    → done → transcript

# After both terminal, write the resolved entry.
```

Only write the resolved entry once BOTH waits have reached terminal state.

---
