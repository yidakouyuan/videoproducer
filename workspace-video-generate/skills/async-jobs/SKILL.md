---
name: async-jobs
description: "How to correctly wait for async jobs (video_generate_*) using video_generate_wait_for_done. Use this whenever you have started a generation job and are waiting for results."
---

# Async Jobs

Async jobs do not return results immediately. After calling `video_generate_start`, you MUST call `video_generate_wait_for_done` to wait for the job to reach a terminal state. The wait tool polls server-side inside the plugin process — you do NOT call `video_generate_result` in a loop yourself.

## Quick Reference

| Status | Meaning | Action |
|--------|---------|--------|
| `queued` | Job is waiting to run | Wait for `video_generate_wait_for_done` to return |
| `running` | Job is in progress | Wait for `video_generate_wait_for_done` to return |
| `done` | Job completed successfully | Extract `local_video_path` and stop |
| `failed` | Job failed | Report `error_message`, do not write a result file |
| `partial` | Partial result available | Evaluate usability, report honestly |
| `cancelled` | Job was cancelled | Report and escalate |
| `timeout` | Wait budget exhausted (job still running in backend) | Surface a blocker to orchestrator. Do NOT retry indefinitely |

## Rules

**Use `video_generate_wait_for_done`, not `video_generate_result` in a loop.**

- A slow job is not a failed job. Generation can take several minutes — `video_generate_wait_for_done` handles this server-side without burning LLM turns.
- Do not infer, fabricate, or skip ahead. `local_video_path` only exists once the wait returns `status: done`.
- Do not write `video_result.json` or report success without a confirmed `local_video_path` from tool output.
- **`timeout` is a blocker, not a retry trigger.** If `video_generate_wait_for_done` returns `status: "timeout"` after a 15-minute wait, something is wrong (backend overloaded, job stuck). Surface the timeout to orchestrator with the `job_id` so it can decide whether to abandon or wait more — do NOT loop on `wait_for_done` indefinitely on your own.

## Pattern

```
video_generate_start(...)        → get job_id
video_generate_wait_for_done(job_id, max_wait_sec=900)
                                 → status: done       → extract local_video_path ✓
                                 OR status: timeout   → surface blocker to orchestrator
                                 OR status: failed/partial/cancelled → handle, stop
```

`video_generate_result` is reserved for one-off peeks (e.g., debugging "is this still running?"). Never use it as the main wait mechanism.

---
