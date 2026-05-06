# RUN_LAYOUT.md — Shared Run Directory

Each pipeline run creates a directory at `~/.openclaw/runs/{run_id}/` where `run_id` is a timestamp: `YYYYMMDD_HHMMSS`.

Agents write intermediate artifacts to this directory instead of passing large payloads through conversation context.

## Directory tree

> ⚠️ **Final curated outputs live at the run ROOT. Per-iteration intermediate data lives under `raw/`. Do not look for `research_douyin.json` / `research_web.json` under `raw/` — they are at the root.**

```
~/.openclaw/runs/{run_id}/
├── brief.json                  # orchestrator writes
├── research_douyin.json        # research-supervisor writes  ← run ROOT, NOT raw/
├── research_web.json           # research-supervisor writes  ← run ROOT, NOT raw/
├── script.json                 # writer writes
├── video_result.json           # video-generate writes
└── raw/                        # per-iteration intermediate data, NOT final products
    ├── douyin_iter{n}.json     # douyin-search writes (one per iteration)
    ├── web_iter{n}.json        # web-search writes (one per iteration)
    ├── jobs_iter{n}.json       # research-supervisor writes (analyze/transcribe job IDs for resume)
    └── resolved_iter{n}.json   # research-supervisor writes (analyzed + transcribed candidates)
```

## File Map

| File | Location | Written by | Read by |
|---|---|---|---|
| `brief.json` | root | orchestrator | tag-matcher, research-supervisor, writer, publisher |
| `research_douyin.json` | **root** | research-supervisor (Step 6) | writer |
| `research_web.json` | **root** | research-supervisor (Step 6) | writer |
| `script.json` | root | writer | video-generate, publisher |
| `video_result.json` | root | video-generate | orchestrator, publisher |
| `publish_result.json` | root | publisher (Persist publish outcome step) | backward chain (`scripts/episode_init.py`, future `outcome_aggregator.py`) |
| `raw/douyin_iter{n}.json` | `raw/` | douyin-search | research-supervisor |
| `raw/web_iter{n}.json` | `raw/` | web-search | research-supervisor |
| `raw/jobs_iter{n}.json` | `raw/` | research-supervisor (Step 3) | research-supervisor (resume after interrupt) |
| `raw/resolved_iter{n}.json` | `raw/` | research-supervisor (Step 3) | research-supervisor (Step 4, 6) |

`raw/` files are saved after each iteration. `douyin_iter{n}` and `web_iter{n}` contain raw discovery candidates. `resolved_iter{n}` contains the analysis and transcription results for shortlisted candidates in that iteration. `jobs_iter{n}` persists analyze/transcribe job IDs so that polling can be resumed if the session is interrupted. research-supervisor reads all of them when evaluating coverage and deciding whether to iterate.

## Schemas

### brief.json
```json
{
  "run_id": "20260314_143022",
  "full_user_query": "",
  "topic": "",
  "grounded_tag": "",
  "task_mode": "return_video | publish_directly"
}
```

### raw/jobs_iter{n}.json
Array of in-flight async job IDs for iteration n. Written immediately after each `video_analyze_start` / `transcribe_start` so polling can be resumed if the session is interrupted. Each entry:
```json
{
  "aweme_id": "",
  "share_url": "",
  "media_id": "",
  "analyze_job_id": "",
  "transcribe_job_id": ""
}
```

### raw/resolved_iter{n}.json
Array of resolved and analyzed candidates for iteration n. Each entry:
```json
{
  "media_id": "",
  "aweme_id": "",
  "share_url": "",
  "video_analysis": "",
  "transcript": "",
  "retain": null,       // set in Step 4: true = keep, false = drop
  "drop_reason": ""     // set in Step 4 when retain = false: failed_analysis | off_topic | duplicate | no_usable_content
}
```

### research_douyin.json
Array of filtered video research results written by research-supervisor. Each entry is extracted from `raw/resolved_iter{n}.json` — only retained candidates, with content ready for the writer:
```json
{
  "title": "",
  "tag": "",
  "video_analysis": "",
  "transcript": ""
}
```

### research_web.json
Array of filtered web research results written by research-supervisor. Each entry:
```json
{
  "title": "",
  "url": "",
  "summary": "",
  "full_text": ""
}
```

### script.json
Written by `writer`. Two output modes share the same file — pick one based on `task_mode` and the script complexity.

