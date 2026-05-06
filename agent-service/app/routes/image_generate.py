"""
图片生成路由层。

对外暴露：
  GET    /image/generate/models           查询当前 provider 的可用模型
  POST   /image/generate/start            启动生成任务
  GET    /image/generate/result/{job_id}  查询任务状态（支持 long-poll）
  DELETE /image/generate/{job_id}         删除任务记录

Provider 选择（环境变量 IMAGE_PROVIDER）：
  kling    → KlingImageProvider    (需 KLING_ACCESS_KEY + KLING_SECRET_KEY)
  wanx     → WanxImageProvider     (需 WANX_API_KEY)
  minimax  → MiniMaxImageProvider  (需 MINIMAX_API_KEY)
  mock     → MockImageProvider（默认，无需外部依赖）

注意路由定义顺序：固定路径 /models 和 /start 必须在 /{job_id} 之前注册。
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Query, Request

from app.infra.response import ok
from app.providers.mock_image_provider import MockImageProvider
from app.schemas.image_generate import (
    DeleteImageData,
    ImageModelsData,
    ImageResultData,
    StartImageData,
    StartImageRequest,
)
from app.services.image_generate_service import ImageGenerateService

router = APIRouter(prefix="/image/generate", tags=["image-generate"])

# ---------------------------------------------------------------------------
# Provider 选择
# ---------------------------------------------------------------------------

_provider_name = os.environ.get("IMAGE_PROVIDER", "").strip().lower()

if _provider_name == "kling":
    from app.providers.kling_image_provider import KlingImageProvider
    _provider = KlingImageProvider()
elif _provider_name == "wanx":
    from app.providers.wanx_image_provider import WanxImageProvider
    _provider = WanxImageProvider()
elif _provider_name == "minimax":
    from app.providers.minimax_image_provider import MiniMaxImageProvider
    _provider = MiniMaxImageProvider()
elif _provider_name in ("", "mock"):
    _provider = MockImageProvider()
    _provider_name = "mock"
else:
    raise ValueError(
        f"未知的 IMAGE_PROVIDER='{_provider_name}'。"
        "有效值：kling | wanx | minimax | mock。"
        "不设置则默认使用 mock。"
    )


def get_image_generate_provider():
    return _provider


def get_image_generate_service(
    provider=Depends(get_image_generate_provider),
) -> ImageGenerateService:
    return ImageGenerateService(provider=provider)


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


# ---------------------------------------------------------------------------
# GET /image/generate/models
# ---------------------------------------------------------------------------


@router.get(
    "/models",
    summary="列出当前 provider 的可用图片生成模型",
)
async def list_models(request: Request) -> dict:
    """
    返回当前激活的图片生成 provider（由 IMAGE_PROVIDER 环境变量决定）所支持的模型列表。

    字段说明：
    - name: 传给 image_generate_start 的 model 参数值
    - modes: ["t2i"] 仅文生图，["t2i","i2i"] 同时支持图生图/风格迁移
    - default: true 表示不传 model 时使用该模型
    """
    rid, t0 = _ctx(request)
    models_raw: list[dict] = getattr(_provider, "available_models", lambda: [])()
    data = ImageModelsData(
        provider=_provider_name,
        models=models_raw,
    )
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# POST /image/generate/start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    summary="启动图片生成任务（异步，返回 job_id）",
)
async def start_generate(
    body: StartImageRequest,
    request: Request,
    service: ImageGenerateService = Depends(get_image_generate_service),
) -> dict:
    """
    提交图片生成任务，立即返回 job_id + status=queued。

    - prompt 必填
    - style_reference_path 可选，传入则使用图生图/风格迁移模式，保持视觉风格一致
    - model 可选，覆盖服务端默认模型（用 /models 接口查看可用值）
    """
    rid, t0 = _ctx(request)
    data: StartImageData = await service.start_generate(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# GET /image/generate/result/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/result/{job_id}",
    summary="查询图片生成任务结果",
)
async def get_generate_result(
    job_id: str,
    request: Request,
    service: ImageGenerateService = Depends(get_image_generate_service),
    wait_sec: int = Query(
        default=0,
        ge=0,
        le=120,
        description=(
            "Long-poll 等待秒数（0 = 立即返回）。"
            "传入 > 0 时，服务端最多等待 wait_sec 秒直到 job 进入 terminal 状态再返回。"
            "建议值：30。"
        ),
    ),
) -> dict:
    """
    轮询图片生成任务状态。状态机：queued → running → done / failed

    - status=done 时返回 local_image_path 和 image_url
    - job_id 不存在 → 404 NOT_FOUND
    - wait_sec > 0 时启用 long-poll，减少 agent 轮询次数
    """
    rid, t0 = _ctx(request)
    data: ImageResultData = await service.get_result(job_id, wait_sec=wait_sec)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


# ---------------------------------------------------------------------------
# DELETE /image/generate/{job_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{job_id}",
    summary="删除图片生成任务记录",
)
async def delete_generate(
    job_id: str,
    request: Request,
    service: ImageGenerateService = Depends(get_image_generate_service),
) -> dict:
    """删除任务记录（不删除已下载到本地的图片文件）。job_id 不存在 → 404 NOT_FOUND"""
    rid, t0 = _ctx(request)
    data: DeleteImageData = await service.delete_generate(job_id)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
