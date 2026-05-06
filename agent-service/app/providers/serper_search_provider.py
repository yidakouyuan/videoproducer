"""
Serper.dev 搜索 provider。

后端层重试 3 次（agent 不感知）：429 / 5xx 时指数退避 0.8s → 1.6s → 3.2s。
3 次都失败抛 ProviderError，让 agent 自己决定要不要 fallback 到 browser。
"""
from __future__ import annotations

import asyncio
import os
from typing import List

import httpx

from app.infra.exceptions import ProviderError
from app.schemas.web import WebSearchHit


SERPER_URL = "https://google.serper.dev/search"
TIMEOUT_S = 20.0
MAX_RETRIES = 3


class SerperSearchProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("SERPER_API_KEY", "")
        if not self._api_key:
            raise ProviderError("SERPER_API_KEY is not set")

    async def search(
        self,
        query: str,
        top_k: int = 10,
        country: str = "cn",
        lang: str = "zh",
    ) -> List[WebSearchHit]:
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": top_k, "gl": country, "hl": lang}

        last_err: Exception | None = None
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.post(SERPER_URL, headers=headers, json=payload)
                except httpx.HTTPError as e:
                    last_err = e
                    await asyncio.sleep(min(8.0, 0.8 * (2 ** attempt)))
                    continue

                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = ProviderError(f"Serper {resp.status_code}: {resp.text[:200]}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(min(8.0, 0.8 * (2 ** attempt)))
                        continue
                    break

                if resp.status_code != 200:
                    raise ProviderError(
                        f"Serper {resp.status_code}: {resp.text[:200]}",
                        extra={"query": query},
                    )

                data = resp.json()
                return _parse_organic(data)

        raise ProviderError(
            f"Serper failed after {MAX_RETRIES} retries: {last_err}",
            extra={"query": query},
        )


def _parse_organic(data: dict) -> List[WebSearchHit]:
    organic = data.get("organic") or []
    hits: List[WebSearchHit] = []
    for idx, item in enumerate(organic, start=1):
        url = item.get("link") or ""
        if not url:
            continue
        hits.append(
            WebSearchHit(
                title=item.get("title") or url,
                url=url,
                snippet=(item.get("snippet") or "").replace(
                    "Your browser can't play this video.", ""
                ).strip(),
                date=item.get("date"),
                source=item.get("source"),
                position=idx,
            )
        )
    return hits


def render_search_markdown(
    queries: List[str],
    results: List[List[WebSearchHit]],
    errors: List[str | None] | None = None,
) -> str:
    """
    把多条 query 的结果拼成 ready-to-cite markdown 块。

    `errors[i]` 非 None 表示该 query 失败 —— 在对应位置 render 一段错误提示，
    其余 query 不受影响。这跟 service 层的 `return_exceptions=True` 配合，
    实现批量调用部分成功部分失败时仍向 agent 返回可用的部分结果。
    """
    if errors is None:
        errors = [None] * len(queries)
    blocks: List[str] = []
    for q, hits, err in zip(queries, results, errors):
        if err:
            blocks.append(f"A Google search for '{q}' failed: {err}")
            continue
        if not hits:
            blocks.append(f"A Google search for '{q}' found 0 results.\n")
            continue
        lines = [f"A Google search for '{q}' found {len(hits)} results:", "", "## Web Results"]
        for h in hits:
            extra = ""
            if h.date:
                extra += f"\nDate published: {h.date}"
            if h.source:
                extra += f"\nSource: {h.source}"
            lines.append(f"{h.position}. [{h.title}]({h.url}){extra}\n{h.snippet}")
        blocks.append("\n\n".join(lines))
    return "\n\n=======\n\n".join(blocks)
