"""
Web Service — 业务编排层。

职责：
- 接收 route 的请求对象
- 调用 SerperSearchProvider / JinaFetchProvider 做批量并发
- 聚合 partial-success（用 asyncio.gather(return_exceptions=True)，单条失败不影响其他）
- 把 domain 层结果（List[WebSearchHit] / WebFetchOne）转为响应 schema
- 渲染 ready-to-cite markdown，包含失败 query 的标注

Provider 的异常（ProviderError 等）在 search 路径上由 service 收口，转成 errors[i] 字符串；
在 fetch 路径上转成 WebFetchOne(ok=False, error=...)。
两个路径都不向上抛 ProviderError，避免批量调用因单条失败而整批 502。
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from app.providers.jina_fetch_provider import JinaFetchProvider
from app.providers.serper_search_provider import SerperSearchProvider, render_search_markdown
from app.schemas.web import (
    WebFetchData,
    WebFetchOne,
    WebFetchRequest,
    WebSearchData,
    WebSearchHit,
    WebSearchRequest,
)


class WebService:
    def __init__(
        self,
        search_provider: SerperSearchProvider,
        fetch_provider: JinaFetchProvider,
    ) -> None:
        self._search = search_provider
        self._fetch = fetch_provider

    async def search(self, req: WebSearchRequest) -> WebSearchData:
        raw = await asyncio.gather(
            *(
                self._search.search(q, req.top_k, req.country, req.lang)
                for q in req.query
            ),
            return_exceptions=True,
        )
        results: List[List[WebSearchHit]] = []
        errors: List[Optional[str]] = []
        for item in raw:
            if isinstance(item, Exception):
                results.append([])
                errors.append(str(item))
            else:
                results.append(item)
                errors.append(None)
        return WebSearchData(
            queries=list(req.query),
            results=results,
            errors=errors,
            markdown=render_search_markdown(req.query, results, errors),
        )

    async def fetch(self, req: WebFetchRequest) -> WebFetchData:
        raw = await asyncio.gather(
            *(self._fetch.fetch(u, req.max_chars) for u in req.url),
            return_exceptions=True,
        )
        items: List[WebFetchOne] = []
        for url, item in zip(req.url, raw):
            if isinstance(item, Exception):
                items.append(WebFetchOne(url=url, ok=False, error=str(item)))
            else:
                items.append(item)
        return WebFetchData(items=items)
