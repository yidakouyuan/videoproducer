# AGENTS.md - orchestrator

## Environment

- `exec` shell: Windows cmd.exe (NOT bash). For unix pipelines use `bash -lc '...'`.
- workdir: already your workspace. Never run `pwd` / `wsl.exe pwd` / `powershell pwd` to check.
- runs root: `~/.openclaw/runs/`  (Windows form: `C:\Users\Administrator\.openclaw\runs\`).

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-orchestrator/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `~/.openclaw/docs/EXEC_ENV.md` — exec is cmd.exe, not bash; cmd-equivalents and `bash -lc` escape hatch

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-orchestrator/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-orchestrator/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-orchestrator/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/orchestrator.md` — stage playbook (skip if missing). Note: `~/.openclaw/insights/suggestions.json` is read at Step 1 below — do not duplicate that read here.
5. **Check for promotion proposals** — if `~/.openclaw/workspace-orchestrator/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-orchestrator/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-orchestrator/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge (process some clusters and leave others without deleting).

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-orchestrator/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Routing auto-chain (MUST)

The routing chain `tag-matcher → research-supervisor → writer → video-generate → (Step 6 deliver video)` auto-executes end-to-end without user check-ins. Concretely:

1. **Each worker's completion push triggers the next spawn IN THE SAME TURN.** When you receive an `[Internal task completion event]` from worker X, your turn does:
   - (a) verify X's on-disk artifact (per Step N spec for that worker)
   - (b) optionally send a result-summary `message` to user (FYI, no question)
   - (c) IMMEDIATELY call `sessions_spawn` for worker X+1 (or, after video-generate, run Step 6 deliver-video)
   - (d) only THEN `sessions_yield` to wait for the next worker's push

   **DO NOT `sessions_yield` / `NO_REPLY` between (b) and (c).** DO NOT wait for the user to type "继续 / 好 / 推进吧 / OK" — the chain proceeds automatically the instant the previous worker's artifact is verified.

2. **Status & summary messages MUST be informational only.** Never include "要继续吗 / 是否推进 / 确认一下 / 需要我继续吗 / [yes]/[no]" or any wording that implies the user must respond before the next worker starts. Phrase as updates ("X 已完成，主要结果是 …，正在启动 Y"), not as decision points. The user can interrupt at any time by sending a new message; you don't need to invite them to.

3. **The chain proceeds even when a worker's output looks subjectively suboptimal** (low-quality summary, weak research signal, generic script). Quality filtering is downstream agents' job; orchestrator's only failure-stop conditions are (a) hard blocker reported by the worker, (b) on-disk verification failure.

4. **The only three legitimate places to pause for user input:**
   - Initial brief intake — if the user query is ambiguous AND the ambiguity blocks tag-matcher, ask one clarifying question. Otherwise just run.
   - Publish gate — when `task_mode = publish_directly`, confirm once before sending to `publisher` (see "If `task_mode = publish_directly`" subsection in Step 6).
   - Terminal blocker — a worker reports `failed` AND the failure is unrecoverable; surface to user and yield.

5. **After Step 5 (video-generate) completes successfully, IMMEDIATELY run Step 6 (deliver video) in the same turn.** Do NOT wait for the user to say "把视频发我 / 现在怎么样了". The video gets staged and `message`-sent the moment `video_result.json` finalizes.

This rule overrides any per-step phrasing elsewhere in this file that may read like a check-in invitation.

## Input

You receive the full user query.

Before delegation, normalize it into a minimal internal brief and generate or accept a `run_id`:

- `run_id` = timestamp `YYYYMMDD_HHMMSS`, unless the incoming request explicitly provides `run_id` from an external Message Adapter. In that case, use the provided `run_id` exactly.
- `raw_request`
- `task_mode`: `return_video` | `publish_directly`
- `topic`
- `duration_target_sec` (optional): integer seconds parsed from explicit time clues in the user's query (e.g. "30 秒" → 30, "一分钟" → 60, "两分钟左右" → 120). If the user does not state a duration, leave this field unset / null — writer will use natural pacing.
- `channel` (optional): current delivery channel, e.g. `telegram`, `whatsapp`, or `feishu`.
- `reply_target` (optional): platform-specific conversation id for final delivery.
- `source_message_id` (optional): platform message id for traceability.

The `run_id` is the primary state anchor for this pipeline run. All downstream agents receive it instead of large data payloads. → See `~/.openclaw/docs/RUN_LAYOUT.md` for the shared run directory structure.

For external Message Adapter entries (for example Feishu), `~/.openclaw/runs/{run_id}/entry_message.json` and `run_status.json` may already exist before Step 1. If present, read `entry_message.json` first and treat it as the authoritative source for `channel`, `reply_target`, `source_message_id`, and raw input text; keep `run_status.json` for the external adapter to monitor.

## Working schema

### Step 1 — Intake

- Read the full user query.
- Identify the main topic.
- Determine `task_mode`: `return_video` | `publish_directly`.
- **Parse `duration_target_sec` from explicit time clues**: scan the user query for phrases like "30 秒 / 60 秒 / 一分钟 / 两分钟 / 30 seconds / one minute" and convert to integer seconds. If the query says "30 秒左右" or "差不多一分钟", still capture the round value (30 / 60). If no duration clue is present, leave `duration_target_sec` unset — do not invent a default.
- Generate `run_id = YYYYMMDD_HHMMSS`, unless the external request already supplied `run_id`; external `run_id` wins.
- Use `exec` to create the run directory: `mkdir -p ~/.openclaw/runs/{run_id}/raw`

**Check historical suggestions (optional):**
If `~/.openclaw/insights/suggestions.json` exists, read it. Use your own judgment to decide whether its contents are relevant to this request. If relevant, include a `historical_suggestions` field in brief.json. If not relevant, omit it entirely — do not force a fit.

- Write `~/.openclaw/runs/{run_id}/brief.json` with `run_id`, `full_user_query`, `topic`, `task_mode`, `duration_target_sec` (only when parsed from the query — omit the field entirely otherwise; do not write `null` or `0`), `channel`, `reply_target`, `source_message_id` when present, and `historical_suggestions` (if applicable). (Leave `grounded_tag` empty — fill after Step 2.)

Do not start downstream execution before the directory exists and brief is written.

### Step 2 — Topic grounding

Send to `tag-matcher`:

- `run_id`

**Immediately after spawn** — send the user a progress ack via `message.send`:
> `[选题 grounding] 已启动，预计约 1–2 分钟。`

tag-matcher reads `brief.json` from `~/.openclaw/runs/{run_id}/`.

Receive from `tag-matcher`:

- a more specific grounded tag
- tag-related grounding context

Update `~/.openclaw/runs/{run_id}/brief.json` with `grounded_tag`. The Orchestrator may lightly clean or select this result, but must not replace specialist judgment.

### Step 3 — Research

Send to `research-supervisor`:

- `run_id`

**Immediately after spawn** — send the user a progress ack via `message.send`:
> `[研究检索] 已启动，预计约 15–20 分钟。这是最耗时阶段，supervisor 在 plugin 内并行等待视频分析与转写，期间不会有中间消息属正常。`

research-supervisor reads `brief.json` from `~/.openclaw/runs/{run_id}/`.

Receive from `research-supervisor`: confirmation that `research_douyin.json` and `research_web.json` have been written to `~/.openclaw/runs/{run_id}/`.

**After receiving confirmation, read both files yourself and verify** (mirror the Step 5 video_result check — do NOT trust supervisor's text claim alone, since supervisor's reply can be self-contradictory; only the on-disk artifacts are ground truth):

Both `research_douyin.json` and `research_web.json` are **streaming artifacts** per `~/.openclaw/docs/STREAMING_PROTOCOL.md`. Verify each via stat:
- If `<name>.json` exists → it's the **finalized** array; read and check length ≥ 1.
- Else if `<name>.json.partial` exists → supervisor never finalized. Read the `.partial` to see the failure record. If it has `status:"failed"`, treat it as a blocker with the recorded error. If not, treat it as `silent_failure` (supervisor reported success but didn't finalize).
- Else neither file exists → blocker `not_produced`.

For finalized files, both arrays must have length ≥ 1 (neither is empty `[]`). Do not inspect individual entry quality at this gate — entry-level filtering is the writer's job; this gate only catches "the upstream produced nothing for one of the two channels".

If verification fails on **either** channel, OR if supervisor's reply text contains keywords like `blocker` / `insufficient` / `failed` / `silent_failure`, do NOT proceed to Step 4. Instead, surface to user via `message.send`:

> `[研究阶段] 未能拿到可用证据。具体原因（如 supervisor 在回执里给出）：<copy supervisor's blocker reason verbatim>。可能是后端 Gemini 服务对该主题的内容限制、quota / rate limit，或上游网络问题。建议：尝试不同主题、稍后重试、或检查 backend 日志确认具体错误。`

This is the **failure-path exception** per "Routing auto-chain" rule 4 (terminal blocker): yield after surfacing the blocker. Do NOT silently spawn writer with empty research — that produces an unsalvageable downstream cascade. **(Successful research must IMMEDIATELY proceed to Step 4 in the same turn — no user prompt, no "要继续吗" check-in.)**

### Step 4 — Writing

Send to `writer`:

- `run_id`

**Immediately after spawn** — send the user a progress ack via `message.send`:
> `[脚本撰写] 已启动，预计约 1–2 分钟。`

Writer reads research files from `~/.openclaw/runs/{run_id}/` and writes `script.json` there.

Receive from `writer`: confirmation that `script.json` has been written.

### Step 5 — Video generation

Send to `video-generate`:

- `run_id`

**Immediately after spawn** — send the user a progress ack via `message.send`:
> `[视频生成] 已启动，预计约 2–3 分钟。`

video-generate reads `script.json` from `~/.openclaw/runs/{run_id}/` and writes `video_result.json` there. The artifact is **streaming** per `~/.openclaw/docs/STREAMING_PROTOCOL.md` — video-generate writes `video_result.json.partial` early (so you can monitor progress) and atomically promotes it to `video_result.json` only on terminal success.

Receive from `video-generate`: confirmation that `video_result.json` has been finalized.

After receiving confirmation, verify on disk (do NOT trust the agent's text alone):
- If `~/.openclaw/runs/{run_id}/video_result.json` exists (the **finalized** file) → read it and verify `status == "done"` and `local_video_path` is non-empty. Proceed to Step 6.
- Else if only `video_result.json.partial` exists → finalize did not run. Read the `.partial`:
  - If `status:"failed"` → blocker with the recorded error.
  - Otherwise → `silent_failure` (agent reported success but didn't finalize). Surface a blocker.
- Else neither exists → blocker `not_produced`.

If verification fails on any path, do not proceed to Step 6. Return a blocker — the video is not ready.

**Mid-stage progress check (optional)**: while you are yielded waiting for video-generate, you may peek at progress without consuming the artifact:
```
exec bash -lc 'python3 ~/.openclaw/scripts/streaming_io.py read ~/.openclaw/runs/{run_id}/video_result.json --role watcher'
```
This returns the partial payload annotated with `_partial: true`, `_age_sec`, `_writer_alive`. Use only if a stall is suspected; routine polling is unnecessary.

### Step 6 — Deliver results to user

Read from `~/.openclaw/runs/{run_id}/`:
- `video_result.json` → `local_video_path`
- `script.json` → complete script
- `brief.json` → `grounded_tag`

**Sending the video — TWO required tool calls. The actual tool name is `message` (NOT `message.send`). Writing `MEDIA:/home/...` or any path string into your final assistant text does NOT upload the file — OpenClaw will only deliver media when you explicitly call the `message` tool with a `media` argument.**

The path in `local_video_path` is a Windows path (e.g., `C:\Users\...`). The `message` tool cannot use a Windows path directly. Workflow:

1. **Call `stage_video_for_send`** to convert and stage the file:

   `stage_video_for_send(source_path=<local_video_path>, run_id=<run_id>)`

   Returns either:
   - `{ ok: true, staged_path: "/home/administrator/.openclaw/runs/<run_id>/video.mp4" }` → use `staged_path` verbatim in step 2. Do NOT modify it.
   - `{ ok: false, status: "error", error: "..." }` → report the exact error to the user; do NOT attempt to send a raw or guessed path.

2. **Call `message` with `action: "send"` and pass `staged_path` as the `media` field.** Use channel/target from your delivery context (the same channel/target you've been replying on).

   If `channel == "feishu"` and the current OpenClaw runtime does not expose a native Feishu `message` channel, do not fabricate a `message` call. Ensure `video_result.json` is finalized and write `delivery_result.json` with `{"channel":"feishu","target":"<reply_target>","status":"pending_external_adapter"}`. The FastAPI Feishu Message Adapter watches the run result and sends the final link/path back to the Feishu chat.

   Example call (mirror this shape exactly):
   ```
   message(
     action="send",
     channel="telegram",            # use the current delivery channel
     target="<your delivery target id, e.g. 8762244147>",
     media="<staged_path from step 1>",
     caption="**grounded tag**\n<grounded_tag>\n\n**完整脚本**\n<full script text>"
   )
   ```

   The `caption` field is where you put the grounded tag and complete script — that's how the user receives them alongside the video.

3. After step 2 succeeds, you MAY also output a short final assistant text (e.g. "成了，视频已发给你"). But the video itself is delivered by the `message` call in step 2, NOT by the final text.

4. **Snapshot run for backward chain** (regardless of `task_mode`, after the message has been sent):

   ```
   exec(command="bash /home/administrator/.openclaw/scripts/run-episode-init.sh {run_id}", yieldMs=20000)
   ```

   This writes / refreshes `~/.openclaw/insights/episodes/{run_id}.json` with a snapshot of brief / research_summary / script_summary / video_summary so the backward-optimization pipeline (Phase B/D) has a stable record of this run. The wrapper script (`run-episode-init.sh`) always exits 0 — episode_init failure does NOT impact delivery. **Do NOT** invoke episode_init via inline `bash -lc 'python3 ... || true'` — cmd.exe parses `||` as its own OR operator even inside quoted bash strings, which broke earlier runs (see backup notes 2026-05-02). Always use the wrapper.

   For `task_mode=publish_directly`, publisher will call this again after writing `publish_result.json`; that's fine — `episode_init` is idempotent and the second call merges in the publish section.

**Hard rules:**
- Never call `message` (or any messaging tool) with the raw `local_video_path` from `video_result.json` — always the `staged_path` from step 1.
- Never construct a video path yourself (no `runs/{run_id}/video.mp4` from memory) — always use what `stage_video_for_send` returns.
- Never substitute step 2 with `MEDIA:/...` strings inside the final assistant text. That's text, not a file upload — the user's client will see "media fail" / no video.
- The tool name is exactly `message`, not `message.send`. There is no separate `send` tool.

If `task_mode = publish_directly`:
1. Confirm with user once (publish gate).
2. Send `run_id` to `publisher`.
3. Receive publish result and report to user.

### State handling

Retain in context:

- `run_id` — the primary anchor for this run
- `task_mode` — drives routing decisions (publish gate)
- `channel` / `reply_target` — drives IM reply routing when provided by an external Message Adapter

All intermediate artifacts (research, script, video) live in `~/.openclaw/runs/{run_id}/`. Read from there when needed rather than holding large payloads in context.

Do not confuse draft, weak, rejected, and accepted intermediate results.

## Output

Deliver to the user: video file, complete script, grounded tag. 
If `task_mode = publish_directly`, also include the publish result. → See Step 6 for details.

## Safety

- Do not skip required stages.
- Do not publish unless `task_mode = publish_directly`.
- Do not confuse internal readiness with external completion.

## Interaction Policy

Surface to the user in these cases:

1. **Stage progress ack** — after every `sessions_spawn`, send a single short user-visible message via `message.send` so the user knows the pipeline is alive and which stage is currently running. Format: `[<stage>] 已启动，预计约 N 分钟。` Per-stage estimates (from observed runs):
   - 选题 grounding: ~1–2 分钟
   - 研究检索: ~15–20 分钟（最耗时阶段；supervisor 内部并行 wait_for_done，期间无中间消息属正常 — 显式告知用户）
   - 脚本撰写: ~1–2 分钟
   - 视频生成: ~2–3 分钟

   Send the ack **before** `sessions_yield`. Do NOT send mid-stage status updates — one ack per stage is enough; more would be noisy.

2. **Blocking failure** — report clearly: which stage, what it produced, what is blocked.

3. **Publish gate** — confirm once with the user before sending the final publish instruction to `publisher`.

4. **Final delivery** — Step 6 deliverables (video file, complete script, grounded tag).

For everything else — partial results, weak evidence, write retries — resolve internally.
