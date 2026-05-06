# MEMORY_LAYOUT.md — Memory Stack & Read/Write Protocol

This document is the single source of truth for **what kinds of memory exist in this OpenClaw deployment, where each lives on disk, who writes it, and who reads it**. Every agent's `AGENTS.md` references back here.

The whole point: agents should not invent their own conventions. Five layers, each with a clear write path and a clear read path.

---

## The five layers

```
L0  Identity (static)          workspace-<self>/{SOUL,IDENTITY,USER,AGENTS}.md, skills/**/SKILL.md
L1  Run-time state (per-run)   ~/.openclaw/runs/<run_id>/...
L2  Daily notes (per-day)      workspace-<self>/memory/YYYY-MM-DD.md
L3  Long-term lessons          workspace-<self>/MEMORY.md
L4  Project insights           ~/.openclaw/insights/{episodes,playbooks,suggestions.json}
L5  Trace archive (read-only)  ~/.openclaw/trace_bundles/<run_id>/
```

---

## L0 — Identity (static, human-edited)

Files: `SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, plus `skills/<skill>/SKILL.md`.

- **Writer**: human (you, the operator). Agents do not write here.
- **Reader**: every agent, every session, before doing anything else.
- **Purpose**: who I am, my role, my permitted scope, my user, my workflow.

This layer changes only when the operator deliberately edits a workspace. Treat it as read-only at runtime.

---

## L1 — Run-time state (per-run, streaming-capable)

Path: `~/.openclaw/runs/<run_id>/...` — see RUN_LAYOUT.md for the per-file map.

- **Writer**: each agent writes the artifacts it owns (orchestrator → `brief.json`, research-supervisor → `research_*.json`, writer → `script.json`, video-generate → `video_result.json`).
- **Reader**: downstream agents per the RUN_LAYOUT.md "Read by" column.
- **Purpose**: the only state shared across agents within one pipeline run. Treat the on-disk artifact as ground truth — never trust an agent's self-reported "I wrote it" without a re-read.

**Streaming**: long-tailed artifacts use the `partial + atomic rename` protocol — see STREAMING_PROTOCOL.md. Currently:
- `video_result.json`, `research_douyin.json`, `research_web.json` → streaming.
- Everything else → write-once.

---

## L2 — Daily notes (per-agent, per-day, agent-written)

Path: `workspace-<self>/memory/YYYY-MM-DD.md`

- **Writer**: the agent itself, **after** the Completion gate, **before** `sessions_yield` / `NO_REPLY` / final reply.
- **Reader**: the agent itself, every session start (today's file + yesterday's file).
- **Format**: append-only. One line per lesson:
  ```
  - [HH:MM] <terse lesson>; src: run=<run_id>
  ```
- **Purpose**: short-term memory. Carry forward "things I learned this run that I'd want to remember tomorrow." Crashes, surprises, recoveries, user corrections.

**Write quality bar**: skip if nothing surprising happened. A noisy daily log is worse than a silent one. The bar is "would future-me thank present-me for writing this." Do not log routine successes.

**Cross-day continuity**: read both today's and yesterday's file at session start to bridge midnight resets.

---

## L3 — Long-term lessons (per-agent, promoted)

Path: `workspace-<self>/MEMORY.md`

- **Writer**: only the agent itself ever writes the live `MEMORY.md`. Proposals come in via `MEMORY.md._pending_<YYYYMMDD>.md` files (see Promotion lifecycle below); the agent reviews them at session start and chooses what to merge.
- **Reader**: the agent itself, every session start.
- **Format**: structured Markdown sections. Lessons that stayed relevant across many runs and many days.
- **Purpose**: the agent's accumulated wisdom. What patterns work, what to avoid, hard-won facts that don't change run-to-run.

**Promotion bar**: a lesson reaches L3 only if it appeared in L2 across multiple days, or if `stats-analyzer` saw it across multiple runs (when that pipeline matures). Don't dump every L2 line into L3 — L3 is for what survived.

### L2 → L3 promotion lifecycle

The split between **recall** (find candidates from L2) and **precision** (decide what's worth L3) is intentional:

```
[L2 daily notes accumulate]
       │
       ▼
scripts/promote_memory.py  ─── recall: cluster recurring lessons
       │                        (Jaccard ≥ 0.4 OR ≥ 2 long-token anchors)
       ▼
workspace-<self>/MEMORY.md._pending_<YYYYMMDD>.md  ─── proposals on disk
       │
       ▼
agent reads it on next session start  ─── precision: human-grade judgment
       │
       ▼
agent appends keepers to MEMORY.md     ─── only the agent writes MEMORY.md
       │
       ▼
