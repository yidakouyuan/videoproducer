"""
视频数据统计模块请求与响应 Schema。

对应接口：
  POST /stats/write
  GET  /stats/query
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /stats/write
# ---------------------------------------------------------------------------


class VideoStatsWriteItem(BaseModel):
    platform: str = Field("douyin", description="平台，如 douyin")
    title: str = Field(..., description="视频标题")
    publish_time: str = Field(..., description="发布时间，ISO 8601，如 2026-03-10T12:00:00Z")
    duration_sec: Optional[float] = Field(None, description="视频时长（秒）")
    play_count: Optional[int] = Field(None, description="播放量")
    like_count: Optional[int] = Field(None, description="点赞量")
    comment_count: Optional[int] = Field(None, description="评论量")
    share_count: Optional[int] = Field(None, description="分享量")
    collect_count: Optional[int] = Field(None, description="收藏量")
    danmaku_count: Optional[int] = Field(None, description="弹幕量")
    completion_rate: Optional[float] = Field(None, description="完播率，0.0~1.0")
    two_sec_exit_rate: Optional[float] = Field(None, description="2s 跳出率，0.0~1.0")
    follower_gain: Optional[int] = Field(None, description="吸粉量")
    follower_loss: Optional[int] = Field(None, description="脱粉量")
    fan_play_ratio: Optional[float] = Field(None, description="粉丝播放占比，0.0~1.0")
    extra: Optional[Dict[str, Any]] = Field(None, description="预留扩展字段")


class StatsWriteRequest(BaseModel):
    items: List[VideoStatsWriteItem] = Field(..., description="快照列表，单条也用列表包装")


class StatsWriteResultItem(BaseModel):
    video_id: str
    snapshot_id: int


class StatsWriteData(BaseModel):
    written: int
    results: List[StatsWriteResultItem]


# ---------------------------------------------------------------------------
# GET /stats/query
# ---------------------------------------------------------------------------


class VideoStatsItem(BaseModel):
    video_id: str
    platform: str
    title: str
    publish_time: str
    duration_sec: Optional[float] = None
    snapshot_id: int
    snapshot_at: str
    play_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    share_count: Optional[int] = None
    collect_count: Optional[int] = None
    danmaku_count: Optional[int] = None
    completion_rate: Optional[float] = None
    two_sec_exit_rate: Optional[float] = None
    follower_gain: Optional[int] = None
    follower_loss: Optional[int] = None
    fan_play_ratio: Optional[float] = None
    extra: Optional[str] = None


class StatsQueryData(BaseModel):
    total_count: int
    limit: int
    offset: int
    items: List[VideoStatsItem]
