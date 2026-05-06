"""
视频生成模块请求与响应 Schema。

对应接口：
  POST   /video/generate/start
  GET    /video/generate/result/{job_id}
  DELETE /video/generate/{job_id}
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /video/generate/start
# ---------------------------------------------------------------------------


class StartGenerateRequest(BaseModel):
    prompt: str = Field(..., description="视频生成文字描述")
    duration: int = Field(6, description="视频时长（秒），默认 6")
    first_frame_path: Optional[str] = Field(
        None,
        description=(
            "首帧参考图：本地文件路径或公网 URL。传入则使用 i2v（图生视频）模式，"
            "让生成视频以这张图作为第一帧；不传则为纯文生视频（t2v）。"
        ),
    )
    model: Optional[str] = Field(
        None,
        description="模型名称，覆盖服务端默认值。不传则使用环境变量配置的默认模型。",
    )


class StartGenerateData(BaseModel):
    job_id: str
    status: str
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /video/generate/result/{job_id}
# ---------------------------------------------------------------------------


class GenerateResultData(BaseModel):
    job_id: str
    status: str
    task_id: Optional[str] = None
    local_video_path: Optional[str] = None
    manifest_path: Optional[str] = None
    first_frame_path: Optional[str] = None    # 提交时传入的首帧（用于排查）
    model: Optional[str] = None               # 实际使用的模型名
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# DELETE /video/generate/{job_id}
# ---------------------------------------------------------------------------


class DeleteGenerateData(BaseModel):
    job_id: str
    deleted: bool
