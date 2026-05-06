---
name: douyin-browser
description: "Search Douyin for candidate videos via browser on the Windows node. You MUST call browser for every discovery query — do not generate candidates from memory or inference."
---

# Douyin Browser Search

You MUST call the `browser` tool for every assigned query with `target="node"` and `profile="openclaw"`. Do NOT use relay or any other profile — only the openclaw profile on the Windows Node works.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| All browser calls | MUST use `browser(target="node", profile="openclaw", ...)` — relay and local browser will fail |
| Missing `aweme_id` or `share_url` | Set `"weak": true`, include the entry |
| Budget reached | Stop — do not exceed it |
| Browser node unavailable | Stop immediately, report exact error to `research-supervisor` |

## Solution

### Step-by-Step

1. Open Douyin in the browser
2. Execute each assigned query via browser search
3. For each result card, collect:
   - `aweme_id`, `share_url`
   - `like_count`, `collect_count`, `comment_count`
   - `title`, `creator`, `query_source`
4. Deduplicate across queries — one entry per video, best metadata wins
5. Rank by: topical relevance → metadata completeness → engagement
6. Return the strongest candidates within the assigned budget

## Gotchas

- Do not call media, transcribe, or analysis tools — collect surface metadata only.
- If strong candidates cannot be found, return a structured weak-result with the specific reason. Do not pad with low-quality entries to fill the budget.

---
