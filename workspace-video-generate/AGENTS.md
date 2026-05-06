# AGENTS.md - video-generate

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-video-generate/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `skills/video-generation/SKILL.md`, then `skills/async-jobs/SKILL.md`, then `skills/video-stitch/SKILL.md`

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-video-generate/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-video-generate/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-video-generate/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/video-generate.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-video-generate/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-video-generate/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-video-generate/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-video-generate/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive:

- `run_id`
- optional: generation mode hint (`t2v` or `i2v`)
- optional: `first_frame_path` for image-to-video generation (single-shot mode only; multi-shot reads it from each shot's `reference_image_path`)

Read `~/.openclaw/runs/{run_id}/script.json` (→ `~/.openclaw/docs/RUN_LAYOUT.md`). If the file is missing or unreadable, return a blocker immediately.

Check whether `shots[]` is present and non-empty in `script.json`:
- **`shots[]` present** → multi-shot storyboard flow (see below)
- **`shots[]` absent** → single-shot flow (legacy, see below)

---

## Working schema — Multi-Shot Storyboard

Use this when `script.json` contains a `shots[]` array with `reference_image_path` per shot.

This flow uses **strict mode**: every shot must produce a successful clip (with up to 1 retry).
No partial stitching — if any shot fails twice, abort the whole run.

1. **Read all shots** from `script.json`.
   - Each shot has: `index`, `duration`, `prompt`, `narration`, `reference_image_path`.

2. **Submit all video generation jobs in parallel**
   For each shot, call `video_generate_start`:
   - `prompt` = shot's `prompt`
   - `duration` = shot's `duration`
   - `first_frame_path` = shot's `reference_image_path` (enables i2v mode)
   - If `reference_image_path` is missing or empty, omit `first_frame_path` (t2v fallback).

   Submit all shots **before** polling any — the backend runs the jobs concurrently regardless of how the agent later waits on them.
   Track in memory: `pending = [{index, job_id, retried: false}, ...]` in shot index order.

   **Write the streaming partial** — once all jobs are submitted, `video_result.json` follows the **partial + atomic rename** protocol per `~/.openclaw/docs/STREAMING_PROTOCOL.md`. Use the `write` tool to create `~/.openclaw/runs/{run_id}/video_result.json.partial` with:
   ```json
   {
     "status": "running",
     "shots": [
       {"index": 1, "job_id": "<job_id_1>", "status": "running"},
       {"index": 2, "job_id": "<job_id_2>", "status": "running"}
     ],
     "progress": {
       "phase": "all_submitted",
       "last_event_ts": "<current UTC ISO8601>",
       "resume_token": "<run_id>",
       "writer_pid": null
     }
   }
   ```
   Do NOT write `video_result.json` directly — only `.partial` until every shot is done and stitched.

3. **Wait sequentially with retry-once**
   For each `(index, job_id)` in `pending`, in order:
   a. Call `video_generate_wait_for_done(job_id, max_wait_sec=900)`. The tool returns when the job reaches a terminal state (`done` / `failed` / `partial` / `cancelled`) or times out.
   b. If `status == "done"`:
      - Record `{index, job_id, status: "done", local_video_path: ...}`.
      - Continue to the next job.
   c. If `status` is non-done **and the shot has not been retried yet**:
      - Mark this shot as `retried: true`.
      - Re-submit by calling `video_generate_start` with the same `prompt`, `duration`, `first_frame_path` as in step 2. Capture the new `job_id`.
      - Call `video_generate_wait_for_done(new_job_id, max_wait_sec=900)` and inspect the result:
        - If `status == "done"`: record success, continue to next shot.
        - If `status` is still non-done: trigger **abort** (step 3d).
   d. If `status` is non-done **and this is already the retry attempt** (or wait timed out):
      - **Abort the whole run.** Do not continue waiting on remaining shots.
      - For every job_id still in `pending` after the current index, call `video_generate_delete(job_id)` to release the orphan jobs.
      - Also call `video_generate_delete` for every job_id already collected (done or failed) to clean up.
      - Use the `write` tool to overwrite `~/.openclaw/runs/{run_id}/video_result.json.partial` with `{"status":"failed","failed_shot_index":<n>,"error":"<both error messages>","progress":{"phase":"failed","last_event_ts":"<now>","resume_token":"<run_id>","writer_pid":null}}`. **Do NOT finalize** — the failed `.partial` is the failure record.
      - Return a blocker to orchestrator naming the failing shot index, both `error_message` values (original + retry), and the run_id.
      - **Do not call `video_stitch`. Do not finalize `video_result.json`.**

   Note: total wall-clock time ≈ max(individual job duration), because all jobs were submitted in step 2 and run concurrently in the backend. Sequential `wait_for_done` doesn't slow things down — the second and third waits typically return immediately because those jobs finished while the first wait was blocking.

4. **Stitch clips** — follow `skills/video-stitch/SKILL.md`
   Once every shot is `done` (no failed shots survive to this step), call `video_stitch` with the `local_video_path` values of all shots in ascending `index` order.
   - If stitch fails with `reencode=false`: retry **once** with `reencode=true` (and omit `output_name` for auto-naming).
   - If reencode also fails: use the `write` tool to overwrite `~/.openclaw/runs/{run_id}/video_result.json.partial` with `{"status":"failed","error":"<stitch errors>","progress":{"phase":"failed","last_event_ts":"<now>","resume_token":"<run_id>","writer_pid":null}}`. Do NOT finalize. Return a blocker with both error messages.

5. **Clean up**
   Call `video_generate_delete` for every job_id used in this run (originals + any retry job_ids).

6. **Finalize the result**

   6a. **Stage stitched video to a stable WSL run-dir path.** `video_stitch` returns a Windows TEMP path like `C:\Users\Administrator\AppData\Local\Temp\openclaw\uploads\final_<run_id>.mp4`. TEMP is unstable (cleanup TTL, disk pressure) — copy to the WSL run dir first so downstream consumers (backward chain, episode_init, archival) get a stable path:
   ```
   exec bash -lc 'cp "<wsl-view-of-stitched-path>" /home/administrator/.openclaw/runs/{run_id}/video.mp4'
   ```
   Convert the Windows path to its WSL view by replacing `C:\` → `/mnt/c/` and `\` → `/`. Example: `C:\Users\Administrator\AppData\Local\Temp\openclaw\uploads\final_20260502_210457.mp4` → `/mnt/c/Users/Administrator/AppData/Local/Temp/openclaw/uploads/final_20260502_210457.mp4`. Verify exit code 0 before proceeding; if cp fails, surface a blocker.

   6b. **Overwrite `~/.openclaw/runs/{run_id}/video_result.json.partial`** (use the `write` tool) with the full final payload — the **stable run-dir path** plus per-shot details (every `status: "done"`):
   ```json
   {
     "job_id": "vg_stitch_<run_id>",
     "status": "done",
     "local_video_path": "/home/administrator/.openclaw/runs/<run_id>/video.mp4",
     "manifest_path": "",
     "shots": [
       {"index": 1, "job_id": "<final job_id>", "status": "done", "local_video_path": "<per-shot clip — keep Windows TEMP path; per-shot clips are not staged>"}
     ],
     "progress": {
       "phase": "done",
       "last_event_ts": "<current UTC ISO8601>",
       "resume_token": "<run_id>",
       "writer_pid": null
     }
   }
   ```
   ⚠️ `local_video_path` (top-level) MUST be the stable run-dir path from 6a, NOT the original Windows TEMP path returned by `video_stitch`. Per-shot `local_video_path` entries can stay as Windows TEMP (they're internal references; orchestrator only reads the top-level).

   6c. **Atomically promote `.partial` to `.json`:**
   ```
   exec bash -lc 'python3 ~/.openclaw/scripts/streaming_io.py finalize ~/.openclaw/runs/{run_id}/video_result.json.partial'
   ```
   Verify the exec exit code is 0. After success, `~/.openclaw/runs/{run_id}/video_result.json` exists and orchestrator can consume it.

   6d. Return confirmation to orchestrator: file finalized, run_id.

---

## Working schema — Single-Shot (Legacy)

Use this when `script.json` has no `shots[]`.

Interpretation rules:
- If no `first_frame_path` is provided, prepare a **text-to-video** request using `shot_notes` (and `script` for context).
- If a valid `first_frame_path` is provided, prepare an **image-to-video** request.

1. **Read the script**
   - Read `~/.openclaw/runs/{run_id}/script.json`.
   - Determine whether the request is `t2v` or `i2v`.

2. **Build the generation prompt**
   - Use `shot_notes` as the primary source for the prompt — it describes the visual direction.
   - Reference `script` for tone and narration context if needed.
   - For `i2v`, also include `first_frame_path`.

3. **Generate video** → `video-generation` skill.
   - Call `video_generate_start` to submit, capture the returned `job_id`.

   **Write the streaming partial** — before waiting, give orchestrator and other watchers early visibility. `video_result.json` follows the **partial + atomic rename** protocol per `~/.openclaw/docs/STREAMING_PROTOCOL.md`. Use the `write` tool to create `~/.openclaw/runs/{run_id}/video_result.json.partial` with:
   ```json
   {
     "job_id": "<job_id>",
     "status": "running",
     "progress": {
       "phase": "polling",
       "last_event_ts": "<current UTC ISO8601, e.g. 2026-04-29T15:00:00Z>",
       "resume_token": "<job_id>",
       "writer_pid": null
     }
   }
   ```
   Generate `last_event_ts` yourself in UTC (no need to call exec for it). Do NOT write `video_result.json` directly — only `.partial` until the job is done.

   - Then call `video_generate_wait_for_done(job_id, max_wait_sec=900)` — this is a server-side wait. **Do NOT** call `video_generate_result` in a loop yourself; that wastes turns and tokens. Use `video_generate_result` only for one-off peeks (e.g., debugging).
   - The wait tool returns the same shape as `video_generate_result` plus a `waited_sec` field. If it returns `status: "timeout"`, the job didn't finish within the budget — surface a blocker; do NOT retry indefinitely.
   - On `done`: extract `local_video_path`, `manifest_path`, `task_id`.
   - On `failed`: overwrite `video_result.json.partial` with `{"job_id":"...","status":"failed","error":"<reason>","progress":{"phase":"failed","last_event_ts":"<now>","resume_token":"<job_id>","writer_pid":null}}` and stop. **Do NOT finalize** — the failed `.partial` is the failure record for next session to inspect.

4. **Finalize the result**

   4a. **Stage video to a stable WSL run-dir path.** `wait_for_done` returns a Windows TEMP path like `C:\Users\Administrator\AppData\Local\Temp\openclaw\uploads\minimax_<task_id>_<ts>.mp4`. TEMP is unstable — copy to run dir first:
   ```
   exec bash -lc 'cp "<wsl-view-of-windows-path>" /home/administrator/.openclaw/runs/{run_id}/video.mp4'
   ```
   Convert the Windows path to its WSL view by replacing `C:\` → `/mnt/c/` and `\` → `/`. Verify exit code 0 before proceeding; if cp fails, surface a blocker.

   4b. **Overwrite `~/.openclaw/runs/{run_id}/video_result.json.partial`** with the final payload (use the `write` tool):
   ```json
   {
     "job_id": "<job_id>",
     "status": "done",
     "local_video_path": "/home/administrator/.openclaw/runs/<run_id>/video.mp4",
     "manifest_path": "<from wait_for_done result>",
     "task_id": "<from wait_for_done result>",
     "progress": {
       "phase": "done",
       "last_event_ts": "<current UTC ISO8601>",
       "resume_token": "<job_id>",
       "writer_pid": null
     }
   }
   ```
   ⚠️ `local_video_path` MUST be the stable run-dir path from 4a, NOT the original Windows TEMP path from `wait_for_done`.

   4c. **Atomically promote `.partial` to `.json`:**
   ```
   exec bash -lc 'python3 ~/.openclaw/scripts/streaming_io.py finalize ~/.openclaw/runs/{run_id}/video_result.json.partial'
   ```
   Verify the exec exit code is 0 (a non-zero exit means rename failed; surface a blocker — do NOT report success). After success, `~/.openclaw/runs/{run_id}/video_result.json` exists and orchestrator can consume it.

   4d. Return confirmation to orchestrator: file finalized, run_id.

---

## Output

`video_result.json` is a **streaming artifact** (per `~/.openclaw/docs/STREAMING_PROTOCOL.md`). The flow is:

1. Write `~/.openclaw/runs/{run_id}/video_result.json.partial` (with `progress` block) early, so orchestrator/watchers can see the stage is alive.
2. Update the `.partial` as the run advances (optional intermediate updates, required final overwrite with full payload).
3. On terminal success: `exec bash -lc 'python3 ~/.openclaw/scripts/streaming_io.py finalize ~/.openclaw/runs/{run_id}/video_result.json.partial'` — this atomic rename promotes `.partial` to `.json`.
4. On terminal failure: overwrite `.partial` with `status: "failed"` and **do NOT finalize**. Surface a blocker.

Schema for the final payload: `~/.openclaw/docs/RUN_LAYOUT.md`. The `progress` block is added by this protocol; consumers ignore it.

Return confirmation to orchestrator only after finalize succeeds. If generation failed, return the failure clearly — do not finalize a fabricated path.

---

## Completion gate (MUST)

Before any final reply, `sessions_yield`, or `NO_REPLY`, verify your declared deliverable on disk:

1. **Read** `~/.openclaw/runs/{run_id}/video_result.json` (the **finalized** file, not `.partial`) — must parse as JSON. If only `video_result.json.partial` exists and `video_result.json` does not, **finalize did not run or it failed**: surface a blocker. Do NOT report success.
2. **Verify common fields**:
   - `status == "done"` (not `queued` / `running` / `failed` / `partial` / `cancelled`)
   - `local_video_path` is a non-empty string referring to an actual file on disk
   - `job_id` is non-empty
3. **Mode-specific verification**:
   - **Single-shot mode** (no `shots` key in result): the three checks above are sufficient.
   - **Storyboard mode** (`shots[]` array present in result): strict mode requires
     - **every** entry in `shots[]` has `status == "done"` and a non-empty `local_video_path` (per-shot clip)
     - the top-level `local_video_path` (the stitched output) is the result of `video_stitch`, not a per-shot clip
     - if any shot in `shots[]` is non-done, the file should not have been written — surface a blocker instead

If `status` is a non-terminal value (`queued` / `running`): you exited too early.
- Single-shot mode: call `video_generate_wait_for_done(job_id=...)` again to continue waiting until terminal.
- Storyboard mode: this should not happen under strict mode — the per-shot wait+retry loop only writes the result file when every shot is `done`. If you see this, it's a bug; surface a blocker.

If `status` is a terminal failure (`failed` / `cancelled`): do NOT write `video_result.json`; return the failure to orchestrator instead.

If `status == "done"` but `local_video_path` is empty: do NOT mark complete — surface a blocker.

**Cap**: do not loop on the gate more than 2 times.

---

## Safety

- Do not rewrite the script beyond what is needed to form the generation request.
- Do not report success without a real `local_video_path`.
