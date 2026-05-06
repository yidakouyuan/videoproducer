"""
Local ScriptPack provider backed by workspace-tag-matcher/data/script_packs.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.domain.models import CommunityReport, EvidencePack, ScriptPack, TagCard
from app.infra.exceptions import NotFoundError


class LocalScriptPackProvider:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or _default_script_pack_path()).expanduser()

    async def get_script_pack(
        self,
        tag: str,
        top_k_communities: int,
        top_k_cooccur: int,
        lang: str,
        version: str,
    ) -> ScriptPack:
        pack = self._match(tag)
        if pack is None:
            raise NotFoundError(f"tag '{tag}' not found in local script_packs.json")

        canonical_topic = str(pack["canonical_topic"])
        tags = [str(item) for item in pack.get("tags", [])]
        evidence_notes = [str(item) for item in pack.get("evidence_notes", [])]
        return ScriptPack(
            canonical_topic=canonical_topic,
            tag_card=TagCard(
                tag=canonical_topic,
                summary_1_2_sentences=f"本地 fallback script pack：{canonical_topic}",
            ),
            community_reports=[
                CommunityReport(
                    community_id="local-001",
                    title=f"{canonical_topic} 本地 fallback",
                    summary="本地 Mac 开发兜底数据，用于 tag_get_script_pack 不命中真实 GraphRAG 时继续 pipeline。",
                    findings=[],
                    member_tags=tags[:top_k_cooccur],
                    report_source="local_fallback",
                )
            ][:top_k_communities],
            evidence_packs=[
                EvidencePack(
                    tag=canonical_topic,
                    top_titles=evidence_notes,
                    stats_snapshot={"source": "local_fallback"},
                    cooccur_topk=[{"tag": item, "w_count": 1, "w_recent": 1} for item in tags[:top_k_cooccur]],
                )
            ],
            search_seeds={
                "douyin_queries": [str(item) for item in pack.get("douyin_queries", [])],
                "web_queries": [str(item) for item in pack.get("web_queries", [])],
                "hook_examples": [str(item) for item in pack.get("hook_examples", [])],
                "shot_suggestions": [str(item) for item in pack.get("shot_suggestions", [])],
            },
        )

    def _match(self, query: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        packs = json.loads(self.path.read_text(encoding="utf-8"))
        best_pack: dict[str, Any] | None = None
        best_score = 0
        for pack in packs:
            terms = [pack.get("canonical_topic", ""), *pack.get("tags", [])]
            score = sum(1 for term in terms if term and (term in query or query in term))
            if score > best_score:
                best_score = score
                best_pack = pack
        return best_pack if best_score > 0 else None


def _default_script_pack_path() -> Path:
    env_path = os.getenv("TAG_FALLBACK_SCRIPT_PACK_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[3] / "workspace-tag-matcher" / "data" / "script_packs.json"
