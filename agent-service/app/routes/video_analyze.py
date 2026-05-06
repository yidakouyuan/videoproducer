"""
视频分析路由层。

对外暴露：
  POST   /video/analyze/start
  GET    /video/analyze/result/{job_id}
  DELETE /video/analyze/{job_id}

注意路由定义顺序：固定路径 /start 必须在 /{job_id} 之前注册。
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Request

from app.infra.response import ok
from app.providers.base import VideoAnalysisProvider
from app.providers.gemini_video_analysis_provider import GeminiVideoAnalysisProvider
from app.providers.mock_video_analysis_provider import MockVideoAnalysisProvider
from app.schemas.video_analyze import (
    AnalysisResultData,
    DeleteAnalysisData,
    StartAnalysisData,
    StartAnalysisRequest,
)
from app.services.video_analysis_service import VideoAnalysisService

router = APIRouter(prefix="/video/analyze", tags=["video-analyze"])

# ---------------------------------------------------------------------------
# 依赖注入：Provider 切换点
#
# 环境变量 USE_REAL_GEMINI=1 → GeminiVideoAnalysisProvider（需 GEMINI_API_KEY）
# 否则                       → MockVideoAnalysisProvider（2秒后返回 mock 结果）
#
# 示例：
#   USE_REAL_GEMINI=1 GEMINI_API_KEY=xxx uvicorn app.main:app
# ---------------------------------------------------------------------------

_use_real = os.environ.get("USE_REAL_GEMINI", "").strip() == "1"
_provider: VideoAnalysisProvider = (
    GeminiVideoAnalysisProvider() if _use_real else MockVideoAnalysisProvider()
)


def get_video_analysis_provider() -> VideoAnalysisProvider:
    return _provider


def get_video_analysis_service(
    provider: VideoAnalysisProvider = Depends(get_video_analysis_provider),
) -> VideoAnalysisService:
    return VideoAnalysisService(provider=provider)


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


# ---------------------------------------------------------------------------
# POST /video/analyze/start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    summary="启动视频分析任务（异步，返回 job_id）",
)
async def start_analysis(
    body: StartAnalysisRequest,
    request: Request,
    service: VideoAnalysisService = Depends(get_video_analysis_service),
) -> dict:
    """
    提交视频分析任务（如 Gemini 视频理解），立即返回 job_id + status=queued。

    - media_id 对应视频不存在 → 404 NOT_FOUND
    - 分析服务不可用           → 502 PROVIDER_ERROR
    """
    rid, t0 = _ctx(request)
    data: StartAnalysisData = await service.start_analysis(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# GET /video/analyze/result/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/result/{job_id}",
    summary="查询视频分析任务结果",
)
async def get_analysis_result(
    job_id: str,
    request: Request,
    service: VideoAnalysisService = Depends(get_video_analysis_service),
) -> dict:
    """
    轮询视频分析任务状态。

    status 状态机：queued → running → done / failed / partial / cancelled

    - status=queued/running 时 video_breakdown 为 null，客户端应继续轮询
    - status=done 时返回完整 video_breakdown
    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: AnalysisResultData = await service.get_result(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# DELETE /video/analyze/{job_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{job_id}",
    summary="删除视频分析任务结果",
)
async def delete_analysis(
    job_id: str,
    request: Request,
    service: VideoAnalysisService = Depends(get_video_analysis_service),
) -> dict:
    """
    删除分析任务记录、video_breakdown 及相关缓存 summary。

    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: DeleteAnalysisData = await service.delete_analysis(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
