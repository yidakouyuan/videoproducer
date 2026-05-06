"""
Web 搜索 / 抓取的请求与响应模型。

设计目标：作为 OpenClaw agent 的轻量替代 Playwright 入口
- /web/search → Serper API
- /web/fetch  → Jina Reader (raw markdown, no LLM extraction)

agent 自身就是 LLM，不需要服务端二次提取，markdown 直接喂回去自己判断。

入参 query / url 始终是数组（plugin 端固定包数组），单条用 `["hello"]` 形式调用。
不用 Union[str, List[str]] 是为了避免 plugin TypeBox + OpenClaw runtime 解析 union 的兼容风险。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class WebSearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: List[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="query 数组（即使只查一条也用单元素数组 ['hello']）。批量并发执行。",
    )
    top_k: int = Field(10, ge=1, le=20)
    country: str = Field("cn", description="Serper gl 参数")
    lang: str = Field("zh", description="Serper hl 参数")


class WebSearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    date: Optional[str] = None
    source: Optional[str] = None
    position: Optional[int] = None


class WebSearchData(BaseModel):
    queries: List[str]
    results: List[List[WebSearchHit]]
    errors: List[Optional[str]] = Field(
        default_factory=list,
        description="与 queries 一一对应；成功时为 None，失败时为错误字符串。批量调用中部分失败不影响其他 query 的结果。",
    )
    markdown: str = Field(
        "",
        description="预渲染的 markdown，agent 可直接当作 evidence 块引用；失败的 query 在 markdown 里也有标注",
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


class WebFetchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: List[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="URL 数组（即使只抓一条也用单元素数组）。批量并发抓取。",
    )
    max_chars: int = Field(
        30000,
        ge=2000,
        le=80000,
        description="单页 markdown 截断上限，避免 trajectory 爆炸",
    )


class WebFetchOne(BaseModel):
    url: str
    ok: bool
    status: Optional[int] = None
    title: Optional[str] = None
    markdown: str = ""
    truncated: bool = False
    error: Optional[str] = None


class WebFetchData(BaseModel):
    items: List[WebFetchOne]
