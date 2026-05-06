"""
Image Generate Service — 业务编排层。

职责：
  - 生成全局唯一 job_id（ig_ 前缀）
  - 调用 Provider 提交 / 查询 / 删除任务
  - 将 domain ImageGenerateJob 转换为 HTTP 响应 schema
  - 处理业务规则（job 不存在时抛 NotFoundError）
  - 不感知 HTTP、不感知 request_id
"""
from __future__ import annotations

import asyncio
import uuid

from app.domain.models import ImageGenerateJob
from app.infra.exceptions import NotFoundError
from app.schemas.image_generate import (
    DeleteImageData,
    ImageResultData,
    StartImageData,
    StartImageRequest,
)

_TERMINAL_STATUSES = {"done", "failed", "partial", "cancelled"}


class ImageGenerateService:
    def __init__(self, provider) -> None:
        self._p = provider

    async def start_generate(self, req: StartImageRequest) -> StartImageData:
        job_id = f"ig_{uuid.uuid4().hex[:12]}"
        job: ImageGenerateJob = await self._p.start_generate(
            job_id=job_id,
            prompt=req.prompt,
            style_reference_path=req.style_reference_path,
            model=req.model,
        )
        return StartImageData(job_id=job.job_id, status=job.status, model=job.model)

    async def get_result(self, job_id: str, wait_sec: int = 0) -> ImageResultData:
        """查询任务状态。

        wait_sec > 0 时启用 long-poll：服务端最多等待 wait_sec 秒，
        每 2 秒检查一次 job 状态，一旦进入 terminal 状态立即返回。
        """
        job: ImageGenerateJob | None = await self._p.get_generate_result(job_id)
        if job is None:
            raise NotFoundError(f"job_id '{job_id}' not found")

        if wait_sec > 0 and job.status not in _TERMINAL_STATUSES:
            deadline = asyncio.get_running_loop().time() + wait_sec
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(2)
                job = await self._p.get_generate_result(job_id)
                if job is None:
                    raise NotFoundError(f"job_id '{job_id}' not found")
                if job.status in _TERMINAL_STATUSES:
                    break

        return ImageResultData(
            job_id=job.job_id,
            status=job.status,
            task_id=job.task_id,
            local_image_path=job.local_image_path,
            image_url=job.image_url,
            manifest_path=job.manifest_path,
            error_message=job.error_message,
        )

    async def delete_generate(self, job_id: str) -> DeleteImageData:
        deleted = await self._p.delete_generate(job_id)
        if not deleted:
            raise NotFoundError(f"job_id '{job_id}' not found")
        return DeleteImageData(job_id=job_id, deleted=True)
