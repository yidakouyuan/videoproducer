"""
Kling（快手可灵）图片生成 Provider — 使用 Kolors 模型。

流程：
  start_generate  → 创建 job → 启动 asyncio 后台任务
  后台任务         → POST /v1/images/generations 提交任务
                  → 轮询 GET /v1/images/generations/{task_id} 直到 succeed/failed
                  → 下载图片，写 manifest
                  → 更新 job 状态

模型：
  kolors                 - 纯文生图（t2i）
  kolors-image-to-image  - 图生图/风格迁移（i2i），传入 style_reference_path 时自动使用

认证：JWT（HS256），每次请求前重新生成，有效期 30 分钟。

环境变量：
  KLING_ACCESS_KEY     必填
  KLING_SECRET_KEY     必填
  KLING_IMAGE_MODEL    可选，默认 kolors
  KLING_IMAGE_OUT_DIR  图片输出目录，默认 ./data/uploads
  POLL_INTERVAL_SEC    轮询间隔（秒），默认 5
  MAX_WAIT_SEC         最长等待（秒），默认 300
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
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

_API_BASE = "https://api.klingai.com"
_DEFAULT_MODEL = "kolors"
_DEFAULT_OUT_DIR = os.environ.get("MEDIA_OUT_DIR") or "./data/uploads"
_DEFAULT_ASPECT = os.environ.get("KLING_IMAGE_ASPECT", "9:16")  # 抖音 9:16 竖屏;改 "16:9" 切横屏
_DEFAULT_POLL_SEC = 5.0
_DEFAULT_MAX_WAIT_SEC = 300.0

# ---------------------------------------------------------------------------
# 可用模型清单
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = [
    {"name": "kolors", "modes": ["t2i"], "default": True,
     "description": "Kolors 文生图，高质量"},
    {"name": "kolors-image-to-image", "modes": ["t2i", "i2i"], "default": False,
     "description": "Kolors 图生图/风格迁移，保持参考图风格"},
]

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, ImageGenerateJob] = {}

# ---------------------------------------------------------------------------
# JWT 工具
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _kling_jwt(ak: str, sk: str) -> str:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iss": ak, "iat": now, "exp": now + 1800}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    sig = _b64url(hmac.new(sk.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{sig}"


def _auth_headers(ak: str, sk: str) -> dict:
    return {
        "Authorization": f"Bearer {_kling_jwt(ak, sk)}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _image_to_base64_or_url(path: str) -> str:
    """本地文件转 base64 data URI，URL 原样返回。"""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    with open(path, "rb") as f:
        ext = Path(path).suffix.lower().lstrip(".")
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        return f"data:image/{mime};base64,{base64.b64encode(f.read()).decode()}"


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
    ak: str,
    sk: str,
    out_dir: Path,
    poll_sec: float,
    max_wait_sec: float,
) -> None:
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"
    loop = asyncio.get_running_loop()
    is_i2i = bool(style_reference_path)

    # 有参考图时自动使用 i2i 模型（仅当当前模型是纯 t2i 变体时才升级）
    if is_i2i and "image-to-image" not in model:
        model = "kolors-image-to-image"
        job.model = model

    try:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": _DEFAULT_ASPECT,
        }
        if is_i2i:
            body["image"] = _image_to_base64_or_url(style_reference_path)  # type: ignore[arg-type]
            body["image_fidelity"] = 0.5

        create_resp = await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{_API_BASE}/v1/images/generations",
                headers=_auth_headers(ak, sk),
                json=body,
                timeout=30,
            ),
        )
        create_resp.raise_for_status()
        create_data = create_resp.json()

        code = create_data.get("code", -1)
        if code != 0:
            raise ProviderError(f"Kling 图片创建任务失败 code={code}: {create_data.get('message')}")

        task_id = create_data.get("data", {}).get("task_id")
        if not task_id:
            raise ProviderError(f"Kling 图片返回中找不到 task_id: {create_data}")

        job.task_id = task_id

        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            await asyncio.sleep(poll_sec)

            poll_resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{_API_BASE}/v1/images/generations/{task_id}",
                    headers=_auth_headers(ak, sk),
                    timeout=30,
                ),
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            task_status = poll_data.get("data", {}).get("task_status", "")

            if task_status == "succeed":
                images = poll_data["data"].get("task_result", {}).get("images", [])
                if not images:
                    raise ProviderError(f"Kling 图片 succeed 但无图片 URL: {poll_data}")
                image_url = images[0].get("url")
                if not image_url:
                    raise ProviderError(f"Kling 图片 URL 为空: {poll_data}")

                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                ext = "jpg"
                img_path = out_dir / f"kling_img_{task_id}_{ts}.{ext}"
                await loop.run_in_executor(None, lambda: _download_file(image_url, img_path))

                out_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = out_dir / f"kling_img_{task_id}_{ts}.json"
                manifest_path.write_text(
                    json.dumps({
                        "job_id": job_id, "task_id": task_id, "model": model,
                        "prompt": prompt, "is_i2i": is_i2i,
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

            if task_status == "failed":
                raise ProviderError(f"Kling 图片任务失败: task_id={task_id}")

        raise ProviderError(f"Kling 图片任务超时（{max_wait_sec}s）: task_id={task_id}")

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"图片生成任务异常: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# KlingImageProvider
# ---------------------------------------------------------------------------


class KlingImageProvider:
    """Kling（快手可灵）Kolors 图片生成 Provider。"""

    def __init__(self) -> None:
        self._ak = os.environ.get("KLING_ACCESS_KEY", "")
        self._sk = os.environ.get("KLING_SECRET_KEY", "")
        self._model = os.environ.get("KLING_IMAGE_MODEL", _DEFAULT_MODEL)
        self._out_dir = Path(os.environ.get("KLING_IMAGE_OUT_DIR", _DEFAULT_OUT_DIR))
        self._poll_sec = float(os.environ.get("POLL_INTERVAL_SEC", str(_DEFAULT_POLL_SEC)))
        self._max_wait_sec = float(os.environ.get("MAX_WAIT_SEC", str(_DEFAULT_MAX_WAIT_SEC)))

        if not self._ak or not self._sk:
            raise ValueError("KLING_ACCESS_KEY 和 KLING_SECRET_KEY 未配置，请在 .env 中设置。")

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
            ak=self._ak, sk=self._sk, out_dir=self._out_dir,
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
