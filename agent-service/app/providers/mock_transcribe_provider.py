"""
Mock Transcribe Provider。

Job 状态机（与视频分析 Mock 一致）：
  start_transcribe 调用时：创建 job，状态设为 "queued"。
  get_transcribe_result 调用时：
    - 若距创建 < 2 秒 → 返回 "running"（模拟转写进行中）
    - 否则           → 返回 "done" + mock transcript / highlights

替换成真实实现时：
  1. 新建 app/providers/openai_transcribe_provider.py
  2. start_transcribe → 提取音频 → 调 OpenAI Whisper API → 存 DB
  3. get_transcribe_result → 查 DB 状态
  4. delete_transcribe → 删 DB 记录 + highlights 缓存
  5. 在 routes/transcribe.py 的 get_transcribe_provider() 里换实例
"""
from __future__ import annotations

import time
from typing import Optional

from app.domain.models import TranscribeJob, TranscriptHighlight

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, TranscribeJob] = {}
_MOCK_DELAY_SEC: float = 2.0

# ---------------------------------------------------------------------------
# Mock 转写数据（对应接口文档示例）
# ---------------------------------------------------------------------------

_MOCK_TRANSCRIPT = (
    "大家好，今天给大家分享清迈三天两夜的完整攻略。"
    "第一天我们先去清迈古城，那里有很多好看的寺庙。"
    "重点推荐：清迈咖啡馆一定要避坑，别去游客区，要去本地人常去的那几家。"
    "第二天可以去素帖山，山顶俯瞰整个清迈，超级好拍。"
    "最后一天逛夜市，周六夜市是性价比最高的，记得砍价。"
)

_MOCK_HIGHLIGHTS = [
    TranscriptHighlight(start_sec=12.3, end_sec=16.8, text="重点：清迈咖啡馆避坑"),
    TranscriptHighlight(start_sec=24.0, end_sec=29.5, text="素帖山俯瞰清迈，超级好拍"),
    TranscriptHighlight(start_sec=38.1, end_sec=42.0, text="周六夜市性价比最高，记得砍价"),
]

_MOCK_FULL_HIGHLIGHTS = _MOCK_HIGHLIGHTS  # full 模式复用，真实实现可返回更密集的段落


# ---------------------------------------------------------------------------
# Mock Provider 实现
# ---------------------------------------------------------------------------


class MockTranscribeProvider:
    """结构严格对齐 TranscribeProvider Protocol。"""

    async def start_transcribe(
        self,
        job_id: str,
        media_id: str,
        provider_name: str,
        lang: str,
        mode: str,
    ) -> TranscribeJob:
        job = TranscribeJob(
            job_id=job_id,
            media_id=media_id,
            provider_name=provider_name,
            lang=lang,
            mode=mode,
            status="queued",
        )
        _job_store[job_id] = job
        return job

    async def get_transcribe_result(self, job_id: str) -> Optional[TranscribeJob]:
        job = _job_store.get(job_id)
        if job is None:
            return None

        elapsed = time.time() - job.created_at

        if elapsed < _MOCK_DELAY_SEC:
            job.status = "running"
        else:
            job.status = "done"
            job.transcript = _MOCK_TRANSCRIPT
            job.highlights = (
                _MOCK_FULL_HIGHLIGHTS if job.mode == "full" else _MOCK_HIGHLIGHTS
            )
            job.confidence = 0.85

        return job

    async def delete_transcribe(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
