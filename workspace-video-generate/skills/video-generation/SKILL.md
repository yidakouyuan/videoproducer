---
name: video-generation
description: "Submit and wait for video generation jobs. You MUST call video_generate_start then video_generate_wait_for_done — do not report local_video_path without receiving it from a tool call, and do not loop on video_generate_result yourself."
---

# Video Generation

You MUST call `video_generate_start` to begin generation, then call `video_generate_wait_for_done` to wait for terminal state. Do NOT call `video_generate_result` in a loop yourself — that wastes LLM turns and tokens. The wait tool polls server-side inside the plugin process.

Do not report a `local_video_path` without receiving it from actual tool output.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| script.json is ready | MUST call `video_generate_start` immediately |
| `video_generate_start` returned a `job_id` | MUST call `video_generate_wait_for_done(job_id=...)` next — single call, server-side wait |
| Status is `queued` or `running` | Should never observe these from `wait_for_done` — it only returns on terminal state. If you see them, you're calling `video_generate_result` directly (don't) |
| Status is `done` | Extract `local_video_path` and `manifest_path` from tool response |
| Status is `failed` / `partial` / `cancelled` | Return `error_message` — do not write a result file |
| Status is `timeout` | Wait budget exhausted (default 15 min). Surface a blocker to orchestrator. Do NOT retry indefinitely (→ AGENTS.md) |
| After handoff complete | Call `video_generate_delete(job_id=...)` to clean up |

## Solution

### Step-by-Step

1. Build the prompt from `shot_notes` in `script.json`
2. Call `video_generate_start` → save `job_id`
3. Call `video_generate_wait_for_done(job_id, max_wait_sec=900)` — single tool call, server-side wait (→ `async-jobs` skill)
4. On `done`: extract `local_video_path`, `manifest_path`, `task_id` from the tool response
5. Write `video_result.json` and return confirmation

### Response Shapes

Done:
```json
{ "ok": true, "data": { "job_id": "vg_...", "status": "done", "task_id": "cgt-...", "local_video_path": "c:/...", "manifest_path": "c:/...", "waited_sec": 240 } }
```

Failed:
```json
{ "ok": true, "data": { "job_id": "vg_...", "status": "failed", "error_message": "..." } }
```

Timeout (job still running in backend, but wait budget exhausted):
```json
{ "ok": false, "status": "timeout", "message": "Job did not reach a terminal state within 900s", "job_id": "vg_...", "waited_sec": 900 }
```

## Gotchas

- Build the prompt from `shot_notes` only — do not substitute your own concept.
- Only pass `first_frame_path` when explicitly provided — never fabricate a path.
- Do not report success without a confirmed `local_video_path` from tool output.
- Do not call `video_generate_result` in a loop. Use `video_generate_wait_for_done` instead. `video_generate_result` is only useful for one-off peeks (e.g., debugging).

---
