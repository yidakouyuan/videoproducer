# VideoClaw

基于 [OpenClaw](https://openclaw.ai) 的多 Agent 短视频自动化生产系统。

你只需要在飞书里发送一句视频需求，VideoClaw 会自动完成选题接地、热门内容调研、脚本撰写、分镜视频生成、自动拼接、结果回传，并可继续接入抖音发布与数据复盘。

> 一句话概括：把“我想做一条短视频”到“成片可发布”之间的琐碎流程，交给一组专职 Agent 协同完成。

---

## 核心能力

- **多 Agent 流水线**：orchestrator 统一调度 tag-matcher、research-supervisor、writer、video-generate、publisher 等专职 Agent。
- **双通道调研**：同时结合抖音候选视频与网页资料，为脚本生成提供内容依据。
- **脚本与分镜生成**：生成标题、旁白、镜头描述、标签和多分镜 storyboard。
- **视频生成与拼接**：支持 MiniMax Hailuo、字节跳动 Seedance/Ark 等视频生成服务；多分镜可并行生成并通过 ffmpeg 自动拼接。
- **发布与反馈闭环**：可接入抖音创作者中心发布，并通过 stats collector/analyzer 跟踪表现数据，反哺下一轮内容生产。
- **本地可调试**：FastAPI 后端提供健康检查、任务状态查询、视频生成、转写、分析、标签检索等 HTTP API。

---

## Demo

示例输入：

```text
请你给我做一个户外美食相关的30秒左右的视频
```

示例流水线：

```text
tag-matcher
  -> research-supervisor
     -> douyin-search
     -> web-search
  -> writer
  -> video-generate
  -> publisher
```

## 系统架构

VideoClaw 由三层组成：

### 1. OpenClaw 多 Agent 流水线

```text
用户请求
  -> orchestrator          总协调，创建 run_id 并推进流程
  -> tag-matcher           将宽泛话题接地为可检索、可创作的具体标签
  -> research-supervisor   规划调研任务，并发调度子 Agent
     -> douyin-search      检索抖音候选视频
     -> web-search         搜集网页背景资料
  -> writer                生成完整脚本、分镜、旁白、标题和标签
  -> video-generate        调用视频生成服务，等待异步任务完成并拼接
  -> publisher             可选：发布到抖音创作者中心
```

流水线通过 `run_id` 共享状态。每次任务会在 OpenClaw runs 目录中生成一组结构化产物，例如：

```text
runs/<run_id>/
  brief.json
  research_douyin.json
  research_web.json
  script.json
  video_result.json
  publish_result.json
```

### 2. 外部 HTTP 服务（`agent-service/`）

`agent-service` 是一个 Python FastAPI 后端，为 OpenClaw 插件提供重型能力：

- 抖音视频解析、下载与清理
- Gemini 视频分析与音频转写
- MiniMax / Seedance 视频生成
- 多分镜视频拼接
- 标签知识库查询
- 视频表现数据存储与查询
- 飞书机器人事件回调与任务状态观察

服务启动后可访问：

```text
GET  /health
GET  /docs
GET  /runs
GET  /runs/{run_id}/status
POST /webhooks/feishu/events
```

### 3. OpenClaw 插件（`openclaw-plugins/video-http-tools/`）

TypeScript 插件负责把 OpenClaw Tool 调用转发到 FastAPI：

- `tag_get_script_pack`
- `media_resolve_video`
- `media_fetch_video`
- `video_analyze_start`
- `transcribe_start`
- `video_generate_start`
- `video_generate_wait_for_done`
- `video_stitch`
- `stats_query`
- `stats_writer`

---

## 项目结构

```text
.
├── agent-service/                  # FastAPI 后端服务
│   ├── app/
│   │   ├── routes/                 # HTTP 路由
│   │   ├── services/               # 业务服务
│   │   ├── providers/              # Gemini、MiniMax、Seedance、Douyin 等 provider
│   │   ├── schemas/                # Pydantic 请求/响应模型
│   │   └── adapters/               # 飞书等消息适配器
│   ├── video-agent-system/         # 抖音采集与标签知识库构建工具
│   ├── requirements.txt
│   └── .env.example
│
├── openclaw-plugins/
│   └── video-http-tools/           # OpenClaw HTTP 工具插件
│
├── workspace-orchestrator/         # 总协调 Agent
├── workspace-tag-matcher/          # 标签接地 Agent
├── workspace-research-supervisor/  # 调研协调 Agent
├── workspace-douyin-search/        # 抖音检索 Agent
├── workspace-web-search/           # 网页检索 Agent
├── workspace-writer/               # 脚本写作 Agent
├── workspace-video-generate/       # 视频生成 Agent
├── workspace-publisher/            # 发布 Agent
├── workspace-stats-collector/      # 数据采集 Agent
├── workspace-stats-analyzer/       # 数据分析 Agent
│
├── docs/                           # 架构、协议、调试文档
├── cron/                           # 定时任务配置
├── pics/                           # README 与文档图片
├── openclaw.example.json           # OpenClaw 配置模板
└── setup.sh                        # 生成 openclaw.json 的初始化脚本
```

---
## 飞书机器人入口

飞书入口由 `agent-service` 直接接收事件，然后把标准化后的消息交给 OpenClaw orchestrator。

### 1. 创建飞书自建应用

在飞书开放平台创建企业自建应用，并记录：

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
```

### 2. 配置回调

FastAPI 回调地址：

```text
POST /webhooks/feishu/events
```

本地开发可用 ngrok 或 cloudflared 暴露：

```bash
ngrok http 8000
```

然后在飞书开放平台事件订阅中填写：

```text
https://你的公网地址/webhooks/feishu/events
```

### 3. 启用飞书配置

在 `agent-service/.env` 中设置：

```bash
FEISHU_BOT_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx

OPENCLAW_ORCHESTRATOR_COMMAND="openclaw agents spawn orchestrator"
OPENCLAW_RUNS_ROOT=~/.openclaw/runs
OPENCLAW_START_MODE=cli
FEISHU_RESULT_WATCH_TIMEOUT_SEC=3600
FEISHU_RESULT_WATCH_INTERVAL_SEC=10
```

飞书内可用命令：

```text
/status <run_id>
/runs
```

更多细节见 [docs/FEISHU_ADAPTER.md](docs/FEISHU_ADAPTER.md)。

---



## 数据反馈闭环

VideoClaw 的长期目标不是只跑完一次生成，而是通过每条视频的表现数据不断改进内容策略。

```text
已发布视频
  -> stats-collector   定期采集播放、点赞、评论、分享、收藏等指标
  -> stats-analyzer    生成周报与内容建议
  -> orchestrator      在下一次选题、脚本与分镜决策中参考历史反馈
```

相关 Agent：

- `workspace-stats-collector/`
- `workspace-stats-analyzer/`

相关文档：

- [docs/BACKWARD_ROUTING.md](docs/BACKWARD_ROUTING.md)
- [docs/BACKWARD_REWARD.md](docs/BACKWARD_REWARD.md)
- [docs/BACKWARD_OPS.md](docs/BACKWARD_OPS.md)

---

## 重要文档

- [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)：系统总览与阶段规划
- [docs/PIPELINE.md](docs/PIPELINE.md)：主流水线说明
- [docs/RUN_LAYOUT.md](docs/RUN_LAYOUT.md)：任务运行目录结构
- [docs/STREAMING_PROTOCOL.md](docs/STREAMING_PROTOCOL.md)：流式写入与恢复协议
- [docs/ASYNC_JOBS.md](docs/ASYNC_JOBS.md)：异步任务协议
- [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md)：本地开发调试
- [docs/FEISHU_ADAPTER.md](docs/FEISHU_ADAPTER.md)：飞书机器人接入
- [docs/BROWSER.md](docs/BROWSER.md)：Windows 浏览器节点与抖音发布
- [agent-service/API_documents.txt](agent-service/API_documents.txt)：后端 API 说明
- [agent-service/video-agent-system/tag_knowledge_db/README.md](agent-service/video-agent-system/tag_knowledge_db/README.md)：标签知识库构建

---


## Roadmap

- 完善发布后数据采集与指标归因
- 强化 weekly insight 对下一轮脚本和分镜的影响
- 支持更多视频生成 provider
- 增强飞书交互卡片与任务状态展示
- 补充端到端示例与部署脚本






