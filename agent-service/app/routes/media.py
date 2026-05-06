"""
媒体路由层。

对外暴露：
  POST   /media/resolve_video
  POST   /media/fetch_video
  POST   /media/cleanup
  DELETE /media/{media_id}

注意路由定义顺序：固定路径（/resolve_video, /fetch_video, /cleanup）
必须在路径参数路由（/{media_id}）之前注册，否则 FastAPI 会误匹配。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

import os

from app.infra.response import ok
from app.providers.base import MediaProvider
from app.providers.douyin_media_provider import DouyinMediaProvider
from app.providers.mock_media_provider import MockMediaProvider
from app.schemas.media import (
    CleanupData,
    CleanupRequest,
    DeleteMediaData,
    FetchedVideoData,
    FetchVideoRequest,
    ResolvedVideoData,
    ResolveVideoRequest,
)
from app.services.media_service import MediaService

router = APIRouter(prefix="/media", tags=["media"])

# ---------------------------------------------------------------------------
# 依赖注入：Provider 切换点
#
# 环境变量 USE_REAL_DOUYIN=1 → DouyinMediaProvider（真实 yt-dlp 提取）
# 否则       → MockMediaProvider（内存 mock，供测试 / 开发使用）
#
# 示例：
#   USE_REAL_DOUYIN=1 DOUYIN_COOKIE_FILE=/path/to/cookies.txt uvicorn app.main:app
# ---------------------------------------------------------------------------

_use_real = os.environ.get("USE_REAL_DOUYIN", "").strip() == "1"
_provider: MediaProvider = DouyinMediaProvider() if _use_real else MockMediaProvider()


def get_media_provider() -> MediaProvider:
    return _provider


def get_media_service(
    provider: MediaProvider = Depends(get_media_provider),
) -> MediaService:
    return MediaService(provider=provider)


# ---------------------------------------------------------------------------
# 辅助：从 request.state 提取 rid / elapsed_ms
# ---------------------------------------------------------------------------


def _ctx(request: Request) -> tuple[str, float]:
    """返回 (request_id, started_at)。"""
    return request.state.request_id, request.state.started_at


# ---------------------------------------------------------------------------
# POST /media/resolve_video
# ---------------------------------------------------------------------------


@router.post(
    "/resolve_video",
    summary="解析平台视频，获取可下载的 video_url",
)
async def resolve_video(
    body: ResolveVideoRequest,
    request: Request,
    service: MediaService = Depends(get_media_service),
) -> dict:
    """
    根据平台内容引用（当前仅支持抖音）解析出正式的 video_url。

    - 解析失败（网络 / 反爬） → 502 PROVIDER_ERROR
    - 视频已删除 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: ResolvedVideoData = await service.resolve_video(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# POST /media/fetch_video
# ---------------------------------------------------------------------------


@router.post(
    "/fetch_video",
    summary="下载并缓存视频，生成系统内部 media_id",
)
async def fetch_video(
    body: FetchVideoRequest,
    request: Request,
    service: MediaService = Depends(get_media_service),
) -> dict:
    """
    下载已解析成功的视频，生成系统内部可稳定使用的 media_id。

    - resolved_video_ref.downloadable=False → 422 INVALID_INPUT
    - 下载 / 存储失败 → 502 PROVIDER_ERROR
    """
    rid, t0 = _ctx(request)
    data: FetchedVideoData = await service.fetch_video(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# POST /media/cleanup
# ---------------------------------------------------------------------------


@router.post(
    "/cleanup",
    summary="批量清理缓存视频（支持 dry_run 预览）",
)
async def cleanup(
    body: CleanupRequest,
    request: Request,
    service: MediaService = Depends(get_media_service),
) -> dict:
    """
    按条件批量清理缓存视频，防止长期占用空间。
    建议先用 dry_run=true 预览，确认后再执行删除。
    """
    rid, t0 = _ctx(request)
    data: CleanupData = await service.cleanup(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# DELETE /media/{media_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{media_id}",
    summary="删除已缓存的视频资源",
)
async def delete_media(
    media_id: str,
    request: Request,
    service: MediaService = Depends(get_media_service),
) -> dict:
    """
    删除本地缓存文件、对象存储文件及 StoredMedia 记录。

    - media_id 不存在 → 404 NOT_FOUND
    """
    rid, t0 = _ctx(request)
    data: DeleteMediaData = await service.delete_media(media_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
