"""
Feishu run observation registry and recovery helpers.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from app.adapters.feishu import FeishuAdapter
from app.services.workflow_service import OpenClawWorkflowClient

logger = logging.getLogger(__name__)

VIDEO_FAILED_REPLY = "视频生成失败，已记录错误日志"

_observing_run_ids: set[str] = set()
_observing_tasks: dict[str, asyncio.Task] = {}


def is_observing(run_id: str) -> bool:
    return run_id in _observing_run_ids


def observing_run_ids() -> set[str]:
    return set(_observing_run_ids)


def clear_observing_registry_for_tests() -> None:
    for task in list(_observing_tasks.values()):
        if not task.done():
            task.cancel()
    _observing_tasks.clear()
    _observing_run_ids.clear()


def schedule_feishu_observation(run_id: str, chat_id: str) -> bool:
    if is_observing(run_id):
        logger.info("skip duplicate feishu observation: run_id=%s", run_id)
        return False

    _observing_run_ids.add(run_id)
    task = asyncio.create_task(_observe_and_reply_registered(run_id, chat_id))
    _observing_tasks[run_id] = task
    logger.info("scheduled feishu observation: run_id=%s", run_id)
    return True


async def recover_feishu_observers() -> list[str]:
    workflow = OpenClawWorkflowClient()
    recovered: list[str] = []
    if not workflow.runs_root.exists():
        logger.info("skip feishu recovery; runs root does not exist: %s", workflow.runs_root)
        return recovered

    for status_path in sorted(workflow.runs_root.glob("*/run_status.json")):
        status = _read_status_file(status_path)
        if not _should_recover_status(status):
            continue

        run_id = str(status.get("run_id") or status_path.parent.name)
        reply_target = str(status.get("reply_target") or "")
        if schedule_feishu_observation(run_id, reply_target):
            recovered.append(run_id)

    logger.info("feishu startup recovery scheduled runs: %s", recovered)
    return recovered


async def observe_and_reply_feishu(run_id: str, chat_id: str) -> None:
    adapter = FeishuAdapter()
    workflow = OpenClawWorkflowClient()
    timeout_sec = int(os.environ.get("FEISHU_RESULT_WATCH_TIMEOUT_SEC", "3600"))
    interval_sec = int(os.environ.get("FEISHU_RESULT_WATCH_INTERVAL_SEC", "10"))
    result = await workflow.observe_video_result(run_id, timeout_sec=timeout_sec, interval_sec=interval_sec)

    if result.status == "generated":
        output = result.output_video or "未找到成片路径"
        ok_reply = await _safe_send_text(adapter, chat_id, f"视频已生成：{output}\nrun_id: {run_id}")
        if ok_reply:
            workflow.update_run_status(run_id, "replied", output_video=output)
        else:
            workflow.update_run_status(run_id, "reply_failed", error="failed to reply generated video", output_video=output)
        return

    error_text = _short_error(result.error)
    failed_reply = await _safe_send_text(adapter, chat_id, f"{VIDEO_FAILED_REPLY}\nrun_id: {run_id}\n原因：{error_text}")
    if not failed_reply:
        workflow.update_run_status(run_id, "reply_failed", error=f"failed to reply failure message: {error_text}")


async def _observe_and_reply_registered(run_id: str, chat_id: str) -> None:
    try:
        await observe_and_reply_feishu(run_id, chat_id)
    finally:
        _observing_run_ids.discard(run_id)
        _observing_tasks.pop(run_id, None)
        logger.info("finished feishu observation: run_id=%s", run_id)


async def _safe_send_text(adapter: FeishuAdapter, chat_id: str, text: str) -> bool:
    try:
        await adapter.sendText(chat_id, text)
        return True
    except Exception:
        logger.exception("reply feishu failed: chat_id=%s", chat_id)
        return False


def _read_status_file(path: Path) -> dict[str, Any]:
    try:
        return OpenClawWorkflowClient._read_json_file(path)
    except Exception:
        logger.warning("failed to read run_status during recovery: %s", path, exc_info=True)
        return {}


def _should_recover_status(status: dict[str, Any]) -> bool:
    return (
        status.get("channel") == "feishu"
        and bool(status.get("reply_target"))
        and status.get("status") in {"running", "generated"}
    )


def _short_error(error: str | None) -> str:
    if not error:
        return "unknown"
    return error[:160]
