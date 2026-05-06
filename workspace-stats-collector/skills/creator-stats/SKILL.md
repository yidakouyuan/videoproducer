---
name: creator-stats
description: "Navigate to Douyin Creator Center data dashboard via browser on the Windows node and collect video performance stats. You MUST use the browser tool at every step — do not simulate or infer any data."
---

# Creator Stats

Navigate to the Douyin Creator Center data analytics section and extract per-video performance metrics.

## Quick Reference

| Situation | Required Action |
|-----------|--------|
| All browser calls | MUST use `browser(target="node", profile="openclaw", ...)` — relay and local browser will fail |
| Login expired / not logged in | Stop immediately, report `login_required` to agent |
| Metric not shown on page | Omit the field — do not substitute zero or a guess |
| Pagination available | Continue collecting until all pages are exhausted |
| Browser node unavailable | Stop immediately, report exact error |

## Solution

### Step-by-Step

1. Open Douyin Creator Center in browser: navigate to `https://creator.douyin.com`
2. Confirm you are logged in. If not, stop and report `login_required`.
3. Navigate to the data analytics section (数据 → 视频数据 or equivalent)
4. For each video card / row in the data table:
   - Read `title` and `publish_time`
   - Read all visible metrics: play_count, like_count, comment_count, share_count, collect_count, completion_rate, two_sec_exit_rate, follower_gain, follower_loss, fan_play_ratio, duration_sec
   - Only record fields that are explicitly shown — skip fields not present
5. If the list is paginated, advance through all pages
6. Return the complete collected list to the agent

### Return

Return an array of collected video stat objects:

```json
[
  {
    "platform": "douyin",
    "title": "video title here",
    "publish_time": "2026-03-10T12:00:00Z",
    "play_count": 100000,
    "like_count": 5000,
    "comment_count": 200,
    "share_count": 300,
    "collect_count": 1200,
    "completion_rate": 0.43,
    "two_sec_exit_rate": 0.18,
    "follower_gain": 320,
    "follower_loss": 12,
    "fan_play_ratio": 0.25
  }
]
```

## Gotchas

- The platform data page may use abbreviated numbers — convert to integers before returning.
- publish_time must be converted to ISO 8601 UTC format.
- Do not navigate to the publish/upload flow — data section only.

---
