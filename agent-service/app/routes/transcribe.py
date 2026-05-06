"""
转写路由层。

对外暴露：
  POST   /transcribe/start
  GET    /transcribe/result/{job_id}
  DELETE /transcribe/{job_id}

注意路由定义顺序：固定路径 /start 必须在 /{job_id} 之前注册。
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Request

from app.infra.response import ok
from app.providers.base import TranscribeProvider
from app.providers.gemini_transcribe_provider import GeminiTranscribeProvider
from app.providers.mock_transcribe_provider import MockTranscribeProvider
from app.schemas.transcribe import (
    DeleteTranscribeData,
    StartTranscribeData,
    StartTranscribeRequest,
    TranscribeResultData,
)
from app.services.transcribe_service import TranscribeService

router = APIRouter(prefix="/transcribe", tags=["transcribe"])

# ---------------------------------------------------------------------------
# 依赖注入：Provider 切换点
#
# 环境变量 USE_REAL_GEMINI=1 → GeminiTranscribeProvider（需 GEMINI_API_KEY）
# 否则                       → MockTranscribeProvider（2秒后返回 mock 结果）
#
# 示例：
#   USE_REAL_GEMINI=1 GEMINI_API_KEY=xxx uvicorn app.main:app
# ---------------------------------------------------------------------------

_use_real = os.environ.get("USE_REAL_GEMINI", "").strip() == "1"
_provider: TranscribeProvider = (
    GeminiTranscribeProvider() if _use_real else MockTranscribeProvider()
)


def get_transcribe_provider() -> TranscribeProvider:
    return _provider


def get_transcribe_service(
    provider: TranscribeProvider = Depends(get_transcribe_provider),
) -> TranscribeService:
    return TranscribeService(provider=provider)


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


# ---------------------------------------------------------------------------
# POST /transcribe/start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    summary="启动转写任务（异步，返回 job_id）",
)
async def start_transcribe(
    body: StartTranscribeRequest,
    request: Request,
    service: TranscribeService = Depends(get_transcribe_service),
) -> dict:
    """
    提交视频转写任务，立即返回 job_id + status=queued。

    - media_id 对应媒体不存在 → 404 NOT_FOUND
    - 转写服务不可用           → 502 PROVIDER_ERROR
    """
    rid, t0 = _ctx(request)
    data: StartTranscribeData = await service.start_transcribe(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# GET /transcribe/result/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/result/{job_id}",
    summary="查询转写任务结果",
)
async def get_transcribe_result(
    job_id: str,
    request: Request,
    service: TranscribeService = Depends(get_transcribe_service),
) -> dict:
    """
    轮询转写任务状态。

    status 状态机：queued → running → done / failed

    - status=queued/running 时 transcript / highlights 为 null / []，客户端应继续轮询
    - status=done 时返回完整 transcript 和 highlights
    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: TranscribeResultData = await service.get_result(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# DELETE /transcribe/{job_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{job_id}",
    summary="删除转写任务结果",
)
async def delete_transcribe(
    job_id: str,
    request: Request,
    service: TranscribeService = Depends(get_transcribe_service),
) -> dict:
    """
    删除转写记录、transcript、highlights 及相关缓存 summary。

    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: DeleteTranscribeData = await service.delete_transcribe(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
