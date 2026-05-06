"""
转写模块请求与响应 Schema。

对应接口：
  POST   /transcribe/start
  GET    /transcribe/result/{job_id}
  DELETE /transcribe/{job_id}
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# POST /transcribe/start
# ---------------------------------------------------------------------------


class StartTranscribeRequest(BaseModel):
    media_id: str = Field(..., description="已缓存视频的 media_id")
    provider: str = Field(
        "openai",
        description="转写 provider，如 openai / gemini",
    )
    lang: str = Field("zh", description="目标语言代码")
    mode: Literal["highlights", "full"] = Field(
        "highlights",
        description="highlights=只返回关键片段；full=完整转写",
    )


class StartTranscribeData(BaseModel):
    """POST /transcribe/start 的 data 字段。"""

    job_id: str
    status: str  # 固定为 "queued"


# ---------------------------------------------------------------------------
# GET /transcribe/result/{job_id}
# ---------------------------------------------------------------------------


class TranscriptHighlightSchema(BaseModel):
    start_sec: float
    end_sec: float
    text: str


class TranscribeResultData(BaseModel):
    """GET /transcribe/result/{job_id} 的 data 字段，严格对齐接口文档。"""

    job_id: str
    status: str
    transcript: Optional[str] = None
    highlights: List[TranscriptHighlightSchema] = []
    confidence: Optional[float] = None
    # When status == "failed", carries the underlying exception type + message
    # captured by GeminiTranscribeProvider's except blocks. Without this field
    # the failure reason is silently dropped at serialization.
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# DELETE /transcribe/{job_id}
# ---------------------------------------------------------------------------


class DeleteTranscribeData(BaseModel):
    """DELETE /transcribe/{job_id} 的 data 字段。"""

    job_id: str
    deleted: bool
