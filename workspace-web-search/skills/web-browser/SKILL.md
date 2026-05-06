---
name: web-browser
description: "Search & extract evidence from the public web. Prefer the lightweight `web_search_query` + `web_fetch_url` tools; fall back to `browser` only when JS rendering or login state is actually required."
---

# Web Search & Extract

## Decision tree (run for EACH assigned query)

1. **Default — call `web_search_query`** with `query` as an array. Send up to 5 complementary queries in ONE batched call: `web_search_query({ query: ["q1", "q2", ...], top_k: 10 })`.
2. **For each promising hit, call `web_fetch_url`** — also batched (up to 5 URLs in one call): `web_fetch_url({ url: ["u1", "u2", ...], max_chars: 30000 })`. The response is raw markdown; you read and summarize it yourself.
3. **Escalate to `browser(target="node", profile="openclaw")` ONLY** if any of:
   - Jina returns a CAPTCHA / Cloudflare / "login required" page.
   - Page requires authenticated state (paywalled, douyin internal, …).
   - Markdown is empty or clearly truncated and you actually need the rest.
   - You need to interact (click, scroll-load, fill a form).
4. **Never use `browser` as the FIRST step** for a public, static page. The lightweight path covers ~80% of queries at <5% of the token cost.

## Quick reference

| Situation | Required action |
|-----------|-----------------|
| Public web search | `web_search_query` (batch up to 5 queries) |
| Reading an article / blog / news | `web_fetch_url` (batch up to 5 URLs) |
| JS-rendered SPA, login wall, douyin internal | `browser(target="node", profile="openclaw")` |
| Both lightweight tools fail with a clear reason | Document the reason, then `browser` |
| Both lightweight tools succeed but evidence is thin | Refine queries / pick different hits — do NOT escalate to browser |
| Browser node unavailable | Stop immediately, report exact error to `research-supervisor` |

## Output contract

For each accepted result, collect:
- `url`, `title`, `source_name`
- `summary` — concise, generated from what you actually read in the markdown
- `full_text` — raw markdown excerpt (already truncated by `max_chars`)
- `reliability_note`

Stay within the assigned page budget. Deduplicate by URL.

If a result is clearly weak (missing url, unextractable summary), set `"weak": true` and include the entry — do not silently drop or fabricate.

## Gotchas

- Do not invoke `browser` to "double-check" a Jina-fetched page — the markdown IS the evidence.
- Do not expect server-side LLM extraction from `web_fetch_url`; it returns raw markdown and YOU are the LLM.
- Do not drift from assigned queries — expand only when results are clearly insufficient.
- Do not fabricate dates, authorship, or claims not supported by what you actually read.
- Prefer a small, clean result set over a large noisy dump.

---
