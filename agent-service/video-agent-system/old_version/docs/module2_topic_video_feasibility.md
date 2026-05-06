# 模块二：热榜话题下视频抓取（实验版）

日期：2026-02-28

## 目标

基于模块一的热榜词，抓取话题关联视频，不取视频文件本体，仅获取结构化元数据：

1. 标题（`desc`）
2. 标签（`text_extra` / `cha_list`）
3. 互动指标（点赞/评论数/收藏/分享/播放）
4. 可选评论正文（尽力抓取）

## 脚本

`src/douyin_hot_db/collect_douyin_topic_videos_crawler.py`

## 数据落库

1. `videos`：视频基础信息（去重主表）
2. `topic_video_snapshots`：话题与视频关系快照
3. `video_tags`：标签表
4. `video_comments`：评论表（仅当抓到评论接口）

## 运行示例

```bash
python src/douyin_hot_db/collect_douyin_topic_videos_crawler.py \
  --db data/douyin_hot.db \
  --topic-limit 10 \
  --videos-per-topic 20 \
  --capture-comments \
  --dump-payloads-dir data/raw/topic_payloads
```

## 关键说明

1. 默认只抓“有排名位置”的热榜项（过滤头部引导卡片）。  
2. 评论正文抓取依赖页面是否触发评论请求，不保证每次都有；评论总数来自视频统计字段，稳定性更高。  
3. 无图形服务器请保持默认 `headless`，不要加 `--headful`。  
