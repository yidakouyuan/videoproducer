"""
视频生成路由层。

对外暴露：
  POST   /video/generate/start
  GET    /video/generate/result/{job_id}
  DELETE /video/generate/{job_id}

注意路由定义顺序：固定路径 /start 必须在 /{job_id} 之前注册。
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Request

from app.infra.response import ok
from app.providers.mock_video_generate_provider import MockVideoGenerateProvider
from app.schemas.video_generate import (
    DeleteGenerateData,
    GenerateResultData,
    StartGenerateData,
    StartGenerateRequest,
)
from app.services.video_generate_service import VideoGenerateService

router = APIRouter(prefix="/video/generate", tags=["video-generate"])

# ---------------------------------------------------------------------------
# 依赖注入：Provider 切换点
#
# 环境变量 USE_REAL_MINIMAX=1 → MiniMaxVideoProvider（需 MINIMAX_API_KEY）
# 环境变量 USE_REAL_SEEDANCE=1 → SeedanceVideoProvider（需 ARK_API_KEY）
# 否则                          → MockVideoGenerateProvider（2秒后返回 mock 路径）
# ---------------------------------------------------------------------------

_use_minimax = os.environ.get("USE_REAL_MINIMAX", "").strip() == "1"
_use_seedance = os.environ.get("USE_REAL_SEEDANCE", "").strip() == "1"

if _use_seedance:
    from app.providers.seedance_video_provider import SeedanceVideoProvider
    _provider = SeedanceVideoProvider()
elif _use_minimax:
    from app.providers.minimax_video_provider import MiniMaxVideoProvider
    _provider = MiniMaxVideoProvider()
else:
    _provider = MockVideoGenerateProvider()


def get_video_generate_provider():
    return _provider


def get_video_generate_service(
    provider=Depends(get_video_generate_provider),
) -> VideoGenerateService:
    return VideoGenerateService(provider=provider)


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


# ---------------------------------------------------------------------------
# POST /video/generate/start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    summary="启动视频生成任务（异步，返回 job_id）",
)
async def start_generate(
    body: StartGenerateRequest,
    request: Request,
    service: VideoGenerateService = Depends(get_video_generate_service),
) -> dict:
    """
    提交视频生成任务（MiniMax Hailuo 文生视频），立即返回 job_id + status=queued。

    - prompt 必填
    - duration 可选，默认 6（秒）
    - resolution 可选，默认 512P
    - 生成服务不可用 → 502 PROVIDER_ERROR
    """
    rid, t0 = _ctx(request)
    data: StartGenerateData = await service.start_generate(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# GET /video/generate/result/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/result/{job_id}",
    summary="查询视频生成任务结果",
)
async def get_generate_result(
    job_id: str,
    request: Request,
    service: VideoGenerateService = Depends(get_video_generate_service),
) -> dict:
    """
    轮询视频生成任务状态。

    status 状态机：queued → running → done / failed

    - status=done 时返回 local_video_path 和 manifest_path
    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: GenerateResultData = await service.get_result(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# DELETE /video/generate/{job_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{job_id}",
    summary="删除视频生成任务记录",
)
async def delete_generate(
    job_id: str,
    request: Request,
    service: VideoGenerateService = Depends(get_video_generate_service),
) -> dict:
    """
    删除任务记录（不删除已下载到本地的视频文件）。

    - job_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: DeleteGenerateData = await service.delete_generate(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
