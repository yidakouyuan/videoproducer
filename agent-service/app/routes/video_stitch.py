"""
视频拼接路由层。

对外暴露：
  POST /video/stitch   将多个本地 MP4 文件按顺序拼接为单个 MP4

实现：
  - 使用 ffmpeg concat demuxer（流复制模式，极快）
  - 当 reencode=true 时强制转码到 1920x1080 H.264/AAC
  - ffmpeg 通过 asyncio executor 调用，不阻塞事件循环

依赖：
  - 系统需安装 ffmpeg（PATH 中可访问）
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Request

from app.infra.exceptions import InvalidInputError, ProviderError
from app.infra.response import ok
from app.schemas.video_stitch import StitchData, StitchRequest


def _resolve_ffmpeg_bin() -> str:
    """
    定位 ffmpeg 可执行文件。优先级：
    1. .env / 环境变量 FFMPEG_BIN（最显式，绕过 PATH）
    2. shutil.which("ffmpeg")（依赖 PATH，开发环境常用）
    3. imageio_ffmpeg.get_ffmpeg_exe()（pip 装的兜底）
    4. 都找不到 → 抛 ProviderError 告知如何修

    设计原因：Windows 上常见踩坑——winget/conda 装了 ffmpeg 但 PowerShell PATH 没刷新、
    或 shell 父子进程 PATH 不一致，导致 subprocess 抛裸 WinError 2。绑定 FFMPEG_BIN
    后任何 shell 启动 uvicorn 都能跑通，无需依赖 PATH。
    """
    bin_path = os.environ.get("FFMPEG_BIN", "").strip()
    if bin_path:
        if Path(bin_path).is_file():
            return bin_path
        raise ProviderError(
            f"FFMPEG_BIN 配置了但文件不存在: {bin_path}。"
            f"请检查 .env 中的 FFMPEG_BIN 是否指向有效的 ffmpeg.exe。"
        )

    found = shutil.which("ffmpeg")
    if found:
        return found

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    raise ProviderError(
        "ffmpeg 不可用：未在 PATH 中找到、未安装 imageio-ffmpeg、且 .env 未配置 FFMPEG_BIN。"
        "建议在 .env 中配置 FFMPEG_BIN=<完整 ffmpeg.exe 路径>，例如 "
        "C:/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe（winget 安装路径）。"
    )

router = APIRouter(prefix="/video", tags=["video-stitch"])

# 默认输出目录：与视频生成保持一致（默认 MEDIA_OUT_DIR / MINIMAX_OUT_DIR / VIDEO_DATA_DIR），fallback 到 ./data/uploads
_DEFAULT_OUT_DIR = (
    os.environ.get("STITCH_OUT_DIR")
    or os.environ.get("MEDIA_OUT_DIR")
    or os.environ.get("MINIMAX_OUT_DIR")
    or os.environ.get("VIDEO_DATA_DIR")
    or "./data/uploads"
)
_MAX_CLIPS = 200

# 默认输出分辨率（reencode 模式生效）：抖音 9:16 竖屏。
# 通过 STITCH_TARGET 环境变量覆盖（格式 "<width>x<height>"，例如 1920x1080 横屏）。
_DEFAULT_TARGET = os.environ.get("STITCH_TARGET", "1080x1920")
try:
    _TARGET_W, _TARGET_H = (int(x) for x in _DEFAULT_TARGET.lower().split("x"))
except Exception:
    _TARGET_W, _TARGET_H = 1080, 1920


def _ctx(request: Request) -> tuple[str, float]:
    return request.state.request_id, request.state.started_at


def _run_ffmpeg_concat(
    video_paths: list[str],
    output_path: Path,
    reencode: bool,
) -> None:
    """同步运行 ffmpeg 拼接（在 executor 中调用）。"""
    if len(video_paths) > _MAX_CLIPS:
        raise InvalidInputError(f"video_paths 最多支持 {_MAX_CLIPS} 个，当前 {len(video_paths)} 个。")

    for p in video_paths:
        if "'" in p:
            raise InvalidInputError(f"视频路径不能包含单引号字符: {p}")
        if not Path(p).exists():
            raise InvalidInputError(f"视频文件不存在: {p}")

    filelist_path: str | None = None
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        filelist_path = f.name
        for p in video_paths:
            abs_p = str(Path(p).resolve()).replace("\\", "/")
            f.write(f"file '{abs_p}'\n")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_bin = _resolve_ffmpeg_bin()
        if reencode:
            vf = (
                f"scale={_TARGET_W}:{_TARGET_H}:force_original_aspect_ratio=decrease,"
                f"pad={_TARGET_W}:{_TARGET_H}:(ow-iw)/2:(oh-ih)/2:black"
            )
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0",
                "-i", filelist_path,
                "-vf", vf,
                "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path),
            ]
        else:
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0",
                "-i", filelist_path,
                "-c", "copy",
                str(output_path),
            ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            stderr = result.stderr[-2000:] if result.stderr else "(no stderr)"
            if not reencode:
                raise ProviderError(
                    f"ffmpeg 拼接失败（流复制模式）。"
                    f"各片段编码参数可能不一致，请尝试 reencode=true。\n"
                    f"ffmpeg stderr: {stderr}"
                )
            raise ProviderError(f"ffmpeg 拼接失败（转码模式）。\nffmpeg stderr: {stderr}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise ProviderError(
                f"ffmpeg 退出码为 0，但输出文件缺失或为空: {output_path}"
            )

    finally:
        if filelist_path:
            try:
                Path(filelist_path).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# POST /video/stitch
# ---------------------------------------------------------------------------


@router.post(
    "/stitch",
    summary="将多个本地 MP4 文件拼接为单个视频",
)
async def stitch_videos(
    body: StitchRequest,
    request: Request,
) -> dict:
    """
    按 `video_paths` 列表的顺序将多个本地 MP4 文件拼接为单个 MP4。

    - `video_paths` 至少 2 个，最多 200 个，必须为服务端本地路径（已下载的视频）
    - `reencode=false`（默认）：流复制，极快；要求各片段编码参数一致
    - `reencode=true`：转码到 1920x1080 H.264，慢但保证兼容

    如果 `reencode=false` 失败，请用 `reencode=true` 重试。
    """
    rid, t0 = _ctx(request)

    if body.output_name and (
        "/" in body.output_name or "\\" in body.output_name or ".." in body.output_name
    ):
        raise InvalidInputError("output_name 不能包含路径分隔符或 '..'。")

    ts = str(int(time.time()))
    name = body.output_name or f"stitched_{uuid.uuid4().hex[:10]}_{ts}"
    out_dir = Path(_DEFAULT_OUT_DIR).resolve()
    output_path = out_dir / f"{name}.mp4"

    if not str(output_path).startswith(str(out_dir)):
        raise InvalidInputError(f"输出路径超出允许目录: {output_path}")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _run_ffmpeg_concat(body.video_paths, output_path, body.reencode),
    )

    data = StitchData(
        local_video_path=str(output_path),
        clip_count=len(body.video_paths),
    )
    return ok(data.model_dump(), rid, round((time.monotonic() - t0) * 1000, 2))
