"""
Stats Service — 业务编排层。
"""
from __future__ import annotations

from typing import Optional

from app.infra import stats_db
from app.schemas.stats import (
    StatsQueryData,
    StatsWriteData,
    StatsWriteRequest,
    StatsWriteResultItem,
    VideoStatsItem,
)


class StatsService:

    async def write(self, req: StatsWriteRequest) -> StatsWriteData:
        results = []
        for item in req.items:
            video_id, snapshot_id = stats_db.write_snapshot(item.model_dump())
            results.append(StatsWriteResultItem(video_id=video_id, snapshot_id=snapshot_id))
        return StatsWriteData(written=len(results), results=results)

    async def query(
        self,
        platform: Optional[str],
        title: Optional[str],
        publish_since: Optional[str],
        publish_until: Optional[str],
        snapshot_since: Optional[str],
        snapshot_until: Optional[str],
        latest_only: bool,
        limit: int,
        offset: int,
    ) -> StatsQueryData:
        total, rows = stats_db.query_stats(
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
        return StatsQueryData(
            total_count=total,
            limit=limit,
            offset=offset,
            items=[VideoStatsItem(**r) for r in rows],
        )
