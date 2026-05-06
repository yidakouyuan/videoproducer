---
name: media-pipeline
description: "Resolve, fetch, analyze, and transcribe Douyin candidates. You MUST call every tool in sequence — do not write resolved results without actual tool output."
---

# Media Pipeline

Every shortlisted candidate must be processed through this full pipeline before results can be written. Do not populate `video_analysis` or `transcript` from memory — every field must come from actual tool output.

## Quick Reference

| Step | Required Tool Call | Returns |
|------|-------------------|---------|
| 1. Resolve | `media_resolve_video(share_url=...)` | `video_ref` |
| 2. Fetch | `media_fetch_video(video_ref=...)` | `media_id` |
| 3. Start analysis | `video_analyze_start(media_id=...)` | `analyze_job_id` |
| 4. Start transcription | `transcribe_start(media_id=...)` | `transcribe_job_id` |
| **5. Save job IDs** | write `jobs_iter{n}.json` | persisted state |
| 6. Wait for analysis | `video_analyze_wait_for_done(job_id=...)` | analysis result |
| 7. Wait for transcription | `transcribe_wait_for_done(job_id=...)` | transcript |

## Solution

### Step-by-Step

For each shortlisted candidate:

1. **Resolve** — Call `media_resolve_video(share_url=<url>)` → get `video_ref`. Do not proceed without a real `video_ref`.

2. **Fetch** — Call `media_fetch_video(video_ref=<ref>)` → get `media_id`. This is slow — expect it. Do not fabricate a `media_id`.

3. **Analyze + Transcribe** — Call `video_analyze_start(media_id=<id>)` AND `transcribe_start(media_id=<id>)` immediately. Launch both together — do not wait for one before starting the other.

4. **Save job IDs** — Immediately write or update `~/.openclaw/runs/{run_id}/raw/jobs_iter{n}.json` with the `analyze_job_id` and `transcribe_job_id` for this candidate. Do this before waiting. This is required — job IDs exist only in context and will be lost if the session ends. Even with `wait_for_done`, a wait timeout can occur; persisting the `job_id` lets the next session continue waiting on the same backend job, instead of re-analyzing from scratch.

5. **Wait** — Call `video_analyze_wait_for_done(job_id=<analyze_job_id>)` and `transcribe_wait_for_done(job_id=<transcribe_job_id>)` concurrently. Each returns the final result when the job reaches a terminal state. Do NOT call `video_analyze_result` / `transcribe_result` in a loop — that's the old way and wastes turns.

   If a wait returns `{ status: "timeout", job_id, last_status: "running" }`, the job is still alive in the backend. Call `*_wait_for_done(job_id=...)` again with the same `job_id` to continue waiting. Timeout ≠ failure. (→ `async-jobs` skill)

6. **Write** — Only after receiving terminal results, write the entry to `resolved_iter{n}.json`. `video_analysis` and `transcript` must be direct tool output — not summaries or inferences.

## Gotchas

- Skip candidates where `weak: true` — they're missing `aweme_id` or `share_url` and cannot be resolved.
- Only fetch candidates genuinely worth review. Fetching is slow and costly.
- Do not pass failed, partial, or empty job results downstream as usable evidence.

---
