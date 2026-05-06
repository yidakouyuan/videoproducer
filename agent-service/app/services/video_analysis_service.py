"""
Video Analysis Service — 业务编排层。

职责：
  - 生成全局唯一 job_id（va_ 前缀）
  - 调用 VideoAnalysisProvider 提交 / 查询 / 删除任务
  - 将 domain VideoAnalysisJob 转换为 HTTP 响应 schema
  - 处理业务规则（job 不存在时抛 NotFoundError）
  - 不感知 HTTP、不感知 request_id
"""
from __future__ import annotations

import uuid

from app.domain.models import ShotSegment, VideoAnalysisJob, VideoBreakdown
from app.infra.exceptions import NotFoundError
from app.providers.base import VideoAnalysisProvider
from app.schemas.video_analyze import (
    AnalysisResultData,
    DeleteAnalysisData,
    ShotSegmentSchema,
    StartAnalysisData,
    StartAnalysisRequest,
    VideoBreakdownSchema,
)


class VideoAnalysisService:
    def __init__(self, provider: VideoAnalysisProvider) -> None:
        self._p = provider

    # ------------------------------------------------------------------
    # POST /video/analyze/start
    # ------------------------------------------------------------------

    async def start_analysis(self, req: StartAnalysisRequest) -> StartAnalysisData:
        job_id = f"va_{uuid.uuid4().hex[:12]}"
        job: VideoAnalysisJob = await self._p.start_analysis(
            job_id=job_id,
            media_id=req.media_id,
            input_url=req.input_url,
            analysis_profile=req.analysis_profile,
            lang=req.lang,
            output_schema_version=req.output_schema_version,
        )
        return StartAnalysisData(job_id=job.job_id, status=job.status)

    # ------------------------------------------------------------------
    # GET /video/analyze/result/{job_id}
    # ------------------------------------------------------------------

    async def get_result(self, job_id: str) -> AnalysisResultData:
        job: VideoAnalysisJob | None = await self._p.get_analysis_result(job_id)
        if job is None:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return _job_to_result_data(job)

    # ------------------------------------------------------------------
    # DELETE /video/analyze/{job_id}
    # ------------------------------------------------------------------

    async def delete_analysis(self, job_id: str) -> DeleteAnalysisData:
        deleted = await self._p.delete_analysis(job_id)
        if not deleted:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return DeleteAnalysisData(job_id=job_id, deleted=True)


# ---------------------------------------------------------------------------
# 私有：domain → schema 转换
# ---------------------------------------------------------------------------


def _job_to_result_data(job: VideoAnalysisJob) -> AnalysisResultData:
    return AnalysisResultData(
        job_id=job.job_id,
        status=job.status,
        source_quality=job.source_quality,
        analysis_confidence=job.analysis_confidence,
        video_breakdown=_breakdown_schema(job.video_breakdown),
    )


def _breakdown_schema(bd: VideoBreakdown | None) -> VideoBreakdownSchema | None:
    if bd is None:
        return None
    return VideoBreakdownSchema(
        structure=bd.structure,
        editing_style=bd.editing_style,
        shots=[_shot_schema(s) for s in bd.shots],
        audio=bd.audio,
        claims=bd.claims,
    )


def _shot_schema(s: ShotSegment) -> ShotSegmentSchema:
    return ShotSegmentSchema(
        start_sec=s.start_sec,
        end_sec=s.end_sec,
        shot_type=s.shot_type,
        visual=s.visual,
        text_overlay=s.text_overlay,
        camera_motion=s.camera_motion,
        transition_in=s.transition_in,
        transition_out=s.transition_out,
        notes=s.notes,
    )
