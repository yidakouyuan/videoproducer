"""
Gemini 转写 Provider（真实实现）。

流程：
  start_transcribe → 创建 job（queued）→ 启动 asyncio 后台任务
  后台任务          → 上传视频到 Gemini Files API
                   → 等待文件 ACTIVE
                   → generateContent + 结构化 JSON Prompt
                   → 解析 → 写入 job（done / failed）
  get_transcribe_result → 直接读 job 内存状态

环境变量（在 .env 中配置）：
  GEMINI_API_KEY       必填，Google AI Studio 的 API Key
  GEMINI_MODEL         可选，默认 gemini-2.5-pro
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional

from google import genai
from google.genai import types

from app.domain.models import TranscribeJob, TranscriptHighlight
from app.infra.exceptions import ProviderError

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, TranscribeJob] = {}

# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

_TRANSCRIBE_PROMPT_HIGHLIGHTS = """\
请对这段视频进行语音转写，严格以 JSON 格式输出，不要输出任何其他内容。
重要：输出必须是标准 JSON，绝对不允许包含任何注释（不允许 // 或 /* */ 形式的注释）。

JSON 结构如下：
{
  "transcript": "视频中所有语音的完整文字稿，按顺序拼接",
  "highlights": [
    {
      "start_sec": 12.3,
      "end_sec": 16.8,
      "text": "这段话的摘要或原文（重要内容）"
    }
  ],
  "confidence": 0.85
}

要求：
- transcript：把视频中所有说话内容完整转录，保留语序，不要省略
- highlights：从中挑选 3~8 个最有信息量的片段（关键卖点/亮点/结论），包含时间戳
- confidence：转写置信度（0.0~1.0），根据语音清晰度自评

转写语言：{lang}
"""

_TRANSCRIBE_PROMPT_FULL = """\
请对这段视频进行完整语音转写，严格以 JSON 格式输出，不要输出任何其他内容。
重要：输出必须是标准 JSON，绝对不允许包含任何注释（不允许 // 或 /* */ 形式的注释）。

JSON 结构如下：
{
  "transcript": "视频中所有语音的完整文字稿，按顺序拼接",
  "highlights": [
    {
      "start_sec": 0.0,
      "end_sec": 5.0,
      "text": "这段的逐字或摘要内容"
    }
  ],
  "confidence": 0.85
}

要求：
- transcript：把视频中所有说话内容完整转录，逐字逐句，不要省略任何内容
- highlights：对整段视频按句子或短段落切分，每段都要有时间戳，覆盖全部内容
- confidence：转写置信度（0.0~1.0），根据语音清晰度自评

转写语言：{lang}
"""


def _build_prompt(lang: str, mode: str) -> str:
    template = _TRANSCRIBE_PROMPT_FULL if mode == "full" else _TRANSCRIBE_PROMPT_HIGHLIGHTS
    return template.replace("{lang}", lang)


# ---------------------------------------------------------------------------
# 结果解析
# ---------------------------------------------------------------------------


def _strip_json_comments(text: str) -> str:
    """去掉 JSON 中的 // 单行注释。"""
    return re.sub(r'(?<!["\w])//[^\n]*', '', text)


def _parse_result(raw: str) -> tuple[str, list[TranscriptHighlight], float]:
    """
    从 Gemini 返回文本中解析 transcript、highlights、confidence。
    返回 (transcript, highlights, confidence)。
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])

    text = _strip_json_comments(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError(f"Gemini 返回的 JSON 解析失败：{e}\n原始内容：{raw[:300]}")

    transcript = data.get("transcript", "")
    confidence = float(data.get("confidence", 0.75))
    highlights = [
        TranscriptHighlight(
            start_sec=float(h.get("start_sec", 0.0)),
            end_sec=float(h.get("end_sec", 0.0)),
            text=h.get("text", ""),
        )
        for h in data.get("highlights", [])
    ]
    return transcript, highlights, confidence


# ---------------------------------------------------------------------------
# 后台转写任务
# ---------------------------------------------------------------------------


async def _run_transcribe_task(
    job_id: str,
    local_path: Optional[str],
    lang: str,
    mode: str,
    api_key: str,
    model: str,
) -> None:
    """
    asyncio 后台任务：上传视频 → Gemini 转写 → 更新 job 状态。
    任何异常都会将 job 状态设为 failed。
    """
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"

    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(lang, mode)
        loop = asyncio.get_event_loop()

        if not local_path or not os.path.exists(local_path):
            raise ProviderError(f"本地视频文件不存在：local_path={local_path}")

        # Step 1: 上传到 Files API
        uploaded = await loop.run_in_executor(
            None,
            lambda: client.files.upload(
                file=local_path,
                config=types.UploadFileConfig(mime_type="video/mp4"),
            ),
        )

        # Step 2: 等待文件进入 ACTIVE 状态（最多 10 分钟）
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

        # Step 3: 调用 generateContent
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model,
                contents=[video_part, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            ),
        )

        # Step 4: 解析结果
        transcript, highlights, confidence = _parse_result(response.text)

        job.status = "done"
        job.transcript = transcript
        job.highlights = highlights
        job.confidence = confidence

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
        # Surface to backend stdout immediately so failures are visible in the
        # uvicorn console without waiting for the agent to poll. The schema
        # also carries error_message back to the caller, but printing here
        # gives operators real-time diagnostic feedback.
        print(f"[GEMINI TRANSCRIBE FAILED] job={job_id}: ProviderError: {e}", flush=True)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"转写任务异常：{type(e).__name__}: {e}"
        print(f"[GEMINI TRANSCRIBE FAILED] job={job_id}: {type(e).__name__}: {e}", flush=True)


# ---------------------------------------------------------------------------
# GeminiTranscribeProvider
# ---------------------------------------------------------------------------


class GeminiTranscribeProvider:
    """
    真实 Gemini 转写 Provider。

    start_transcribe      → 立即返回 queued job，后台异步执行转写
    get_transcribe_result → 读取 job 当前状态
    delete_transcribe     → 删除 job 记录
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

    async def start_transcribe(
        self,
        job_id: str,
        media_id: str,
        provider_name: str,
        lang: str,
        mode: str,
    ) -> TranscribeJob:
        """
        创建 job 并立即返回（status=queued），后台异步执行 Gemini 转写。

        视频来源：从 DouyinMediaProvider._store 查 media_id 对应的 local_path。
        """
        local_path: Optional[str] = None
        try:
            from app.providers.douyin_media_provider import _store as _media_store
            stored = _media_store.get(media_id)
            if stored and stored.storage.local_path:
                local_path = stored.storage.local_path
        except Exception:
            pass

        job = TranscribeJob(
            job_id=job_id,
            media_id=media_id,
            provider_name=provider_name,
            lang=lang,
            mode=mode,
            status="queued",
        )
        _job_store[job_id] = job

        asyncio.create_task(
            _run_transcribe_task(
                job_id=job_id,
                local_path=local_path,
                lang=lang,
                mode=mode,
                api_key=self._api_key,
                model=self._model,
            )
        )

        return job

    async def get_transcribe_result(self, job_id: str) -> Optional[TranscribeJob]:
        return _job_store.get(job_id)

    async def delete_transcribe(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
