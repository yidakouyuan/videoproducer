"""
图片生成模块请求与响应 Schema。

对应接口：
  GET    /image/generate/models
  POST   /image/generate/start
  GET    /image/generate/result/{job_id}
  DELETE /image/generate/{job_id}
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# GET /image/generate/models
# ---------------------------------------------------------------------------


class ImageModelInfo(BaseModel):
    name: str
    modes: list[str]           # ["t2i"] | ["t2i", "i2i"]
    description: Optional[str] = None
    default: bool = False


class ImageModelsData(BaseModel):
    provider: str
    models: list[ImageModelInfo]


# ---------------------------------------------------------------------------
# POST /image/generate/start
# ---------------------------------------------------------------------------


class StartImageRequest(BaseModel):
    prompt: str = Field(..., description="图片生成文字描述")
    style_reference_path: Optional[str] = Field(
        None,
        description=(
            "风格参考图：本地文件路径或公网 URL。传入则使用图生图/风格迁移模式，"
            "让生成图片与参考图保持视觉风格一致；不传则为纯文生图（t2i）。"
        ),
    )
    model: Optional[str] = Field(
        None,
        description="模型名称，覆盖服务端默认值。不传则使用环境变量配置的默认模型。",
    )


class StartImageData(BaseModel):
    job_id: str
    status: str
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /image/generate/result/{job_id}
# ---------------------------------------------------------------------------


class ImageResultData(BaseModel):
    job_id: str
    status: str
    task_id: Optional[str] = None
    local_image_path: Optional[str] = None
    image_url: Optional[str] = None
    manifest_path: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# DELETE /image/generate/{job_id}
# ---------------------------------------------------------------------------


class DeleteImageData(BaseModel):
    job_id: str
    deleted: bool
