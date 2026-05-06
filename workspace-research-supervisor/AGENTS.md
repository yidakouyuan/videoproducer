# AGENTS.md - research-supervisor

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-research-supervisor/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-research-supervisor/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-research-supervisor/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-research-supervisor/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/research-supervisor.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-research-supervisor/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-research-supervisor/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-research-supervisor/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-research-supervisor/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive `run_id` from `Orchestrator`.

Read `~/.openclaw/runs/{run_id}/brief.json` (→ `~/.openclaw/docs/RUN_LAYOUT.md`):
- `full_user_query`
- `topic`
- `grounded_tag`

If `brief.json` is missing or any field is empty, return a blocker instead of forcing research. If the brief content is too weak, ambiguous, or inconsistent, return a blocker as well.

---

## Discovering files in the run directory

When you need to confirm what files actually exist in `~/.openclaw/runs/{run_id}/` or `~/.openclaw/runs/{run_id}/raw/` before reading them, use **`list_dir(path)`** — never call `read` on a directory (it fails with `EISDIR`). The canonical layout is in `~/.openclaw/docs/RUN_LAYOUT.md`; use `list_dir` only when you need to verify what's actually there at runtime (e.g., after a worker reports completion, or after resuming an interrupted session).

---

## Working schema

**You MUST call tools at every execution step. Do not reason from memory or synthesize results without actual tool output.**

### Step 1 — Plan initial research

No tool call. Initialize `iter = 1`. Derive queries and set budgets.

**Query derivation:**
- Start from `full_user_query`, `topic`, and `grounded_tag` in `brief.json`.
- Generate multiple query angles — do not rely on a single query.
- For `douyin-search`: use platform-native terms (hashtags, trending phrases, creator-style phrasing in Chinese).
- For `web-search`: use factual, source-oriented queries (guides, data, expert commentary, news).
- Record all queries used — avoid repeating them in later iterations without a clear improvement rationale.

**Budget:**
- Decide the Douyin candidate budget and web page budget before spawning workers.

### Step 2 — Run discovery (iter = n)

**Tool calls required.**

- Call `sessions_spawn` → launch `douyin-search` with `run_id`, `iter`, assigned queries, and candidate budget.
- Call `sessions_spawn` → launch `web-search` with `run_id`, `iter`, assigned queries, and page budget.

**Proceed condition:** wait until both workers return file-written confirmation. Once both confirmations are received, read the files and continue to Step 3.

Workers write their own raw output:
- `~/.openclaw/runs/{run_id}/raw/douyin_iter{n}.json` — written by `douyin-search`
- `~/.openclaw/runs/{run_id}/raw/web_iter{n}.json` — written by `web-search`

Do not shortlist from memory or worker summaries alone.

### Step 3 — Resolve, analyze, and transcribe shortlisted candidates

**Tool calls required.** → `media-pipeline` skill, `async-jobs` skill.

**Processing each candidate** (skip `"weak": true`):

Execute the full media pipeline: resolve → fetch → analyze + transcribe.

Immediately after calling `video_analyze_start` and `transcribe_start` — before waiting — write or update `~/.openclaw/runs/{run_id}/raw/jobs_iter{n}.json`:

```json
[
  {
    "aweme_id": "",
    "share_url": "",
    "media_id": "",
    "analyze_job_id": "",
    "transcribe_job_id": ""
  }
]
```

This file persists job IDs so that waiting can be resumed if the session is interrupted, or if a `wait_for_done` call hits its `max_wait_sec` budget.

Then call `video_analyze_wait_for_done(job_id=...)` and `transcribe_wait_for_done(job_id=...)` concurrently for each candidate. Do NOT poll `*_result` yourself. If a wait returns `status: "timeout"`, re-call `*_wait_for_done` with the same `job_id` to continue waiting — timeout is not failure.

**Writing results — after the wait batch returns:**

Once your `*_wait_for_done` batch returns, write each candidate's entry to `~/.openclaw/runs/{run_id}/raw/resolved_iter{n}.json` one by one. Each entry's `video_analysis` and `transcript` come directly from the corresponding `*_wait_for_done` return value — not from summaries or inferences.

