# ASYNC_JOBS.md — Async Job Protocol

Applies to: video analysis (`video_analyze_*`), transcription (`transcribe_*`), video generation (`video_generate_*`).

## Pattern

1. **Start** — call the start tool, save the returned `job_id`.
2. **Persist** — for any job whose result you can't afford to lose
   (e.g., one that may outlive your session), write the `job_id` to
   the run directory (e.g., `raw/jobs_iter{n}.json`) so you can
   resume after a session interrupt OR a wait timeout.
3. **Wait** — call the **`*_wait_for_done`** variant. It does
   server-side polling inside the plugin process and returns only
   when the job reaches a terminal state OR the wait budget is hit.
   You do NOT need to call the `*_result` tool in a loop yourself.
4. **Resume on timeout** — if `*_wait_for_done` returns
   `{ status: "timeout", job_id, last_status: "running" }`, the job
   is still running in the backend. Call `*_wait_for_done(job_id=...)`
   again with the same `job_id` to continue waiting. **Timeout is not
   failure** — only `failed` / `cancelled` / `partial` are.
5. **Fall-back peek** — `*_result` is still useful for a one-shot
   status check (e.g., debugging, "is this still running?"), but is
   NOT how you should normally wait for completion.
6. **Terminal only** — stop work only on a terminal state (see below).

## Why wait_for_done

Calling `*_result` in a loop from the agent burns LLM turns, tokens,
latency, and trace noise — every poll is a model call. The
`*_wait_for_done` variant moves the poll loop into the plugin
process, so it costs zero LLM turns regardless of how long the job
takes. Use it.

## Terminal States

| State | Action |
|---|---|
| `done` | Consume the result |
| `failed` | Report clearly, leave retry to the caller |
| `partial` | Evaluate usability, report honestly |
| `cancelled` | Report and escalate |

## Rules

- `queued` and `running` are not terminal. Keep waiting (use `*_wait_for_done`).
- A slow job is not a failed job — `*_wait_for_done` handles long waits server-side.
- Do not infer or fabricate results before `*_wait_for_done` returns a terminal state.
- Do not report success without a real output artifact (`local_video_path`, transcript, etc.).
