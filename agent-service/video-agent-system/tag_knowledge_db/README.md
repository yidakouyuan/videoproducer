# Tag Knowledge DB

这是一个独立于旧 `tag_db` 的新子工程，用于把抖音视频数据构建成以 `tag` 为核心的离线数据库。

- 目录位置：`video-agent-system/tag_knowledge_db/`
- 默认数据库：`tag_knowledge_db/data/tag_knowledge.db`
- 输入数据：`data/raw/video_detail_results_complete/*.json`

## 覆盖能力

1. 全局去重：`raw tag` 全量去重，跨文件跨批次增量处理。
2. 同义归并占位：新 raw tag 自动创建 identity alias，并进入 LLM 任务队列。
3. 分类占位：对 canonical tag 自动做 heuristic 初分类（`topic/campaign`），并进入 LLM 复核队列。
4. 图谱构建：
   - 共现边总量 `co_cnt_total`
   - 7 天/30 天窗口 `co_cnt_7d/co_cnt_30d`
   - 时间衰减权重 `decayed_weight`
5. Topic/Campaign 分离：通过 view 提供
   - `topic_topic_edges`
   - `campaign_topic_edges`
6. 社区与资产：自动生成社区、社区报告模板、Tag Card、Evidence Pack。
7. LLM 闭环：导出任务、回写结果并重算图谱与资产。

## 文件说明

- `schema.sql`：数据库 schema
- `tag_db_lib.py`：核心逻辑（入库、重算、查询、LLM回写）
- `build_tag_db.py`：构建/增量更新入口
- `query_tag_db.py`：查询入口
- `export_llm_tasks.py`：导出 LLM 待处理任务
- `apply_llm_results.py`：回写 LLM 结果并重算
- `run_llm_tasks_gpt.py`：直接调用 GPT API 执行任务并自动回写
- `export_db_snapshot.py`：把数据库导出为多份 CSV 快照
- `examples/llm_decisions.example.json`：LLM 决策样例

## 快速开始

在项目根目录执行：

```bash
python tag_knowledge_db/build_tag_db.py
```

可选参数：

```bash
python tag_knowledge_db/build_tag_db.py \
  --db tag_knowledge_db/data/tag_knowledge.db \
  --input-dir data/raw/video_detail_results_complete \
  --half-life-days 14 \
  --community-min-edge 2 \
  --export-byog
```

## 查询

```bash
python tag_knowledge_db/query_tag_db.py --tag 影视解说
python tag_knowledge_db/query_tag_db.py --tag 内容启发搜索 --topk 20 --top-titles 20
```

返回内容包含：

- `resolved`（canonical + kind）
- `tag_card`
- `co_tags`
- `evidence_pack`
- `community`（topic）或 `related_topic_communities`（campaign）
- `suggested_tags`（查询召回增强：即使精确匹配失败也会返回相似标签候选）
- `suggested_communities`（由召回候选聚合出的社区候选）

## LLM 任务导出

导出 pending 任务：

```bash
python tag_knowledge_db/export_llm_tasks.py --status pending --limit 200 --output tag_knowledge_db/data/llm_tasks.json
```

导出 JSONL：

```bash
python tag_knowledge_db/export_llm_tasks.py --status pending --limit 200 --output tag_knowledge_db/data/llm_tasks.jsonl --jsonl
```

## 直接用 GPT API 跑 LLM 任务

先配置 API Key（支持放在项目根目录 `.env`）：

```bash
export OPENAI_API_KEY=your_api_key
```

也可以复制 `tag_knowledge_db/.env.example` 到 `tag_knowledge_db/.env` 使用。

直接让脚本读取 pending 任务 -> 调 GPT -> 自动回写并重算：

```bash
python tag_knowledge_db/run_llm_tasks_gpt.py \
  --limit 50 \
  --model gpt-4.1-mini
```

只跑特定任务类型（可重复传参）：

```bash
python tag_knowledge_db/run_llm_tasks_gpt.py \
  --limit 100 \
  --task-type raw_tag_synonym_review \
  --task-type canonical_tag_kind_review
```

仅生成决策 JSON，不写回数据库：

```bash
python tag_knowledge_db/run_llm_tasks_gpt.py \
  --limit 20 \
  --dry-run
```

说明：

- 自动产出决策文件：`tag_knowledge_db/data/llm_decisions.generated.json`
- `--dry-run` 或 `--no-apply` 时不会回写 DB
- 默认失败任务会在非 dry-run 模式标记为 `failed`

## LLM 结果回写

准备决策文件（参考 `examples/llm_decisions.example.json`），然后执行：

```bash
python tag_knowledge_db/apply_llm_results.py \
  --input tag_knowledge_db/examples/llm_decisions.example.json
```

执行后会：

1. 更新 synonym alias
2. 更新 canonical kind
3. 更新 tag card / community report
4. 标记对应任务完成
5. 全量重算统计、边、社区、资产

## BYOG 导出

开启 `--export-byog` 后会导出：

- `tag_knowledge_db/data/byog_export/entities.csv`
- `tag_knowledge_db/data/byog_export/relationships.csv`

可直接作为 GraphRAG BYOG 的输入底稿。

## 数据库快照导出（CSV）

导出全库可读快照（标签、alias、共现边、社区、任务等）：

```bash
python tag_knowledge_db/export_db_snapshot.py \
  --db tag_knowledge_db/data/tag_knowledge.db \
  --output-dir tag_knowledge_db/data/db_snapshot \
  --timestamped
```

输出目录会包含：

- `canonical_tags.csv`
- `raw_tags.csv`
- `tag_aliases.csv`
- `tag_cooccurrence.csv`
- `topic_topic_edges.csv`
- `campaign_topic_edges.csv`
- `communities.csv`
- `community_members.csv`
- `videos.csv`
- `llm_tasks.csv`
- `ingest_runs.csv`
- `summary.json`

## 说明

- 当前社区构建算法为 `connected_components`（工程可落地的默认实现）。
- 若后续接入 Leiden，只需替换社区构建步骤，不影响入库与查询层。
- 对缺失 `tags` 的记录，会从标题 `#标签` 兜底提取。
