# Video Agent System

这是一个用于视频生成全链路 Agent 的工程仓库。当前先完成第一个模块：

- `douyin_hot_db`：建立抖音热榜离线数据库（支持 API 路线和爬取路线）。

## 快速开始

1. 激活你的环境（你已创建 `video` 环境）：

```bash
conda activate video
```

2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 配置环境变量（仅 API 路线需要）：

```bash
cp .env.example .env
# 编辑 .env，填入 DOUYIN_CLIENT_KEY / DOUYIN_CLIENT_SECRET
```

4. 安装 Playwright 浏览器驱动（仅爬取路线需要）：

```bash
playwright install chromium
```

## 路线 A：开放 API（关键词搜索库）

```bash
python src/douyin_hot_db/collect_douyin_openapi.py \
  --db data/douyin_hot.db \
  --keywords-file keywords.txt \
  --count 20 \
  --max-pages 3
```

## 路线 B：爬取热榜页面（推荐你当前阶段使用）

```bash
python src/douyin_hot_db/collect_douyin_hot_crawler.py \
  --db data/douyin_hot.db \
  --wait-seconds 10 \
  --sync-keywords \
  --dump-raw-json data/raw/hot_payload.json
```

说明：

- 默认是 `headless`，适合无图形界面的服务器环境（DGX/云主机）。
- `--headful`：仅在本机有桌面环境和 `DISPLAY` 时使用。
- 服务器想强制跑 `headful` 可用：`xvfb-run -a python ... --headful`。
- `--sync-keywords`：把热榜词写入 `search_tasks`，后续可给 API 脚本或二次爬取脚本复用。
- 热榜词快照写入 `hot_topic_snapshots`，去重主表写入 `hot_topics`。

## 路线 C：按热榜话题抓视频信息（标题/标签/互动）

```bash
python src/douyin_hot_db/collect_douyin_topic_videos_crawler.py \
  --db data/douyin_hot.db \
  --topic-limit 10 \
  --videos-per-topic 20 \
  --capture-comments \
  --dump-payloads-dir data/raw/topic_payloads
```

说明：

- 读取 `hot_topic_snapshots` 最新成功 run 的话题。
- 输出到：
  - `videos`（视频主信息）
  - `topic_video_snapshots`（话题-视频关系与互动快照）
  - `video_tags`（标签）
  - `video_comments`（评论，若页面触发评论接口）
- 评论正文是否可抓取受页面加载路径、登录态和风控影响，`comment_count`（评论总数）通常更稳定。

## 路线 D：爬取首页推荐流（模拟刷抖音）

小规模验证：

```bash
python src/douyin_hot_db/collect_douyin_home_feed_crawler.py \
  --db data/douyin_hot.db \
  --rounds 10 \
  --videos-per-round 20
```

持续抓取（手动停止）：

```bash
python src/douyin_hot_db/collect_douyin_home_feed_crawler.py \
  --db data/douyin_hot.db \
  --rounds 0 \
  --videos-per-round 20
```

说明：

- `--rounds 0` 表示无限轮次，按 `Ctrl+C` 停止，已抓取数据会保留。
- 显式指定 `--seed-aweme-id` 或 `--seed-url` 时，会直接从该 seed 视频进入 `seed video` 模式，再按配置继续刷。
- 默认只接收 feed 类接口，尽量减少噪音；当接口流量缺失时会自动尝试 DOM 可见卡片提取（全自动兜底）。
- 若首页首轮仍拿不到视频，会自动回退到 `seed video`（从库里最近视频拼 `https://www.douyin.com/video/{aweme_id}` 继续刷流），可用 `--no-auto-seed-fallback` 关闭。
- 在 `seed video` 模式下默认会自动跳到“未访问过的相关推荐视频”继续抓取（链式扩散），可用 `--no-traverse-related` 关闭。
- 可加 `--debug-dump-dir data/raw/home_feed_debug` 导出每轮 URL+payload 诊断文件，便于排查风控/解析问题。
- 若你想多抓但允许噪音，可加 `--include-related`。
- 输出到：
  - `videos`（视频主信息）
  - `video_tags`（标签）
  - `home_feed_snapshots`（首页轮次快照）

## 路线 E：按视频 URL 富化元数据（推荐与路线 D 搭配）

从首页/话题已抓到的 `aweme_id` 二次访问视频页，补齐：

- 标题、作者
- 点赞/评论/收藏/分享/播放（尽力抓取）
- 标签（标题 `#` + aweme payload）

运行示例（默认读取最新 `home_feed` run 里“元数据缺失”的视频）：

```bash
python src/douyin_hot_db/collect_douyin_video_detail_enricher.py \
  --db data/douyin_hot.db \
  --limit 100 \
  --debug-dump-dir data/raw/video_detail_debug
```

默认会额外导出可直接查看的结果 JSON：

`data/raw/video_detail_results/<run_id>.json`

指定某个 `aweme_id`：

```bash
python src/douyin_hot_db/collect_douyin_video_detail_enricher.py \
  --db data/douyin_hot.db \
  --aweme-id 7611851491078409481 \
  --force
```

输出到：
- `videos`（补全字段）
- `video_tags`（新增标签）
- `video_detail_snapshots`（富化快照）
- `data/raw/video_detail_results/<run_id>.json`（可直接查看的结果文件）

## 路线 F：全自动流水线（首页抓取 -> 富化 -> 完整互动样本导出）

```bash
python src/douyin_hot_db/run_auto_pipeline.py \
  --db data/douyin_hot.db \
  --home-rounds 5 \
  --home-videos-per-round 20 \
  --enrich-limit 100
```

说明：

- 自动顺序执行：
1. `collect_douyin_home_feed_crawler.py`
2. `collect_douyin_video_detail_enricher.py`
3. `export_video_detail_complete_metrics.py`
- 产出“完整互动指标样本（点赞/评论/收藏/分享）”到：
  - `data/raw/video_detail_results_complete/<enrich_run_id>.complete4.json`
- 运行日志和摘要在：
  - `data/logs/auto_pipeline/*.log`
  - `data/logs/auto_pipeline/*.summary.json`
- 自带并发锁，避免重复启动多实例。

## 当前模块目标

- 支持“开放 API 路线”与“网页爬取路线”并行建设；
- 当前优先可落地的是热榜词离线库；
- 后续在热榜词基础上补齐热视频明细采集与打分。

## 目录结构

```text
video-agent-system/
  ├── .env.example
  ├── keywords.txt
  ├── requirements.txt
  ├── docs/
  │   ├── module1_api_feasibility.md
  │   ├── module1_crawler_plan.md
  │   ├── module2_topic_video_feasibility.md
  │   ├── module3_home_feed_feasibility.md
  │   ├── module4_video_detail_enricher.md
  │   └── module5_auto_pipeline.md
  └── src/
      └── douyin_hot_db/
          ├── collect_douyin_home_feed_crawler.py
          ├── collect_douyin_hot_crawler.py
          ├── collect_douyin_openapi.py
          ├── collect_douyin_topic_videos_crawler.py
          ├── collect_douyin_video_detail_enricher.py
          ├── export_video_detail_complete_metrics.py
          ├── run_auto_pipeline.py
          └── schema.sql
```
