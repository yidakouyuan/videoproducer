"""
Tag / GraphRAG 查询接口的请求与响应 Schema。
对应接口：POST /tag/script_pack
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class ScriptPackRequest(BaseModel):
    tag: str = Field(..., description="目标标签，如 '清迈旅行'")
    top_k_communities: int = Field(3, ge=1, le=20, description="返回社区报告数量上限")
    top_k_cooccur: int = Field(20, ge=1, le=100, description="共现标签数量上限")
    lang: str = Field("zh", description="语言代码")
    version: str = Field("latest", description="GraphRAG 版本")


# ---------------------------------------------------------------------------
# 响应 data 内部结构
# ---------------------------------------------------------------------------


class TagCardSchema(BaseModel):
    tag: str
    summary_1_2_sentences: str


class FindingItemSchema(BaseModel):
    summary: str
    explanation: str


class CommunityReportSchema(BaseModel):
    community_id: str
    title: str
    summary: Optional[str] = None
    findings: List[FindingItemSchema] = []
    rating: Optional[float] = None
    report_source: str = "template"
    member_tags: List[str] = []


class CooccurItemSchema(BaseModel):
    tag: str
    w_count: int
    w_recent: int


class EvidencePackSchema(BaseModel):
    tag: str
    top_titles: List[str] = []
    stats_snapshot: Dict[str, Any] = {}
    cooccur_topk: List[Dict[str, Any]] = []


class ScriptPackData(BaseModel):
    """POST /tag/script_pack 的 data 字段，严格对齐接口文档输出结构。"""

    tag: str
    canonical_topic: str
    tag_card: Optional[TagCardSchema] = None
    community_reports: List[CommunityReportSchema] = []
    evidence_packs: List[EvidencePackSchema] = []
    search_seeds: Dict[str, List[str]] = {}
