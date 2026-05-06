---
name: sessions
description: "Spawn and manage douyin-search and web-search worker sessions. You MUST use sessions_spawn to launch workers — do not call their tools directly."
---

# Sessions

You MUST spawn worker sessions via `sessions_spawn`. Do not call `browser` or any discovery tools directly — delegate to the worker agents instead.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| Launching discovery workers | MUST `sessions_spawn` each worker |
| `raw/*.json` files are missing | MUST spawn workers — these files do not pre-exist, they are produced by workers you spawn |
| Worker needs to retry with new queries | `sessions_send` to the existing session |
| Confused or stuck session | Spawn fresh |

## Tools

| Tool | Purpose |
|------|---------|
| `sessions_spawn` | Launch a worker agent session |
| `sessions_send` | Continue or revise an existing worker session |
| `session_status` | Check worker session status |

## Workers

Every `sessions_spawn` call MUST include `agentId`. Without it, a nameless generic session is created — it will not have the correct identity, workspace, tools, or skills.

| Worker | agentId | Input | Output |
|--------|---------|-------|--------|
| Douyin Search | `douyin-search` | `run_id`, `iter`, queries, candidate budget | `raw/douyin_iter{n}.json` |
| Web Search | `web-search` | `run_id`, `iter`, queries, page budget | `raw/web_iter{n}.json` |

## Gotchas

- MUST pass `agentId` in every `sessions_spawn` call — spawning without `agentId` creates a nameless generic session, not the target worker.
- DO NOT pass `streamTo` with `runtime: "subagent"`. `streamTo` is only valid with `runtime: "acp"`. Using it with `runtime: "subagent"` will fail with `INVALID_REQUEST: streamTo is only supported for runtime=acp`. Auto-announce already pushes child completions back to your session — you do NOT need streamTo to receive them.
- Minimum working `sessions_spawn` args:
  ```
  { agentId, task, runtime: "subagent", mode: "run" }
  ```
  Add `cwd`, `cleanup`, `timeoutSeconds`, `lightContext` only when you actually need them.
- `raw/douyin_iter{n}.json` and `raw/web_iter{n}.json` do not pre-exist. They are created by the workers you spawn. Missing raw files mean workers have not run yet — spawn them.
- Launch both workers together — do not wait for one before starting the other.
- Wait for both file-written confirmations before proceeding to Step 3.
- Do not shortlist from worker summaries alone — read the actual output files.

---
