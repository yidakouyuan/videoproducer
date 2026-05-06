# Local Development

This guide covers the local Mac path for Feishu → OpenClaw → VideoClaw, with special attention to `tag_get_script_pack`.

## Start agent-service first

The OpenClaw `video-http-tools` plugin calls the FastAPI backend. Start it before sending Feishu messages:

```bash
cd agent-service
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/tag/script_pack \
  -H 'Content-Type: application/json' \
  -d '{"tag":"露营美食"}'
```

## Backend base URL

Default local URL:

```bash
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8000
```

`openclaw.example.json` also sets:

```json
"plugins": {
  "entries": {
    "video-http-tools": {
      "config": {
        "baseUrl": "http://127.0.0.1:8000"
      }
    }
  }
}
```

The plugin resolves base URL in this order:

1. `plugins.entries["video-http-tools"].config.baseUrl`
2. `AGENT_SERVICE_BASE_URL`
3. `VIDEO_HTTP_TOOLS_BASE_URL`
4. `http://127.0.0.1:8000`

## Where tag_get_script_pack comes from

- OpenClaw tool definition: `openclaw-plugins/video-http-tools/src/tools/tag.ts`
- Plugin registration entry: `openclaw-plugins/video-http-tools/src/index.ts`
- HTTP helper/config: `openclaw-plugins/video-http-tools/src/shared.ts`
- FastAPI route: `agent-service/app/routes/tag.py`
- Route path: `POST /tag/script_pack`
- Tag-matcher permission: `openclaw.example.json` agent `tag-matcher.tools.allow`

The tag-matcher agent must allow:

```json
["group:fs", "tag_get_script_pack"]
```

`group:fs` is required so tag-matcher can read the local fallback data if the HTTP tool is not registered or the backend is down.

## Fallback script packs

Local fallback data lives at:

```text
workspace-tag-matcher/data/script_packs.json
```

Each item contains:

- `canonical_topic`
- `tags`
- `douyin_queries`
- `web_queries`
- `hook_examples`
- `shot_suggestions`
- `evidence_notes`

Current built-in examples:

- `露营美食`
- `户外烧烤`
- `城市探店`

If both `tag_get_script_pack` and the local JSON are unavailable, tag-matcher should generate a minimal fallback grounding package from the user input and continue the pipeline.

## Troubleshooting tag_get_script_pack

If tag-matcher says `tag_get_script_pack` is missing or the HTTP backend is not running:

1. Confirm FastAPI is running: `curl http://127.0.0.1:8000/health`
2. Confirm the tag route works: `curl -X POST http://127.0.0.1:8000/tag/script_pack -H 'Content-Type: application/json' -d '{"tag":"露营美食"}'`
3. Confirm `openclaw.example.json` or generated `openclaw.json` has `video-http-tools` loaded.
4. Confirm `baseUrl` is `http://127.0.0.1:8000` on Mac local development.
5. Confirm tag-matcher has `tag_get_script_pack` and `group:fs` in tool allowlist.
6. If the tool still fails, verify tag-matcher used local fallback by checking its structured return:
   - `notes_for_orchestrator` contains a fallback warning.
   - `grounding_results[0].source` is `local_script_pack` or `minimal_fallback`.
   - `best_matches` is non-empty.

## Start OpenClaw

After FastAPI is running:

```bash
openclaw start
```

Then trigger from Feishu:

```text
帮我做一个露营美食 30 秒短视频
```

Expected tag-matcher behavior on local Mac:

1. Try `tag_get_script_pack`.
2. If unavailable, read `workspace-tag-matcher/data/script_packs.json`.
3. Return a structured grounding result, not a blocker.
