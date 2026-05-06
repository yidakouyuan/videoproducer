# AGENTS.md — stats-collector

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-stats-collector/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-stats-collector/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-stats-collector/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-stats-collector/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/stats-collector.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-stats-collector/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-stats-collector/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-stats-collector/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after writing `last_run.txt`): if you learned something non-trivial that future-you would want to know (e.g. a Creator Center page-layout change you had to work around, or a metric whose name moved), **append one line** to `~/.openclaw/workspace-stats-collector/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You are triggered by a cron job. No user-provided input is expected. Run the full collection flow unconditionally.

---

## Working Schema

### Step 1 — Navigate to Creator Center data dashboard

Use the `creator-stats` skill to open Douyin Creator Center in the browser and reach the video data overview page.

If the browser node is unavailable or login is expired, stop immediately and report the exact error. Do not proceed.

### Step 2 — Collect video stats

For each video listed in the data dashboard:

Collect all available metrics:
- `title`, `publish_time`
- `play_count`, `like_count`, `comment_count`, `share_count`, `collect_count`
- `completion_rate`, `two_sec_exit_rate`
- `follower_gain`, `follower_loss`, `fan_play_ratio`
- `duration_sec` (if shown)

Only include fields that the platform actually displays. Do not fill in zeroes or guesses for missing fields — omit them entirely.

Paginate through all pages of the data list until all published videos are covered.

### Step 3 — Write to database

Call `stats_write` with all collected items in a single batch.

If the write fails (non-2xx response), stop and report the error with the full response body. Do not retry silently.

### Step 4 — Report

Log completion:
- How many videos were collected
- How many snapshots were written (`data.written` from response)
- Any videos that were skipped and why

Write a one-line summary to `~/.openclaw/workspace-stats-collector/last_run.txt`:
```
YYYY-MM-DDTHH:MM:SSZ  collected=N  written=N  status=ok|error
```

---

## Output

No user-facing output. Internal log only (last_run.txt).

## Safety

- Never write fabricated or zero-filled data.
- Never proceed past a browser or login failure — report it.
- This is a read-only operation on the platform; it does not publish, edit, or delete anything on Douyin.
