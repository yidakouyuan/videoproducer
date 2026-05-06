# OpenClaw 视频生成-发布流水线 · 记忆管理与 Backward 体系（汇报材料 + Phase A 实施蓝图）

> **本文件用途**：(1) 对外汇报当前系统设计与已落地工作；(2) 记录下一步 Phase A 的具体实施步骤。
> ExitPlanMode 之后可直接将本文件 `cp` 到 `Desktop/trace/final/docs/SYSTEM_OVERVIEW.md` 作为汇报材料分发。
>
> 实际生效根目录：WSL `~/.openclaw/` ；Windows snapshot：`C:\Users\Administrator\Desktop\trace\v12\` 与 `…\final\`（三方保持一致）。

---

## 一、项目概况

### 1.1 系统定位

跑在 OpenClaw 之上的**多 agent 视频生成-发布流水线**：用户给一句话需求 → 自动完成选题接地 → 双通道研究检索 → 脚本撰写 → 视频生成 → 抖音发布 → 平台数据回流 → **下一次跑得更好**。终极目标对标 NousResearch 的 Hermes Agent："越用越好用"。

### 1.2 Agent 架构

```
                         ┌──────────────┐
            user ──────► │ orchestrator │ ──── 6 步流水编排，run_id 是状态主键
                         └──────┬───────┘
                                │ sessions_spawn (OpenClaw 子代理协议)
            ┌───────────────────┼───────────────────┬────────────────┐
            ▼                   ▼                   ▼                ▼
    ┌──────────────┐   ┌────────────────────┐  ┌─────────┐   ┌─────────────┐
    │ tag-matcher  │   │research-supervisor │  │ writer  │   │video-generate│
    └──────────────┘   └─────────┬──────────┘  └─────────┘   └─────────────┘
                                 │
                       ┌─────────┴─────────┐
                       ▼                   ▼
                ┌─────────────┐   ┌────────────────┐
                │douyin-search│   │  web-search    │
                └─────────────┘   └────────────────┘
                                                 ▼
                                          ┌────────────┐
                                          │ publisher  │ ──── 抖音发布（CDP 桥接）
                                          └────────────┘

    [独立 cron 链]
    ┌──────────────────┐    ┌─────────────────┐
    │ stats-collector  ├───►│ stats-analyzer  │ ──── 抓 Douyin 运营数据 → suggestions.json
    └──────────────────┘    └─────────────────┘     （backward 闭环现状：壳已搭建未真正跑通）
