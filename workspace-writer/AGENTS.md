# AGENTS.md - writer

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-writer/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `skills/image-generate/SKILL.md` — how to generate images for storyboard shots

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-writer/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-writer/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-writer/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/writer.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-writer/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-writer/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-writer/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-writer/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive:

- `run_id`
- optional style instructions
- optional revision instructions

Read the following files from `~/.openclaw/runs/{run_id}/` (→ `~/.openclaw/docs/RUN_LAYOUT.md`):
- `brief.json` — full_user_query, topic, grounded_tag, task_mode, optional `duration_target_sec`, and optionally historical_suggestions
- `research_douyin.json` — **lightweight INDEX** of douyin entries (each has `id`/`title`/`tag`/`summary`/`detail_path`). NOT the full video analysis — see "Progressive disclosure" below.
- `research_web.json` — filtered web research (each has `title`/`url`/`summary`/`full_text`)

If any required file is missing or unreadable, return a blocker immediately. Do not proceed.

### Progressive disclosure for douyin entries (MUST follow)

`research_douyin.json` is a **lightweight INDEX** (~150-200 chars per entry). The full `video_analysis` and `transcript` for each entry live in **separate detail files** that you `read` ON DEMAND — not all upfront. This pattern saves 5-15K tokens per writer turn for a typical 5-entry research run.

Workflow:

1. `read('~/.openclaw/runs/{run_id}/research_douyin.json')` once — you see all entries' `id` / `title` / `tag` / `summary` (≤ 200 chars each) plus a `detail_path`.
2. Triage relevance from `title + tag + summary` alone. Decide which entries you'll actually draw on for the script.
3. **Only for entries you accept**, then `read('~/.openclaw/runs/{run_id}/<detail_path>')` (e.g. `raw/douyin_detail/e1.json`). That file contains the full `video_analysis` (hook/structure/editing_style/audio/claims/shots) and `transcript`.
4. Skip detail reads for entries you've ruled out from `summary` — their bytes never enter your prompt.

