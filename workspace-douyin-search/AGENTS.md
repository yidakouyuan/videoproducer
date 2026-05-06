# AGENTS.md — douyin-search

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-douyin-search/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-douyin-search/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-douyin-search/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-douyin-search/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/douyin-search.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-douyin-search/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-douyin-search/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-douyin-search/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-douyin-search/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive from `research-supervisor`:
- `run_id`
- `iter` — iteration number (1, 2, 3…)
- one or more search queries
- a candidate budget
- optional filtering or ranking hints

If the assigned queries are too weak, unclear, or unusable, return a structured weak-result immediately.

## Working schema

Execute the `douyin-browser` skill with the assigned queries and budget.

### File-handling rules

- Your job is to **write** `raw/douyin_iter{n}.json`. Do **not** read it first to "check if it exists" — if it doesn't exist yet, that is expected. Just write it.
- Do not speculatively read other files in the run directory just because they might exist. The only file you read from the run dir is what `research-supervisor` explicitly tells you to consume.
- If you genuinely need to inspect what's already in a directory, use **`list_dir(path)`** (read-only, never fails with `EISDIR` like `read` does).

## Output

Write results to `~/.openclaw/runs/{run_id}/raw/douyin_iter{n}.json` — the full candidate list within budget.

Each entry must include:
```json
{
  "platform": "douyin",
  "aweme_id": "",
  "share_url": "https://v.douyin.com/...",
  "like_count": null,
  "collect_count": null,
  "comment_count": null,
  "title": "",
  "creator": "",
  "query_source": "",
  "weak": false         // set to true if aweme_id or share_url is missing
}
```

**`weak` rule:** if `aweme_id` or `share_url` cannot be collected from the page, set `"weak": true`. Do not omit the entry — include it so research-supervisor can see the full picture. Entries marked `weak: true` will be skipped during resolve and fetch.

Then return confirmation to `research-supervisor`: file written, candidate count, any notable weaknesses.

## Safety

- Never exceed the assigned budget.

