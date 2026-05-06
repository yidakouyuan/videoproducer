# Skill: Video Stitching

## Purpose

Concatenate multiple per-shot video clips into a single final video using the `video_stitch` tool. Call this after all shot videos are done (status=done).

## Tool

| Tool | Purpose |
|---|---|
| `video_stitch` | POST /video/stitch — ffmpeg concat on the server |

## When to Call

After the multi-shot polling loop finishes and you have `local_video_path` for each successful shot. Pass all paths **in shot index order**.

## Parameters

```
video_stitch(
  video_paths = ["./data/uploads/clip_shot1.mp4", "./data/uploads/clip_shot2.mp4", ...],
  output_name = "final_<run_id>",   // optional, auto-generated if omitted
  reencode    = false               // see below
)
```

## reencode Flag

| Mode | Speed | When to use |
|---|---|---|
| `reencode=false` (default) | Very fast (stream copy, no re-encode) | All clips from the same provider at the same resolution |
| `reencode=true` | Slower (H.264 transcode to 1920×1080) | Mixed providers, mixed resolutions, or if default mode fails |

**Retry rule:** If `reencode=false` returns an error mentioning codec mismatch or "Invalid data", retry immediately with `reencode=true`.

## Response Shape (success)

```json
{
  "ok": true,
  "data": {
    "local_video_path": "./data/uploads/stitched_abc123_1234567890.mp4",
    "clip_count": 3
  }
}
```

`local_video_path` is the final video to write into `video_result.json`.

## Failure Handling

- If `video_stitch` fails even with `reencode=true`: return a blocker with the ffmpeg error message. Do not fabricate a path.
- This skill is only invoked in strict mode — by the time you reach `video_stitch`, every shot must already be `done`. If a shot is missing, the upstream wait+retry loop should have aborted before getting here.

## Example — Multi-Shot Result File

After stitching, write `video_result.json` (strict mode, all shots done):

```json
{
  "job_id": "vg_stitch_abc",
  "status": "done",
  "local_video_path": "./data/uploads/final_20260101_120000.mp4",
  "shots": [
    {"index": 1, "job_id": "vg_xxx", "status": "done", "local_video_path": "./data/uploads/clip1.mp4"},
    {"index": 2, "job_id": "vg_yyy", "status": "done", "local_video_path": "./data/uploads/clip2.mp4"},
    {"index": 3, "job_id": "vg_zzz", "status": "done", "local_video_path": "./data/uploads/clip3.mp4"}
  ]
}
```

Top-level `status` should always be `"done"` when this file is written. If any shot failed (after retry), the file is not written at all — the run aborts upstream.
