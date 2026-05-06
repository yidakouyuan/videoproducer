"""
Gemini 视频分析 Provider（真实实现）。

流程：
  start_analysis  → 创建 job（queued）→ 启动 asyncio 后台任务
  后台任务         → 上传视频到 Gemini Files API
                  → 等待文件 ACTIVE
                  → generateContent + 结构化 JSON Prompt
                  → 解析 → 写入 job（done / failed）
  get_analysis_result → 直接读 job 内存状态

环境变量（在 .env 中配置）：
  GEMINI_API_KEY       必填，Google AI Studio 的 API Key
  GEMINI_MODEL         可选，默认 gemini-2.0-flash
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

from google import genai
from google.genai import types

from app.domain.models import (
    ShotSegment,
    VideoAnalysisJob,
    VideoBreakdown,
)
from app.infra.exceptions import NotFoundError, ProviderError

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, VideoAnalysisJob] = {}

# ---------------------------------------------------------------------------
# 分析 Prompt 模板
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT = """\
请对这段短视频进行结构化分析，严格以 JSON 格式输出，不要输出任何其他内容。
重要：输出必须是标准 JSON，绝对不允许包含任何注释（不允许 // 或 /* */ 形式的注释）。

JSON 结构如下（字段含义见注释，注释不需要出现在输出中）：
{
  "structure": {
    "hook": "开场钩子描述（1~2句话）",
    "body": ["主体段落1", "主体段落2"],
    "cta": "结尾 CTA 描述"
  },
  "editing_style": {
    "pace": "slow | medium | fast",
    "cut_frequency": "low | medium | high",
    "transition_patterns": ["转场方式1", "转场方式2"],
    "caption_style": "字幕风格描述",
    "effects": ["特效1", "特效2"]
  },
  "shots": [
    {
      "start_sec": 0.0,
      "end_sec": 3.5,
      "shot_type": "hook | intro | body | cta | transition | other",
      "visual": "画面内容描述",
      "text_overlay": "画面上的文字（若无则为 null）",
      "camera_motion": "static | pan | tilt | zoom-in | zoom-out | handheld | other",
      "transition_in": "cut | fade | dissolve | wipe | other",
      "transition_out": "cut | fade | dissolve | wipe | other",
      "notes": "补充说明（可为 null）"
    }
  ],
  "audio": {
    "bgm_style": {
      "mood": "背景音乐情绪",
      "genre": "音乐流派",
      "bpm_estimate": 120
    },
    "audio_mix": {
      "music_dominant": true,
      "voiceover": false,
      "sfx": ["音效1"]
    }
  },
  "claims": [
    {"type": "template | insight | trend | other", "text": "描述"}
  ],
  "summary": "100-150 个中文字的视频整体概述：开场钩子 + 主体内容方向 + 视频卖点/给观众的承诺。要让读者一句话就能判断这条素材是否切题。**不要复述步骤细节**（细节已经在 structure.body 里），保持单段、信息密度高、不分行。",
  "source_quality": "high | medium | low",
  "analysis_confidence": 0.85
}

分析语言：{lang}
分析重点（analysis_profile）：{profile}

⚠️ summary 字段是给下游 writer 做 quick-skim 的入口——它会基于 summary 决定是否进一步加载完整的 video_breakdown 与 transcript。所以 summary 必须独立成义、覆盖钩子+主体+卖点三个维度，不能和 structure.hook 重复。
"""

_PROFILE_HINTS = {
    "travel": "旅游类短视频，关注路线规划、地点展示、避坑提示、预算分享等内容结构",
    "food": "美食类短视频，关注食材展示、制作步骤、口感描述、餐厅探店等内容结构",
    "vlog": "日常 vlog，关注生活记录、情感表达、场景切换节奏等内容结构",
    "product": "商品/带货类，关注卖点展示、价格锚点、用户痛点、购买引导等内容结构",
    "default": "通用短视频，关注内容结构、视觉表达、音频配合、受众吸引力",
}


def _build_prompt(lang: str, profile: str) -> str:
    hint = _PROFILE_HINTS.get(profile, _PROFILE_HINTS["default"])
    return _ANALYSIS_PROMPT.replace("{lang}", lang).replace("{profile}", hint)


# ---------------------------------------------------------------------------
# 结果解析
# ---------------------------------------------------------------------------


def _strip_json_comments(text: str) -> str:
    """去掉 JSON 中的 // 单行注释（Gemini 有时会在 JSON 里加注释）。"""
    import re
    # 去掉字符串之外的 // 注释（简单实现，覆盖主要场景）
    result = re.sub(r'(?<!["\w])//[^\n]*', '', text)
    return result


