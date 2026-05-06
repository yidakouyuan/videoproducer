"""
媒体模块请求与响应 Schema。

对应接口：
  POST   /media/resolve_video
  POST   /media/fetch_video
  DELETE /media/{media_id}
  POST   /media/cleanup
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# POST /media/resolve_video
# ---------------------------------------------------------------------------


class DouyinSourceRefRequest(BaseModel):
    """抖音平台内容引用（输入侧），aweme_id / share_url 是抖音特有字段。"""

    platform: Literal["douyin"] = "douyin"
    aweme_id: str = Field(..., description="抖音视频 ID，即 aweme_id")
    share_url: str = Field(..., description="抖音分享链接")


class ResolveVideoRequest(BaseModel):
    source_ref: DouyinSourceRefRequest


class ResolvedVideoData(BaseModel):
    """POST /media/resolve_video 成功时的 data 字段，严格对齐接口文档。"""

    platform: str
    aweme_id: str
    share_url: str
    video_url: str
    downloadable: bool


# ---------------------------------------------------------------------------
# POST /media/fetch_video
# ---------------------------------------------------------------------------


class ResolvedVideoRefRequest(BaseModel):
    """fetch_video 输入中的 resolved_video_ref。

    结构与 ResolvedVideoData 对称，是调用方将 resolve 结果原样回传。
    """

    platform: str
    aweme_id: str
    share_url: str
    video_url: str
    downloadable: bool


class FetchVideoRequest(BaseModel):
    resolved_video_ref: ResolvedVideoRefRequest


class FetchedVideoData(BaseModel):
    """POST /media/fetch_video 成功时的 data 字段。"""

    media_id: str
    platform: str
    aweme_id: str
    share_url: str
    local_video_path: Optional[str] = None
    object_url: Optional[str] = None
    duration_sec: Optional[float] = None


# ---------------------------------------------------------------------------
# DELETE /media/{media_id}
# ---------------------------------------------------------------------------


class DeleteMediaData(BaseModel):
    """DELETE /media/{media_id} 的 data 字段。"""

    media_id: str
    deleted: bool
    deleted_local_file: bool
    deleted_object_file: bool


# ---------------------------------------------------------------------------
# POST /media/cleanup
# ---------------------------------------------------------------------------


class CleanupRequest(BaseModel):
    older_than_days: Optional[int] = Field(None, ge=1, description="清理 N 天前的媒体")
    only_unreferenced: bool = Field(True, description="只清理未被引用的媒体")
    limit: int = Field(100, ge=1, le=1000, description="单次最多处理数量")
    dry_run: bool = Field(True, description="True 时只预览，不真正删除")


class CleanupCandidate(BaseModel):
    media_id: str
    local_video_path: Optional[str] = None
    size_bytes: Optional[int] = None


class CleanupData(BaseModel):
    """POST /media/cleanup 的 data 字段。"""

    dry_run: bool
    matched_count: int
    deleted_count: int
    candidates: List[CleanupCandidate] = []
