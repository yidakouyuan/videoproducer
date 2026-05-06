"""
Feishu bot webhook routes.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.adapters.feishu import FeishuAdapter
from app.infra.response import ok
from app.services.feishu_observer_service import is_observing, schedule_feishu_observation
from app.services.workflow_service import OpenClawWorkflowClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/feishu", tags=["feishu"])

EMPTY_MESSAGE_REPLY = "请输入视频主题，例如：帮我做一个露营美食 30 秒短视频"
NON_TEXT_REPLY = "当前暂时只支持文本选题"
START_FAILED_REPLY = "任务启动失败，请稍后重试"
VIDEO_FAILED_REPLY = "视频生成失败，已记录错误日志"
ACK_REPLY = "已收到任务，正在生成视频"


@router.post("/events", summary="飞书事件回调")
async def feishu_events(request: Request) -> dict[str, Any]:
    rid, t0 = request.state.request_id, request.state.started_at
    event = await request.json()
    logger.info("received feishu event: %s", _safe_event_for_log(event))

    adapter = FeishuAdapter()
    if _is_challenge_event(event):
        if not adapter.verify_token(event):
            raise HTTPException(status_code=403, detail="invalid feishu verification token")
        return {"challenge": event.get("challenge")}

    if os.environ.get("FEISHU_BOT_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("feishu bot disabled; event ignored")
        return ok({"status": "ignored", "reason": "FEISHU_BOT_ENABLED is false"}, rid, _elapsed_ms(t0))

    if not adapter.verify_token(event):
        raise HTTPException(status_code=403, detail="invalid feishu verification token")

    message = adapter.parseIncoming(event)
    logger.info(
        "normalized feishu message: platform=%s message_id=%s chat_id=%s user_id=%s message_type=%s text=%r",
        message.platform,
        message.message_id,
        message.chat_id,
        message.user_id,
        message.message_type,
        message.text,
    )

    if message.message_type != "text":
        await _safe_send_text(adapter, message.chat_id, NON_TEXT_REPLY)
        return ok({"status": "ignored", "reason": "non_text_message"}, rid, _elapsed_ms(t0))

    if not message.text.strip():
        await _safe_send_text(adapter, message.chat_id, EMPTY_MESSAGE_REPLY)
        return ok({"status": "ignored", "reason": "empty_message"}, rid, _elapsed_ms(t0))

    workflow = OpenClawWorkflowClient()
    command = _parse_command(message.text)
    if command:
        reply = _handle_command(command, workflow)
        await _safe_send_text(adapter, message.chat_id, reply)
        return ok({"status": "command_handled", "command": command["name"]}, rid, _elapsed_ms(t0))

    try:
        start = await workflow.start(message)
    except Exception:
        logger.exception("pipeline start failed for feishu message_id=%s", message.message_id)
        await _safe_send_text(adapter, message.chat_id, START_FAILED_REPLY)
        return ok({"status": "failed", "reason": "pipeline_start_failed"}, rid, _elapsed_ms(t0))

    logger.info("pipeline start success: run_id=%s channel=feishu", start.run_id)
    await _safe_send_text(adapter, message.chat_id, _format_start_reply(message.text, start.run_id, start.status))
    schedule_feishu_observation(start.run_id, message.chat_id)
    return ok({"status": start.status, "run_id": start.run_id}, rid, _elapsed_ms(t0))


async def _safe_send_text(adapter: FeishuAdapter, chat_id: str, text: str) -> bool:
    try:
        await adapter.sendText(chat_id, text)
        return True
    except Exception:
        logger.exception("reply feishu failed: chat_id=%s", chat_id)
        return False


def _is_challenge_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "url_verification" and "challenge" in event


def _safe_event_for_log(event: dict[str, Any]) -> dict[str, Any]:
    safe = dict(event)
    if safe.get("token"):
        safe["token"] = "***"
    return safe


def _elapsed_ms(started_at: float) -> float:
    return round((time.monotonic() - started_at) * 1000, 2)


def _parse_command(text: str) -> dict[str, str | None] | None:
    cleaned = text.strip()
    if cleaned in {"/runs", "最近任务"}:
        return {"name": "runs", "run_id": None}

    for prefix in ("/status", "状态", "查询"):
        if cleaned == prefix:
            return {"name": "status", "run_id": None}
        marker = f"{prefix} "
        if cleaned.startswith(marker):
            run_id = cleaned[len(marker) :].strip()
            return {"name": "status", "run_id": run_id or None}

    return None


def _handle_command(command: dict[str, str | None], workflow: OpenClawWorkflowClient) -> str:
    if command["name"] == "runs":
        return _format_recent_runs(workflow)
    if command["name"] == "status":
        run_id = command.get("run_id")
        if not run_id:
            return "请带上 run_id，例如：/status 20260506_134628"
        return _format_run_status(workflow, run_id)
    return "暂不支持该命令"


def _format_run_status(workflow: OpenClawWorkflowClient, run_id: str) -> str:
    try:
        status = workflow.read_run_status(run_id)
    except FileNotFoundError:
        return f"没有找到 run_id：{run_id}\n可以发送 /runs 查看最近任务。"

    files = workflow.run_file_state(run_id)
    lines = [
        "任务状态",
        f"run_id: {status.get('run_id') or run_id}",
        f"status: {status.get('status') or 'unknown'}",
        f"channel: {status.get('channel') or 'unknown'}",
        f"created_at: {status.get('created_at') or '-'}",
        f"updated_at: {status.get('updated_at') or '-'}",
        f"observing: {str(is_observing(run_id)).lower()}",
        f"entry_message: {_yes_no(files['entry_message_exists'])}",
        f"video_result: {_yes_no(files['video_result_exists'])}",
        f"error_file: {_yes_no(files['error_exists'])}",
    ]
    if status.get("output_video"):
        lines.append(f"output_video: {status['output_video']}")
    if status.get("error"):
        lines.append(f"error: {_short_text(str(status['error']))}")
    return "\n".join(lines)


def _format_recent_runs(workflow: OpenClawWorkflowClient) -> str:
    runs = workflow.list_run_statuses(limit=5)
    if not runs:
        return "暂时没有历史任务。发送一个视频主题即可创建新任务。"

    lines = ["最近任务"]
    for item in runs:
        run_id = item.get("run_id") or "-"
        status = item.get("status") or "unknown"
        created_at = item.get("created_at") or "-"
        updated_at = item.get("updated_at") or "-"
        lines.append(f"{run_id} | {status}\ncreated: {created_at}\nupdated: {updated_at}")
        if item.get("output_video"):
            lines.append(f"output: {item['output_video']}")
    return "\n\n".join(lines)


def _format_start_reply(topic: str, run_id: str, status: str) -> str:
    return (
        f"{ACK_REPLY}\n"
        f"任务主题：{_short_text(topic, 80)}\n"
        f"run_id：{run_id}\n"
        f"当前状态：{status}\n"
        f"查询进度：发送 /status {run_id}"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _short_text(text: str, limit: int = 160) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."
