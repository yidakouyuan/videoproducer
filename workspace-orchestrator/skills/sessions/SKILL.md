---
name: sessions
description: "Delegate pipeline stages to child agents. You MUST use sessions_spawn or sessions_send for all specialist work — never perform it yourself."
---

# Sessions

You MUST delegate all specialist work via child agent sessions. Do not call specialist tools (`tag_get_script_pack`, `media_*`, `video_*`, `transcribe_*`, `browser`) directly — spawn the appropriate agent instead.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| Starting a new pipeline stage | MUST `sessions_spawn` a new child session |
| Revising the same artifact | `sessions_send` to the existing session |
| Unstable or confused session history | Spawn fresh |
| Any specialist tool needed | MUST delegate — do not call it yourself |

## Solution

### Tools

| Tool | Purpose |
|------|---------|
| `sessions_spawn` | Start a new child agent session |
| `sessions_send` | Continue or revise an existing session |
| `sessions_list` | List active sessions |
| `sessions_history` | Inspect a session's message history |
| `session_status` | Check session status |

### Child Agents

Every `sessions_spawn` call MUST include `agentId`. Without it, a nameless generic session is created — it will not have the correct identity, workspace, tools, or skills.

| Agent | agentId | Input | Output |
|-------|---------|-------|--------|
| Tag Matcher | `tag-matcher` | `run_id` | grounded tag |
| Research Supervisor | `research-supervisor` | `run_id` | `research_douyin.json` + `research_web.json` |
| Writer | `writer` | `run_id` + optional style/revision hints | `script.json` |
| Video Generate | `video-generate` | `run_id` + optional mode/frame hint | `video_result.json` |
| Publisher | `publisher` | `run_id` | publish result |

## Gotchas

- MUST pass `agentId` in every `sessions_spawn` call — spawning without `agentId` creates a nameless generic session, not the target agent.
- DO NOT pass `streamTo` with `runtime: "subagent"`. `streamTo` is only valid with `runtime: "acp"`. Using it with `runtime: "subagent"` will fail with `INVALID_REQUEST: streamTo is only supported for runtime=acp`. Auto-announce already pushes child completions back to your session — you do NOT need streamTo to receive them.
- Minimum working `sessions_spawn` args:
  ```
  { agentId, task, runtime: "subagent", mode: "run" }
  ```
  Add `cwd`, `cleanup`, `timeoutSeconds`, `lightContext` only when you actually need them.
- Always advance from the **latest accepted artifact**, not the latest message.
- When delegating: state what's accepted, what to produce, and whether it's a new run or revision.

---
