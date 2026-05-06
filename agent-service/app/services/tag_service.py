"""
Tag Service — 业务编排层。

职责：
- 接收来自 route 的请求对象
- 调用 provider 获取 domain 对象（ScriptPack）
- 将 domain 对象转换为 HTTP 响应 schema（ScriptPackData）
- 不感知 request_id、HTTP status，只抛 AppError 子类

provider 的异常（NotFoundError / ProviderError）直接向上透传，
由 main.py 的全局异常处理器统一转为 ErrorResponse。
"""
from __future__ import annotations

from dataclasses import asdict

from app.domain.models import CommunityReport, EvidencePack, FindingItem, ScriptPack, TagCard
from app.providers.base import ScriptPackProvider
from app.schemas.tag import (
    CommunityReportSchema,
    EvidencePackSchema,
    FindingItemSchema,
    ScriptPackData,
    ScriptPackRequest,
    TagCardSchema,
)


class TagService:
    def __init__(self, provider: ScriptPackProvider) -> None:
        self._provider = provider

    async def get_script_pack(self, req: ScriptPackRequest) -> ScriptPackData:
        """调用 provider 查询 ScriptPack，转换为响应 schema。"""
        script_pack: ScriptPack = await self._provider.get_script_pack(
            tag=req.tag,
            top_k_communities=req.top_k_communities,
            top_k_cooccur=req.top_k_cooccur,
            lang=req.lang,
            version=req.version,
        )
        return _to_schema(tag=req.tag, script_pack=script_pack)


# ---------------------------------------------------------------------------
# domain → schema 转换（私有，只在本层使用）
# ---------------------------------------------------------------------------


def _to_schema(tag: str, script_pack: ScriptPack) -> ScriptPackData:
    return ScriptPackData(
        tag=tag,
        canonical_topic=script_pack.canonical_topic,
        tag_card=_tag_card_schema(script_pack.tag_card),
        community_reports=[_community_report_schema(r) for r in script_pack.community_reports],
        evidence_packs=[_evidence_pack_schema(e) for e in script_pack.evidence_packs],
        search_seeds=script_pack.search_seeds,
    )


def _tag_card_schema(tc: TagCard | None) -> TagCardSchema | None:
    if tc is None:
        return None
    return TagCardSchema(
        tag=tc.tag,
        summary_1_2_sentences=tc.summary_1_2_sentences,
    )


def _community_report_schema(r: CommunityReport) -> CommunityReportSchema:
    return CommunityReportSchema(
        community_id=str(r.community_id),
        title=r.title,
        summary=r.summary,
        findings=[FindingItemSchema(summary=f.summary, explanation=f.explanation) for f in r.findings],
        rating=r.rating,
        report_source=r.report_source,
        member_tags=r.member_tags,
    )


def _evidence_pack_schema(e: EvidencePack) -> EvidencePackSchema:
    return EvidencePackSchema(
        tag=e.tag,
        top_titles=e.top_titles,
        stats_snapshot=e.stats_snapshot,
        cooccur_topk=e.cooccur_topk,
    )