agent deletes the _pending file        ─── only delete after processing all clusters
```

**The script never writes `MEMORY.md` directly.** Auto-merging is dangerous: a noisy MEMORY.md is worse than a silent one. The script's job is recall (surface what could matter); promotion is precision (the agent decides).

**Triggering `promote_memory.py`**: manually, on cron, or as a sub-step of a future L4 agent. The script is read-only on `MEMORY.md` and only writes `MEMORY.md._pending_*.md`, so it is safe to run any time:

```
python ~/.openclaw/scripts/promote_memory.py --workspace workspace-orchestrator
python ~/.openclaw/scripts/promote_memory.py --workspace ALL --since-days 30
python ~/.openclaw/scripts/promote_memory.py --workspace workspace-writer --dry-run   # preview, no file written
```

Tunables: `--threshold` (Jaccard, default 0.4), `--min-cluster-size` (default 2), `--since-days` (default 30). Long-token anchor threshold is hard-coded (≥ 5-char tokens, ≥ 2 shared).

**Half-merge prevention**: each AGENTS.md says "Do NOT half-merge — process every cluster (or skip the file entirely) before deleting `_pending`." If the agent has no time, it should leave the file in place; promote_memory.py will re-surface anything that recurs again next time it runs.

**File hygiene**: only one `_pending_*.md` per workspace at a time is the target. If multiple accumulate (e.g., the script ran several times without an agent processing in between), the agent should consolidate by reading the newest and deleting the older ones — the newest reflects the most recent recall.

---

## L4 — Project insights (cross-agent, backward optimization)

Path: `~/.openclaw/insights/`

```
insights/
├── episodes/<run_id>.json     # collect-agent writes
├── playbooks/<topic>.md       # analyse-agent writes
├── playbooks/<stage>.md       # analyse-agent writes
└── suggestions.json           # analyse-agent writes
```

- **Writer**:
  - `collect-agent` → `episodes/<run_id>.json` after each pipeline run completes.
  - `analyse-agent` → aggregates episodes (recent N + all anomalies) into `suggestions.json` and topic/stage `playbooks/*.md`.
- **Reader**:
  - `orchestrator` reads `suggestions.json` at Step 1 (already wired) and may include relevant entries in `brief.historical_suggestions`.
  - Each stage agent reads `playbooks/<my_stage>.md` at session start (when it exists).
- **Purpose**: cross-run learning. "What did past runs teach us about this topic / this stage?" This is the backward-optimization closing loop.

**Schemas**: see `insights/episodes/SCHEMA.md` and `insights/SUGGESTIONS_SCHEMA.md` (created with the collect/analyse agents).

**Confidence**: every entry in `suggestions.json` carries `confidence` and `source_run_ids`. Consumers MUST treat them as advisory, not authoritative — the agent's own judgment for the current request still wins.

---

## L5 — Trace archive (read-only, generated)

Path: `~/.openclaw/trace_bundles/<run_id>/{trace.json,trace.md,summary.json,README.md}`

- **Writer**: `scripts/assemble_trace.py` (the operator runs it; later collect-agent triggers it automatically).
- **Reader**: `collect-agent` (primary), human operators (debugging).
- **Purpose**: complete event-stream archive of one run, joining all agents' transcripts on `run_id`. Schema: `openclaw-trace-bundle` v2.

**Do not edit** trace bundles. They are a derived archive; rerun `assemble_trace.py` to refresh.

---

## Per-session protocol (every agent)

At session start (after L0 reads required by `AGENTS.md`):

```
1. Read workspace-<self>/MEMORY.md            # L3 — long-term, if non-empty
2. Read workspace-<self>/memory/<today>.md    # L2 — today, if non-empty
3. Read workspace-<self>/memory/<yesterday>.md# L2 — cross-day continuity
4. Read ~/.openclaw/insights/playbooks/<my_stage>.md  # L4 — if exists
   (orchestrator additionally reads ~/.openclaw/insights/suggestions.json — already in Step 1)
5. If workspace-<self>/MEMORY.md._pending_*.md exists:
   review each cluster, append keepers to MEMORY.md (in your own words,
   citing source dates), then delete the _pending file. Do NOT half-merge.
   See "L2 → L3 promotion lifecycle" above.
```

Before exiting (after Completion gate, before `sessions_yield` / `NO_REPLY` / final reply):

```
6. If you learned something non-trivial worth a future-you reading,
   append one line to workspace-<self>/memory/<today>.md.
   Skip if nothing surprising happened.
```

---

## What NOT to put in memory

Skip writing to L2/L3/L4 if the content fits any of these:

- Routine success (the run worked, nothing notable).
- Information already in L0 (SOUL/AGENTS/SKILL — that's identity, not learning).
- Information derivable from current code/files (`git log`, current AGENTS.md state).
- Content that belongs in `runs/<run_id>/` per-run state (that's L1).

---

## Read-write summary table

| Layer | Writer            | Reader                        | Cadence    |
|-------|-------------------|-------------------------------|------------|
| L0    | operator (human)  | every agent every session     | static     |
| L1    | per-stage agent   | per-stage agent + downstream  | per run    |
| L2    | self              | self                          | per session|
| L3    | analyse-agent + self | self                       | per agent  |
| L4    | collect + analyse agents | orchestrator + stage agents | cross-run  |
| L5    | assemble_trace.py | collect-agent + humans        | per run    |

---

## Cross-references

- File-streaming format: `~/.openclaw/docs/STREAMING_PROTOCOL.md`
- Run directory structure: `~/.openclaw/docs/RUN_LAYOUT.md`
- Async job pattern: `~/.openclaw/docs/ASYNC_JOBS.md`
- Pipeline overview: `~/.openclaw/docs/PIPELINE.md`
