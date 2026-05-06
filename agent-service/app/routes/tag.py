"""
Tag 路由层。
对外暴露：POST /tag/script_pack
"""
from __future__ import annotations

import time

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.infra.response import ok
from app.infra.exceptions import NotFoundError
from app.providers.base import ScriptPackProvider
from app.providers.local_script_pack_provider import LocalScriptPackProvider
from app.providers.mock_script_pack_provider import MockScriptPackProvider
from app.schemas.tag import ScriptPackData, ScriptPackRequest
from app.services.tag_service import TagService

router = APIRouter(prefix="/tag", tags=["tag"])


# ---------------------------------------------------------------------------
# 依赖注入：provider 工厂
# TAG_DB_PATH 有效时用真实 GraphRAG provider，否则降级到 mock。
# ---------------------------------------------------------------------------

_provider: ScriptPackProvider | None = None


class FallbackScriptPackProvider:
    def __init__(self, providers: list[ScriptPackProvider]) -> None:
        self.providers = providers

    async def get_script_pack(
        self,
        tag: str,
        top_k_communities: int,
        top_k_cooccur: int,
        lang: str,
        version: str,
    ):
        last_not_found: NotFoundError | None = None
        for provider in self.providers:
            try:
                return await provider.get_script_pack(tag, top_k_communities, top_k_cooccur, lang, version)
            except NotFoundError as exc:
                last_not_found = exc
        if last_not_found is not None:
            raise last_not_found
        raise NotFoundError(f"tag '{tag}' not found")


def get_script_pack_provider() -> ScriptPackProvider:
    global _provider
    if _provider is None:
        providers: list[ScriptPackProvider] = []
        db_path = os.getenv("TAG_DB_PATH", "")
        if db_path and Path(db_path).exists():
            from app.providers.graphrag_script_pack_provider import GraphRAGScriptPackProvider
            providers.append(GraphRAGScriptPackProvider(db_path))
        providers.append(LocalScriptPackProvider())
        providers.append(MockScriptPackProvider())
        _provider = FallbackScriptPackProvider(providers)
    return _provider


def get_tag_service(
    provider: ScriptPackProvider = Depends(get_script_pack_provider),
) -> TagService:
    return TagService(provider=provider)


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


@router.post(
    "/script_pack",
    summary="查询 Tag 的 ScriptPack（GraphRAG 知识起点）",
    response_description="ScriptPack 数据，包含 TagCard、CommunityReport、EvidencePack",
)
async def get_script_pack(
    body: ScriptPackRequest,
    request: Request,
    service: TagService = Depends(get_tag_service),
) -> dict:
    """
    根据 tag 查询 GraphRAG 离线知识结果，作为研究阶段的知识起点。

    - tag 不存在 → 404 NOT_FOUND
    - 下游查询服务不可用 → 502 PROVIDER_ERROR
    """
    rid: str = request.state.request_id
    t0: float = request.state.started_at

    data: ScriptPackData = await service.get_script_pack(body)

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    return ok(data.model_dump(), rid, elapsed)