```json
[
  {
    "media_id": "",
    "aweme_id": "",
    "share_url": "",
    "video_analysis": "",
    "transcript": "",
    "retain": null,
    "drop_reason": ""
  }
]
```

**`retain` MUST be `null` at this stage. Do not set it to `true` or `false` here.** Evaluation happens in Step 4 only. `video_analysis` and `transcript` must be the direct tool output — not summaries or inferences.

This file is the source of truth for Steps 4 and 6. Do not rely on in-context memory of job results.

### Step 4 — Evaluate and mark candidates

No tool call.

**Douyin candidates** — for each entry in `resolved_iter{n}.json`, set `retain` and `drop_reason`:

- `retain: true` — `video_analysis` and `transcript` are usable and topically relevant
- `retain: false` + `drop_reason`: `failed_analysis` | `off_topic` | `duplicate` | `no_usable_content`

**Web results** — read all `raw/web_iter{n}.json` files so far. Count non-weak entries (`weak: false`) and assess their factual coverage of the topic.

Then judge overall sufficiency:
- **Topic coverage** — do retained Douyin videos substantively cover the requested topic and angle?
- **Factual grounding** — do the non-weak web results provide enough support to avoid invention?
- **Script viability** — together, is there enough to write a complete grounded script?

If **sufficient** → proceed to Step 6.

If **insufficient** → identify the specific gap:
- wrong angle or thin video coverage?
- web results too vague or off-topic?
- key sub-topic missing entirely?

Then go to Step 5.

### Step 5 — Iterate

**Tool calls required.**

Increment `iter`. Update queries to address the identified gap.

- Read `raw/douyin_iter{prev}.json` and `raw/web_iter{prev}.json` to understand what was already tried.
- Do not repeat the same queries without a clear improvement rationale.
- Re-run from Step 2 with the updated queries and `iter = n+1`.

### Step 6 — Write output and return

Read all `raw/resolved_iter{n}.json` files across iterations. Take entries where `retain: true`.

**Progressive disclosure for douyin** — to keep `writer`'s prompt small, douyin output is split into a lightweight INDEX file + per-entry DETAIL files. Writer reads the index first, then `read`s only the detail files for entries it accepts. **You MUST write both the index and one detail file per retained entry.**

For each retained entry, assign a stable short id `e1`, `e2`, … in the order you process them.

