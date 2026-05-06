"""
视频数据统计路由层。

对外暴露：
  POST /stats/write   写入快照（支持批量）
  GET  /stats/query   分页查询快照
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request

from app.infra.response import ok
from app.schemas.stats import StatsQueryData, StatsWriteData, StatsWriteRequest
from app.services.stats_service import StatsService

router = APIRouter(prefix="/stats", tags=["stats"])
_service = StatsService()


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


@router.post(
    "/write",
    summary="写入视频数据快照（支持批量）",
)
async def write_stats(body: StatsWriteRequest, request: Request) -> dict:
    """
    写入一条或多条视频指标快照。每次调用均新增快照，不覆盖历史。

    - items 为列表，单条也需包装：{"items": [{...}]}
    - video_id 由后端根据 platform + title + publish_time 自动生成
    - snapshot_at 由后端自动填充为当前 UTC 时间
    """
    rid, t0 = _ctx(request)
    data: StatsWriteData = await _service.write(body)
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))


@router.get(
    "/query",
    summary="分页查询视频数据快照",
)
async def query_stats(
    request: Request,
    platform: Optional[str] = Query(None, description="按平台过滤，如 douyin"),
    title: Optional[str] = Query(None, description="标题模糊匹配"),
    publish_since: Optional[str] = Query(None, description="发布时间起点，ISO 8601"),
    publish_until: Optional[str] = Query(None, description="发布时间终点，ISO 8601"),
    snapshot_since: Optional[str] = Query(None, description="快照时间起点，ISO 8601"),
    snapshot_until: Optional[str] = Query(None, description="快照时间终点，ISO 8601"),
    latest_only: bool = Query(False, description="true 时每个视频只返回最新快照"),
    limit: int = Query(50, ge=1, le=500, description="每页条数，默认 50，最大 500"),
    offset: int = Query(0, ge=0, description="跳过条数，默认 0"),
) -> dict:
    """
    按条件分页查询视频指标快照，结果按 snapshot_at 倒序排列。

    响应包含 total_count 供判断是否需要翻页。
    """
    rid, t0 = _ctx(request)
    data: StatsQueryData = await _service.query(
        platform=platform,
        title=title,
        publish_since=publish_since,
        publish_until=publish_until,
        snapshot_since=snapshot_since,
        snapshot_until=snapshot_until,
        latest_only=latest_only,
        limit=limit,
        offset=offset,
    )
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