```

共 **10 个 agent**，三大类：① 主流水线（6 个）；② 子搜索 worker（2 个）；③ Backward 数据收集（2 个，待激活）。

---

## 二、Pipeline 完整逻辑（脚本生成 → 视频生成 → 发布）

### 2.1 整体流程（orchestrator 6 步）

| 步 | 名称 | 主要动作 | 产物 |
|---|---|---|---|
| 1 | Intake | 解析用户 query → 生成 `run_id=YYYYMMDD_HHMMSS` → 写 brief；可选读取历史 `insights/suggestions.json` | `runs/<run_id>/brief.json` |
| 2 | Topic grounding | spawn `tag-matcher` → 把宽 topic 收敛成 `grounded_tag` | brief.json 更新 |
| 3 | Research | spawn `research-supervisor` → 内部并发 spawn `douyin-search` + `web-search`，多轮 iter，做视频分析与转写 | `research_douyin.json` + `research_web.json` + `raw/<channel>_iter*.json` + `raw/douyin_detail/*.json` |
| 4 | Writing | spawn `writer` → 读 research → 生成脚本 + 分镜（可选 storyboard 模式 2-6 镜头） | `script.json` |
| 5 | Video generation | spawn `video-generate` → t2v 或 i2v；storyboard 模式并行 video_generate_start → wait_for_done → stitch | `video_result.json`（含 `local_video_path`） |
| 6 | Deliver / Publish | 单 shot 发 Telegram；`publish_directly` 模式则 spawn `publisher` 调 douyin CDP 桥发布 | （可选）`publish_result.json` |

**关键状态主键**：`run_id` —— 一切上下游通过 `runs/<run_id>/` 目录共享数据，agent 之间不传大 payload。

### 2.2 各 Agent 职责（精简）

| Agent | 输入 | 关键决策 | 输出 |
|---|---|---|---|
| **orchestrator** | 用户 query | task_mode、`duration_target_sec`、是否 publish | brief.json + 全程编排 |
| **tag-matcher** | brief | 把宽 topic 收敛到能用于 douyin 检索 + 决定后续语料倾向的精细 tag | brief.grounded_tag |
| **research-supervisor** | run_id | 决定 query 角度、迭代次数、retain/drop 候选 | research_douyin.json (索引) + research_web.json + raw/* |
| **douyin-search** | iter+queries | 哪些 aweme 进 shortlist | raw/douyin_iter{n}.json |
| **web-search** | iter+queries | 哪些 url 进 shortlist | raw/web_iter{n}.json |
| **writer** | research | hook 模式、节奏、分镜数、shot 时长、CTA、tags | script.json |
| **video-generate** | script | 单 shot vs storyboard、shot duration、t2v vs i2v | video_result.json |
| **publisher** | run_id | 发布时间窗、最终 hashtag/title 微调 | （url 可解析出 aweme_id，但当前未持久化） |
| **stats-collector** | (cron) | 抓 Creator Center 数据 | stats DB |
| **stats-analyzer** | stats DB | 按 topic 聚类、生成报告 | `insights/suggestions.json` + `reports/stats_*.md` |

### 2.3 数据流（runs/<run_id>/ 产物链）

```
brief.json ─┬─► tag-matcher ──► brief.grounded_tag
            ├─► research-supervisor ──► research_*.json
            │                            │
            │                            └──► writer ──► script.json
            │                                              │
            │                                              ├─► video-generate ──► video_result.json
            │                                              │                       │
            │                                              │                       └─► publisher ──► (Douyin)
            │                                              │
            └─► publisher ◄──────────────────── (script.json 也提供 title/tags)
```

**约束**（`docs/RUN_LAYOUT.md`）：
- 终态产物存在 `<base>.json` 即视为完成，下游可消费
- `raw/*_iter{n}.json` 是 per-iteration checkpoint，已是流式精神
- `raw/jobs_iter{n}.json` 持久化 async job_ids，供 wait 超时后 resume

### 2.4 已落地的鲁棒性改造

- **流式写入协议**（详见 §3.2）：`video_result.json` / `research_douyin.json` / `research_web.json` 走 `partial + atomic rename`，崩溃可恢复 + watcher 可早期 peek 进度
- **完成门控（Completion gate）**：每个 agent 退场前必须回读自己声明的终态产物且非空（避免"NO_REPLY 但实际没产出"的 silent failure）
- **`video_generate_wait_for_done`**：plugin 端 server-side 长轮询，agent 不再 busy-poll（旧 trace 一次 38 次 polling 已消除）

---

## 三、记忆管理（已实施 — Phase 1~4 交付）

### 3.1 5 层记忆模型

```
L0 身份层（静态、人编辑）             workspace-<self>/{SOUL,IDENTITY,USER,AGENTS}.md + skills/**/SKILL.md
L1 运行时态（per-run、流式）          ~/.openclaw/runs/<run_id>/...
L2 短期日志（per-agent、per-day）     workspace-<self>/memory/YYYY-MM-DD.md   ← agent 自主追加 lesson
L3 长期精炼（per-agent、被 promote） workspace-<self>/MEMORY.md              ← 仅 agent 自己 merge 提案
L4 项目级洞察（backward 产物）        ~/.openclaw/insights/{episodes,playbooks,suggestions.json}
L5 完整 trace 归档（只读）            ~/.openclaw/trace_bundles/<run_id>/   （由 scripts/assemble_trace.py 生成）
```

**读取**：每次 session 启动自动读 L0 + L3 + L2-today + L2-yesterday + L4-playbook。
**写入**：L2 由 agent 自己写；L3 走半自动 promote；L4 由 backward 系统写（待实施）。
**契约文档**：`docs/MEMORY_LAYOUT.md`（是各 agent 引用的中心）。

### 3.2 流式写入协议（partial + atomic rename）

**协议**（`docs/STREAMING_PROTOCOL.md`）：

```
in-progress      <base>.json.partial    可读但视为"未完成"，含 progress 块（phase / last_event_ts / resume_token / writer_pid）
terminal         <base>.json            atomic rename 而来；存在即代表完成
failed           <base>.json.partial    含 status:"failed"；不 rename
```

**核心工具**：`scripts/streaming_io.py`（390+ 行，stdlib only），命令：
- `write` — 原子写
- `update-progress` — 自动注入 progress 块
- `finalize [--unwrap <key>]` — 原子改名；array 型产物用 `--unwrap _index` 解包外壳
- `read --role consumer|watcher|resumer` — 按角色读

**消费规则**：
- consumer（writer 等下游）只看 `<base>.json`；遇到 partial 就阻塞或报错
- watcher（orchestrator 等待时 peek 进度）能读 partial、看 phase/age
- resumer（同 producer 重启）按 resume_token 决定续跑或重来

**首批落地**：`video_result.json` / `research_douyin.json` / `research_web.json`。`brief.json` / `script.json` 一锤定音不流式。`raw/*_iter*.json` 已是流式切片。

### 3.3 L2→L3 自动 promote 机制（Phase 4）

```
[L2 daily notes 累积]
       ↓
scripts/promote_memory.py   recall：用 Jaccard ≥ 0.4 OR ≥2 个长 token (≥5 char) 锚点共享聚类
       ↓
workspace-<self>/MEMORY.md._pending_<YYYYMMDD>.md   提案文件（只写 .partial，不动 MEMORY.md）
       ↓
agent 下次启动 step 5 读它   precision：人类级判断 promote / drop / defer
       ↓
agent 自己 append 精炼后到 MEMORY.md → 删 _pending
```

**关键设计**：
- 脚本永不写 MEMORY.md（避免自动 merge 把噪声塞进长期记忆）
- 严格 `- [HH:MM] <lesson>` bullet 格式（避开旧 narrative session 转录的 false positive）
- 半合并防护：要么处理完所有 cluster 再删 `_pending`，要么不动

### 3.4 Phase 1~4 交付清单

| Phase | 主题 | 产物 |
|---|---|---|
| 1 | 5 层架构 + 文档 + 占位 | `docs/MEMORY_LAYOUT.md`, `docs/STREAMING_PROTOCOL.md`, `scripts/streaming_io.py`, 改 `docs/RUN_LAYOUT.md`, 10 个 workspace 加 Memory protocol 段 + MEMORY.md 占位 |
| 2 | backward 闭环（collect/analyse） | ⏸️ 暂缓（已为 Phase 5 重新设计，见下） |
| 3 | partial+rename 落地 | 改 `workspace-video-generate/AGENTS.md`、`workspace-research-supervisor/AGENTS.md`、`workspace-orchestrator/AGENTS.md` 的对应 step 用 partial 协议 |
| 4 | L2→L3 自动 promote | `scripts/promote_memory.py`（336 行），10 个 AGENTS.md 加 `_pending` merge hook，MEMORY_LAYOUT 加 promotion lifecycle 节 |

所有改动**三方同步**：WSL 实际生效端 + `Desktop/trace/v12/` + `Desktop/trace/final/`。

---

## 四、Backward 设计（待实施 — Phase A~E）

### 4.1 目标与参照

**目标**：根据视频发布到 Douyin 后的运营数据作为 reward，反向优化各 agent 的行为，实现"越用越好用"。

**参照系**：[NousResearch Hermes Agent](https://github.com/NousResearch/hermes-agent) + [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) 用的是 [GEPA](https://arxiv.org/abs/2507.19457) + DSPy 思路：
- LLM 读完整 trace → 对 prompt/skill 做 textual mutation
- Pareto frontier 选保留多种互补变体（避免单一 scalar 的 mode collapse）
- Constraint gates 筛掉退化版本
- 比 RL 少 20-60× rollouts；5 轮 evolve 提 15-30% 任务成功率

**本系统的设计原则**：
- **不跑 RL**（数据稀疏、成本高、视频指标方差大）
- **离线批处理**（每累积 N 条同类后跑一次归因，不每条都改 prompt）
- **多目标 Pareto 而非单一 scalar reward**（避免"为提完播牺牲粉丝转化"）
- **Credit assignment 用 LLM critic 读 trace 的自然语言诊断 + 手写 routing rules**（不靠梯度）

### 4.2 Reward 设计（纵向 + 横向）

#### 4.2.1 纵向（单视频随时间）

抓三个时间窗 stats 快照：**T+1h / T+24h / T+72h**。

派生 fingerprint：

| Fingerprint | 公式 | 反映什么 |
|---|---|---|
| `early_burst_ratio` | `play_T1h / play_T24h` | 推荐机制早期推力 |
| `long_tail_ratio` | `play_T72h / play_T24h` | 长尾分发 / 搜索流量 |
| `retention_decay` | `completion_rate_T72h / completion_rate_T1h` | 留存稳定性 |
| `growth_phase` | 上述三者归类 | 早爆早衰 / 慢热长尾 / 死寂 / 稳定增长 |

`growth_phase` 本身是 reward 维度，对应不同 agent 该被反思（见 §4.3.1 routing 表）。

#### 4.2.2 横向（同类对比）

**簇定义**：`(grounded_tag, shot_archetype)` 二元簇。`shot_archetype = (mode: single|storyboard, total_duration_bucket: <30 | 30-60 | >60)`。

**4 维派生指标 + 簇内 percentile**：

| 维度 | 公式 | percentile 计算 |
|---|---|---|
| `retention_pct` | `completion_rate × (1 − two_sec_exit_rate)` | 同簇内 percentile (0-100) |
| `conversion_pct` | `follower_gain / max(play, 100)` | 同上 |
| `engagement_pct` | `(like+comment+share+collect) / play` | 同上 |
| `viral_pct` | `play_T72h / play_T24h` | 同上 |

**Outlier 定义**：簇内 ≥ 5 样本时，任一维度 pct ≥ 90 (top) 或 ≤ 10 (bottom) 即为 outlier，进入 LLM critic。

### 4.3 Credit Assignment 三层

#### 4.3.1 第 1 层 — Routing Rules（手写、领域知识）

把 reward 维度映射到"该被反思的 agent"。这层不是数据学的，是基于"writer 控 hook → 影响 retention"等已知因果关系**写死**的：

```yaml
routing_rules:
  retention_low:                # retention_pct ≤ 10
    primary:   [writer, video-generate]
    secondary: [tag-matcher]
    diagnostic_focus:
      writer:        [hook_pattern, narrative_pace]
      video-generate: [shot_count, shot_avg_duration, first_shot_attention]
      tag-matcher:   [grounded_tag_specificity]

  conversion_low:               # conversion_pct ≤ 10
    primary:   [tag-matcher, writer]
    secondary: [research-supervisor]
    diagnostic_focus:
      tag-matcher: [grounded_tag_audience_match]
      writer:      [value_proposition, CTA_clarity]

  engagement_low:
    primary: [writer]
    diagnostic_focus:
      writer: [narrative_emotion, comment_bait_pattern]

  viral_high:
    primary: [research-supervisor, writer]
    diagnostic_focus:
      research-supervisor: [source_diversity]
      writer:              [evergreen_framing]

  early_burst_only:             # 高早爆 + 低留存
    primary: [writer, publisher]
    diagnostic_focus:
      writer:    [title_clickbait_vs_content]
      publisher: [hashtag_pile_on]

  dead_silence:                 # 全时点低
    primary:   [publisher, tag-matcher]
    secondary: [writer]
    diagnostic_focus:
      publisher:   [publish_time_slot, hashtag_count]
      tag-matcher: [grounded_tag_search_volume]
```

这张表是 backward 系统的"宪法"。所有 attribution events 严格按它路由到 agent。

#### 4.3.2 第 2 层 — 粗粒度统计切片（attributor，纯规则）

每个 agent 都有可分析的"决策点"。Attributor 在累积数据上做切片：

| Agent | 决策点 | 切片输出例子 |
|---|---|---|
| tag-matcher | grounded_tag、specificity（粗/细） | "topic=减肥 + tag='产后减脂' 的 conversion_pct 中位数 70；用泛 tag '减肥' 中位数 40。差异显著（n=8 vs 12）" |
| research-supervisor | retain count、source mix、retain 平均长度 | "美食类 retain ≥ 5 + douyin:web ≈ 3:1 时 retention 中位数 65；其他模式 40" |
| writer | hook 类型（question/statement/number）、shot_count、total_duration | "知识类 hook=question 的 retention_pct 中位数 72；hook=statement 中位数 38" |
| video-generate | mode、shot_avg_duration、max_shot_duration | "duration ≤ 30s 时 single 与 storyboard 无差异；> 30s 时 storyboard 高 18 个百分位" |
| publisher | publish_hour、hashtag_count、title_length | "美食类 publish_hour ∈ [19,21] 早期 play 高 2.1×" |

**统一输出 schema**：

```json
{
  "kind": "stat_attribution",
  "agent": "writer",
  "decision_locator": "hook_pattern",
  "finding": "question hook outperforms statement hook for knowledge topic",
  "evidence": {"n_pos": 15, "n_neg": 11, "median_pos": 72, "median_neg": 38, "p_value": 0.003},
  "confidence": 0.85,
  "source_run_ids": [...]
}
```

#### 4.3.3 第 3 层 — LLM critic（trace-critic，对 outlier）

**只对 outlier 跑**。输入：完整 trace 摘要 + 多维 reward + 同簇平均参照 + routing 表中对应的 diagnostic_focus。

LLM 输出 1-3 条 attribution event（同 schema，`kind=critic_attribution`），按 confidence 排序。`agent` 字段由 routing 表 + decision_locator 唯一确定。

#### 4.3.4 三层协作

| 数据状态 | 主导层 |
|---|---|
| 冷启动（< 10 条） | **第 3 层 critic only**，每条都跑（无 outlier 概念）；结果先入 `_pending` 不直接入 playbook |
| 早期（10-30 条） | 3 + 1 |
| 数据期（30-100 条） | 2 + 3 + 1 |
| 成熟期（> 100 条） | 全开；可启动 Phase E 的 prompt evolution |

### 4.4 五个新组件 + 数据流

```
publisher 完成 ──► [1] publish-recorder
                        │ 解析 url → aweme_id
                        │ 写 runs/<run_id>/publish_result.json
                        │ 初始化 insights/episodes/<run_id>.json (含 trace 切片元数据)
                        ▼
                   [T+1h, T+24h, T+72h cron]
                        ▼
                   [2] outcome-aggregator
                        │ 从 stats DB join 回 episodes
                        │ join key: aweme_id (优先) | (title, publish_time) 兜底
                        │ 计算纵向 fingerprint + 横向 percentile
                        │ 写入 episodes/<run_id>.json 的 reward 块
                        ▼
                   [累积 N 条同簇后]
                        ▼
                ┌──────────────────┬──────────────────┐
        [3] stat-attributor       [4] trace-critic
        纯规则切片                LLM 对 outlier 反思
        输出 attribution events   输出 attribution events
                        └────┬───────────────┘
                             ▼
                   [5] playbook-curator
                        │ 按 routing rules 路由到 agent
                        │ 写 insights/playbooks/<agent>.md      （直接覆盖：attributor 强证据）
                        │ 写 insights/suggestions.json          （by_topic / by_stage）
                        │ 写 workspace-<agent>/MEMORY.md._pending_<date>.md  （critic 弱证据走半自动）
```

### 4.5 Per-Agent 落地矩阵

| Agent | 主要 reward 维度 | 决策点 | 落地形式 |
|---|---|---|---|
| orchestrator | 全维度（topic 路由） | task_mode、duration_target_sec | `insights/suggestions.json` `by_topic` |
| tag-matcher | conversion、viral | grounded_tag specificity & audience match | `playbooks/tag-matcher.md` |
| research-supervisor | viral、retention | retain count、source diversity | `playbooks/research-supervisor.md` |
| writer | retention、engagement | hook pattern、narrative pace、CTA | `playbooks/writer.md` + `MEMORY._pending` |
| video-generate | retention | mode、shot durations、first_shot framing | `playbooks/video-generate.md` |
| publisher | early play_count | publish_hour、hashtag_count、title_length | `playbooks/publisher.md` |

**所有 playbook 入口已在 Phase 1 的 Memory protocol step 4 接好** —— 无需再改 prompt。

### 4.6 实施分期 Phase A~E

| Phase | 主要内容 | 依赖 | 估算 |
|---|---|---|---|
| **A** | publisher 解析 url → 写 publish_result.json + 初始化 insights/episodes/<run_id>.json 元数据 | 无 | 1-2 天 |
| **B** | outcome-aggregator：T+1h/24h/72h cron，写入纵向 + 横向 reward 块 + episodes/SCHEMA.md | A + stats-collector login 修复 | 2-3 天 |
| **C** | stat-attributor 切片脚本 → playbooks 草稿（先 publisher / video-generate / writer 三个） | B | 3-5 天 |
| **D** | trace-critic（LLM 对 outlier）+ playbook-curator 合并路由 | C 跑一段时间累积数据 | 3-5 天 |
| **E**（可选） | GEPA-style prompt evolution batch（每 50-100 条视频） | D 稳定 | 后续 |

---

## 五、Phase A 具体实施步骤（最近期 actionable）

### 5.1 目标

打通"published video → run_id → 平台数据"的关联链。这是后续所有 backward 高级机制的前提：现在 publisher 不持久化 url / aweme_id，stats-collector 抓的数据也无法反查到具体哪个 run。

### 5.2 改动清单

#### 5.2.1 修改 `workspace-publisher/AGENTS.md`

在 step 3 "Return result" 之前插入新 step「**3. Persist publish outcome**」：

- 从已 parsed 的 publisher stdout 中提取 `url` 字段
- 从 url 中正则解析 `aweme_id`（路径形如 `https://creator.douyin.com/.../<aweme_id>` 或其变体；若解析失败 `aweme_id=null`，但 url 必持久化）
- 用 `write` 工具写 `~/.openclaw/runs/{run_id}/publish_result.json`：

```json
{
  "ok": true,
  "run_id": "<run_id>",
  "publish_ts": "<ISO8601 UTC>",
  "platform": "douyin",
  "aweme_id": "<parsed | null>",
  "url": "<full url>",
  "title": "<title from script.json>",
  "hashtags": ["..."],
  "confirmation": "<from bridge stdout>"
}
```

- 调 `exec bash -lc 'python3 ~/.openclaw/scripts/episode_init.py --run-id <run_id>'`（详见 5.2.3）初始化 episode 元数据
- 退出前 Completion gate 仍按现状 verify（不强制读 publish_result.json，避免破坏现有 success/failure 路径）

**为什么不用流式协议**：publish_result 是一锤定音的小对象，无中间态。

#### 5.2.2 更新 `docs/RUN_LAYOUT.md`

在 File Map 表加一行：

| File | Location | Written by | Read by |
|---|---|---|---|
| `publish_result.json` | root | publisher | episode_init.py、未来 backward 链路 |

Schemas 节加 publish_result.json 的 schema（同 5.2.1 中的 JSON）。

#### 5.2.3 新增脚本 `scripts/episode_init.py`

职责：在 publisher 之后立即被调用，把 run 的所有元数据切片写到 `insights/episodes/<run_id>.json`，供后续 backward 阶段消费。

**输入**：`--run-id <run_id>`（必填）；脚本从 `runs/<run_id>/` 各产物中抽取摘要字段。

**输出**：`insights/episodes/<run_id>.json`：

```json
{
  "schema": "openclaw-episode/v1",
  "run_id": "<run_id>",
  "created_at": "<ISO8601>",
  "publish": {
    "aweme_id": "...",
    "url": "...",
    "publish_ts": "...",
    "title": "...",
    "hashtags": ["..."]
  },
  "brief": {
    "topic": "...",
    "grounded_tag": "...",
    "task_mode": "publish_directly",
    "duration_target_sec": 30
  },
  "research_summary": {
    "douyin_count": 6,
    "web_count": 4,
    "douyin_titles": ["..."]
  },
  "script_summary": {
    "title": "...",
    "hook_excerpt": "首 80 字符",
    "shot_count": 4,
    "total_duration": 42,
    "tags": ["..."],
    "mode": "storyboard"
  },
  "video_summary": {
    "job_id": "...",
    "manifest_path": "...",
    "shots_meta": [{"index": 1, "duration": 10}, ...]
  },
  "reward": null
}
```

**关键复用**：脚本应导入 `scripts/assemble_trace.py` 的事件解析 helpers，避免重写 trace 抽取逻辑。

**约束**：
- 纯 stdlib，跨平台（Win + WSL 路径都要支持）
- 失败不阻塞 publish（exec 走 `|| true`，错误日志走 stderr）
- `reward` 字段先留 null，后续由 outcome-aggregator (Phase B) 填

#### 5.2.4 新增 schema 文档 `insights/episodes/SCHEMA.md`

详写 episode JSON 各字段语义、单位、生成方。这是 Phase B 及之后所有组件的契约。

### 5.3 验收标准

```bash
# 1. 跑一次完整 pipeline（publish_directly 模式）
$ openclaw agents spawn orchestrator "做一个美食探店视频并发布"

# 2. publisher 完成后核查
$ cat ~/.openclaw/runs/<run_id>/publish_result.json | jq .
# 必须含非空 url、aweme_id（解析成功的话）、publish_ts

# 3. episode 初始化文件存在
$ cat ~/.openclaw/insights/episodes/<run_id>.json | jq .
# 必须含 publish / brief / research_summary / script_summary / video_summary 五块；reward 为 null

# 4. 失败路径：publisher 失败时 publish_result.json 不应被写为 ok:true
$ ls ~/.openclaw/runs/<failed_run_id>/publish_result.json   # 不存在或 ok:false
$ ls ~/.openclaw/insights/episodes/<failed_run_id>.json     # 不存在
```

### 5.4 双边同步规则

按既有 feedback 契约，每个改动都同步三方：
- WSL `~/.openclaw/`（实际生效，先改）
- `Desktop/trace/v12/`（snapshot，cp 同步）
- `Desktop/trace/final/`（snapshot，cp 同步）

---

## 六、风险与开放问题

### 6.1 已知风险

| 风险 | 缓解 |
|---|---|
| Phase A 之前 stats-collector login 已过期（`status=error, collected=0`），单纯做 A 没有 reward 数据可消费 | A 与 stats-collector login 修复并行做；Phase B 才真正依赖数据 |
| aweme_id 解析失败时 join key 用 (title, publish_time)，title 可能重复 | publish_ts 精确到秒 + title 通常足以唯一；后续可在 stats schema 加 aweme_id 字段彻底解决 |
| LLM critic 单条成本 ~0.5-1 元，冷启动期每条都跑会贵 | 冷启动期阈值开关（< 10 条）；critic 输出强制走 `_pending` 不直接覆盖 playbook，错误成本低 |
| Routing rules 是写死的，可能漏归因 | 表本身写到 `docs/BACKWARD_ROUTING.md`，每次新发现新模式人工补；未来可用 critic 累积反馈再调表 |

### 6.2 留给汇报后讨论的开放问题

1. **Reward 维度**：retention/conversion/engagement/viral 这四维够不够？是否需要加"被举报率"等负向维度？
2. **Outlier 边界**：top/bottom 10% in cluster (n≥5) vs 更激进 20%？前者精准、后者数据稀疏期触发更多。
3. **Playbook 自动化程度**：本方案默认 attributor 直接覆盖 playbook、critic 走 `_pending`。是否需要更保守（全走 `_pending`）？
4. **Phase E 触发阈值**：50 条 vs 100 条视频后启动 prompt evolution？数据稀疏期更激进有 overfit 风险。

---

## 七、关键文件路径速查

### 已落地（Phase 1~4）
- `docs/MEMORY_LAYOUT.md` — 5 层记忆契约
- `docs/STREAMING_PROTOCOL.md` — partial+rename 协议
- `docs/RUN_LAYOUT.md` — runs/<run_id>/ 目录约定（已加流式段）
- `scripts/streaming_io.py` — 流式 IO 工具（CLI: write / update-progress / finalize / read）
- `scripts/promote_memory.py` — L2→L3 promote 工具
- `scripts/assemble_trace.py` — trace bundle 生成（事件抽取 helper 将被 episode_init 复用）
- `workspace-*/AGENTS.md` × 10 — 都加了 Memory protocol 段（含 _pending merge）
- `workspace-*/MEMORY.md` × 10 — 占位 + lifecycle 说明

### Phase A 待新增
- `scripts/episode_init.py` — episode 元数据初始化
- `insights/episodes/SCHEMA.md` — episode v1 schema 文档
- `insights/episodes/<run_id>.json`（运行时产生）
- `runs/<run_id>/publish_result.json`（运行时产生）

### 已存在 backward 入口（待激活）
- `insights/suggestions.json` — orchestrator Step 1 已 read（当前空 stub）
- `insights/playbooks/<agent>.md` — 每个 agent Memory protocol step 4 已 read
- `workspace-<agent>/MEMORY.md._pending_*.md` — 每个 agent Memory protocol step 5 已 read
