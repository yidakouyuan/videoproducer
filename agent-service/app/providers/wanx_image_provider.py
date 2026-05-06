"""
WanX（阿里通义万象）图片生成 Provider。

流程：
  start_generate  → 创建 job → 启动 asyncio 后台任务
  后台任务         → POST DashScope text2image（t2i）
                  → 轮询 GET /api/v1/tasks/{task_id} 直到 SUCCEEDED/FAILED
                  → 下载图片，写 manifest
                  → 更新 job 状态

注意：
  - style_reference_path 传入时，在 prompt 中追加风格描述（WanX t2i 不支持原生 i2i）
  - 若需要原生图生图，可将 model 设为 wanx-sketch-to-image-v1 等支持 img_url 参数的模型

环境变量：
  WANX_API_KEY         必填
  WANX_BASE_URL        可选，默认国际节点
  WANX_IMAGE_MODEL     可选，默认 wanx2.1-t2i-turbo
  WANX_IMAGE_OUT_DIR   图片输出目录，默认 ./data/uploads
  POLL_INTERVAL_SEC    轮询间隔（秒），默认 5
  MAX_WAIT_SEC         最长等待（秒），默认 300
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from app.domain.models import ImageGenerateJob
from app.infra.exceptions import ProviderError

# ---------------------------------------------------------------------------
# 配置默认值
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com"
_DEFAULT_MODEL = "wanx2.1-t2i-turbo"
_DEFAULT_OUT_DIR = os.environ.get("MEDIA_OUT_DIR") or "./data/uploads"
_DEFAULT_SIZE = os.environ.get("WANX_IMAGE_SIZE", "720*1280")  # 抖音 9:16 竖屏;改 "1280*720" 切横屏
_DEFAULT_POLL_SEC = 5.0
_DEFAULT_MAX_WAIT_SEC = 300.0

# ---------------------------------------------------------------------------
# 可用模型清单
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = [
    {"name": "wanx2.1-t2i-turbo", "modes": ["t2i"], "default": True,
     "description": "文生图，速度最快，1024px"},
    {"name": "wanx2.1-t2i-plus", "modes": ["t2i"], "default": False,
     "description": "文生图，高画质"},
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
        "X-DashScope-Async": "enable",
        "Content-Type": "application/json",
    }


def _poll_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


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
    base_url: str,
    out_dir: Path,
    poll_sec: float,
    max_wait_sec: float,
) -> None:
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"
    loop = asyncio.get_running_loop()

    effective_prompt = prompt
    if style_reference_path:
        effective_prompt = f"{prompt} (maintain consistent visual style)"

    try:
        endpoint = f"{base_url}/api/v1/services/aigc/text2image/image-synthesis"
        body = {
            "model": model,
            "input": {
                "prompt": effective_prompt,
                "negative_prompt": "blurry, low quality, distorted",
            },
            "parameters": {
                "size": _DEFAULT_SIZE,
                "n": 1,
            },
        }

        create_resp = await loop.run_in_executor(
            None,
            lambda: requests.post(
                endpoint,
                headers=_auth_headers(api_key),
                json=body,
                timeout=30,
            ),
        )
        create_resp.raise_for_status()
        create_data = create_resp.json()

        output = create_data.get("output", {})
        task_id = output.get("task_id")
        if not task_id:
            raise ProviderError(f"WanX 图片返回中找不到 task_id: {create_data}")

        job.task_id = task_id

        poll_url = f"{base_url}/api/v1/tasks/{task_id}"
        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            await asyncio.sleep(poll_sec)

            poll_resp = await loop.run_in_executor(
                None,
                lambda: requests.get(poll_url, headers=_poll_headers(api_key), timeout=30),
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            task_status = poll_data.get("output", {}).get("task_status", "")

            if task_status == "SUCCEEDED":
                results = poll_data.get("output", {}).get("results", [])
                image_url = results[0].get("url") if results else None

                if not image_url:
                    raise ProviderError(f"WanX 图片 SUCCEEDED 但无图片 URL: {poll_data}")

                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                img_path = out_dir / f"wanx_img_{task_id}_{ts}.jpg"
                await loop.run_in_executor(None, lambda: _download_file(image_url, img_path))

                out_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = out_dir / f"wanx_img_{task_id}_{ts}.json"
                manifest_path.write_text(
                    json.dumps({
                        "job_id": job_id, "task_id": task_id, "model": model,
                        "prompt": prompt, "effective_prompt": effective_prompt,
                        "style_reference_path": style_reference_path,
                        "status": "succeeded", "image_url": image_url,
                        "local_image_path": str(img_path),
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                job.local_image_path = str(img_path)
                job.image_url = image_url
                job.manifest_path = str(manifest_path)
                job.status = "done"
                return

            if task_status == "FAILED":
                raise ProviderError(
                    f"WanX 图片任务失败: task_id={task_id}, "
                    f"{poll_data.get('output', {}).get('message')}"
                )

        raise ProviderError(f"WanX 图片任务超时（{max_wait_sec}s）: task_id={task_id}")

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"图片生成任务异常: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# WanxImageProvider
# ---------------------------------------------------------------------------


class WanxImageProvider:
    """WanX（阿里通义万象）图片生成 Provider。"""

    def __init__(self) -> None:
        self._api_key = os.environ.get("WANX_API_KEY", "")
        self._base_url = os.environ.get("WANX_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        self._model = os.environ.get("WANX_IMAGE_MODEL", _DEFAULT_MODEL)
        self._out_dir = Path(os.environ.get("WANX_IMAGE_OUT_DIR", _DEFAULT_OUT_DIR))
        self._poll_sec = float(os.environ.get("POLL_INTERVAL_SEC", str(_DEFAULT_POLL_SEC)))
        self._max_wait_sec = float(os.environ.get("MAX_WAIT_SEC", str(_DEFAULT_MAX_WAIT_SEC)))

        if not self._api_key:
            raise ValueError("WANX_API_KEY 未配置，请在 .env 中设置。")

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
            api_key=self._api_key, base_url=self._base_url, out_dir=self._out_dir,
            poll_sec=self._poll_sec, max_wait_sec=self._max_wait_sec,
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
