# 飞书机器人 Message Adapter

本文档说明如何把飞书机器人作为 VideoClaw 的外部 IM 入口。这个入口只负责接收飞书消息、转换为统一 `NormalizedMessage`、启动现有 OpenClaw orchestrator 流水线，并在生成完成后把结果回到飞书会话；不改动 `tag-matcher`、`research-supervisor`、`writer`、`video-generate` 的核心逻辑。

## 1. 创建飞书机器人

1. 打开飞书开放平台，创建企业自建应用。
2. 在「凭证与基础信息」里记录：
   - `App ID` → `FEISHU_APP_ID`
   - `App Secret` → `FEISHU_APP_SECRET`
3. 在「应用能力」里启用机器人。
4. 在「权限管理」里至少申请发送消息和接收消息事件相关权限，并发布/安装到目标企业。

## 2. 配置事件回调

FastAPI 新增回调地址：

```text
POST /webhooks/feishu/events
```

本地默认服务是：

```text
http://localhost:8000/webhooks/feishu/events
```

飞书开放平台要求公网 HTTPS 地址。开发时可用 ngrok 或 cloudflared 暴露本地服务：

```bash
ngrok http 8000
```

或：

```bash
cloudflared tunnel --url http://localhost:8000
```

把工具给出的 HTTPS 地址拼上 `/webhooks/feishu/events`，填入飞书「事件订阅」的请求网址。飞书会发送 `url_verification`，服务会返回 `{"challenge":"..."}`。

## 3. 环境变量

在 `agent-service/.env` 中配置：

```bash
FEISHU_BOT_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
# FEISHU_ENCRYPT_KEY=xxx

OPENCLAW_ORCHESTRATOR_COMMAND="openclaw agents spawn orchestrator"
OPENCLAW_RUNS_ROOT=~/.openclaw/runs
OPENCLAW_START_MODE=cli
# OPENCLAW_WORKDIR=/home/YOUR_USER/.openclaw
FEISHU_RESULT_WATCH_TIMEOUT_SEC=3600
FEISHU_RESULT_WATCH_INTERVAL_SEC=10
```

`FEISHU_ENCRYPT_KEY` 预留给加密事件。当前最小可运行版本建议在飞书后台先使用未加密事件回调。

## 4. 本地启动

