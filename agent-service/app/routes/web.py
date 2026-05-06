"""
Web 路由层。
- POST /web/search   → Serper API
- POST /web/fetch    → Jina Reader

两个接口都接收 `query` / `url` 数组（即使只查一条也用单元素数组），批量内部并发；
单条失败不影响整批，失败信息在响应里逐条标注（见 WebSearchData.errors / WebFetchOne.error）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from app.infra.response import ok
from app.providers.jina_fetch_provider import JinaFetchProvider
from app.providers.serper_search_provider import SerperSearchProvider
from app.schemas.web import WebFetchRequest, WebSearchRequest
from app.services.web_service import WebService


router = APIRouter(prefix="/web", tags=["web"])


# ---------------------------------------------------------------------------
# 依赖注入：provider + service 工厂（懒加载单例）
# - provider 在第一次注入时实例化；env 缺 key 时直接 raise → 全局 handler → 502
# - service 持有 provider 引用，无状态，可单例
# ---------------------------------------------------------------------------

_search_provider: SerperSearchProvider | None = None
_fetch_provider: JinaFetchProvider | None = None
_web_service: WebService | None = None


def get_search_provider() -> SerperSearchProvider:
    global _search_provider
    if _search_provider is None:
        _search_provider = SerperSearchProvider()
    return _search_provider


def get_fetch_provider() -> JinaFetchProvider:
    global _fetch_provider
    if _fetch_provider is None:
        _fetch_provider = JinaFetchProvider()
    return _fetch_provider


def get_web_service(
    search_provider: SerperSearchProvider = Depends(get_search_provider),
    fetch_provider: JinaFetchProvider = Depends(get_fetch_provider),
) -> WebService:
    global _web_service
    if _web_service is None:
        _web_service = WebService(search_provider, fetch_provider)
    return _web_service


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


@router.post(
    "/search",
    summary="Serper Google 搜索（轻量替代 Playwright）",
)
async def web_search(
    body: WebSearchRequest,
    request: Request,
    service: WebService = Depends(get_web_service),
) -> dict:
    rid: str = request.state.request_id
    t0: float = request.state.started_at

    data = await service.search(body)
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    return ok(data.model_dump(), rid, elapsed)


@router.post(
    "/fetch",
    summary="Jina Reader 抓取页面 markdown（不做 LLM 提取）",
)
async def web_fetch(
    body: WebFetchRequest,
    request: Request,
    service: WebService = Depends(get_web_service),
) -> dict:
    rid: str = request.state.request_id
    t0: float = request.state.started_at

    data = await service.fetch(body)
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    return ok(data.model_dump(), rid, elapsed)
