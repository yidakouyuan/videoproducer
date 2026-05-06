---
name: creator-center
description: "Upload and publish a video to Douyin Creator Center via browser on the Windows node. You MUST use the browser tool at every step — do not simulate or skip any part of the flow."
---

# Creator Center

You MUST use the `browser` tool for every step of the upload and publish flow. Do not simulate, skip, or report state without actual browser confirmation.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| All browser calls | MUST use `browser(target="node", profile="openclaw", ...)` — relay and local browser will fail |
| After file selection | MUST wait for platform upload confirmation — file selected ≠ upload complete |
| Before publishing | MUST have Orchestrator authorization |
| Browser node unavailable | Stop immediately, report exact error to Orchestrator |

## Solution

### Step-by-Step

1. Navigate to Douyin Creator Center via browser
2. Upload `local_video_path` — wait for platform-side upload confirmation before proceeding
3. Fill `title` and `tags` exactly from `script.json`
4. Submit — confirm `published` state via browser before reporting success

### Return

```json
{
  "success": true,
  "status": "published | publish-ready | upload-complete | waiting-for-confirmation | blocked | failed",
  "publish_url": "",
  "error": ""
}
```

## Gotchas

- Final publish is irreversible — do not publish without Orchestrator authorization.
- Use `title` and `tags` exactly as written — do not invent or modify metadata.
- Do not report `published` without actual browser confirmation of the published state.

---
