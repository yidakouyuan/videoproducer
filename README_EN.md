# VideoClaw

A fully automated Douyin video production system built on [OpenClaw](https://openclaw.ai).

Send a topic via Telegram or WhatsApp. The system researches it, writes a script, generates a video, publishes it to Douyin — and learns from every video's performance to do better next time.

---

## Architecture

The system has two parts that work together:

### Part 1 — OpenClaw Agent Pipeline

A chain of specialized agents coordinated by an orchestrator:

```
User Request (Telegram / WhatsApp)
  → orchestrator        ← coordinates the pipeline; references weekly reports
  → tag-matcher         ← grounds the topic into specific Douyin tags
  → research-supervisor ← plans and coordinates research (runs in parallel)
    ├── douyin-search   ← finds candidate videos on Douyin
    └── web-search      ← gathers supporting evidence from the web
  → writer              ← turns research into a complete script
  → video-generate      ← generates the video via HTTP service
  → publisher           ← publishes to Douyin Creator Center
```

### Part 2 — External HTTP Service (`agent-service/`)

A Python FastAPI backend that the OpenClaw plugin calls to do the heavy lifting:

- Fetch and analyze Douyin videos (via cookies + Gemini)
- Transcribe video audio (Gemini)
- Generate videos (MiniMax Hailuo or ByteDance Seedance/Ark)
- Serve tag knowledge from GraphRAG knowledge base
- Store and query video performance stats

### Feedback Loop

The system closes the loop between production and performance:

```
Published videos
  → stats-collector (every 6h)   ← collects performance data into SQLite
  → stats-analyzer (Mon 9 AM)    ← generates weekly report
  → orchestrator                 ← uses reports to inform future production
```

---

## Prerequisites

- [OpenClaw](https://openclaw.ai) installed
- Python 3.10+
- A **Douyin account** (cookies for media fetching)
- **Google Gemini API key** (transcription + video analysis)
- At least one **video generation API key**: MiniMax Hailuo or ByteDance Ark (Seedance)
- A **Telegram bot** and/or **WhatsApp account**
- _(Optional)_ A **Windows node** for browser-based Douyin Creator Center publishing — see [docs/BROWSER.md](docs/BROWSER.md)

---

## Quick Start

### Step 1 — Clone the repo

Clone into your OpenClaw directory (default `~/.openclaw`):

```bash
git clone https://github.com/yangyuhang2003-netizen/videoclaw.git ~/.openclaw
cd ~/.openclaw
```

### Step 2 — Start the external service

The external service must be running before OpenClaw starts.

```bash
cd agent-service
pip install -r requirements.txt
```

Copy and fill in the config:

```bash
cp .env.example .env
# Edit .env — fill in API keys and paths
```

Put your Douyin cookies in `config/douyin_cookies.txt` (Netscape format, exported from browser).

Build the tag knowledge base (one-time setup):

```bash
cd video-agent-system/tag_knowledge_db
# See tag_knowledge_db/README.md for the full build process
```

Start the service:

```bash
cd ~/agent-service   # or wherever you cloned it
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Windows users** can use the restart script (edit the paths at the top first):

```powershell
powershell .\kill_restart.ps1
```

Verify it's running:

```bash
curl http://localhost:8000/health
```

### Step 3 — Configure OpenClaw

Back in the repo root:

```bash
./setup.sh
```

This generates `openclaw.json` from the template with your install path set. Then fill in the remaining placeholders:

| Placeholder | What to fill in |
|---|---|
| `YOUR_TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `YOUR_TELEGRAM_USER_ID` | Your Telegram user ID (`tg:12345678`) |
| `YOUR_WHATSAPP_NUMBER` | With country code, e.g. `+8613800000000` |
| `YOUR_GATEWAY_AUTH_TOKEN` | Any random secret string |
| `YOUR_VIDEO_SERVICE_HOST` | IP of the machine running the external service (Step 2) |

### Step 4 — Install the plugin

```bash
cd openclaw-plugins/video-http-tools
npm install
npm run build
```

### Step 5 — Start OpenClaw

```bash
openclaw start
```

Send a topic to your Telegram bot or WhatsApp to trigger the pipeline.

---

## Windows Node Setup (for Douyin publishing)

If you're running OpenClaw on WSL and want browser-based Douyin Creator Center publishing, you need a Windows node connected to OpenClaw. See [docs/BROWSER.md](docs/BROWSER.md).

If you're on macOS or don't need Creator Center publishing, skip this entirely.

---

## Project Structure

```
├── agent-service/               # Python FastAPI backend (external HTTP service)
│   ├── app/
│   │   ├── providers/            # Integrations: Gemini, MiniMax, Seedance, Douyin
│   │   ├── routes/               # API endpoints
│   │   ├── services/             # Business logic
│   │   ├── schemas/              # Request/response models
│   │   └── infra/                # DB, exceptions, response formatting
│   ├── video-agent-system/
│   │   ├── src/                  # Douyin video collection pipeline
│   │   └── tag_knowledge_db/     # GraphRAG tag knowledge base builder
│   ├── .env.example              # Config template
│   └── kill_restart.ps1          # Windows restart script
│
├── openclaw-plugins/
│   └── video-http-tools/         # OpenClaw plugin wrapping the HTTP service
│
├── workspace-orchestrator/       # Orchestrator agent
├── workspace-tag-matcher/        # Tag grounding agent
├── workspace-research-supervisor/# Research coordinator
├── workspace-douyin-search/      # Douyin search agent
├── workspace-web-search/         # Web research agent
├── workspace-writer/             # Script writing agent
├── workspace-video-generate/     # Video generation agent
├── workspace-publisher/          # Douyin Creator Center publisher
├── workspace-stats-collector/    # Performance data collector
├── workspace-stats-analyzer/     # Weekly report generator
├── workspace/                    # Main agent workspace
│
├── docs/                         # Architecture documentation
├── cron/                         # Scheduled job definitions
├── openclaw.example.json         # OpenClaw config template
└── setup.sh                      # Setup script (generates openclaw.json)
```

---

## Docs

- [docs/PIPELINE.md](docs/PIPELINE.md) — Full pipeline and data flow
- [docs/RUN_LAYOUT.md](docs/RUN_LAYOUT.md) — Run directory structure
- [docs/ASYNC_JOBS.md](docs/ASYNC_JOBS.md) — Async job handling
- [docs/BROWSER.md](docs/BROWSER.md) — Windows browser node protocol
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — Shared agent principles
- [agent-service/API_documents.txt](agent-service/API_documents.txt) — External service API reference
- [agent-service/video-agent-system/tag_knowledge_db/README.md](agent-service/video-agent-system/tag_knowledge_db/README.md) — Tag knowledge base build guide
