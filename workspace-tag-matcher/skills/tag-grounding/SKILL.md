---
name: tag-grounding
description: "Ground a topic into Douyin tags. Prefer tag_get_script_pack, but use local script_packs.json or a minimal fallback when the HTTP tool is unavailable."
---

# Tag Grounding

Prefer `tag_get_script_pack` for each candidate tag. If the tool is unregistered, errors, or the HTTP backend is down, do not block the pipeline only because of that tool failure. Fall back to `~/.openclaw/workspace-tag-matcher/data/script_packs.json`; if that file is missing or has no match, generate a minimal fallback script pack from the user input and include a warning.

## Solution

```
tag_get_script_pack(tag, top_k_communities=3, top_k_cooccur=20, lang="zh", version="latest")
```

Fallback data:

```
~/.openclaw/workspace-tag-matcher/data/script_packs.json
```

- Normalize the topic before passing as `tag` — remove phrasing noise, preserve meaningful constraints (audience, location, style).
- When the topic has multiple angles, call with multiple candidate tags — do not force a single match.
- Evaluate each result: `strong | usable_but_broad | ambiguous | weak | blocked`.
- Return all results with minimal loss — do not silently drop ambiguous or weak matches.

## Gotchas

- If a result is broad or off-angle, state it explicitly — do not pass a weak match as strong.
- If multiple interpretations remain plausible, preserve all of them in the output.
- If `tag_get_script_pack` fails with connection/registration errors, write the warning into `notes_for_orchestrator` and continue with local/minimal fallback.

---
