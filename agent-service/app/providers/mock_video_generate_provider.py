"""
Mock Video Generate Provider。

Job 状态机：
  start_generate 调用时：创建 job，状态设为 "queued"。
  get_generate_result 调用时：
    - 距创建 < 2 秒 → "running"
    - 否则         → "done" + mock 路径

替换成真实实现时：
  1. 在 routes/video_generate.py 的 get_video_generate_provider() 里换成 MiniMaxVideoProvider
  2. 本文件保留，供 USE_REAL_MINIMAX 未设置时使用
"""
from __future__ import annotations

import time
from typing import Optional

from app.domain.models import VideoGenerateJob

_job_store: dict[str, VideoGenerateJob] = {}
_MOCK_DELAY_SEC: float = 2.0


class MockVideoGenerateProvider:

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        duration: int,
        first_frame_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> VideoGenerateJob:
        job = VideoGenerateJob(
            job_id=job_id,
            prompt=prompt,
            status="queued",
            duration=duration,
            first_frame_path=first_frame_path,
            model=model or "mock",
        )
        _job_store[job_id] = job
        return job

    async def get_generate_result(self, job_id: str) -> Optional[VideoGenerateJob]:
        job = _job_store.get(job_id)
        if job is None:
            return None
        elapsed = time.time() - job.created_at
        if elapsed < _MOCK_DELAY_SEC:
            job.status = "running"
        else:
            job.status = "done"
            job.task_id = "mock_task_000"
            job.local_video_path = f"C:/Users/Administrator/AppData/Local/Temp/openclaw/uploads/minimax_mock_{job_id}.mp4"
            job.manifest_path = f"C:/Users/Administrator/AppData/Local/Temp/openclaw/uploads/minimax_mock_{job_id}.json"
        return job

    async def delete_generate(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
