# BACKWARD_REWARD.md — Reward Specification

This document is the canonical reference for **how the reward block in `insights/episodes/<run_id>.json` is computed and what it means**. All Phase B/C/D code reads from `cluster_lib.py`; the formulas there are the source of truth and this doc reflects them.

If you change anything here, update `scripts/cluster_lib.py` to match (or the other way around) — never let them drift.

---

## 1. Reward block layout

After Phase B (`outcome_aggregator.py`) processes an episode, `episode.reward` looks like:

```json
{
  "join_status": "ok",
  "captured_windows": ["T+1h", "T+24h", "T+72h"],
  "snapshots": {
    "T+1h":  { "play_count": 312, "completion_rate": 0.42, "two_sec_exit_rate": 0.31,
               "like_count": 8, "comment_count": 1, "share_count": 0, "collect_count": 2,
               "danmaku_count": null, "follower_gain": 1, "follower_loss": 0,
               "fan_play_ratio": 0.12, "snapshot_at": "...", "captured_at": "...",
               "window": "T+1h" },
    "T+24h": { ... },
    "T+72h": { ... }
  },
  "longitudinal": {
    "early_burst_ratio": 0.18,
    "long_tail_ratio":   1.42,
    "retention_decay":   0.91,
    "growth_phase":      "long_tail"
  },
  "horizontal": {
    "cluster_id":         "户外美食__storyboard_30-60s",
    "cluster_n":          12,
    "retention_pct":      58,
    "conversion_pct":     72,
    "engagement_pct":     44,
    "viral_pct":          65,
    "reach_quality_pct":  71,
    "source_window":      "T+72h"
  },
  "outlier_flags": ["conversion_top10"]
}
```

Every numeric value can be `null` — every consumer (Phase C/D) MUST handle nulls.

---

## 2. `join_status` enum

| Value | Meaning | Set when |
|---|---|---|
| `ok` | At least one snapshot was successfully captured | HTTP join succeeded for ≥ 1 window |
| `not_yet` | Episode published < 1h ago, no windows reachable | publish_ts within last 1h |
| `join_failed` | All HTTP queries returned 0 matching items | bad title encoding, video deleted, etc. |
| `no_publish` | Episode is `task_mode=return_video` (no Douyin publish) | `publish.publish_ts is None` |

Phase C/D MUST skip episodes whose `join_status` is anything but `ok`.

---

## 3. Snapshot capture (the `snapshots` block)

Captured at three windows after publish:

| Window | Age threshold | Purpose |
|---|---|---|
| `T+1h`  | publish_ts + 1h  | Recommendation algorithm's early push signal |
| `T+24h` | publish_ts + 24h | Natural distribution stabilized |
| `T+72h` | publish_ts + 72h | Long-tail / search-driven traffic |

**Each snapshot is the latest available stats DB record** at the moment of capture. The plugin's `stats-collector` cron is the upstream — outcome_aggregator just reads what's there.

**Why these 3 windows specifically**: empirically Douyin's "推荐池" decision is reflected within ~1h (early_burst), the bulk of distribution lands by ~24h (the core volume), and the long-tail / search index kicks in by ~72h (viral signal). More windows would be free bookkeeping but no extra signal.

**Snapshot schema** mirrors the stats DB columns exactly (see `openclaw-plugins/video-http-tools/src/tools/stats.ts`):
`play_count`, `like_count`, `comment_count`, `share_count`, `collect_count`, `danmaku_count`, `completion_rate`, `two_sec_exit_rate`, `follower_gain`, `follower_loss`, `fan_play_ratio`. Plus two metadata fields:
- `snapshot_at` — when the platform itself snapshotted (from stats DB)
- `captured_at` — when outcome_aggregator captured it
- `window` — `T+1h` / `T+24h` / `T+72h`

`null` is preserved verbatim (not coerced to 0). Phase C/D treat null and 0 differently — `null` = "platform doesn't show this metric", 0 = "metric exists and equals 0".

---

## 4. Longitudinal block (single-episode trajectory)

Computed by `cluster_lib.longitudinal_fingerprint(snapshots)`.

### 4.1 Ratios

| Field | Formula | Definition |
|---|---|---|
| `early_burst_ratio` | `play_T+1h / play_T+24h` | "What fraction of 24h play came in the first hour" — >0.5 means platform pushed hard early |
| `long_tail_ratio` | `play_T+72h / play_T+24h` | >1 = still gaining views past 24h (search / re-distribution) |
| `retention_decay` | `completion_rate_T+72h / completion_rate_T+1h` | <1 = late viewers retain less than early ones |

Any field is `null` if its required snapshots are missing.

### 4.2 `growth_phase` classification (priority order)

Implemented in `cluster_lib.py` lines around `growth_phase`:

```
1. dead_silence       —  ALL three play_count < 50
2. early_burst_only   —  early_burst_ratio < 0.5  AND  retention_decay < 0.7
3. long_tail          —  long_tail_ratio > 1.3
4. stable_growth      —  any snapshot exists, none of above
5. unknown            —  no snapshot at all
```

