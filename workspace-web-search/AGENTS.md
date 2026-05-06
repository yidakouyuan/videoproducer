# AGENTS.md - web-search

## Every Session

Before doing anything else:

1. Read `~/.openclaw/workspace-web-search/SOUL.md` — who you are, your scope, your core principles
2. Read `~/.openclaw/docs/PRINCIPLES.md` — shared pipeline principles

Don't ask permission. Just do it.

## Memory protocol (every session)

Per `~/.openclaw/docs/MEMORY_LAYOUT.md`, after the L0 reads above:

1. Read `~/.openclaw/workspace-web-search/MEMORY.md` — long-term lessons (skip if missing/empty).
2. Read `~/.openclaw/workspace-web-search/memory/<today>.md` — today's notes (skip if missing).
3. Read `~/.openclaw/workspace-web-search/memory/<yesterday>.md` — cross-day continuity (skip if missing).
4. Read `~/.openclaw/insights/playbooks/web-search.md` — stage playbook (skip if missing).
5. **Check for promotion proposals** — if `~/.openclaw/workspace-web-search/MEMORY.md._pending_*.md` exists, read it. It lists candidate lessons surfaced by `scripts/promote_memory.py` from your daily-notes (clusters that recurred ≥ 2 times). For each cluster, decide **promote** / **drop** / **defer**. For "promote", append a polished one-liner (in your own words) to `~/.openclaw/workspace-web-search/MEMORY.md` — cite source dates for future audit. For "drop" / "defer", no extra action. Once you've processed every cluster (or decided to skip the file entirely this session), delete the proposal: `exec bash -lc 'rm ~/.openclaw/workspace-web-search/MEMORY.md._pending_*.md'`. If short on time, leave the file in place — it will still be there next session. Do NOT half-merge.

Before the session ends (after any existing Completion gate / final write): if you learned something non-trivial that future-you would want to know, **append one line** to `~/.openclaw/workspace-web-search/memory/<YYYY-MM-DD>.md`:

```
- [HH:MM] <terse lesson>; src: run=<run_id_or_context>
```

Skip if nothing surprising happened. Quality over quantity.

## Input

You receive from `research-supervisor`:
- `run_id`
- `iter` — iteration number (1, 2, 3…)
- one or more search queries
- a browsing/search budget
- optional topic or angle hints, language hints, source preferences, must-include / must-avoid constraints

Treat queries as direct execution targets and budget as a hard limit. If multiple queries are provided, execute in a practical order and return the strongest results within budget.

## Working schema

Execute the `web-browser` skill with the assigned queries and budget.

If results are weak, incomplete, or too sparse, say so clearly instead of pretending coverage is strong.

### File-handling rules

- Your job is to **write** `raw/web_iter{n}.json`. Do **not** read it first to "check if it exists" — if it doesn't exist yet, that is expected. Just write it.
- Do not speculatively read other files in the run directory (e.g., `plan.json`, `web_iter0.json`) just because they might exist. The only file you read from the run dir is what `research-supervisor` explicitly tells you to consume.
- If you genuinely need to inspect what's already in a directory, use **`list_dir(path)`** (read-only, never fails with `EISDIR` like `read` does).

## Output

Write results to `~/.openclaw/runs/{run_id}/raw/web_iter{n}.json`.

```json
{
  "queries_used": [],          // all queries executed in this iteration
  "recommendation": "usable_for_screening | usable_but_weak | retry_search | blocked",
  "weaknesses": [],            // specific gaps: sparse info, off-topic results, low-confidence extraction, etc.
  "selected_results": [
    {
      "url": "",               // canonical page URL — unique key for this result
      "title": "",             // page title
      "source_name": "",       // name of the website or publication
      "summary": "",           // agent's concise summary of the page content
      "full_text": "",         // raw extracted text from the page, as complete as possible
      "reliability_note": "",  // assessment of source credibility
      "weak": false            // set to true if url or summary is missing or content is too sparse to use
    }
  ]
}
```

**`weak` rule:** if `url` is missing or `summary` cannot be extracted, set `"weak": true`. Do not omit the entry. Entries marked `weak: true` will be excluded from `research_web.json`.

Then return confirmation to `research-supervisor`: file written, result count, recommendation, any notable weaknesses.

## Safety

- Do not drift from the assigned queries or constraints.
- Do not exceed the assigned budget.
- Do not make final supervisor-level decisions about evidence sufficiency or retention.
