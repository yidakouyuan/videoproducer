"""
视频分析模块请求与响应 Schema。

对应接口：
  POST   /video/analyze/start
  GET    /video/analyze/result/{job_id}
  DELETE /video/analyze/{job_id}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# POST /video/analyze/start
# ---------------------------------------------------------------------------


class StartAnalysisRequest(BaseModel):
    media_id: str = Field(..., description="已缓存视频的 media_id")
    input_url: Optional[str] = Field(
        None, description="可选：直接传入视频 URL（跳过 media_id 查询）"
    )
    analysis_profile: str = Field(
        "travel", description="分析配置，如 travel / food / fashion"
    )
    lang: str = Field("zh", description="语言代码")
    output_schema_version: str = Field("v1", description="输出 schema 版本")


class StartAnalysisData(BaseModel):
    """POST /video/analyze/start 的 data 字段。"""

    job_id: str
    status: str  # 固定为 "queued"


# ---------------------------------------------------------------------------
# GET /video/analyze/result/{job_id}
# ---------------------------------------------------------------------------


class ShotSegmentSchema(BaseModel):
    start_sec: float
    end_sec: float
    shot_type: Optional[str] = None
    visual: Optional[str] = None
    text_overlay: Optional[str] = None
    camera_motion: Optional[str] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
    notes: Optional[str] = None


class VideoBreakdownSchema(BaseModel):
    """对应接口文档中 video_breakdown 字段，严格按文档结构。"""

    structure: Dict[str, Any] = {}
    editing_style: Dict[str, Any] = {}
    shots: List[ShotSegmentSchema] = []
    audio: Dict[str, Any] = {}
    claims: List[Dict[str, Any]] = []
    summary: str = ""  # 100-150 字 quick-skim 概述，给 writer 渐进披露用


class AnalysisResultData(BaseModel):
    """GET /video/analyze/result/{job_id} 的 data 字段。"""

    job_id: str
    status: str
    source_quality: Optional[str] = None
    analysis_confidence: Optional[float] = None
    video_breakdown: Optional[VideoBreakdownSchema] = None
    # When status == "failed", carries the underlying exception type + message
    # captured by GeminiVideoAnalysisProvider's except blocks. Without this
    # field the failure reason is silently dropped at serialization, leaving
    # the supervisor agent unable to distinguish quota / rate-limit /
    # content-policy / network failures.
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# DELETE /video/analyze/{job_id}
# ---------------------------------------------------------------------------


class DeleteAnalysisData(BaseModel):
    """DELETE /video/analyze/{job_id} 的 data 字段。"""

    job_id: str
    deleted: bool