**Why priority order matters**: a video with early_burst=0.18 (heavy hour-1 push, fading by 24h) AND long_tail=1.4 (still climbing by 72h) is unusual but possible — we classify by `early_burst_only` first because the retention_decay signal is the more diagnostic of the two.

**These thresholds are empirical**:
- `0.5` for early_burst: <0.5 means hour-1 was less than half of 24h (i.e., distribution was front-loaded)
- `0.7` for retention_decay: 30%+ drop in completion_rate over 72h is meaningful
- `1.3` for long_tail: >30% growth between 24h and 72h is platform-confirmed long-tail
- `50` for dead: below 50 plays, almost all metrics are statistically meaningless

If routing rules (`docs/BACKWARD_ROUTING.md`) suggest this is wrong, change BOTH this doc AND `cluster_lib.py`.

---

## 5. Horizontal block (cross-episode percentile)

Computed by `cluster_lib.percentile_rank(value, cluster_population)`.

### 5.1 Cluster definition

`cluster_id = "<grounded_tag>__<mode>_<duration_bucket>"`

Where:
- `grounded_tag` from `episode.brief.grounded_tag` (the most load-bearing field)
- `mode` from `episode.script_summary.mode` ∈ {single, storyboard}
- `duration_bucket` from `episode.script_summary.total_duration`:
  - `<30s`: total_duration < 30
  - `30-60s`: 30 ≤ total_duration ≤ 60
  - `>60s`: total_duration > 60
  - `unknowns`: missing or invalid

Examples:
- `户外美食__storyboard_30-60s`
- `美食__single_<30s`
- `unknown__unknown_unknowns` (everything missing — never compare across these)

**Minimum cluster size for percentile to mean anything**: cluster_lib uses 1 sample → 50 (median fallback), 2+ samples → real percentile. Outlier flagging requires ≥ 5.

### 5.2 The 5 reward dimensions

Each derived from the **most recent available snapshot** (`T+72h` preferred → `T+24h` → `T+1h`). The chosen window is recorded in `horizontal.source_window`.

| Dimension | Formula | What it measures | Primary "owning" agent |
|---|---|---|---|
| `retention` | `completion_rate × (1 − two_sec_exit_rate)` | Watching-quality (didn't bounce + finished) | writer + video-generate |
| `conversion` | `(follower_gain − follower_loss) / max(play, 100)` | Net follower gain per view (denom_floor=100 prevents tiny-play noise) | tag-matcher + writer |
| `engagement` | `(like + comment + share + collect + danmaku) / play` | Active interaction rate | writer |
| `viral` | `long_tail_ratio` (`play_T+72h / play_T+24h`) | Beyond-24h sustained growth | research-supervisor + writer |
| `reach_quality` | `1 − fan_play_ratio` | Fraction of plays from non-followers (breakout strength) | tag-matcher + publisher |

**Why these 5 not a single scalar**: a video can be high-retention low-conversion or high-engagement low-reach. Collapsing them hides which agent's decision needs revisiting. Phase C/D credit-assigns per dimension via `BACKWARD_ROUTING.md` rules.

**Why `engagement` includes `danmaku_count`** even though stats-collector currently doesn't capture it: the formula is forward-compatible; null danmaku contributes 0 to the sum but doesn't poison the result. The day stats-collector starts capturing danmaku, no formula change needed.

**Why `conversion` uses `(gain − loss)` not just `gain`**: a video that nets +10 gain but caused 8 unfollows is fundamentally weaker than +10 gain alone. The signed delta is the honest signal.

### 5.3 `<dim>_pct` calculation

For each dimension, percentile within cluster:

```
pop = [derived[dim] for episode in same_cluster_episodes if not null]
if len(pop) == 0: pct = null
elif len(pop) == 1: pct = 50         # median fallback
else: pct = round(100 × count(p < value) / (len(pop) − 1))
```

Note `len-1` denominator: percentile excludes self. Ties get the lower percentile (conservative).

---

## 6. `outlier_flags`

```
if cluster_n < 5: flags = []          # sample too small to call outlier
else:
  for each dim:
    if pct ≤ 10: append "<dim>_bottom10"
    if pct ≥ 90: append "<dim>_top10"
```

Used by Phase D `trace-critic`: only outlier episodes get LLM critique (cost control + signal-to-noise).

---

## 7. Idempotency contract

Re-running `outcome_aggregator.py` produces the **same** episode reward block, given the same stats DB state. Specifically:

- Already-captured snapshots are NOT re-queried (preserves first capture).
- Longitudinal + horizontal + outlier_flags ARE recomputed every run (cheap; uses whatever snapshots exist + cross-episode population).
- Atomic file write ensures partial reads can't see inconsistent state.

This means cron can safely run hourly; the cost is bounded by `episodes_count × HTTP_query_cost`.

---

## 8. Cross-references

- Source of truth (formulas + thresholds): `~/.openclaw/scripts/cluster_lib.py`
- Episode schema: `~/.openclaw/insights/episodes/SCHEMA.md`
- Routing rules (reward dim → agent): `~/.openclaw/docs/BACKWARD_ROUTING.md` (Phase D)
- Run dir layout: `~/.openclaw/docs/RUN_LAYOUT.md`
