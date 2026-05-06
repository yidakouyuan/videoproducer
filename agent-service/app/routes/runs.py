"""
Run status debug routes.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.infra.response import ok
from app.services.feishu_observer_service import is_observing, schedule_feishu_observation
from app.services.workflow_service import OpenClawWorkflowClient

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", summary="列出最近的外部入口 run")
async def list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    workflow = OpenClawWorkflowClient()
    runs = [
        {
            "run_id": status.get("run_id"),
            "status": status.get("status"),
            "channel": status.get("channel"),
            "created_at": status.get("created_at"),
            "updated_at": status.get("updated_at"),
            "output_video": status.get("output_video"),
            "error": status.get("error"),
        }
        for status in workflow.list_run_statuses(limit=limit)
    ]
    return ok({"runs": runs}, _request_id(request), _elapsed_ms(request))


@router.get("/{run_id}/status", summary="查询外部入口 run 状态")
async def get_run_status(run_id: str, request: Request) -> dict[str, Any]:
    workflow = OpenClawWorkflowClient()
    try:
        status = workflow.read_run_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    data = {
        "run_id": status.get("run_id") or run_id,
        "status": status.get("status"),
        "channel": status.get("channel"),
        "reply_target": status.get("reply_target"),
        "created_at": status.get("created_at"),
        "updated_at": status.get("updated_at"),
        "error": status.get("error"),
        "output_video": status.get("output_video"),
        "observing": is_observing(run_id),
        "run_dir": str(workflow.run_dir(run_id)),
        **workflow.run_file_state(run_id),
    }
    return ok(data, _request_id(request), _elapsed_ms(request))


@router.post("/{run_id}/mock-complete", summary="测试模式：模拟视频生成完成")
async def mock_complete_run(
    run_id: str,
    request: Request,
    output_video: str = Query("/tmp/videoclaw_mock_video.mp4"),
) -> dict[str, Any]:
    if not _debug_or_test_enabled():
        raise HTTPException(status_code=403, detail="mock-complete is disabled outside DEBUG or TEST mode")

    workflow = OpenClawWorkflowClient()
    try:
        status = workflow.read_run_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")

    workflow.write_video_result(run_id, output_video=output_video)
    workflow.update_run_status(run_id, "generated", output_video=output_video)
    scheduled = False
    if status.get("channel") == "feishu" and status.get("reply_target"):
        scheduled = schedule_feishu_observation(run_id, str(status["reply_target"]))

    return ok(
        {"run_id": run_id, "output_video": output_video, "scheduled_observer": scheduled},
        _request_id(request),
        _elapsed_ms(request),
    )


def _debug_or_test_enabled() -> bool:
    import os

    return os.environ.get("DEBUG", "").lower() in {"1", "true", "yes", "on"} or os.environ.get(
        "TEST_MODE", ""
    ).lower() in {"1", "true", "yes", "on"} or os.environ.get("ENV", "").lower() == "test"


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _elapsed_ms(request: Request) -> float:
    started_at = getattr(request.state, "started_at", time.monotonic())
    return round((time.monotonic() - started_at) * 1000, 2)