def _parse_breakdown(raw: str) -> tuple[VideoBreakdown, float, str]:
    """
    从 Gemini 返回的文本中提取 JSON，解析为 VideoBreakdown。
    返回 (breakdown, confidence, source_quality)。
    """
    # 去掉 markdown 代码块
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行（```json）和末行（```）
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])

    # 去掉 // 注释
    text = _strip_json_comments(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError(f"Gemini 返回的 JSON 解析失败：{e}\n原始内容：{raw[:300]}")

    shots = [
        ShotSegment(
            start_sec=s.get("start_sec", 0.0),
            end_sec=s.get("end_sec", 0.0),
            shot_type=s.get("shot_type", "other"),
            visual=s.get("visual", ""),
            text_overlay=s.get("text_overlay"),
            camera_motion=s.get("camera_motion", "static"),
            transition_in=s.get("transition_in", "cut"),
            transition_out=s.get("transition_out", "cut"),
            notes=s.get("notes"),
        )
        for s in data.get("shots", [])
    ]

    breakdown = VideoBreakdown(
        structure=data.get("structure", {}),
        editing_style=data.get("editing_style", {}),
        shots=shots,
        audio=data.get("audio", {}),
        claims=data.get("claims", []),
        summary=(data.get("summary") or "").strip(),
    )
    confidence = float(data.get("analysis_confidence", 0.75))
    source_quality = data.get("source_quality", "medium")
    return breakdown, confidence, source_quality


# ---------------------------------------------------------------------------
# 后台分析任务
# ---------------------------------------------------------------------------


async def _run_analysis_task(
    job_id: str,
    local_path: Optional[str],
    input_url: Optional[str],
    lang: str,
    profile: str,
    api_key: str,
    model: str,
) -> None:
    """
    asyncio 后台任务：上传视频 → Gemini 分析 → 更新 job 状态。
    任何异常都会将 job 状态设为 failed。
    """
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"

    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(lang, profile)

        # Step 1: 获取视频内容（本地文件或 URL）
        loop = asyncio.get_event_loop()

        if local_path and os.path.exists(local_path):
            # 用 Files API 上传本地文件（同步操作在线程池运行）
            uploaded = await loop.run_in_executor(
                None,
                lambda: client.files.upload(
                    file=local_path,
                    config=types.UploadFileConfig(mime_type="video/mp4"),
                ),
            )

            # 等待文件进入 ACTIVE 状态（最多 10 分钟）
            for _ in range(120):
                if uploaded.state and uploaded.state.name == "ACTIVE":
                    break
                await asyncio.sleep(5)
                uploaded = await loop.run_in_executor(
                    None, lambda: client.files.get(name=uploaded.name)
                )
            else:
                raise ProviderError("Gemini Files API 文件处理超时（10分钟）")

            video_part = types.Part.from_uri(
                file_uri=uploaded.uri, mime_type="video/mp4"
            )
        elif input_url:
            # 直接用 URL（需公网可达）
            video_part = types.Part.from_uri(
                file_uri=input_url, mime_type="video/mp4"
            )
        else:
            raise ProviderError(f"无法获取视频内容：local_path={local_path}, input_url={input_url}")

        # Step 2: 调用 Gemini generateContent
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model,
                contents=[video_part, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,         # 低温度保证结构稳定
                    max_output_tokens=8192,
                ),
            ),
        )

        raw_text = response.text

        # Step 3: 解析结果
        breakdown, confidence, source_quality = _parse_breakdown(raw_text)

        job.status = "done"
        job.video_breakdown = breakdown
        job.analysis_confidence = confidence
        job.source_quality = source_quality

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
        # Surface to backend stdout immediately so failures are visible in the
        # uvicorn console without waiting for the agent to poll. The schema
        # also carries error_message back to the caller, but printing here
        # gives operators real-time diagnostic feedback.
        print(f"[GEMINI ANALYSIS FAILED] job={job_id}: ProviderError: {e}", flush=True)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"分析任务异常：{type(e).__name__}: {e}"
        print(f"[GEMINI ANALYSIS FAILED] job={job_id}: {type(e).__name__}: {e}", flush=True)


# ---------------------------------------------------------------------------
# GeminiVideoAnalysisProvider
# ---------------------------------------------------------------------------


class GeminiVideoAnalysisProvider:
    """
    真实 Gemini 视频分析 Provider。

    start_analysis  → 立即返回 queued job，后台异步执行分析
    get_analysis_result → 读取 job 当前状态
    delete_analysis → 删除 job 记录
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY 未配置，请在 .env 文件中设置或通过环境变量传入。"
            )

    async def start_analysis(
        self,
        job_id: str,
        media_id: str,
        input_url: Optional[str],
        analysis_profile: str,
        lang: str,
        output_schema_version: str,
    ) -> VideoAnalysisJob:
        """
        创建 job 并立即返回（status=queued），后台异步执行 Gemini 分析。

        视频来源优先级：
          1. 从 DouyinMediaProvider._store 查 media_id 对应的 local_path
          2. 使用 input_url（需公网可达）
        """
        # 尝试从媒体存储中获取本地路径
        local_path: Optional[str] = None
        try:
            from app.providers.douyin_media_provider import _store as _media_store
            stored = _media_store.get(media_id)
            if stored and stored.storage.local_path:
                local_path = stored.storage.local_path
        except Exception:
            pass  # 媒体存储不可用时退回 input_url

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

        # 启动后台分析任务（不等待）
        asyncio.create_task(
            _run_analysis_task(
                job_id=job_id,
                local_path=local_path,
                input_url=input_url,
                lang=lang,
                profile=analysis_profile,
                api_key=self._api_key,
                model=self._model,
            )
        )

        return job

    async def get_analysis_result(self, job_id: str) -> Optional[VideoAnalysisJob]:
        return _job_store.get(job_id)

    async def delete_analysis(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
