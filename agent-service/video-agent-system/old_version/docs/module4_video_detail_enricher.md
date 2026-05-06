# 模块四：视频 URL 元数据富化（实验版）

日期：2026-02-28

## 目标

针对已发现的 `aweme_id / video_url`，二次访问视频页补齐元数据：

1. 标题（`desc`）
2. 作者（`author_name`）
3. 互动指标（点赞/评论/收藏/分享/播放）
4. 标签（`text_extra/cha_list` 或标题 `#`）

## 脚本

`src/douyin_hot_db/collect_douyin_video_detail_enricher.py`

## 选择目标

默认行为：

1. 从最新成功的 `douyin_home_feed_crawler` run 读取 `aweme_id`
2. 仅处理 `videos.desc/author_name` 为空的视频
3. 默认跳过已存在 `video_detail_snapshots` 的 `aweme_id`

可通过参数覆盖：

- `--aweme-id <id>`：指定单个或多个视频 ID（可重复传参）
- `--from-home-run-id <run_id>`：指定首页 run
- `--force`：不跳过已富化视频

## 数据落库

1. `videos`：用非空值增量更新（不会被空值覆盖）
2. `video_tags`：补充标签
3. `video_detail_snapshots`：每次富化快照

## 运行示例

```bash
python src/douyin_hot_db/collect_douyin_video_detail_enricher.py \
  --db data/douyin_hot.db \
  --limit 100 \
  --debug-dump-dir data/raw/video_detail_debug
```

默认会导出可直接阅读的结果 JSON：

`data/raw/video_detail_results/<run_id>.json`

指定视频：

```bash
python src/douyin_hot_db/collect_douyin_video_detail_enricher.py \
  --db data/douyin_hot.db \
  --aweme-id 7611851491078409481 \
  --force
```

## 提取优先级

1. 网络响应 aweme JSON（最高优先级）
2. 页面 `RENDER_DATA`（中优先级）
3. DOM 文本与按钮计数（兜底）

## 结果文件

结果 JSON 每条记录包含：

1. `aweme_id / page_url / title / author_name`
2. `digg_count / comment_count / collect_count / share_count / play_count`
3. `source_kind / source_api_url / captured_at`
4. 标签列表（`tags`）

## 已知限制

1. 登录态和风控会显著影响字段完整度
2. DOM 兜底在某些页面可能抓到“公共区块数字”，并非逐条精确指标
3. 若页面长期停在登录引导，建议先用同一 `--user-data-dir` 完成一次人工扫码登录
