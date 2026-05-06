"""
Transcribe Service — 业务编排层。

职责：
  - 生成全局唯一 job_id（tr_ 前缀）
  - 调用 TranscribeProvider 提交 / 查询 / 删除任务
  - 将 domain TranscribeJob 转换为 HTTP 响应 schema
  - 处理业务规则（job 不存在时抛 NotFoundError）
  - 不感知 HTTP、不感知 request_id
"""
from __future__ import annotations

import uuid

from app.domain.models import TranscribeJob, TranscriptHighlight
from app.infra.exceptions import NotFoundError
from app.providers.base import TranscribeProvider
from app.schemas.transcribe import (
    DeleteTranscribeData,
    StartTranscribeData,
    StartTranscribeRequest,
    TranscribeResultData,
    TranscriptHighlightSchema,
)


class TranscribeService:
    def __init__(self, provider: TranscribeProvider) -> None:
        self._p = provider

    # ------------------------------------------------------------------
    # POST /transcribe/start
    # ------------------------------------------------------------------

    async def start_transcribe(self, req: StartTranscribeRequest) -> StartTranscribeData:
        job_id = f"tr_{uuid.uuid4().hex[:12]}"
        job: TranscribeJob = await self._p.start_transcribe(
            job_id=job_id,
            media_id=req.media_id,
            provider_name=req.provider,
            lang=req.lang,
            mode=req.mode,
        )
        return StartTranscribeData(job_id=job.job_id, status=job.status)

    # ------------------------------------------------------------------
    # GET /transcribe/result/{job_id}
    # ------------------------------------------------------------------

    async def get_result(self, job_id: str) -> TranscribeResultData:
        job: TranscribeJob | None = await self._p.get_transcribe_result(job_id)
        if job is None:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return _job_to_result_data(job)

    # ------------------------------------------------------------------
    # DELETE /transcribe/{job_id}
    # ------------------------------------------------------------------

    async def delete_transcribe(self, job_id: str) -> DeleteTranscribeData:
        deleted = await self._p.delete_transcribe(job_id)
        if not deleted:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return DeleteTranscribeData(job_id=job_id, deleted=True)


# ---------------------------------------------------------------------------
# 私有：domain → schema 转换
# ---------------------------------------------------------------------------


def _job_to_result_data(job: TranscribeJob) -> TranscribeResultData:
    return TranscribeResultData(
        job_id=job.job_id,
        status=job.status,
        transcript=job.transcript,
        highlights=[_highlight_schema(h) for h in job.highlights],
        confidence=job.confidence,
    )


def _highlight_schema(h: TranscriptHighlight) -> TranscriptHighlightSchema:
    return TranscriptHighlightSchema(
        start_sec=h.start_sec,
        end_sec=h.end_sec,
        text=h.text,
    )
