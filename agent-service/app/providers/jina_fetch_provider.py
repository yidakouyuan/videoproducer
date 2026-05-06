"""
Jina Reader 抓取 provider。

GET https://r.jina.ai/{url} 返回站点正文 markdown，无需自己跑 headless 浏览器。
不在服务端做 LLM 二次提取——agent 自己就是 LLM，让它直接读 markdown。

支持多 API key 轮询（防单 key quota 耗尽），后端层重试 3 次。
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import List

import httpx

from app.infra.exceptions import ProviderError
from app.schemas.web import WebFetchOne


JINA_BASE = "https://r.jina.ai/"
TIMEOUT_S = 60.0
MAX_RETRIES = 3


class JinaFetchProvider:
    def __init__(self, api_keys: List[str] | None = None) -> None:
        if api_keys is None:
            raw = os.getenv("JINA_API_KEYS", "")
            api_keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not api_keys:
            # 跟 SerperSearchProvider 对齐：缺 key 直接 raise，避免 silent 走匿名调用导致 agent
            # 拿到 401/429 而不知道是 key 没配。第一次 web_fetch_url 请求时由路由统一返回 502。
            raise ProviderError("JINA_API_KEYS is not set")
        self._keys = api_keys

    def _pick_key(self) -> str:
        return random.choice(self._keys)

    async def fetch(self, url: str, max_chars: int = 30000) -> WebFetchOne:
        headers = {
            "X-Return-Format": "markdown",
            "Authorization": f"Bearer {self._pick_key()}",
        }

        last_status: int | None = None
        last_err: str | None = None
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.get(JINA_BASE + url, headers=headers)
                except httpx.HTTPError as e:
                    last_err = str(e)
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(min(8.0, 0.8 * (2 ** attempt)))
                        continue
                    break

                last_status = resp.status_code
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"jina {resp.status_code}: {resp.text[:200]}"
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(min(8.0, 0.8 * (2 ** attempt)))
                        # 重试时换一个 key（多 key 配置时有效；只有 1 个 key 时无效但无害）
                        headers["Authorization"] = f"Bearer {self._pick_key()}"
                        continue
                    break

                if resp.status_code != 200:
                    return WebFetchOne(
                        url=url,
                        ok=False,
                        status=resp.status_code,
                        error=resp.text[:300],
                    )

                md = resp.text or ""
                title = _extract_title(md)
                truncated = False
                if len(md) > max_chars:
                    md = md[:max_chars] + "\n\n[truncated]"
                    truncated = True
                return WebFetchOne(
                    url=url,
                    ok=True,
                    status=resp.status_code,
                    title=title,
                    markdown=md,
                    truncated=truncated,
                )

        return WebFetchOne(
            url=url,
            ok=False,
            status=last_status,
            error=last_err or "fetch failed after retries",
        )


def _extract_title(markdown: str) -> str | None:
    """Jina markdown 通常以 'Title: ...\\n\\n' 或 '# H1' 开头。取第一个非空线索。"""
    for line in markdown.splitlines()[:10]:
        line = line.strip()
        if line.lower().startswith("title:"):
            return line.split(":", 1)[1].strip() or None
        if line.startswith("# "):
            return line[2:].strip() or None
    return None
