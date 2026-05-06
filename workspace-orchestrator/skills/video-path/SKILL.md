---
name: video-path
description: "Convert a local video path from video_result.json into a sendable form. Always use the `stage_video_for_send` tool for this — never do path conversion or staging by hand."
---

# Video Path

`video_generate_result` returns `local_video_path` as a Windows path (e.g. `C:\Users\Administrator\...`). The built-in `message.send` tool cannot use that directly — files must be under an allowed local directory and use the runtime's path form.

**Use the `stage_video_for_send` tool. It does the conversion, copies the file into the run directory, and returns a `staged_path` you can pass straight to `message.send`. Never do this by hand.**

## Quick Reference

| Situation | Action |
|-----------|--------|
| You have `local_video_path` from `video_result.json` and want to send the video | Call `stage_video_for_send(source_path=<local_video_path>, run_id=<run_id>)` |
| Returned `ok: true, staged_path: "…"` | Pass `staged_path` verbatim to `message.send`. Do NOT modify it. |
| Returned `ok: false, status: "error"` | Report the exact error to the user. Do NOT attempt to send a raw or guessed path. |

## Why a tool, not manual steps

Earlier versions of this skill had three manual steps (convert path, copy file, send). Agents kept skipping the copy step or doing the conversion wrong, then sending a path to a non-existent file. `stage_video_for_send` makes the whole thing atomic: either you get a guaranteed-existing `staged_path` back, or you get a concrete error.

## Gotchas

- Do **not** send the raw Windows path (`C:\…`) to `message.send` — it will fail.
- Do **not** convert the path yourself (`C:\Users\…` → `/mnt/c/Users/…`) and send the converted form — even if the WSL path resolves, `message.send` requires the file under the run directory.
- Do **not** construct `~/.openclaw/runs/{run_id}/video.mp4` from memory and send it — the file may not exist yet. Always use the `staged_path` returned by the tool.
- If `stage_video_for_send` returns `ok: false`, surface the error — do **not** retry with a different path.

---