**Single-shot mode** — for simple, single-clip videos. All four fields required:
```json
{
  "title": "",        // Douyin publish title — used directly by publisher
  "script": "",       // full voiceover/narration text
  "shot_notes": "",   // visual and shot direction — used by video-generate to build the generation prompt
  "tags": []          // suggested tags based on grounded_tag
}
```

**Storyboard mode** — for multi-clip videos that should be generated per shot and stitched. Same four fields plus storyboard:
```json
{
  "title": "",
  "script": "",
  "shot_notes": "",
  "tags": [],
  "visual_style": "",          // overall visual style description used to drive image generation
  "style_anchor_image": "",    // local_image_path of the style anchor image (from image_generate_result)
  "shots": [                   // 2–6 shots, each 4–8 seconds
    {
      "index": 1,              // 1-based, ascending
      "duration": 5,           // seconds; sum across shots ≈ intended total video length
      "prompt": "",            // visual description of what the camera sees in this shot
      "narration": "",         // voiceover excerpt for this shot
      "reference_image_path": "" // local_image_path from image_generate_result, used as first_frame_path for video_generate_start
    }
  ]
}
```

`shots[]` is required when storyboard mode is used. Every shot must have a non-empty `reference_image_path` — writer should not write the file until all images are ready.

### video_result.json
Written by `video-generate`. Two output modes; matches the script.json mode used upstream.

**Single-shot mode**:
```json
{
  "job_id": "",
  "status": "done",            // terminal states: done | failed | partial | cancelled
  "local_video_path": "",       // Windows path on Windows nodes; non-empty when status=done
  "manifest_path": ""
}
```

**Storyboard mode** — `local_video_path` is the stitched output from `video_stitch`; per-shot details under `shots[]`:
```json
{
  "job_id": "",                // a synthetic id for the stitched result, e.g. "vg_stitch_<run_id>"
  "status": "done",            // strict mode: only written when every shot succeeded
  "local_video_path": "",       // path to the final stitched MP4 (output of video_stitch)
  "manifest_path": "",          // optional; can be omitted in storyboard mode
  "shots": [
    {
      "index": 1,
      "job_id": "",            // final job_id used for this shot (may be the retry job)
      "status": "done",        // strict mode: every entry must be "done"
      "local_video_path": ""    // per-shot clip path
    }
  ]
}
```

Storyboard mode is **strict**: if any shot fails (after a single retry), this file is not written at all — the video-generate agent returns a blocker to orchestrator instead. Top-level `status` is always `"done"` when the file exists.

### publish_result.json

Written by `publisher` immediately after the bridge returns (regardless of success/failure), so the backward-optimization pipeline can join published videos back to their `run_id`. Schema:

```json
{
  "ok": true,
  "run_id": "20260427_230544",
  "publish_ts": "2026-05-01T14:23:00Z",
  "platform": "douyin",
  "aweme_id": "7234567890123456789",
  "url": "https://www.douyin.com/video/7234567890123456789",
  "title": "...",
  "hashtags": ["..."],
  "confirmation": "url_changed_after_publish"
}
```

Fields:
- `ok` — bool. Mirrors the bridge's `success` field. `false` on publish failure; the file is still written to record the attempt.
- `aweme_id` — string or `null`. Parsed from `url` via the regex `/video/(\d+)`. `null` if parse fails (the join falls back to `(title, publish_ts)` downstream).
- `url` — full Douyin url from the bridge stdout. May be `null` on early failures.
- `publish_ts` — ISO8601 UTC at write time (NOT bridge time).
- `title` / `hashtags` — exactly as published (from `script.json`).
- `confirmation` — verbatim from bridge: `url_changed_after_publish` | `publish_likely_succeeded` | `publish_unknown_state` | `publish_clicked_but_unconfirmed`.

This file is **not streaming-protocol** (a small one-shot record).

## Rules

- If a required file is missing or unreadable, **return a blocker**. Do not guess or fabricate.
- **Streamable artifacts** (`video_result.json`, `research_douyin.json`, `research_web.json`) — write incrementally to `<base>.json.partial` and atomically `rename -> <base>.json` on terminal success. See `~/.openclaw/docs/STREAMING_PROTOCOL.md`. The presence of `<base>.json` always means "done"; consumers MUST NOT consume `.partial` (only watchers may inspect it).
- **Non-streamable artifacts** (`brief.json`, `script.json`, `raw/*_iter*.json`) — write the file completely before reporting completion to the caller.
- Do not overwrite files from a different `run_id`.
