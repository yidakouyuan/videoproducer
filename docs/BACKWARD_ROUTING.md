# BACKWARD_ROUTING.md — Reward → Agent Routing Rules

This is the **"constitution"** of the backward-optimization system: it maps reward signals to which agent should be reflected on. Hand-authored from domain knowledge — these aren't learned from data. The rules encode known causal structure of the pipeline (writer controls hook → affects retention; publisher controls publish_time → affects early play).

The machine-readable version lives at `~/.openclaw/insights/routing_rules.json`. This doc is the human-readable explanation. **When you change one, change the other.**

Used by:
- `trace-critic` agent (Phase D) — reads `routing_rules.json` to know which agents/decision_points to focus its diagnosis on for a given outlier
- `playbook-curator` script (Phase D) — reads `routing_rules.json` to dispatch attribution events to the correct agent's playbook

---

## 1. How the rules fire

For an episode with `reward.outlier_flags` and `reward.longitudinal.growth_phase`:

```
For each rule R in routing_rules.rules:
    if R.trigger evaluates true on this episode's reward block:
        - LLM critic (Phase D) receives R.primary, R.secondary, R.diagnostic_focus
          as targeted reflection scope
        - Curator routes critic's output `attribution events` to the agents
          listed in R.primary (and R.secondary if confidence is high)
```

A single episode can fire multiple rules (e.g. `retention_bottom10` AND `early_burst_only`).

---

## 2. The rules table (mirror of routing_rules.json)

### 2.1 Horizontal (cross-cluster outlier) rules

| Rule | Trigger | Primary agent(s) | Secondary | Why |
|---|---|---|---|---|
| `retention_bottom10` | retention_pct ≤ 10 | writer, video-generate | tag-matcher | Hook bombed / shots dragged / wrong audience |
| `retention_top10`    | retention_pct ≥ 90 | writer, video-generate | — | Learn from positive |
| `conversion_bottom10`| conversion_pct ≤ 10 | tag-matcher, writer | research-supervisor | Wrong audience or no value-prop / CTA |
| `conversion_top10`   | conversion_pct ≥ 90 | tag-matcher, writer | — | Learn from positive |
| `engagement_bottom10`| engagement_pct ≤ 10 | writer | — | No emotional hook / no comment bait |
| `engagement_top10`   | engagement_pct ≥ 90 | writer | — | Learn from positive |
| `viral_top10`        | viral_pct ≥ 90 | research-supervisor, writer | — | Topical novelty / evergreen framing |
| `reach_quality_bottom10` | reach_quality_pct ≤ 10 | tag-matcher, publisher | — | Mostly old fans — tag too narrow / hashtag too generic |

### 2.2 Longitudinal (single-trajectory) rules

| Rule | Trigger | Primary | Secondary | Why |
|---|---|---|---|---|
| `early_burst_only` | growth_phase == "early_burst_only" | writer, publisher | — | Title/hook overpromised; viewers bounced after platform's early push |
| `dead_silence` | growth_phase == "dead_silence" | publisher, tag-matcher | writer | No distribution at all — fundamentals wrong (time / tag / hook) |
| `long_tail` | growth_phase == "long_tail" | research-supervisor, writer | tag-matcher | Search-driven sustained growth — content has topical staying power |

### 2.3 Diagnostic focus per agent (the LLM critic's hint set)

When a rule fires, the critic gets a list of **decision_locator names** that it should specifically reason about. These are the names from `agent_decision_points` in routing_rules.json. Examples:

- `writer.hook_pattern` — `question` / `statement` / `number` / `contrast`
- `writer.narrative_pace` — words/second; pause patterns
- `video-generate.shot_avg_duration` — average seconds per shot
- `publisher.publish_hour` — 0-23

**Why a fixed decision-point taxonomy**: critic outputs use these names as `decision_locator` field in attribution events; curator + downstream stat-attributor (Phase C) speak the same vocabulary; playbooks aggregate by these keys.

---

## 3. Why these rules and not others

### Why `retention_bottom10` primary is writer + video-generate (not just writer)

Retention is a joint product:
- writer's hook decides if viewers stick around the first 5 seconds
- video-generate's shot pacing decides if they stick around for the full 30 seconds

If we only blamed writer, we'd miss the case where the hook is great but shot 1 is 12 seconds of static visuals.

### Why `conversion_bottom10` primary is tag-matcher + writer (not video-generate)

Conversion (follower_gain / play) is mostly about whether the audience saw value worth subscribing for. That's:
- tag-matcher's job: did we get this video to the right audience? (a 美食 video shown to 财经 users won't convert)
- writer's job: was there a value proposition or CTA worth following the creator for?

video-generate doesn't drive conversion much — even a great-looking video doesn't convert if it's irrelevant to the viewer.

### Why `early_burst_only` primary is writer + publisher (not video-generate)

Early burst then drop = platform pushed but viewers fled. The "fled" reason is almost always:
- title clickbait (writer wrote misleading title)
- hashtag pile-on attracting irrelevant clicks (publisher chose too many trending tags)

Shot quality is fine — they're bouncing in 2 seconds, not 20.

### Why `dead_silence` primary is publisher + tag-matcher

If platform never picked it up, the content quality didn't even get a chance. The bottlenecks are upstream of content:
- publisher: wrong hour, too few/generic hashtags
- tag-matcher: grounded_tag has no audience pool to draw from

We list writer as secondary in case the title/hook is so off it lost cold-start review, but that's rare.

---

## 4. Using `routing_rules.json` programmatically

```python
import json
rules = json.load(open("~/.openclaw/insights/routing_rules.json"))
# Find which rules fire for an episode:
def fires(rule_id, rule, reward):
    if rule_id.endswith("_bottom10") or rule_id.endswith("_top10"):
        return rule_id in (reward.get("outlier_flags") or [])
    if rule_id in ("early_burst_only", "dead_silence", "long_tail"):
        return (reward.get("longitudinal") or {}).get("growth_phase") == rule_id
    return False
```

(playbook_curator.py implements this, with proper null-handling.)

---

## 5. Evolution

These rules are v1 — based on conventional wisdom about Douyin's recommendation pipeline. They will be wrong sometimes. The intended evolution path:

1. **Now (v1)**: hand-authored, frozen for stability while data accumulates
2. **After ≥ 50 episodes per cluster**: stat-attributor (Phase C) statistical evidence may CONTRADICT a rule (e.g. data shows engagement is also driven by shot pacing, not just writer). Update both the rule and this doc.
3. **After Phase E**: prompt evolution may auto-discover new rules. Curator could append discovered rules below as proposals for human review.

When you change a rule, bump `routing_rules.json::version` to today's date (YYYY-MM-DD). Consumers don't strictly need to re-read on version change but it's a useful audit trail.

---

## 6. Cross-references

- Reward formulas: `~/.openclaw/docs/BACKWARD_REWARD.md`
- Episode schema: `~/.openclaw/insights/episodes/SCHEMA.md`
- Diagnostics (attribution event) schema: `~/.openclaw/insights/diagnostics/SCHEMA.md`
- Routing rules JSON (machine-readable, source of truth): `~/.openclaw/insights/routing_rules.json`
