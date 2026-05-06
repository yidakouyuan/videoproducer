# 模块一：方案二（爬取）实施说明

日期：2026-02-28

## 目标

在不依赖开放 API 权限的前提下，建立可持续更新的抖音热榜离线数据库。

## 当前实现

脚本：`src/douyin_hot_db/collect_douyin_hot_crawler.py`

能力：

1. 打开 `https://www.douyin.com/hot`。
2. 优先捕获页面实际网络响应中的 JSON 热榜数据。
3. 若网络 JSON 捕获不足，降级到 DOM 解析提取热词。
4. 入库到 SQLite：
   - `hot_topics`：热词主表（去重）
   - `hot_topic_snapshots`：每次抓取快照（排名/热度/原始 JSON）
   - `runs`：抓取批次状态
5. 可选把热词同步到 `search_tasks`（后续做视频明细抓取）。

## 运行命令

```bash
python src/douyin_hot_db/collect_douyin_hot_crawler.py \
  --db data/douyin_hot.db \
  --wait-seconds 10 \
  --sync-keywords \
  --dump-raw-json data/raw/hot_payload.json
```

无图形界面的服务器不要加 `--headful`。若确实需要可视化模式，可用：

```bash
xvfb-run -a python src/douyin_hot_db/collect_douyin_hot_crawler.py --headful
```

## 常见问题

1. 抓不到数据：先用 `--headful` 登录抖音，再重跑。  
2. 只拿到少量词：调大 `--wait-seconds`（例如 15~20）。  
3. 无法打开浏览器：先执行 `playwright install chromium`。  
4. 被风控：降低抓取频率，使用持久化 profile（默认 `data/browser_profile`）。

## 风险提醒

1. 页面结构或请求链路变化会影响爬取稳定性。  
2. 抓取需遵守平台服务条款及当地法律法规。  
3. 不建议高并发、长时间无间隔抓取。  