```bash
cd agent-service
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证服务：

```bash
curl http://localhost:8000/health
```

调试飞书 challenge：

```bash
curl -X POST http://localhost:8000/webhooks/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{"type":"url_verification","token":"你的 verification token","challenge":"abc"}'
```

预期返回：

```json
{"challenge":"abc"}
```

## 5. 示例输入与输出

在飞书里给机器人发送：

```text
帮我做一个露营美食 30 秒短视频
```

机器人会先回复：

```text
已收到任务，正在生成视频
任务主题：帮我做一个露营美食 30 秒短视频
run_id：20260506_134628
当前状态：running
查询进度：发送 /status 20260506_134628
```

服务会创建 `run_id`，写入：

- `~/.openclaw/runs/<run_id>/entry_message.json`
- `~/.openclaw/runs/<run_id>/run_status.json`

然后把 `channel=feishu`、`reply_target=<chat_id>` 和原始文本交给 OpenClaw orchestrator。生成完成后，adapter 会读取 `~/.openclaw/runs/<run_id>/video_result.json`，向飞书会话发送：

```text
视频已生成：<成片链接或本地路径>
run_id: 20260506_134628
```

## 6. 状态查询

FastAPI 提供本地调试接口：

```text
GET /runs/{run_id}/status
```

示例：

```bash
curl http://localhost:8000/runs/20260506_134628/status
```

返回字段：

```json
{
  "data": {
    "run_id": "20260506_134628",
    "status": "running",
    "channel": "feishu",
    "reply_target": "oc_xxx",
    "created_at": "2026-05-06T05:46:28.000000+00:00",
    "updated_at": "2026-05-06T05:46:29.000000+00:00",
    "error": null,
    "output_video": null,
    "observing": true,
    "run_dir": "/home/YOUR_USER/.openclaw/runs/20260506_134628",
    "entry_message_exists": true,
    "video_result_exists": false,
    "error_exists": false
  }
}
```

`status` 取值：

- `pending`：run 目录与入口消息已创建，尚未确认 OpenClaw 启动成功
- `running`：orchestrator 已启动
- `generated`：已检测到成功的 `video_result.json`
- `failed`：启动、生成、观察超时或错误文件检测失败
- `replied`：已向飞书回复生成结果
- `reply_failed`：生成结果已有，但飞书回复失败

列出最近 run：

```bash
curl "http://localhost:8000/runs?limit=20"
```

返回每个 run 的 `run_id/status/channel/created_at/updated_at/output_video/error`，用于真实联调时快速定位最近一次消息对应的任务。

## 7. 飞书内命令

用户可以直接在飞书里查询任务，不需要打开本地调试接口。

查询单个任务：

```text
/status 20260506_134628
状态 20260506_134628
查询 20260506_134628
```

返回示例：

```text
任务状态
run_id: 20260506_134628
status: running
channel: feishu
created_at: 2026-05-06T05:46:28.000000+00:00
updated_at: 2026-05-06T05:46:29.000000+00:00
observing: true
entry_message: yes
video_result: no
error_file: no
```

如果 `output_video` 已存在，会附带成片链接或路径；如果 `error` 已存在，会附带简短错误。

查看最近 5 个任务：

```text
/runs
最近任务
```

返回每个任务的 `run_id`、`status`、`created_at`、`updated_at`，有 `output_video` 时也会展示。

常见命令错误：

- `/status` 未带 run_id：机器人会提示 `请带上 run_id，例如：/status 20260506_134628`
- run_id 不存在：机器人会提示没有找到该任务，并建议发送 `/runs`
- `/runs` 没有历史任务：机器人会提示先发送视频主题创建任务
- 非飞书 channel 的 run 也能查，回复会展示 `channel` 字段

当前返回使用纯文本。`FeishuAdapter` 已预留 `sendCard()` 接口，但还没有接入飞书交互卡片 API。

## 8. 错误处理

- 空消息：`请输入视频主题，例如：帮我做一个露营美食 30 秒短视频`
- 非文本消息：`当前暂时只支持文本选题`
- pipeline 启动失败：`任务启动失败，请稍后重试`
- 视频生成失败：`视频生成失败，已记录错误日志`

本地 Mac 联调时，OpenClaw 的 `tag_get_script_pack` 依赖 `agent-service`。如果 tag-matcher 卡在选题 grounding，请先看 [LOCAL_DEV.md](LOCAL_DEV.md) 的 `tag_get_script_pack` 排查与 fallback 说明。

## 9. 真实联调检查清单

1. FastAPI 已启动：`curl http://localhost:8000/health`
2. `.env` 中 `FEISHU_BOT_ENABLED=true`
3. `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN` 与飞书后台一致
4. 飞书事件回调 URL 是公网 HTTPS：`https://<domain>/webhooks/feishu/events`
5. 飞书 challenge 返回 `{"challenge":"..."}`
6. 机器人已安装到目标群或用户会话
7. 飞书事件订阅已启用文本消息接收事件
8. FastAPI 日志出现 `received feishu event`
9. `OPENCLAW_ORCHESTRATOR_COMMAND` 在服务器 shell 中可用
10. `OPENCLAW_RUNS_ROOT` 与 OpenClaw orchestrator 使用的 `~/.openclaw/runs` 指向同一位置
11. 发送测试消息后，`/runs/<run_id>/status` 能看到 `running`
12. 生成结束后，`video_result.json` 出现在 `~/.openclaw/runs/<run_id>/`
13. 飞书收到 `视频已生成：...`

## 10. 端到端联调流程

1. 启动 FastAPI：`uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. 暴露公网地址：`ngrok http 8000` 或 `cloudflared tunnel --url http://localhost:8000`
3. 飞书后台配置 `https://<domain>/webhooks/feishu/events`，确认 challenge 成功。
4. 在飞书给机器人发：`帮我做一个露营美食 30 秒短视频`
5. 预期收到：`已收到任务，正在生成视频` 和 `run_id`。
6. 查最近任务：`curl "http://localhost:8000/runs?limit=5"`
7. 查单个状态：`curl http://localhost:8000/runs/<run_id>/status`
8. 确认 `observing=true`、`entry_message_exists=true`、`status=running`。
9. 确认 OpenClaw 侧 `~/.openclaw/runs/<run_id>/brief.json`、后续研究/脚本/视频文件陆续生成。
10. 生成完成后，确认 `video_result_exists=true`、`status` 最终变为 `replied`，飞书收到 `视频已生成：...`。

## 11. 服务重启后的任务恢复

FastAPI 启动时会扫描 `OPENCLAW_RUNS_ROOT` 下的 `*/run_status.json`。

满足以下条件的任务会重新启动观察器：

- `channel == "feishu"`
- `reply_target` 存在
- `status` 是 `running` 或 `generated`

不会恢复：

- `replied`
- `failed`
- `reply_failed`
- 非飞书 channel
- 没有 `reply_target` 的 run

