"""
Mock Video Analysis Provider。

Job 状态机（Mock 简化版）：
  start_analysis 调用时：创建 job，状态设为 "queued"。
  get_analysis_result 调用时：
    - 若距创建 < 2 秒 → 返回 "running"（模拟分析进行中）
    - 否则           → 返回 "done" + mock VideoBreakdown（模拟完成）
  这样客户端在 start 后立即轮询会看到 running → done 的状态迁移。

替换成真实实现时：
  1. 新建 app/providers/gemini_video_analysis_provider.py
  2. start_analysis → 调 Gemini Files API 上传 + generateContent
  3. get_analysis_result → 轮询 Gemini operation / 查本地 DB
  4. delete_analysis → 删除 Gemini 文件 + 本地记录
  5. 在 routes/video_analyze.py 的 get_video_analysis_provider() 里换实例
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from app.domain.models import (
    ShotSegment,
    VideoAnalysisJob,
    VideoBreakdown,
)

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, VideoAnalysisJob] = {}

# Mock 分析延迟（秒）：距创建不足此时长时返回 "running"
_MOCK_ANALYSIS_DELAY_SEC: float = 2.0

# ---------------------------------------------------------------------------
# Mock VideoBreakdown（对应接口文档示例）
# ---------------------------------------------------------------------------

_MOCK_BREAKDOWN = VideoBreakdown(
    structure={
        "hook": "开场3秒强钩子",
        "body": ["路线介绍", "避坑点"],
        "cta": "结尾引导收藏",
    },
    editing_style={
        "pace": "fast",
        "cut_frequency": "high",
        "transition_patterns": ["硬切", "推拉变焦"],
        "caption_style": "大字标题+关键词高亮",
        "effects": ["whoosh音效"],
    },
    shots=[
        ShotSegment(
            start_sec=0.0,
            end_sec=2.8,
            shot_type="hook",
            visual="航拍+快速蒙太奇",
            text_overlay="清迈3天2夜这样玩",
            camera_motion="zoom-in",
            transition_in="cut",
            transition_out="cut",
            notes="节奏密集",
        ),
        ShotSegment(
            start_sec=2.8,
            end_sec=8.5,
            shot_type="intro",
            visual="咖啡馆室内空镜",
            text_overlay="Day1 必去清迈古城",
            camera_motion="pan",
            transition_in="cut",
            transition_out="fade",
            notes="过渡到主体内容",
        ),
        ShotSegment(
            start_sec=8.5,
            end_sec=35.0,
            shot_type="body",
            visual="多景点快剪合集",
            text_overlay=None,
            camera_motion="handheld",
            transition_in="cut",
            transition_out="cut",
            notes="信息密度高",
        ),
    ],
    audio={
        "bgm_style": {
            "mood": "upbeat",
            "genre": "electronic",
            "bpm_estimate": 118,
        },
        "audio_mix": {
            "music_dominant": True,
            "voiceover": True,
            "sfx": ["whoosh"],
        },
    },
    claims=[
        {"type": "template", "text": "典型旅游清单类爆款模板"},
    ],
)


# ---------------------------------------------------------------------------
# Mock Provider 实现
# ---------------------------------------------------------------------------


class MockVideoAnalysisProvider:
    """结构严格对齐 VideoAnalysisProvider Protocol。"""

    async def start_analysis(
        self,
        job_id: str,
        media_id: str,
        input_url: Optional[str],
        analysis_profile: str,
        lang: str,
        output_schema_version: str,
    ) -> VideoAnalysisJob:
        job = VideoAnalysisJob(
            job_id=job_id,
            media_id=media_id,
            input_url=input_url,
            analysis_profile=analysis_profile,
            lang=lang,
            output_schema_version=output_schema_version,
            status="queued",
        )
        _job_store[job_id] = job
        return job

    async def get_analysis_result(self, job_id: str) -> Optional[VideoAnalysisJob]:
        job = _job_store.get(job_id)
        if job is None:
            return None

        elapsed = time.time() - job.created_at

        if elapsed < _MOCK_ANALYSIS_DELAY_SEC:
            # 模拟分析进行中
            job.status = "running"
        else:
            # 模拟分析完成
            job.status = "done"
            job.source_quality = "high"
            job.analysis_confidence = 0.78
            job.video_breakdown = _MOCK_BREAKDOWN

        return job

    async def delete_analysis(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
