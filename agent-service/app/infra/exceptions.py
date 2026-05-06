"""
业务异常定义。所有可预期的业务错误都继承自 AppError。
"""
from __future__ import annotations


class AppError(Exception):
    """所有可预期业务异常的基类。"""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, extra: object = None) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class InvalidInputError(AppError):
    code = "INVALID_INPUT"
    http_status = 422


class ProviderError(AppError):
    """上游 provider（Gemini / OpenAI / 抖音）调用失败。"""

    code = "PROVIDER_ERROR"
    http_status = 502


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