内存里维护了 observing registry，同一个 `run_id` 同时只会被一个观察器处理。观察完成后会自动移除 registry；状态接口的 `observing` 字段可以看到当前是否正在观察。

## 12. 用 mock-complete 验证飞书回传

`mock-complete` 只在 `DEBUG=true`、`TEST_MODE=true` 或 `ENV=test` 时可用，生产环境默认禁用。

典型流程：

1. 设置测试模式：

```bash
export TEST_MODE=true
```

2. 发一条飞书文本消息，拿到 `run_id`。
3. 手动写入模拟完成：

```bash
curl -X POST "http://localhost:8000/runs/<run_id>/mock-complete?output_video=https://example.com/mock.mp4"
```

4. 查询状态：

```bash
curl http://localhost:8000/runs/<run_id>/status
```

5. 预期飞书收到：

```text
视频已生成：https://example.com/mock.mp4
run_id: <run_id>
```

如果生产环境误调用，会返回 `403 mock-complete is disabled outside DEBUG or TEST mode`。

## 13. 常见错误排查

### challenge 不通过

- 检查 `FEISHU_VERIFICATION_TOKEN` 是否和飞书后台完全一致。
- 确认回调服务收到的是未加密事件；当前最小版本尚未实现 `FEISHU_ENCRYPT_KEY` 解密。
- 看 FastAPI 日志是否有 `invalid feishu verification token`。

### 收不到事件

- 确认公网地址可以访问，并且路径是 `/webhooks/feishu/events`。
- 确认 ngrok/cloudflared 没断开。
- 确认飞书应用已发布并安装到企业或测试范围。
- 确认订阅了消息接收事件，机器人也在对应会话里。

### pipeline 未启动

- 查 `/runs/<run_id>/status` 的 `error`。
- 如果 `/runs?limit=5` 里没有新 run，说明飞书事件没有进入或被 `FEISHU_BOT_ENABLED=false` 忽略。
- 如果有 run 但 `status=failed` 且 `error` 提到 OpenClaw command，说明 `OPENCLAW_ORCHESTRATOR_COMMAND` 执行失败。
- 确认 `OPENCLAW_ORCHESTRATOR_COMMAND` 可以直接在同一机器执行。
- 如 OpenClaw 命令依赖特定目录，设置 `OPENCLAW_WORKDIR=/home/YOUR_USER/.openclaw`。
- 查看 FastAPI 日志里的 `starting openclaw orchestrator` 和 `pipeline start failed`。

### run_id 目录不存在

- 确认 `OPENCLAW_RUNS_ROOT` 是否写错。
- 确认 FastAPI 进程用户对该目录有写权限。
- 正常情况下收到文本消息后应立即创建 `~/.openclaw/runs/<run_id>/entry_message.json` 和 `run_status.json`。

### video_result.json 未生成

- 先看 `/runs/<run_id>/status`：
  - `observing=false` 且 `status=running`：服务可能重启后恢复失败，重启 FastAPI 或检查 startup recovery 日志。
  - `video_result_exists=false`：OpenClaw 还没有生成最终视频结果。
  - `error_exists=true`：查看 `error` 字段或 `error.json`。
- 查 `run_status.json` 是否已经是 `failed`。
- 查 `error.json` 是否存在。
- 查 OpenClaw orchestrator / video-generate 日志。
- 确认 orchestrator 使用了 adapter 提供的 `run_id`，而不是另建了一个 run。
- 如果超过 `FEISHU_RESULT_WATCH_TIMEOUT_SEC`，adapter 会把状态置为 `failed` 并写入超时原因。

### 飞书回复失败

- 查 `run_status.json` 是否为 `reply_failed`。
- 如果 `status=generated` 但长期未到 `replied`，查 `observing` 是否为 `true`。
- 确认 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 有效。
- 确认应用有发送消息权限，并已发布/安装。
- 确认 `reply_target` 是飞书 `chat_id`。
- 查看 FastAPI 日志里的 `reply feishu failed`。

## 14. 相关代码

- 通用类型：`agent-service/app/adapters/base.py`
- 飞书 adapter：`agent-service/app/adapters/feishu/adapter.py`
- 飞书 route：`agent-service/app/routes/feishu.py`
- Run 状态 route：`agent-service/app/routes/runs.py`
- 飞书观察器与恢复：`agent-service/app/services/feishu_observer_service.py`
- OpenClaw 启动客户端：`agent-service/app/services/workflow_service.py`
- Telegram/WhatsApp 兼容 adapter：`agent-service/app/adapters/telegram/`、`agent-service/app/adapters/whatsapp/`
