"""
响应构建辅助函数 + request_id / elapsed_ms 中间件。
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.schemas.common import ErrorDetail, ErrorResponse, OkResponse, ResponseMeta


# ---------------------------------------------------------------------------
# 构建响应的便捷函数
# ---------------------------------------------------------------------------


def ok(data: Any, request_id: str, elapsed_ms: float | None = None) -> dict:
    return OkResponse(
        data=data,
        meta=ResponseMeta(request_id=request_id, elapsed_ms=elapsed_ms),
    ).model_dump(exclude_none=False)


def err(
    code: str,
    message: str,
    request_id: str,
    http_status: int = 500,
    extra: Any = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, extra=extra),
        meta=ResponseMeta(request_id=request_id),
    ).model_dump(exclude_none=True)
    return JSONResponse(status_code=http_status, content=body)


# ---------------------------------------------------------------------------
# 中间件：注入 request_id + elapsed_ms
# ---------------------------------------------------------------------------

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        request.state.started_at = time.monotonic()

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
