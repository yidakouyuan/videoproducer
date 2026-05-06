"""
FastAPI 应用入口。
"""
from __future__ import annotations

import os
import time

from dotenv import load_dotenv

load_dotenv()  # 从工作目录的 .env 文件加载环境变量

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.infra.exceptions import AppError
from app.infra.response import RequestContextMiddleware, err
from app.services.feishu_observer_service import recover_feishu_observers

app = FastAPI(
    title="OpenClaw Agent API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

app.add_middleware(RequestContextMiddleware)


# ---------------------------------------------------------------------------
# 统一异常处理
# ---------------------------------------------------------------------------


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return err(
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        http_status=exc.http_status,
        extra=exc.extra,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return err(
        code="INTERNAL_ERROR",
        message=str(exc),
        request_id=request_id,
        http_status=500,
    )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/health")
async def health(request: Request) -> dict:
    request_id = getattr(request.state, "request_id", "unknown")
    started_at = getattr(request.state, "started_at", time.monotonic())
    elapsed_ms = round((time.monotonic() - started_at) * 1000, 2)
    return {
        "ok": True,
        "data": {"status": "ok"},
        "meta": {"request_id": request_id, "elapsed_ms": elapsed_ms},
    }


@app.on_event("startup")
async def recover_feishu_runs_on_startup() -> None:
    await recover_feishu_observers()


# ---------------------------------------------------------------------------
# 挂载路由
# ---------------------------------------------------------------------------

from app.routes import feishu, image_generate, media, runs, stats, tag, transcribe, video_analyze, video_generate, video_stitch, web  # noqa: E402

app.include_router(tag.router)
app.include_router(media.router)
app.include_router(video_analyze.router)
app.include_router(transcribe.router)
app.include_router(video_generate.router)
app.include_router(image_generate.router)
app.include_router(video_stitch.router)
app.include_router(stats.router)
app.include_router(web.router)
app.include_router(feishu.router)
app.include_router(runs.router)

# ---------------------------------------------------------------------------
# 静态文件：下载的视频通过 /videos/{media_id}.mp4 访问
# object_url = SERVER_BASE_URL/videos/{media_id}.mp4
# ---------------------------------------------------------------------------

_video_dir = os.environ.get("VIDEO_DATA_DIR", "c:/openclaw_agent/data/videos")
os.makedirs(_video_dir, exist_ok=True)
app.mount("/videos", StaticFiles(directory=_video_dir), name="videos")