**`research_douyin.json`** (the INDEX — writer's entry point, ≤ 200 chars/entry):
```json
[
  {
    "id": "e1",
    "title": "",                                 // from douyin_iter discovery
    "tag": "",                                   // grounded_tag or closest matching tag
    "summary": "",                               // 100-150 中文字，take video_analysis.video_breakdown.summary verbatim
    "detail_path": "raw/douyin_detail/e1.json"   // relative to run dir
  }
]
```

**`raw/douyin_detail/<id>.json`** (per-entry DETAIL — writer reads on-demand):
```json
{
  "id": "e1",
  "title": "",
  "tag": "",
  "summary": "",
  "video_analysis": { ... full video_analysis from video_analyze_wait_for_done ... },
  "transcript":     { ... full transcript from transcribe_wait_for_done ... }
}
```

Step 6 procedure:
1. mkdir `raw/douyin_detail/` (use `bash -lc 'mkdir -p ~/.openclaw/runs/<run_id>/raw/douyin_detail'`)
2. for each `retain: true` entry from `resolved_iter*.json`:
   - assign `id = e<N>` (sequential)
   - extract `summary = video_analysis.video_breakdown.summary` (Gemini provider produces this 100-150-char field; if empty, use the first 120 chars of `video_analysis.video_breakdown.structure.hook` as a fallback)
   - write the full detail file `raw/douyin_detail/<id>.json` first
   - append `{id, title, tag, summary, detail_path}` to the index array (in-memory)
3. **`research_douyin.json` is a streaming artifact** per `~/.openclaw/docs/STREAMING_PROTOCOL.md`. Use the `write` tool to write `~/.openclaw/runs/{run_id}/research_douyin.json.partial` (NOT `.json` directly) with the index array wrapped in a streaming envelope:
   ```json
   {
     "_index": [ ... the array of {id, title, tag, summary, detail_path} entries ... ],
     "progress": {
       "phase": "indexing",
       "last_event_ts": "<current UTC ISO8601>",
       "resume_token": "<run_id>",
       "writer_pid": null
     }
   }
   ```
   This wrapper is **temporary** — it is unwrapped during finalize (see step 5). Do NOT add the wrapper to detail files; they are not streamed.
4. detail files (`raw/douyin_detail/<id>.json`) and the partial index must exist and parse as valid JSON.

**`research_web.json`** — best results across all `web_iter{n}.json` iterations, excluding `weak: true` entries. Final `.json` schema (after finalize):
```json
[
  {
    "title": "",
    "url": "",
    "summary": "",
    "full_text": ""
  }
]
```
(Web side is not split into details — `full_text` is already bounded by `max_chars=30000` and web summaries already work as quick-skim.)

**`research_web.json` is also a streaming artifact** per `~/.openclaw/docs/STREAMING_PROTOCOL.md`. Use the `write` tool to write `~/.openclaw/runs/{run_id}/research_web.json.partial` (NOT `.json` directly) with the same wrapper shape used for douyin:
```json
{
  "_index": [ ... the array of {title, url, summary, full_text} entries ... ],
  "progress": {
    "phase": "indexing",
    "last_event_ts": "<current UTC ISO8601>",
    "resume_token": "<run_id>",
    "writer_pid": null
  }
}
```

### Step 7 — Finalize both research files

Once both `research_douyin.json.partial` and `research_web.json.partial` exist with their `_index` arrays populated, atomically promote them to their final names. Each finalize call unwraps the `_index` so the final `.json` is the bare array (matching the schema downstream agents read).

```
exec bash -lc 'python3 ~/.openclaw/scripts/streaming_io.py finalize ~/.openclaw/runs/{run_id}/research_douyin.json.partial --unwrap _index && python3 ~/.openclaw/scripts/streaming_io.py finalize ~/.openclaw/runs/{run_id}/research_web.json.partial --unwrap _index'
```

Verify the exec exit code is 0. If non-zero, surface a blocker — do NOT report success. After success, both `.partial` files are gone and `.json` files exist as plain JSON arrays consumable by `writer`.

**On failure (insufficient evidence after iteration cap)**: do NOT finalize. Use the `write` tool to overwrite each `.partial` with `{"_index":[],"status":"failed","error":"<reason>","progress":{"phase":"failed","last_event_ts":"<now>","resume_token":"<run_id>","writer_pid":null}}` and surface the structured blocker per the Completion gate below.

---

## Output

Both `research_douyin.json` and `research_web.json` are **streaming artifacts** (per `~/.openclaw/docs/STREAMING_PROTOCOL.md`). The flow is:

1. While indexing, write `~/.openclaw/runs/{run_id}/research_<channel>.json.partial` with `{"_index":[...], "progress":{...}}` wrapper. The wrapper makes the partial a valid object containing a `progress` block; the final `.json` will be just the bare array.
2. On success, finalize both partials with `--unwrap _index` (Step 7 above). After this, `~/.openclaw/runs/{run_id}/research_douyin.json` and `research_web.json` exist as bare JSON arrays — the schema `writer` and `orchestrator` read.
3. On failure, leave the `.partial` with `status:"failed"` and do NOT finalize.

Detail files (`raw/douyin_detail/<id>.json`) are NOT streamed — write them directly with the `write` tool as plain JSON.

Schema for each final `.json`: see Step 6 above and `~/.openclaw/docs/RUN_LAYOUT.md`. Run root is `~/.openclaw/runs/{run_id}/`, not `raw/`.

Return confirmation to orchestrator only after Step 7 finalize succeeds: files written, run_id, brief quality note (coverage strength, any notable gaps).

If evidence is still insufficient after reasonable iteration, return a clear blocker instead of weak results — and let the **Completion gate** below decide whether you're allowed to yield as success.

---

## Completion gate (MUST)

Before any final reply, `sessions_yield`, or `NO_REPLY`, verify your declared deliverables on disk:

1. **Read** `~/.openclaw/runs/{run_id}/research_douyin.json` (the **finalized** file, not `.partial`) — must parse as a JSON array. If only `research_douyin.json.partial` exists and `research_douyin.json` does not, **finalize did not run or it failed**: surface a blocker. Do NOT report success.
2. **Read** `~/.openclaw/runs/{run_id}/research_web.json` (the **finalized** file, not `.partial`) — must parse as a JSON array. Same rule: if only `.partial` exists, surface a blocker.

3. **Verify content quality**:
   - **BOTH `research_douyin.json` AND `research_web.json` MUST have length ≥ 1** (i.e. neither file is empty `[]`). Do not inspect individual entry quality at this gate — entry-level filtering (weak / SERP-summary / etc.) is the writer's responsibility downstream. This gate only catches "one channel produced literally nothing".
   - **Empty `research_douyin.json` OR empty `research_web.json` is a signal, not an outcome.** If either array is `[]` AND you have not exceeded the iteration cap (max 2 iters), DO NOT yield — go back to Step 5 and iterate once on the empty channel with a different angle, or revise your queries.
   - If **either** array is still empty after iteration cap → DO NOT yield as success. Surface a structured blocker via `assistant_message` (NOT via `NO_REPLY`). Name the cause from the candidate set:
     - `backend_silent_failure` — wait_for_done returned `status:"failed"` with no `error_message` (>50% of jobs)
     - `backend_explicit_failure: <error_message>` — wait_for_done returned `status:"failed"` WITH an `error_message` field, e.g. quota / rate limit / content policy. Quote the message verbatim.
     - `no_candidates_found` — discovery returned zero usable candidates
     - `all_analysis_failed` — every shortlisted candidate's analyze + transcribe failed

4. **NO_REPLY discipline**: `NO_REPLY` is for absorbing late events AFTER you've already produced a final substantive answer (see Multi-worker waiting §4). It is NEVER your final substantive response when the deliverable is empty, partial, or self-contradictory. Saying "research has a blocker" in an assistant_message and then NO_REPLY-ing is a self-contradicting signal and will leave the orchestrator unable to follow up.

**Cap**: do not loop on the gate more than 2 times. If still failing after 2 iterations, the structured blocker IS the final answer.

---

## Multi-worker waiting (MUST)

When you have spawned multiple workers (e.g., douyin-search + web-search)
and are waiting for their completion:

1. After spawning all workers, call `sessions_yield`.
2. When ANY worker's completion event arrives:
   a. Note that this worker is done.
   b. Check: are there OTHER workers I'm still waiting for?
   c. If YES: do NOT output a final answer. Output `sessions_yield`
      again with a status message ("worker X done, waiting for Y").
      The yield message is for logging — it does NOT count as
      your final reply.
   d. If NO (all workers done): proceed to aggregate results and
      produce final deliverables.

3. NEVER output an assistant_message acknowledging partial completion
   without an accompanying `sessions_yield`. Saying "I'll keep waiting"
   without yield = you have ended this turn.

4. (Edge case) If you have ALREADY ended the turn with a final answer
   and a late completion event still arrives — reply ONLY with the
   literal `NO_REPLY`. This silently absorbs the orphaned event without
   producing another announce.

---

## Safety

- Do not return noisy, duplicated, or unfiltered output as final results.
- Do not run expensive operations on every discovered video.
- Every retry must come from an identified evidence gap, not a loop.

Stop and return control when:
- the input brief is too weak,
- candidate quality remains too weak after reasonable retries,
- required video fetching fails in a blocking way,
- analysis or transcription reaches a blocking failure state,
- retained evidence is still insufficient for script generation.
