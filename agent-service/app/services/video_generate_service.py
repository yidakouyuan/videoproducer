"""
Video Generate Service — 业务编排层。

职责：
  - 生成全局唯一 job_id（vg_ 前缀）
  - 调用 Provider 提交 / 查询 / 删除任务
  - 将 domain VideoGenerateJob 转换为 HTTP 响应 schema
  - 处理业务规则（job 不存在时抛 NotFoundError）
  - 不感知 HTTP、不感知 request_id
"""
from __future__ import annotations

import uuid

from app.domain.models import VideoGenerateJob
from app.infra.exceptions import NotFoundError
from app.schemas.video_generate import (
    DeleteGenerateData,
    GenerateResultData,
    StartGenerateData,
    StartGenerateRequest,
)


class VideoGenerateService:
    def __init__(self, provider) -> None:
        self._p = provider

    async def start_generate(self, req: StartGenerateRequest) -> StartGenerateData:
        job_id = f"vg_{uuid.uuid4().hex[:12]}"
        job: VideoGenerateJob = await self._p.start_generate(
            job_id=job_id,
            prompt=req.prompt,
            duration=req.duration,
            first_frame_path=req.first_frame_path,
            model=req.model,
        )
        return StartGenerateData(job_id=job.job_id, status=job.status, model=job.model)

    async def get_result(self, job_id: str) -> GenerateResultData:
        job: VideoGenerateJob | None = await self._p.get_generate_result(job_id)
        if job is None:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return GenerateResultData(
            job_id=job.job_id,
            status=job.status,
            task_id=job.task_id,
            local_video_path=job.local_video_path,
            manifest_path=job.manifest_path,
            first_frame_path=job.first_frame_path,
            model=job.model,
            error_message=job.error_message,
        )

    async def delete_generate(self, job_id: str) -> DeleteGenerateData:
        deleted = await self._p.delete_generate(job_id)
        if not deleted:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return DeleteGenerateData(job_id=job_id, deleted=True)
