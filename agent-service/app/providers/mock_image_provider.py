"""
Mock Image Generate Provider。

Job 状态机：
  start_generate 调用时：创建 job，状态设为 "queued"。
  get_generate_result 调用时：
    - 距创建 < 2 秒 → "running"
    - 否则         → "done" + mock 路径
"""
from __future__ import annotations

import time
from typing import Optional

from app.domain.models import ImageGenerateJob

_job_store: dict[str, ImageGenerateJob] = {}
_MOCK_DELAY_SEC: float = 2.0

AVAILABLE_MODELS = [
    {"name": "mock", "modes": ["t2i", "i2i"], "default": True,
     "description": "Mock provider — 无需 API，立即返回假路径"},
]


class MockImageProvider:

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        style_reference_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ImageGenerateJob:
        job = ImageGenerateJob(
            job_id=job_id,
            prompt=prompt,
            status="queued",
            style_reference_path=style_reference_path,
            model=model or "mock",
        )
        _job_store[job_id] = job
        return job

    async def get_generate_result(self, job_id: str) -> Optional[ImageGenerateJob]:
        job = _job_store.get(job_id)
        if job is None:
            return None
        elapsed = time.time() - job.created_at
        if elapsed < _MOCK_DELAY_SEC:
            job.status = "running"
        else:
            job.status = "done"
            job.task_id = "mock_img_task_000"
            job.local_image_path = f"./data/uploads/mock_{job_id}.jpg"
            job.manifest_path = f"./data/uploads/mock_{job_id}.json"
        return job

    async def delete_generate(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True

    @staticmethod
    def available_models() -> list[dict]:
        return AVAILABLE_MODELS