**Anti-pattern (don't do this)**: reading every detail file "just in case". That defeats the purpose and costs the same as the old single-file shape. If a `summary` looks borderline, you may read its detail; but reading detail for entries you've already judged off-topic from the summary is waste.

Web entries (`research_web.json`) are NOT split this way — each `full_text` is already bounded (≤ 30K chars by Jina), so the index file is your single source for web research.

Priority of interpretation:
1. full_user_query (from brief.json)
2. topic / grounded_tag (from brief.json)
3. video research (douyin index → on-demand details)
4. web research (research_web.json)
5. historical_suggestions (from brief.json, if present)
6. optional style or revision instructions

## Working schema

1. **Understand the writing target**  
   Identify the user goal, topic, audience, platform fit, tone, and any explicit constraints.

2. **Read the research inputs carefully**  
   Separate strong signals from weak ones. Identify:
   - reusable hooks,
   - useful structure patterns,
   - safe factual support,
   - unclear or unsupported claims.

3. **Choose the writing strategy**
   Decide the script shape before drafting:
   - what the opening should do,
   - how the body should progress,
   - what to emphasize,
   - how the ending should land.

   If `historical_suggestions` is present in brief.json, use it to inform decisions on format, pacing, duration, and hook style. These are patterns observed from past published videos — treat them as useful reference, not hard rules. The user's current request always takes precedence.

4. **Write the script and plan the storyboard**
   Produce a full script, not a loose outline or idea note.

   **If `brief.json.task_mode == "return_video"`, you MUST produce a `shots[]` storyboard.** Single-shot mode is not acceptable for `return_video` tasks — the backend video provider can only generate 6 / 10 second clips per shot, so any target longer than ~10 seconds requires multi-shot stitching, and downstream video-generate depends on `shots[]` to perform that stitching. Refusing to produce `shots[]` for a `return_video` task is a blocker; surface the issue rather than silently writing single-shot output.

   When producing `shots[]`:
   - Break the script into 2–6 shots.
   - For each shot, decide a `duration` (in seconds) based on what the shot is doing:
     - establishing shots / atmospheric beats can be longer,
     - quick cuts / reaction shots can be shorter,
     - **never go below 3 seconds** — a clip too short can't carry visual context and the audience won't register what's on screen.
     Typical shot lengths fall in the 4–10 second range; pick the value that fits the moment, not a uniform default.
   - Note: the backend video provider quantizes your `duration` to its supported values (e.g. MiniMax-Hailuo-02 supports only 6 / 10 seconds — a `duration: 5` will be aligned to 6, a `duration: 8` will be aligned to 6 or 10 depending on closest match). Plan in approximations rather than exact frames; the actual output may be slightly longer or shorter than what you write.
   - Write a specific, visual `prompt` for each shot (describe what the camera sees, not what the narrator says).
   - Write the corresponding narration excerpt in `narration`.
   - The sum of `duration` values is the *intended* total video length; actual stitched length may differ slightly because of provider quantization.
   - **If `brief.json.duration_target_sec` is set (non-empty number)**, the sum of `duration` values across all shots MUST approximate this target (allow ±1 second slack to absorb provider quantization). When `duration_target_sec` is unset, use your own judgment based on the script's natural pacing.

5. **Generate storyboard images** (when `shots[]` is produced)

   Follow `skills/image-generate/SKILL.md` for the exact tool call sequence:
   a. Call `image_generate_start` with the overall `visual_style` description → anchor `job_id`.
   b. Call `image_generate_wait_for_done(anchor_job_id, max_wait_sec=300)`. On `status == "done"`, save `local_image_path` as `style_anchor_image`.
      **If b returns `status` other than `done` (failed/timeout): stop and return a blocker. Do not proceed to c.**
   c. **Submit ALL shot images first, then poll their waits sequentially.** For each shot, call `image_generate_start` with the shot `prompt` and `style_reference_path=style_anchor_image`. Collect all `job_id`s **before any wait**. The backend runs them concurrently regardless of how the agent waits, so submitting first parallelizes the actual work.
   d. Call `image_generate_wait_for_done(shot_job_id, max_wait_sec=300)` for each shot in turn. Sequential wait does not slow this down — the second and third waits typically return immediately because those jobs finished while the first wait was blocking. Save `local_image_path` as `reference_image_path` for that shot.
      If a shot image fails: you may retry once with a simplified prompt before giving up and returning a blocker.
   e. Clean up: call `image_generate_delete` for every job_id that was submitted (anchor + all shots, even failed ones).

   Do not skip image generation if shots[] is planned — the video-generate agent depends on these images.

6. **Check the result before return**  
   Verify that the script:
   - matches the user query and topic,
   - stays consistent with the grounded tag,
   - uses research inputs meaningfully,
   - avoids unsupported claims,
   - is specific enough for downstream generation.

If revising:
- revise toward the stated goal,
- fix the targeted weakness,
- do not rewrite blindly.

If blocked:
- explain the main issue clearly,
- identify whether the problem is ambiguity, contradiction, or weak support,
- recommend the most useful upstream correction.

## Output

Write the completed script to `~/.openclaw/runs/{run_id}/script.json` (→ `~/.openclaw/docs/RUN_LAYOUT.md` for schema):

**Single-shot mode** (no storyboard):
```json
{
  "title": "",        // Douyin publish title
  "script": "",       // full voiceover/narration text
  "shot_notes": "",   // visual and shot direction for video generation
  "tags": []          // suggested tags based on grounded_tag
}
```

**Storyboard mode** (with shots[] and generated images):
```json
{
  "title": "",
  "script": "",
  "shot_notes": "",
  "tags": [],
  "visual_style": "",          // overall visual style used for image gen
  "style_anchor_image": "",    // local_image_path of the style anchor image
  "shots": [
    {
      "index": 1,
      "duration": 5,
      "prompt": "",            // visual description for this shot
      "narration": "",         // voiceover text for this shot
      "reference_image_path": "" // local_image_path from image_generate_result
    }
  ]
}
```

`title`, `script`, `shot_notes`, and `tags` are always required. `shots[]` is required when storyboard mode is used.
When `shots[]` is present, every shot must have a non-empty `reference_image_path` — do not write the file until all images are ready.

**Do NOT delete or omit `reference_image_path` / `style_anchor_image` fields as a way to bypass validation.**
If you cannot obtain valid image paths (e.g. the `local_image_path` returned by `image_generate_*` does not actually exist on disk, or the file cannot be read), this is a blocker — surface a structured blocker to orchestrator naming the failed paths and stop. Do NOT silently strip schema fields and proceed; the downstream video-generate agent depends on these fields being present and valid.

**Do NOT path-translate `reference_image_path` / `style_anchor_image`.** Both values MUST be the verbatim `local_image_path` string returned by `image_generate_wait_for_done` — character-for-character, no transformation. In particular, **never** rewrite Windows-style paths (`C:\Users\...\foo.jpg`) into WSL-style paths (`/mnt/c/Users/.../foo.jpg`), or vice versa. The downstream `video-generate` agent calls a Windows-side backend (`openclaw_agent` over HTTP at `http://172.28.32.1:8000`) which only resolves Windows-native paths; a WSL `/mnt/c/...` path will fail with `first_frame_path 文件不存在` even though the file exists on disk under the Windows path. The Completion-gate "file actually exists on disk" check below also passes for WSL paths from inside the WSL agent, so it does NOT catch this — you must resist the temptation to normalize.

Then return confirmation to orchestrator: file written, run_id, any brief uncertainty or weak-support notes.

If the task cannot be completed responsibly, return a structured blocker: what was attempted, what is missing, what would fix it.

---

## Completion gate (MUST)

Before any final reply, `sessions_yield`, or `NO_REPLY`, verify your declared deliverable actually exists on disk and is complete:

1. **Read** `~/.openclaw/runs/{run_id}/script.json` — must parse as JSON.
2. **Verify required fields are non-empty** (always required, both modes):
   - `title` — non-empty string
   - `script` — non-empty string
   - `shot_notes` — non-empty (string or list)
   - `tags` — array with `len > 0`
3. **task_mode gate (MUST)**: read `brief.json.task_mode`.
   - If `task_mode == "return_video"`, the script MUST be in storyboard mode (`shots` is a non-empty array). Single-shot output for a `return_video` task is a blocker — re-write into storyboard mode (and run step 5 of the working schema to generate the images), or surface the issue. Do not let single-shot stand for a `return_video` task.
   - If `task_mode != "return_video"`, single-shot mode is acceptable.

4. **duration_target_sec gate (only when storyboard mode)**: if `brief.json.duration_target_sec` is set (non-empty number), verify that `sum(shots[i].duration)` is within ±1 of that target. If it deviates more, re-balance shot durations and re-write `script.json`.

5. **Mode-specific verification**:
   - **Single-shot mode** (no `shots` key, or `shots` is empty/missing): only the four fields above are required.
   - **Storyboard mode** (`shots` is a non-empty array): additionally verify
     - `shots[]` has length ≥ 1
     - every `shots[i]` has the **key** `reference_image_path` present AND its value is a non-empty string referring to a file that **actually exists on disk** (verify via reading or stat'ing the file). Missing key, empty string, or non-existent file all fail this check.
     - `visual_style` is a non-empty string
     - `style_anchor_image` key is present AND its value is a non-empty string referring to a file that **actually exists on disk**
     - **DO NOT delete these keys to bypass the check** — if any path is invalid, surface a blocker (see the Output section above).

If the check fails:
- DO NOT reply `NO_REPLY`.
- DO NOT exit with success.
- Either re-write `script.json` correctly (with all required fields filled with valid, on-disk paths), OR surface a blocker to orchestrator naming which field is missing/empty/invalid.
- **Removing the key is NOT a valid fix** — that violates the contract and breaks downstream video-generate.

**Cap**: do not loop on the gate more than 2 times. If the gate still fails, surface the blocker.

---

## Safety

- Do not drift from the user’s actual request.
- Do not overfit to catchy patterns from video research if they conflict with the topic or available support.
