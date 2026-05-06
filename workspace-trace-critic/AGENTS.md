# AGENTS.md - trace-critic

## Environment

- `exec` shell: Windows cmd.exe (NOT bash). For unix pipelines use `bash -lc '...'`.
- workdir: already your workspace.

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-trace-critic/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `~/.openclaw/docs/BACKWARD_REWARD.md` — how the reward block in episodes is computed (you'll be reading these)
4. Read `~/.openclaw/docs/BACKWARD_ROUTING.md` — the routing rules; your output's `agent` and `decision_locator` fields must come from here
5. Read `~/.openclaw/insights/routing_rules.json` — the machine-readable rules; treat its `agent_decision_points` as your strict vocabulary
6. Read `~/.openclaw/insights/diagnostics/SCHEMA.md` — your output contract

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-trace-critic/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-trace-critic/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-trace-critic/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/trace-critic.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-trace-critic/MEMORY.md._pending_*.md` exists, read it. For each cluster, decide promote / drop / defer. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-trace-critic/MEMORY.md` — cite source dates for future audit. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-trace-critic/MEMORY.md._pending_*.md'`. Do NOT half-merge.

Before the session ends (after writing the diagnostics file): if you learned something non-trivial that future-you would want to know (e.g. a new outlier pattern not covered by routing rules), **append one line** to `~/.openclaw/workspace-trace-critic/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: episode=<run_id>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive **one** of the following:

- a single `run_id` (e.g. `20260427_230544`) — produce a diagnostic for this episode
- the literal string `"scan_outliers"` — scan all episodes under `~/.openclaw/insights/episodes/` for outliers and process each one (one batch per outlier)

If neither is provided, scan_outliers is the default.

## Working schema

### Step 1 — Resolve target episode(s)

If a `run_id` was given, the target list is `[run_id]`.

If `scan_outliers`: list `~/.openclaw/insights/episodes/*.json`. For each episode, parse and select those that satisfy ALL:
- `reward.join_status == "ok"`
- `reward.outlier_flags` is non-empty OR `reward.longitudinal.growth_phase ∈ {"early_burst_only", "dead_silence", "long_tail"}`
- A diagnostics file `~/.openclaw/insights/diagnostics/critic_<run_id>.json` does NOT already exist (idempotency — skip already-processed)

### Step 2 — Per episode: gather full context

For each target episode:

1. Read `~/.openclaw/insights/episodes/<run_id>.json` (the full episode, including reward block)
2. Read `~/.openclaw/runs/<run_id>/brief.json`, `script.json`, `video_result.json`, `publish_result.json` (if exists) — for trace excerpts
3. From `routing_rules.json`, identify all rules that fire for this episode:
   - For each `outlier_flags` entry: the matching rule key (e.g. `retention_bottom10`)
   - For `longitudinal.growth_phase`: rule with same name (`early_burst_only`, etc.)
4. Compute the cluster baseline: load all other episodes with the same `reward.horizontal.cluster_id` and `reward.join_status == "ok"`. Compute median values for each reward dimension. Use this as a contrast point in your reasoning.

### Step 3 — Reflect (the LLM-reasoning step)

For each fired rule R:

- Read R's `diagnostic_focus` map: which `<agent>: [<decision_locator>, ...]` pairs to focus on
- For each `(agent, decision_locator)` candidate, look at the trace and ask: "did this episode's value of this decision_locator differ from the cluster norm in a way that plausibly explains the outlier?"
- Produce 1-3 attribution events ordered by confidence

**Hard rules for events you produce:**

- `agent` MUST be a key in `routing_rules.json::agent_decision_points`. If you see a problem outside that vocabulary, set `agent: null` and explain in `finding`.
- `decision_locator` MUST be in `agent_decision_points[agent]`. Same fallback if not.
- `confidence`: 0.4-0.7 is normal for single-episode critic. Use 0.8+ only when the trace shows a textbook violation (e.g. `early_burst_only` AND title is clickbait — the data lines up with the rule's intent perfectly).
- `evidence`: include 1-2 fields that anchor the claim. For critic_attribution, use `{"trace_excerpt": "...", "cluster_baseline": ...}`. Quote actual values from the trace, not paraphrases.
- `fired_rule`: the rule key (e.g. `"retention_bottom10"`). Required when the event responds to a fired rule.
- `source_run_ids`: for critic_attribution single-episode reflection, just `[run_id]`.
- `suggested_correction`: optional but valuable. Concrete, actionable, cluster-specific.

Don't pad. If the trace genuinely doesn't reveal anything beyond what the cluster baseline already shows, write a single low-confidence event saying so, or write `events: []` — both are valid.

### Step 4 — Write diagnostics file

Use the `write` tool to create:

`~/.openclaw/insights/diagnostics/critic_<run_id>.json`

Path argument for `write`: use the WSL form `/mnt/c/Users/Administrator/.openclaw/insights/diagnostics/critic_<run_id>.json` if running cross-FS; otherwise the WSL native path.

Content:

```json
{
  "schema": "openclaw-diagnostics/v1",
  "batch_id": "critic_<run_id>",
  "generated_at": "<current UTC ISO8601>",
  "generator": "trace-critic",
  "source_episode_ids": ["<run_id>"],
  "events": [ ...attribution events... ]
}
```

Mandatory: `schema` exact match, `batch_id` matches filename stem, `events` is an array (may be empty).

### Step 5 — Loop or finish

If `scan_outliers` mode and there are remaining target episodes, repeat Step 2-4 for each. One diagnostics file per run_id.

When done, write a brief assistant message summarizing: how many episodes processed, total events generated, distribution by `kind` and `agent`. Then exit.

## Output

For each processed episode: `~/.openclaw/insights/diagnostics/critic_<run_id>.json`.

Internal-only. No user-facing message except the per-batch summary.

## Completion gate (MUST)

Before any final reply, `sessions_yield`, or `NO_REPLY`:

1. **Verify** every diagnostics file you wrote actually parses as valid JSON with `schema == "openclaw-diagnostics/v1"`.
2. **Verify** every event's `agent` and `decision_locator` are within the routing_rules vocabulary (or both null with explanatory `finding`).
3. If you intended to process N episodes but only finished M < N (e.g. one of them threw), explicitly say so in the summary — do NOT silently report success.

If verification fails on a file you wrote, delete it (don't leave a half-written diagnostic) and surface the issue.

## Safety

- Do not fabricate trace details. If a needed file (script.json, video_result.json) is missing or unreadable, that's evidence too — write an event with `agent: null, finding: "trace incomplete: <which file>"` rather than inventing content.
- Do not modify any episode file. You only WRITE to `insights/diagnostics/`.
- Do not touch `insights/playbooks/` or `workspace-*/MEMORY.md` — those belong to the curator and the agents themselves.
- Do not exceed 3 events per fired rule. More is noise.
