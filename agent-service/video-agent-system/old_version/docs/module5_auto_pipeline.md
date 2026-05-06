# 模块五：全自动视频样本流水线

日期：2026-02-28

## 目标

把“抓 URL -> 富化互动指标 -> 导出完整样本”串成单命令自动化流程，持续积累可训练样本。

## 脚本

`src/douyin_hot_db/run_auto_pipeline.py`

## 执行步骤

1. 运行 `collect_douyin_home_feed_crawler.py` 抓取首页视频 URL
2. 运行 `collect_douyin_video_detail_enricher.py` 获取视频互动元数据
3. 运行 `export_video_detail_complete_metrics.py` 导出互动指标完整样本 JSON

## 运行示例

```bash
python src/douyin_hot_db/run_auto_pipeline.py \
  --db data/douyin_hot.db \
  --home-rounds 5 \
  --home-videos-per-round 20 \
  --enrich-limit 100
```

## 关键输出

1. 完整互动样本：
   `data/raw/video_detail_results_complete/<enrich_run_id>.complete4.json`
2. 流水线日志：
   `data/logs/auto_pipeline/*.log`
3. 流水线摘要：
   `data/logs/auto_pipeline/*.summary.json`

## 健康检查

可通过参数配置最低阈值：

1. `--min-home-videos`（首页抓取最少条数）
2. `--min-enriched-records`（富化快照最少条数）
3. `--min-complete-records`（完整样本最少条数）

## 稳定性

1. 内置文件锁，避免并发重复启动。
2. 默认复用 `data/browser_profile`，保持会话状态。
3. 若任一步骤失败，流水线以非 0 退出，并写入失败摘要。
