# AGENTS.md — stats-analyzer

## Environment

- `exec` shell: Windows cmd.exe (NOT bash). For unix pipelines use `bash -lc '...'`.
- workdir: already your workspace. Never run `pwd` to check.

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-stats-analyzer/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles
3. Read `~/.openclaw/docs/EXEC_ENV.md` — exec is cmd.exe; cmd-equivalents and `bash -lc` escape hatch

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-stats-analyzer/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-stats-analyzer/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-stats-analyzer/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/stats-analyzer.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-stats-analyzer/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-stats-analyzer/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-stats-analyzer/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after writing `suggestions.json` and `last_run.txt`): if you learned something non-trivial that future-you would want to know (e.g. a topic-grouping rule that worked well, or a misleading metric pattern), **append one line** to `~/.openclaw/workspace-stats-analyzer/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You are triggered by a cron job. No user-provided input is expected. Run the full analysis flow unconditionally.

---

## Working Schema

### Step 1 — Fetch all latest stats

Call `stats_query` with:
- `platform=douyin`
- `latest_only=true`
- `limit=200`, `offset=0`

If `total_count` exceeds `limit`, paginate (offset=200, 400, …) until all videos are retrieved.

If the query fails, stop and report the error.

### Step 2 — Analyze

With the full dataset, compute per-video metrics and cross-video patterns.

**Per-video metrics:**
- Engagement rate: `(like_count + comment_count + share_count + collect_count) / play_count`
- Follower conversion rate: `follower_gain / play_count`
- Retention quality: `completion_rate` and `two_sec_exit_rate`

**Group by topic using your own judgment.** Look at the video titles and group them into meaningful topic categories (e.g. travel, food, lifestyle). Within each group, identify patterns — what format, length, or style correlates with better performance.

**Cross-video patterns:**
- Which videos have the highest engagement/conversion? What do they share?
- Correlation between completion_rate and follower_gain?
- Duration vs play_count — any sweet spot?
- Average completion_rate — which videos fall below?

**Red flags:** two_sec_exit_rate > 0.25 / completion_rate < 0.30 / high play but near-zero follower_gain

**Positive patterns:** top performers by engagement, conversion, retention

### Step 3 — _DEPRECATED, do not write_

> **As of 2026-05-02 (Phase D of the backward pipeline):** machine-readable `~/.openclaw/insights/suggestions.json` is now produced exclusively by `scripts/playbook_curator.py`, which sources both stat-attributor and trace-critic events. This agent **must NOT** write `suggestions.json` — concurrent writes from two producers would race and corrupt orchestrator's input.
>
> Skip this step. Proceed to Step 4 (the human report is still your responsibility).

### Step 4 — Generate human report

Use `exec` to create the reports directory: `mkdir -p ~/.openclaw/reports`

Write `~/.openclaw/reports/stats_YYYYMMDD.md`:

```markdown
# Weekly Video Performance Report — YYYY-MM-DD

## Overview
- Total videos tracked: N
- Date range: [earliest publish_time] → [latest publish_time]
- Latest snapshot: [most recent snapshot_at]

## Top Performers
[top 3 by engagement rate with key metrics]

## Red Flags
[videos with poor hook or retention, with specific numbers]

## Trends & Patterns
[data-backed observations, grouped by topic]

## Suggestions by Topic
[per-topic suggestions derived from the data]
```

### Step 5 — Write run log

Write a one-line summary to `~/.openclaw/workspace-stats-analyzer/last_run.txt`:
```
YYYY-MM-DDTHH:MM:SSZ  videos=N  topics=N  report=~/.openclaw/reports/stats_YYYYMMDD.md  status=ok|error
```

---

## Output

- `~/.openclaw/reports/stats_YYYYMMDD.md` — **human-readable full report** (your primary deliverable)
- `~/.openclaw/workspace-stats-analyzer/last_run.txt` — run log

**Removed (Phase D, 2026-05-02):** `~/.openclaw/insights/suggestions.json` is no longer your output. That file is now owned by `scripts/playbook_curator.py`, which integrates trace-critic + stat-attributor signals. Do NOT write it.

## Safety

- This is a read-only operation on the database.
- Do not publish or modify any videos.
- If there are fewer than 3 videos in the database, note the limited dataset and still report what's available — don't skip the run.
