# BACKWARD_OPS.md — How to run the backward pipeline

This is an ops cheatsheet for running `outcome_aggregator.py` (Phase B) and other backward pipeline scripts on a schedule. None of these are auto-configured — you pick one and enable it when you're ready to start collecting reward data.

## Manual one-shot

For testing or backfill:

```bash
python ~/.openclaw/scripts/outcome_aggregator.py                              # full run + auto chain curator
python ~/.openclaw/scripts/outcome_aggregator.py --episode 20260427_230544    # single episode
python ~/.openclaw/scripts/outcome_aggregator.py --dry-run                    # plan only
python ~/.openclaw/scripts/outcome_aggregator.py --no-curator                 # skip curator chain
```

By default `outcome_aggregator.py` automatically chains into `playbook_curator.py` after capturing rewards. Pass `--no-curator` to disable. The script is idempotent and safe to re-run any time.

## End-to-end demo (manual chain, one-shot)

To verify the entire backward chain end-to-end after publishing real videos:

```bash
# 1. Run a publish_directly pipeline (this writes runs/<run_id>/* + episode)
openclaw agents spawn orchestrator "做一个测试视频并发布"

# 2. Wait for stats-collector to capture stats. This is the critical bottleneck:
#    it currently runs every 6h and needs Creator Center login healthy.
#    Manually trigger if needed:
openclaw agents spawn stats-collector "manual run"

# 3. Capture rewards (joins stats DB → episodes; also auto-chains curator)
python ~/.openclaw/scripts/outcome_aggregator.py

# 4. If outliers were flagged in step 3, spawn trace-critic on each:
bash ~/.openclaw/scripts/spawn_critic_for_outliers.sh

# 5. trace-critic sessions are async. Wait ~1-2 min, then re-run aggregator
#    (which will auto-chain curator and consume the new diagnostics):
python ~/.openclaw/scripts/outcome_aggregator.py

# 6. Inspect outputs
ls ~/.openclaw/insights/playbooks/                      # per-agent playbooks
ls ~/.openclaw/workspace-*/MEMORY.md._pending_*.md      # pending promotions
cat ~/.openclaw/insights/suggestions.json                # orchestrator-readable
```

**Reality check on what you'll see after just one run:**

| What you'll see | Why |
|---|---|
| `episode <run_id>.json` written immediately | episode_init runs at publish time |
| `reward.join_status: not_yet` for ~1h | T+1h window not reached |
| `reward.outlier_flags: []` | needs ≥ 5 episodes in same cluster (`grounded_tag × shot_archetype`) for percentile to mean anything |
| empty `playbooks/<agent>.md` | curator only writes from strong-evidence events |
| `_pending` files only after critic runs | weak-evidence path |

**The full backward learning loop genuinely requires data accumulation** (≥ 5 publishes in the same `(grounded_tag, shot_archetype)` cluster). One run lets you verify the **plumbing** works; ~5-10 runs lets you see real outlier flags; ongoing runs let the playbooks evolve.

## Option 1 — WSL crontab (recommended)

Most direct. Add to `crontab -e` inside WSL:

```cron
# every hour, capture any reachable T+1h/24h/72h windows
5 * * * *   /usr/bin/python3 /home/administrator/.openclaw/scripts/outcome_aggregator.py >> /home/administrator/.openclaw/logs/outcome_aggregator.log 2>&1
```

The `5 * * * *` (5 min past the hour) gives stats-collector — which runs at `0 */6 * * *` — a buffer to finish writing before we read.

**Pros**: completely decoupled from OpenClaw runtime; survives OpenClaw restart; no OpenClaw config changes needed.

**Cons**: lives outside OpenClaw's `cron/jobs.json`, so `openclaw cron list` won't show it.

## Option 2 — Piggyback on stats-collector

If you want the aggregator to run **right after** stats-collector finishes (same data freshness), append a step to `workspace-stats-collector/AGENTS.md`:

```
### Step 5 — Trigger backward aggregator (best-effort)

After Step 4 writes last_run.txt, call:

  exec(command="bash -lc 'python3 ~/.openclaw/scripts/outcome_aggregator.py || true'", yieldMs=120000)

This refreshes ~/.openclaw/insights/episodes/*.json reward blocks. Failure does NOT impact the collector's success — `|| true` ensures best-effort.
```

**Pros**: maximum data freshness — aggregator runs as soon as new stats land.

**Cons**: couples two concerns; stats-collector cron is currently `0 */6 * * *` so windows hit every 6h not every hour. To restore hourly cadence you'd also change `cron/jobs.json` `expr` to `0 * * * *` (and stats-collector login must be solid for that frequency).

## Option 3 — New OpenClaw cron entry (heaviest)

Add to `~/.openclaw/cron/jobs.json` `jobs[]`:

```json
{
  "id": "outcome-aggregator",
  "agentId": "main",
  "name": "outcome-aggregator",
  "enabled": true,
  "schedule": { "kind": "cron", "expr": "5 * * * *", "tz": "Asia/Shanghai" },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "Run outcome_aggregator: exec bash -lc 'python3 ~/.openclaw/scripts/outcome_aggregator.py'. Report only meaningful state changes (new captures, join_failed counts, cluster sizes that crossed thresholds)."
  }
}
```

**Pros**: visible to `openclaw cron list`; gateway manages it.

**Cons**: every hour spawns a `main` agent session (LLM cost just to run a Python script — wasteful). Use only if you want LLM commentary on each run.

## Recommendation

**Start with Option 1 (WSL crontab)** for the cleanest separation. Switch to Option 2 only after you decide stats-collector should also run hourly.

## Health check

```bash
# Has cron actually run recently?
tail -5 ~/.openclaw/logs/outcome_aggregator.log

# How many episodes are in each join_status?
python3 -c "
import json, glob
from collections import Counter
status = Counter()
for p in glob.glob('/home/administrator/.openclaw/insights/episodes/*.json'):
    d = json.load(open(p, encoding='utf-8'))
    status[(d.get('reward') or {}).get('join_status') or 'no_reward'] += 1
print(dict(status))
"

# Inspect a specific episode's reward
python3 -c "
import json
print(json.dumps(json.load(open('/home/administrator/.openclaw/insights/episodes/<run_id>.json'))['reward'], indent=2, ensure_ascii=False))
"
```

## Other backward pipeline scripts (Phase D)

When Phase D ships, two more scripts will need scheduling on the same cadence (or every 6h is fine):

- `scripts/playbook_curator.py` — once per day, after diagnostics accumulate
- `trace-critic` agent — triggered per outlier episode (event-driven, not cron)

Their ops docs will land alongside D's release.
