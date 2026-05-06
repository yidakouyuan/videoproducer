"""
MiniMax Hailuo 视频生成 Provider（真实实现）。

流程：
  start_generate  → 创建 job（queued）→ 启动 asyncio 后台任务
  后台任务         → 若有 first_frame_path 则将其转 base64（本地）或直传 URL → 加入 request body
                  → POST /v1/video_generation 提交任务，拿到 task_id
                  → 每 10s 轮询 GET /v1/query/video_generation?task_id=xxx
                  → status=Success → 用 file_id 调 GET /v1/files/retrieve 换 download_url
                  → 下载 MP4 到 MINIMAX_OUT_DIR，写 manifest JSON
                  → 更新 job 状态（done / failed）
  get_generate_result → 读取 job 内存状态
  delete_generate     → 删除 job 记录（不删除已下载文件）

i2v（图生视频）说明：
  - MiniMax-Hailuo-02 模型支持 i2v 模式，传入首帧图后视频会以该图为第一帧
  - first_frame_image 字段接受公网 URL 或 data URI（data:image/jpeg;base64,xxx）
  - 不传 first_frame_path 时退化为纯 t2v

环境变量（在 .env 中配置）：
  MINIMAX_API_KEY      必填
  MINIMAX_MODEL        可选，默认 MiniMax-Hailuo-02
  MINIMAX_OUT_DIR      视频输出目录，默认 C:/Users/Administrator/AppData/Local/Temp/openclaw/uploads
  POLL_INTERVAL_SEC    轮询间隔秒数，默认 10
  MAX_WAIT_SEC         最长等待秒数，默认 300
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from app.domain.models import VideoGenerateJob
from app.infra.exceptions import ProviderError

# ---------------------------------------------------------------------------
# 配置默认值
# ---------------------------------------------------------------------------

_API_BASE = "https://api.minimax.io/v1"
_DEFAULT_MODEL = "MiniMax-Hailuo-02"
_DEFAULT_OUT_DIR = (
    os.environ.get("MEDIA_OUT_DIR")
    or "C:/Users/Administrator/AppData/Local/Temp/openclaw/uploads"
)
_DEFAULT_POLL_SEC = 10.0
_DEFAULT_MAX_WAIT_SEC = 300.0

# ---------------------------------------------------------------------------
# 进程内 Job Store
# ---------------------------------------------------------------------------

_job_store: dict[str, VideoGenerateJob] = {}


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
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


_MIME_BY_EXT = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "webp": "webp",
}

# MiniMax 限制:base64 + data URL 前缀整体 ≤ 20MB
# 我们用 18MB 作为本地阈值,留 ~10% 余量给 base64 膨胀(b64 比原始大 4/3)
_MAX_FIRST_FRAME_BYTES = 18 * 1024 * 1024

# MiniMax-Hailuo-02 视频时长合法值。Agent 可以传任意整数,这里向最近合法值对齐,
# 距离相同时取较小值(节约 API 配额)。换 provider(seedance/kling/...)时各自维护。
_MINIMAX_ALLOWED_DURATIONS = (6, 10)


def _resolve_minimax_duration(requested: int) -> int:
    """把 agent 请求的 duration 对齐到 MiniMax 合法值。

    选择策略:最接近的合法值;距离相同时取较小者。
      requested=4  -> 6   (没法更短)
      requested=5  -> 6
      requested=6  -> 6
      requested=7  -> 6   (|7-6|=1, |7-10|=3,选 6)
      requested=8  -> 6   (|8-6|=2 = |8-10|=2,平局选小)
      requested=9  -> 10
      requested=10 -> 10
      requested=15 -> 10  (没法更长)
    """
    return min(_MINIMAX_ALLOWED_DURATIONS, key=lambda x: (abs(x - requested), x))


def _first_frame_to_minimax(path: str) -> str:
    """把 first_frame_path 转成 MiniMax 接受的 first_frame_image 字段值。

    - 公网 URL(http/https)原样返回
    - 本地文件读为 bytes,转 data URI: data:image/<mime>;base64,<b64>
    - 不支持的扩展名 fallback 为 jpeg(MiniMax 文档要求 mime 必须与实际格式匹配,
      所以 writer agent 应保证生成 jpg/png/webp,这里只是兜底)
    """
    if path.startswith("http://") or path.startswith("https://"):
        return path
    p = Path(path)
    if not p.exists():
        raise ProviderError(f"first_frame_path 文件不存在: {path}")
    size = p.stat().st_size
    if size > _MAX_FIRST_FRAME_BYTES:
        raise ProviderError(
            f"first_frame_path 文件过大: {size} bytes(MiniMax 限制 ~20MB)。"
            f"建议压缩或换公开 URL。文件: {path}"
        )
    ext = p.suffix.lower().lstrip(".")
    mime = _MIME_BY_EXT.get(ext, "jpeg")  # 不识别的扩展名兜底为 jpeg
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# 后台生成任务
# ---------------------------------------------------------------------------


async def _run_generate_task(
    job_id: str,
    prompt: str,
    duration: int,
    model: str,
    api_key: str,
    out_dir: Path,
    poll_sec: float,
    max_wait_sec: float,
    first_frame_path: Optional[str] = None,
) -> None:
    job = _job_store.get(job_id)
    if job is None:
        return

    job.status = "running"
    loop = asyncio.get_event_loop()
    headers = _auth_headers(api_key)

    try:
        # Step 1: 构造 request body(t2v / i2v)
        # duration 对齐到 MiniMax 合法值。原始值保留在 manifest 里供排查。
        actual_duration = _resolve_minimax_duration(duration)
        body: dict = {"model": model, "prompt": prompt, "duration": actual_duration}
        # resolution 字段(MiniMax 视频分辨率)。
        # 默认 1080P;通过 MINIMAX_VIDEO_RESOLUTION 环境变量覆盖。
        # 注意 i2v 模式下,实际输出分辨率通常会跟随首帧图比例。
        resolution = os.environ.get("MINIMAX_VIDEO_RESOLUTION", "1080P")
        if resolution:
            body["resolution"] = resolution
        if first_frame_path:
            body["first_frame_image"] = _first_frame_to_minimax(first_frame_path)

        # Step 2: 提交生成任务
        create_resp = await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{_API_BASE}/video_generation",
                headers=headers,
                json=body,
                timeout=30,
            ),
        )
        create_resp.raise_for_status()
        create_data = create_resp.json()

        base_resp = create_data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            raise ProviderError(f"MiniMax 创建任务失败：{base_resp.get('status_msg')}")

        task_id = create_data.get("task_id")
        if not task_id:
            raise ProviderError(f"MiniMax 返回中找不到 task_id：{create_data}")

        job.task_id = task_id

        # Step 2: 轮询状态
        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            await asyncio.sleep(poll_sec)

            poll_resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{_API_BASE}/query/video_generation",
                    headers=headers,
                    params={"task_id": task_id},
                    timeout=30,
                ),
            )
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()

            status = poll_data.get("status", "")

            if status == "Success":
                file_id = poll_data.get("file_id")
                if not file_id:
                    raise ProviderError(f"status=Success 但找不到 file_id：{poll_data}")

                # Step 3: 获取下载 URL
                retrieve_resp = await loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f"{_API_BASE}/files/retrieve",
                        headers=headers,
                        params={"file_id": file_id},
                        timeout=30,
                    ),
                )
                retrieve_resp.raise_for_status()
                retrieve_data = retrieve_resp.json()
                download_url = retrieve_data.get("file", {}).get("download_url")
                if not download_url:
                    raise ProviderError(f"无法从 files/retrieve 拿到 download_url：{retrieve_data}")

                # Step 4: 下载 MP4
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                mp4_path = out_dir / f"minimax_{task_id}_{ts}.mp4"
                await loop.run_in_executor(None, lambda: _download_file(download_url, mp4_path))

                # Step 5: 写 manifest
                out_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = out_dir / f"minimax_{task_id}_{ts}.json"
                manifest_path.write_text(
                    json.dumps({
                        "job_id": job_id,
                        "task_id": task_id,
                        "model": model,
                        "prompt": prompt,
                        "requested_duration": duration,
                        "actual_duration": actual_duration,
                        "first_frame_path": first_frame_path,
                        "mode": "i2v" if first_frame_path else "t2v",
                        "status": "succeeded",
                        "download_url": download_url,
                        "mp4_path": str(mp4_path),
                        "file_id": file_id,
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                job.local_video_path = str(mp4_path)
                job.manifest_path = str(manifest_path)
                job.status = "done"
                return

            if status == "Fail":
                raise ProviderError(f"MiniMax 任务失败：task_id={task_id}")

            # Queueing / Processing → 继续等待

        raise ProviderError(f"MiniMax 任务超时（{max_wait_sec}s）：task_id={task_id}")

    except ProviderError as e:
        job.status = "failed"
        job.error_message = str(e)
    except Exception as e:
        job.status = "failed"
        job.error_message = f"生成任务异常：{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# MiniMaxVideoProvider
# ---------------------------------------------------------------------------


class MiniMaxVideoProvider:
    """
    MiniMax Hailuo 视频生成 Provider（文生视频）。

    start_generate      → 立即返回 queued job，后台异步执行生成
    get_generate_result → 读取 job 当前状态
    delete_generate     → 删除 job 记录（不删除已下载文件）
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("MINIMAX_API_KEY", "")
        self._model = os.environ.get("MINIMAX_MODEL", _DEFAULT_MODEL)
        self._out_dir = Path(os.environ.get("MINIMAX_OUT_DIR", _DEFAULT_OUT_DIR))
        self._poll_sec = float(os.environ.get("POLL_INTERVAL_SEC", str(_DEFAULT_POLL_SEC)))
        self._max_wait_sec = float(os.environ.get("MAX_WAIT_SEC", str(_DEFAULT_MAX_WAIT_SEC)))

        if not self._api_key:
            raise ValueError("MINIMAX_API_KEY 未配置，请在 .env 文件中设置。")

    async def start_generate(
        self,
        job_id: str,
        prompt: str,
        duration: int,
        first_frame_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> VideoGenerateJob:
        resolved_model = model or self._model
        job = VideoGenerateJob(
            job_id=job_id,
            prompt=prompt,
            status="queued",
            duration=duration,
            first_frame_path=first_frame_path,
            model=resolved_model,
        )
        _job_store[job_id] = job

        asyncio.create_task(
            _run_generate_task(
                job_id=job_id,
                prompt=prompt,
                duration=duration,
                model=resolved_model,
                api_key=self._api_key,
                out_dir=self._out_dir,
                poll_sec=self._poll_sec,
                max_wait_sec=self._max_wait_sec,
                first_frame_path=first_frame_path,
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
