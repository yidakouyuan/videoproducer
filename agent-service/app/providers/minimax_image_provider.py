"""
MiniMax（海螺）图片生成 Provider。

API 为同步接口，直接返回图片 URL，无需轮询。
后台任务封装为统一的异步 Job 模式。

流程：
  start_generate  → 创建 job → 启动 asyncio 后台任务
  后台任务         → POST /v1/image_generation（同步，直接返回）
                  → 下载图片，写 manifest
                  → 更新 job 状态

环境变量：
  MINIMAX_API_KEY       必填
  MINIMAX_IMAGE_MODEL   可选，默认 image-01
  MINIMAX_IMAGE_OUT_DIR 图片输出目录，默认 ./data/uploads
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from app.domain.models import ImageGenerateJob
from app.infra.exceptions import ProviderError

# ---------------------------------------------------------------------------
# 配置默认值
# ---------------------------------------------------------------------------

_API_BASE = "https://api.minimaxi.chat/v1"
_DEFAULT_MODEL = "image-01"
_DEFAULT_OUT_DIR = os.environ.get("MEDIA_OUT_DIR") or "./data/uploads"
_DEFAULT_ASPECT = os.environ.get("MINIMAX_IMAGE_ASPECT", "9:16")  # 抖音 9:16 竖屏;改 "16:9" 切横屏

# ---------------------------------------------------------------------------
# 可用模型清单
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = [
    {"name": "image-01", "modes": ["t2i"], "default": True,
     "description": "MiniMax 海螺图片生成，高质量"},
]

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, ImageGenerateJob] = {}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=512 * 1024):
                if chunk:
                    f.write(chunk)


# ---------------------------------------------------------------------------
# 后台生成任务
# ---------------------------------------------------------------------------


async def _run_generate_task(
    job_id: str,
    prompt: str,
    style_reference_path: Optional[str],
    model: str,
    api_key: str,
    out_dir: Path,
) -> None:
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"
    loop = asyncio.get_running_loop()

    try:
        # 注意：MiniMax image API 不支持传入参考图片；
        # style_reference_path 仅用于 prompt 提示词增强（非真正的图生图）。
        effective_prompt = prompt
        if style_reference_path:
            effective_prompt = f"{prompt} (maintain consistent visual style)"

        body: dict = {
            "model": model,
            "prompt": effective_prompt,
            "aspect_ratio": _DEFAULT_ASPECT,
            "response_format": "url",
            "n": 1,
        }

        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{_API_BASE}/image_generation",
                headers=_auth_headers(api_key),
                json=body,
                timeout=60,
            ),
        )
        resp.raise_for_status()
        data = resp.json()

        # MiniMax 业务层错误：HTTP 200 但 base_resp.status_code != 0。
        # raise_for_status 只拦 HTTP 错，必须再检查这里才能识别业务失败。
        base = data.get("base_resp") or {}
        code = base.get("status_code")
        if code is not None and code != 0:
            raise ProviderError(
                f"MiniMax 业务返回失败 status_code={code} status_msg={base.get('status_msg')}"
            )

        # 字段提取兼容多种已知响应形态：
        #   image-01 实际响应：data.image_urls (复数 list) — v9 trajectory 取证
        #   旧/兜底形态：data.url / data.image_url / data[0].url / data[0].image_url
        image_url = None
        if "data" in data:
            result_data = data["data"]
            if isinstance(result_data, list) and result_data:
                first = result_data[0]
                image_url = first.get("url") or first.get("image_url")
                if not image_url:
                    urls = first.get("image_urls") or first.get("urls")
                    if isinstance(urls, list) and urls:
                        image_url = urls[0]
            elif isinstance(result_data, dict):
                image_url = result_data.get("url") or result_data.get("image_url")
                if not image_url:
                    urls = result_data.get("image_urls") or result_data.get("urls")
                    if isinstance(urls, list) and urls:
                        image_url = urls[0]
        if not image_url:
            image_url = data.get("image_url") or data.get("url")

        if not image_url:
            # 不要把整个 data 序列化进 error（含临时 OSS 签名 URL，会撑爆 trajectory）。
            keys_top = list(data.keys())
            keys_data = list(data.get("data", {}).keys()) if isinstance(data.get("data"), dict) else []
            raise ProviderError(
                f"MiniMax 图片生成无法定位 URL 字段；顶层 keys={keys_top} data 子层 keys={keys_data}"
            )

        task_id = data.get("id")
        job.task_id = task_id

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name_part = task_id or job_id
        img_path = out_dir / f"minimax_img_{name_part}_{ts}.jpg"
        await loop.run_in_executor(None, lambda: _download_file(image_url, img_path))

        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / f"minimax_img_{name_part}_{ts}.json"
        manifest_path.write_text(
            json.dumps({
                "job_id": job_id, "task_id": task_id, "model": model,
                "prompt": prompt, "style_reference_path": style_reference_path,
                "status": "succeeded", "image_url": image_url,
                "local_image_path": str(img_path),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        job.local_image_path = str(img_path)
        job.image_url = image_url
        job.manifest_path = str(manifest_path)
        job.status = "done"

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"图片生成任务异常: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# MiniMaxImageProvider
# ---------------------------------------------------------------------------


class MiniMaxImageProvider:
    """MiniMax（海螺）图片生成 Provider。"""

    def __init__(self) -> None:
        self._api_key = os.environ.get("MINIMAX_API_KEY", "")
        self._model = os.environ.get("MINIMAX_IMAGE_MODEL", _DEFAULT_MODEL)
        self._out_dir = Path(os.environ.get("MINIMAX_IMAGE_OUT_DIR", _DEFAULT_OUT_DIR))

        if not self._api_key:
            raise ValueError("MINIMAX_API_KEY 未配置，请在 .env 中设置。")

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        style_reference_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ImageGenerateJob:
        resolved_model = model or self._model
        job = ImageGenerateJob(
            job_id=job_id, prompt=prompt, status="queued",
            style_reference_path=style_reference_path, model=resolved_model,
        )
        _job_store[job_id] = job
        asyncio.create_task(_run_generate_task(
            job_id=job_id, prompt=prompt,
            style_reference_path=style_reference_path, model=resolved_model,
            api_key=self._api_key, out_dir=self._out_dir,
        ))
        return job

    async def get_generate_result(self, job_id: str) -> Optional[ImageGenerateJob]:
        return _job_store.get(job_id)

    async def delete_generate(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True

    @staticmethod
    def available_models() -> list[dict]:
        return AVAILABLE_MODELS
