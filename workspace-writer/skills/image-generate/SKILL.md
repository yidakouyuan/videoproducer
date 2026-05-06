# Skill: Image Generation for Storyboard

## Purpose

Generate reference images for each storyboard shot so that the video-generate agent can use them as first frames (i2v mode). Using a shared style anchor ensures visual consistency across shots.

## Tools Available

| Tool | Purpose |
|---|---|
| `image_generate_models` | List available models (call once before starting) |
| `image_generate_start` | Submit a generation job, returns `job_id` |
| `image_generate_wait_for_done` | **Preferred** — server-side wait until terminal (done/failed). One call per image. |
| `image_generate_result` | Snapshot or long-poll. Use only when you need concurrent polling of many jobs (rare). |
| `image_generate_delete` | Clean up after all images retrieved |

## Full Workflow

### Step 1 — Generate the style anchor image

The style anchor sets the visual tone for the entire video. All shot images reference it.

```
anchor_resp = image_generate_start(
  prompt = "<overall_visual_style> — cinematic establishing shot. Example: warm golden-hour lighting, shallow depth of field, realistic photography style",
  style_reference_path = null   // no reference for the anchor itself
)

result = image_generate_wait_for_done(job_id = anchor_resp.job_id, max_wait_sec = 300)
```

`wait_for_done` returns once the job reaches a terminal state. On `status == "done"`, save `local_image_path` as `style_anchor_image`. On `status == "failed"`, check `error_message`; you may retry once with a simplified prompt before giving up.

### Step 2 — Generate per-shot reference images

For each shot in `shots[]`, generate an image using the style anchor as reference:

```
shot_resp = image_generate_start(
  prompt = "<shot.prompt>",
  style_reference_path = "<style_anchor_image>"
)

result = image_generate_wait_for_done(job_id = shot_resp.job_id, max_wait_sec = 300)
```

Save `result.local_image_path` as `shots[i].reference_image_path`.

You can submit all shot jobs first, then wait_for_done each one in turn — the backend runs them concurrently, so sequential waits won't slow you down (the second/third wait usually returns immediately because those jobs finished while the first was waiting).

### Step 3 — Clean up

After all images are retrieved:
```
image_generate_delete(job_id = "<anchor_job_id>")
image_generate_delete(job_id = "<shot_job_id_1>")
...
```

## Polling Rules

- **Default**: use `image_generate_wait_for_done` — one call, one terminal answer.
- Status values: `queued` → `running` → `done` / `failed`
- If `wait_for_done` returns `status == "timeout"`, the job exceeded `max_wait_sec` (default 300s). Surface a blocker; do not loop indefinitely.
- If `status == "failed"`, check `error_message` and retry with a simplified prompt if it's a content policy rejection.
- Use `image_generate_result(wait_sec=30)` only when you genuinely need to peek at progress mid-run (rare in practice).

## Response Shape (done)

```json
{
  "job_id": "ig_abc123",
  "status": "done",
  "local_image_path": "./data/uploads/kling_img_xyz_20260101_120000.jpg",
  "image_url": "https://...",
  "manifest_path": "./data/uploads/kling_img_xyz_20260101_120000.json"
}
```

Use `local_image_path` as `style_anchor_image` or `reference_image_path` in `script.json`.

## Provider Capabilities

| Provider | Style Reference | Notes |
|---|---|---|
| `kling` (Kolors) | Native i2i — actual image sent to API | Best visual consistency across shots |
| `wanx` | Prompt augmentation only — reference not sent | Visual consistency is prompt-driven only |
| `minimax` | Prompt augmentation only — reference not sent | Same limitation as wanx |
| `mock` | No-op | For testing only |

For best results use `kling` as `IMAGE_PROVIDER` when storyboard consistency matters.

## Prompt Writing Tips

- Be specific and visual: describe what the camera sees, lighting, mood, composition.
- Avoid narrative ("the hero walks") — describe the frame ("a figure silhouetted against a sunset").
- Keep prompts under 200 characters for best results.
- Append the overall style to each shot prompt if needed (e.g., "warm cinematic lighting, realistic photography").

## Example Script.json Output

The `duration` values below are illustrative; pick lengths that fit the pacing of each shot (see writer AGENTS.md Step 4). Backend may quantize them to provider-supported values (e.g. MiniMax: 6 / 10).

```json
{
  "title": "探秘清迈古城",
  "script": "清迈，泰国北部的文化之心...",
  "shot_notes": "清迈古城风光，庙宇与街道",
  "tags": ["清迈", "旅行", "泰国"],
  "visual_style": "warm golden-hour light, cinematic travel photography, shallow depth of field",
  "style_anchor_image": "./data/uploads/kling_img_anchor_20260101.jpg",
  "shots": [
    {
      "index": 1,
      "duration": 6,
      "prompt": "Ancient Thai temple at golden hour, warm amber light on ornate golden spires, misty morning atmosphere",
      "narration": "清迈，泰国北部的文化之心",
      "reference_image_path": "./data/uploads/kling_img_shot1_20260101.jpg"
    },
    {
      "index": 2,
      "duration": 10,
      "prompt": "Narrow lantern-lit alley in old city, colorful market stalls, locals walking, warm evening glow",
      "narration": "古城的街道上，每一步都是历史",
      "reference_image_path": "./data/uploads/kling_img_shot2_20260101.jpg"
    }
  ]
}
```
