"""
统一 HTTP 响应 Pydantic v2 模型 + 异常定义。
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class ResponseMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str
    elapsed_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# 成功响应
# ---------------------------------------------------------------------------


class OkResponse(BaseModel, Generic[T]):
    """ok=true 时的统一响应体。"""

    model_config = ConfigDict(populate_by_name=True)

    ok: bool = True
    data: T
    meta: ResponseMeta


# ---------------------------------------------------------------------------
# 失败响应
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    extra: Optional[Any] = None


class ErrorResponse(BaseModel):
    """ok=false 时的统一响应体。"""

    model_config = ConfigDict(populate_by_name=True)

    ok: bool = False
    error: ErrorDetail
    meta: ResponseMeta
