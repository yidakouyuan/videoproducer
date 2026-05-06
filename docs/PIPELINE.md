# PIPELINE.md — openclaw Video Creation Pipeline

Read this to understand the full picture: what the pipeline does, where you fit, and how your output is used downstream.

---

## Overview

openclaw turns a user request into a published Douyin video through a chain of specialized agents coordinated by the orchestrator.

```
User Request
    ↓
[orchestrator]          ← coordinates the full pipeline
    ↓
[tag-matcher]           ← grounds the topic into specific tags
    ↓
[research-supervisor]   ← plans and coordinates research
    ├── [douyin-search] ← finds candidate videos on Douyin
    └── [web-search]    ← gathers supporting evidence from the web
    ↓
[writer]                ← turns research into a complete script
    ↓
[video-generate]        ← generates the video (async)
    ↓  (only if publish_directly + user confirmed)
[publisher]             ← publishes to Douyin Creator Center
    ↓
User (status update)
```

---

## Agents at a Glance

| Agent | Type | Receives from | Delivers to |
|---|---|---|---|
| **orchestrator** | coordinator | user | everyone |
| **tag-matcher** | leaf | orchestrator | orchestrator |
| **research-supervisor** | coordinator | orchestrator | orchestrator |
| **douyin-search** | leaf | research-supervisor | research-supervisor |
| **web-search** | leaf | research-supervisor | research-supervisor |
| **writer** | leaf | orchestrator | orchestrator |
| **video-generate** | leaf | orchestrator | orchestrator |
| **publisher** | leaf | orchestrator | Douyin / user |

---

## Stage-by-Stage Data Flow

### Stage 1 — Topic Grounding

**orchestrator → tag-matcher → orchestrator**

- Input: full user query + topic
- Output: grounded tag + tag context (`canonical_topic`, `script_pack`, `search_seeds`)

### Stage 2 — Research

**orchestrator → research-supervisor → orchestrator**

research-supervisor internally dispatches two workers in parallel:
- **douyin-search**: queries + candidate budget → candidate video list (`aweme_id`, `share_url`, engagement metadata)
- **web-search**: queries + page budget → web result set (summaries + excerpts)

research-supervisor then shortlists, downloads, analyzes, transcribes, and filters.

- Output: `video_research_results` + `web_research_results` (filtered, enriched — not raw)

### Stage 3 — Writing

**orchestrator → writer → orchestrator**

- Input: full user query + topic + grounded tag + research results
- Output: complete script (`title`, `script`, `shot_notes`, `tags`)

### Stage 4 — Video Generation

**orchestrator → video-generate → orchestrator**

- Input: complete script
- Output: `local_video_path` (after async polling — may take a while)

### Stage 5 — Publishing _(conditional)_

**orchestrator → publisher → Douyin**

Only runs when `task_mode = publish_directly` AND the user has confirmed at the publish gate.

- Input: `local_video_path` + complete script + grounded tag
- Output: publish result (`success`, `status`, `error`)

---

## Key Rules

- **Orchestrator** holds pipeline state via `run_id`. All downstream agents receive `run_id` and read/write files in `~/.openclaw/runs/{run_id}/` — not large data payloads in context. → See `~/.openclaw/docs/RUN_LAYOUT.md`.
- **Leaf agents** only speak to whoever called them. They do not reach across the pipeline.
- **research-supervisor** is the only non-leaf agent besides orchestrator. It coordinates its own sub-workers but does not own the full pipeline.
- **Nothing reaches the publisher** without passing through the orchestrator's publish gate.
