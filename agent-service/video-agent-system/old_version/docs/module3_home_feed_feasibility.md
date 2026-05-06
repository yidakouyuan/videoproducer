# 模块三：首页推荐流抓取（实验版）

日期：2026-02-28

## 目标

模拟“刷抖音首页”，连续抓取推荐流视频元数据：

1. 视频 ID（`aweme_id`）
2. 标题（`desc`）
3. 视频播放 URL（`video_url`）
4. 互动指标（点赞/评论/收藏/分享/播放）
5. 标签（`text_extra` / `cha_list`）

## 脚本

`src/douyin_hot_db/collect_douyin_home_feed_crawler.py`

## 数据落库

1. `videos`：视频基础信息（去重主表）
2. `video_tags`：标签
3. `home_feed_snapshots`：首页轮次快照（`run_id + round_num + rank_in_round`）

## 运行示例

```bash
python src/douyin_hot_db/collect_douyin_home_feed_crawler.py \
  --db data/douyin_hot.db \
  --rounds 10 \
  --videos-per-round 20
```

无限轮次：

```bash
python src/douyin_hot_db/collect_douyin_home_feed_crawler.py \
  --db data/douyin_hot.db \
  --rounds 0 \
  --videos-per-round 20
```

## 噪音控制

1. 默认只保留 feed 类接口（噪音更低）。  
2. 如需更高召回可加 `--include-related`，但会引入相关推荐/合集内容。  
3. 若发现跨主题重复视频增多，优先关闭 `--include-related` 并缩短单轮动作。  
