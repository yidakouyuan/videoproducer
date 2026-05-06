"""
Seedance 视频生成 Provider（真实实现）。

流程：
  start_generate  → 创建 job（queued）→ 启动 asyncio 后台任务
  后台任务         → 如果 first_frame_path 是本地文件则先上传到 Ark Files API
                  → 调用 Ark.content_generation.tasks.create 提交生成任务
                  → 轮询状态直到 succeeded / failed
                  → succeeded → 下载 MP4 到 SEEDANCE_OUT_DIR，写 manifest JSON
                  → 更新 job 状态（done / failed）
  get_generate_result → 读取 job 内存状态
  delete_generate     → 删除 job 记录（不删除已下载文件）

环境变量（在 .env 中配置）：
  ARK_API_KEY          必填
  ARK_BASE_URL         可选，默认东南亚节点
  SEEDANCE_MODEL       可选，默认 seedance-1-5-pro-251215
  SEEDANCE_OUT_DIR     视频输出目录，默认 c:/openclaw_agent/data/videos
  SEEDANCE_MANIFEST_DIR manifest 输出目录，默认 c:/openclaw_agent/data/manifests
  POLL_INTERVAL_SEC    轮询间隔秒数，默认 3
  MAX_WAIT_SEC         最长等待秒数，默认 300
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from app.domain.models import VideoGenerateJob
from app.infra.exceptions import ProviderError

# ---------------------------------------------------------------------------
# 配置默认值
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
_DEFAULT_MODEL = "seedance-1-5-pro-251215"
_DEFAULT_OUT_DIR = (
    os.environ.get("MEDIA_OUT_DIR")
    or "C:/Users/Administrator/AppData/Local/Temp/openclaw/uploads"
)
_DEFAULT_MANIFEST_DIR = _DEFAULT_OUT_DIR
_DEFAULT_POLL_SEC = 3.0
_DEFAULT_MAX_WAIT_SEC = 300.0

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, VideoGenerateJob] = {}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _find_first_url(obj: Any) -> Optional[str]:
    """从 SDK 返回对象中启发式找到视频 URL。"""
    def walk(x: Any) -> Optional[str]:
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() in ("url", "video_url", "download_url", "file_url", "play_url"):
                    if isinstance(v, str) and v.startswith("http"):
                        return v
                got = walk(v)
                if got:
                    return got
        elif isinstance(x, list):
            for it in x:
                got = walk(it)
                if got:
                    return got
        else:
            try:
                return walk(x.model_dump())
            except Exception:
                try:
                    return walk(x.__dict__)
                except Exception:
                    return None
        return None
    return walk(obj)


def _download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _is_local_file(path: str) -> bool:
    """判断是本地路径还是 URL。"""
    return not path.startswith("http://") and not path.startswith("https://")


# ---------------------------------------------------------------------------
# 后台生成任务
# ---------------------------------------------------------------------------


async def _run_generate_task(
    job_id: str,
    prompt: str,
    first_frame_path: Optional[str],
    model: str,
    api_key: str,
    base_url: str,
    out_dir: Path,
    manifest_dir: Path,
    poll_sec: float,
    max_wait_sec: float,
) -> None:
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"

    try:
        try:
            from byteplussdkarkruntime import Ark  # type: ignore
        except ImportError:
            from volcenginesdkarkruntime import Ark  # type: ignore
    except ImportError:
        job.status = "failed"
        job.error_message = "Ark SDK 未安装，请 pip install volcengine-python-sdk[ark]"
        return

    try:
        loop = asyncio.get_event_loop()
        client = Ark(base_url=base_url, api_key=api_key)

        # Step 1: 构造 content
        first_frame_url: Optional[str] = None
        if first_frame_path:
            if _is_local_file(first_frame_path):
                # 本地文件 → 上传到 Ark Files API，换成 URL
                # 注：Ark Files API 上传接口可能随 SDK 版本变化，此处使用通用路径
                try:
                    upload_result = await loop.run_in_executor(
                        None,
                        lambda: client.files.create(
                            file=(Path(first_frame_path).name, open(first_frame_path, "rb"), "image/jpeg"),
                        ),
                    )
                    first_frame_url = getattr(upload_result, "url", None) or getattr(upload_result, "file_url", None)
                except Exception as e:
                    raise ProviderError(f"首帧图片上传失败：{e}")
            else:
                first_frame_url = first_frame_path

        content: list[dict] = [{"type": "text", "text": prompt}]
        if first_frame_url:
            content.append({"type": "image_url", "image_url": {"url": first_frame_url}})

        # Step 2: 提交生成任务
        create_result = await loop.run_in_executor(
            None,
            lambda: client.content_generation.tasks.create(model=model, content=content),
        )
        task_id = getattr(create_result, "id", None) or getattr(create_result, "task_id", None)
        if not task_id:
            raise ProviderError(f"无法从 create_result 中找到 task_id：{create_result}")

        job.task_id = task_id

        # Step 3: 轮询
        deadline = time.time() + max_wait_sec
        last = None
        while time.time() < deadline:
            last = await loop.run_in_executor(
                None,
                lambda: client.content_generation.tasks.get(task_id=task_id),
            )
            status = getattr(last, "status", None) or getattr(last, "state", None)
            status_s = str(status).lower() if status is not None else ""

            if status_s == "succeeded":
                # Step 4: 下载视频
                video_url = _find_first_url(last)
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                mp4_path = out_dir / f"seedance_{task_id}_{ts}.mp4"

                if video_url:
                    await loop.run_in_executor(None, lambda: _download_file(video_url, mp4_path))
                else:
                    raise ProviderError("任务成功但无法找到视频 URL（请查看 manifest raw_result）")

                # Step 5: 写 manifest
                manifest_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = manifest_dir / f"seedance_{task_id}_{ts}.json"
                try:
                    raw = last.model_dump()
                except Exception:
                    try:
                        raw = last.__dict__
                    except Exception:
                        raw = str(last)

                manifest_path.write_text(
                    json.dumps({
                        "job_id": job_id,
                        "task_id": task_id,
                        "model": model,
                        "prompt": prompt,
                        "first_frame_path": first_frame_path,
                        "status": "succeeded",
                        "video_url": video_url,
                        "mp4_path": str(mp4_path),
                        "raw_result": raw,
                    }, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )

                job.local_video_path = str(mp4_path)
                job.manifest_path = str(manifest_path)
                job.status = "done"
                return

            if status_s == "failed":
                raise ProviderError(f"Seedance 任务失败：task_id={task_id}")

            await asyncio.sleep(poll_sec)

        raise ProviderError(f"Seedance 任务超时（{max_wait_sec}s）：task_id={task_id}")

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"生成任务异常：{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# SeedanceVideoProvider
# ---------------------------------------------------------------------------


class SeedanceVideoProvider:
    """
    真实 Seedance 视频生成 Provider。

    start_generate      → 立即返回 queued job，后台异步执行生成
    get_generate_result → 读取 job 当前状态
    delete_generate     → 删除 job 记录（不删除已下载文件）
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("ARK_API_KEY", "")
        self._base_url = os.environ.get("ARK_BASE_URL", _DEFAULT_BASE_URL)
        self._model = os.environ.get("SEEDANCE_MODEL", _DEFAULT_MODEL)
        self._out_dir = Path(os.environ.get("SEEDANCE_OUT_DIR", _DEFAULT_OUT_DIR))
        self._manifest_dir = Path(os.environ.get("SEEDANCE_MANIFEST_DIR", _DEFAULT_MANIFEST_DIR))
        self._poll_sec = float(os.environ.get("POLL_INTERVAL_SEC", str(_DEFAULT_POLL_SEC)))
        self._max_wait_sec = float(os.environ.get("MAX_WAIT_SEC", str(_DEFAULT_MAX_WAIT_SEC)))

        if not self._api_key:
            raise ValueError("ARK_API_KEY 未配置，请在 .env 文件中设置。")

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        duration: int,
        first_frame_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> VideoGenerateJob:
        # Seedance 当前不通过 duration 控制(time scale 由模型决定),但保留参数以统一 provider 协议。
        resolved_model = model or self._model
        job = VideoGenerateJob(
            job_id=job_id,
            prompt=prompt,
            duration=duration,
            first_frame_path=first_frame_path,
            model=resolved_model,
            status="queued",
        )
        _job_store[job_id] = job

        asyncio.create_task(
            _run_generate_task(
                job_id=job_id,
                prompt=prompt,
                first_frame_path=first_frame_path,
                model=resolved_model,
                api_key=self._api_key,
                base_url=self._base_url,
                out_dir=self._out_dir,
                manifest_dir=self._manifest_dir,
                poll_sec=self._poll_sec,
                max_wait_sec=self._max_wait_sec,
            )
        )

        return job

    async def get_generate_result(self, job_id: str) -> Optional[VideoGenerateJob]:
        return _job_store.get(job_id)

    async def delete_generate(self, job_id: str) -> bool:
        if job_id not in _job_store:
            return False
        del _job_store[job_id]
        return True
