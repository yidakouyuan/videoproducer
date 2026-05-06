"""
GraphRAG ScriptPack Provider。

从 tag_knowledge.db（SQLite，只读）查询 tag 信息，组装 ScriptPack。
数据库由 video-agent-system/tag_knowledge_db/build_tag_db.py 离线构建。

查询路径：
  输入 tag
    → normalize(tag)
    → canonical_tags / tag_aliases  找 canonical_tag_id
    → tag_cards                     → tag_card.summary
    → community_members + communities → community_reports
    → tag_cooccurrence + canonical_tags → cooccur_topk
    → canonical_tag_stats           → top_titles / stats_snapshot
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional

from app.domain.models import (
    CommunityReport,
    EvidencePack,
    FindingItem,
    ScriptPack,
    TagCard,
)
from app.infra.exceptions import NotFoundError


def _normalize(tag: str) -> str:
    """与 tag_db_lib.normalize_tag() 保持一致：NFKC + 去# + 去空格 + 小写。"""
    t = unicodedata.normalize("NFKC", tag)
    t = t.lstrip("#").strip().lower()
    return t[:64]


class GraphRAGScriptPackProvider:
    """读取 tag_knowledge.db 实现 ScriptPackProvider Protocol。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        # 只读模式，WAL 兼容
        uri = f"file:{self._db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_script_pack(
        self,
        tag: str,
        top_k_communities: int,
        top_k_cooccur: int,
        lang: str,
        version: str,
    ) -> ScriptPack:
        norm = _normalize(tag)
        tag_id, canonical_name = self._resolve_tag(norm)
        if tag_id is None:
            raise NotFoundError(f"tag '{tag}' not found in GraphRAG knowledge base")

        tag_card = self._get_tag_card(tag_id, canonical_name)
        community_reports = self._get_community_reports(tag_id, top_k_communities)
        evidence_pack = self._get_evidence_pack(tag_id, canonical_name, top_k_cooccur)
        search_seeds = self._build_search_seeds(tag_id, canonical_name, top_k_cooccur)

        return ScriptPack(
            canonical_topic=canonical_name,
            tag_card=tag_card,
            community_reports=community_reports,
            evidence_packs=[evidence_pack] if evidence_pack else [],
            search_seeds=search_seeds,
        )

    # ------------------------------------------------------------------
    # 内部查询
    # ------------------------------------------------------------------

    def _resolve_tag(self, norm: str) -> tuple[Optional[int], str]:
        """先查 canonical_tags（精确匹配），再查 tag_aliases。返回 (tag_id, canonical_name)。"""
        row = self._conn.execute(
            "SELECT canonical_tag_id, canonical_name FROM canonical_tags "
            "WHERE canonical_name = ? AND merged_into IS NULL LIMIT 1",
            (norm,),
        ).fetchone()
        if row:
            return row["canonical_tag_id"], row["canonical_name"]

        row = self._conn.execute(
            "SELECT ct.canonical_tag_id, ct.canonical_name "
            "FROM tag_aliases ta "
            "JOIN canonical_tags ct ON ta.canonical_tag_id = ct.canonical_tag_id "
            "WHERE ta.raw_tag_norm = ? AND ct.merged_into IS NULL LIMIT 1",
            (norm,),
        ).fetchone()
        if row:
            return row["canonical_tag_id"], row["canonical_name"]

        return None, norm

    def _get_tag_card(self, tag_id: int, canonical_name: str) -> Optional[TagCard]:
        row = self._conn.execute(
            "SELECT card_text FROM tag_cards WHERE canonical_tag_id = ?",
            (tag_id,),
        ).fetchone()
        if not row:
            return None
        return TagCard(tag=canonical_name, summary_1_2_sentences=row["card_text"])

    def _get_community_reports(self, tag_id: int, top_k: int) -> list[CommunityReport]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT
                c.community_id,
                c.report_text,
                c.report_title,
                c.report_summary,
                c.report_rating,
                c.report_findings_json,
                c.report_source,
                c.level
            FROM community_members cm
            JOIN communities c ON cm.community_id = c.community_id
            WHERE cm.canonical_tag_id = ?
            ORDER BY c.level DESC, c.topic_count DESC
            LIMIT ?
            """,
            (tag_id, top_k),
        ).fetchall()

        reports = []
        for r in rows:
            # title：优先 LLM 产出的 report_title，降级用 report_text 首句
            title = r["report_title"] or _first_sentence(r["report_text"] or "")

            # summary
            summary = r["report_summary"] or None

            # findings
            findings: list[FindingItem] = []
            if r["report_findings_json"]:
                try:
                    raw = json.loads(r["report_findings_json"])
                    findings = [
                        FindingItem(
                            summary=f.get("summary", ""),
                            explanation=f.get("explanation", ""),
                        )
                        for f in raw
                        if isinstance(f, dict)
                    ]
                except (json.JSONDecodeError, TypeError):
                    pass

            # 社区成员标签名（top-5）
            member_rows = self._conn.execute(
                """
                SELECT ct.canonical_name
                FROM community_members cm
                JOIN canonical_tags ct ON cm.canonical_tag_id = ct.canonical_tag_id
                WHERE cm.community_id = ?
                ORDER BY cm.member_rank
                LIMIT 5
                """,
                (r["community_id"],),
            ).fetchall()
            member_tags = [m["canonical_name"] for m in member_rows]

            reports.append(
                CommunityReport(
                    community_id=str(r["community_id"]),
                    title=title,
                    summary=summary,
                    findings=findings,
                    rating=r["report_rating"],
                    report_source=r["report_source"] or "template",
                    member_tags=member_tags,
                )
            )
        return reports

    def _get_evidence_pack(
        self, tag_id: int, canonical_name: str, top_k_cooccur: int
    ) -> Optional[EvidencePack]:
        stats_row = self._conn.execute(
            "SELECT video_count, digg_sum, collect_sum, comment_sum, share_sum, "
            "score, title_samples_json FROM canonical_tag_stats WHERE canonical_tag_id = ?",
            (tag_id,),
        ).fetchone()
        if not stats_row:
            return None

        top_titles: list[str] = []
        if stats_row["title_samples_json"]:
            try:
                samples = json.loads(stats_row["title_samples_json"])
                top_titles = [s["title"] for s in samples if isinstance(s, dict) and "title" in s]
            except (json.JSONDecodeError, TypeError):
                pass

        stats_snapshot = {
            "video_count": stats_row["video_count"],
            "digg_sum": stats_row["digg_sum"],
            "collect_sum": stats_row["collect_sum"],
            "comment_sum": stats_row["comment_sum"],
            "share_sum": stats_row["share_sum"],
            "score": stats_row["score"],
        }

        cooccur_topk = self._get_cooccur(tag_id, top_k_cooccur)

        return EvidencePack(
            tag=canonical_name,
            top_titles=top_titles,
            stats_snapshot=stats_snapshot,
            cooccur_topk=cooccur_topk,
        )

    def _get_cooccur(self, tag_id: int, top_k: int) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                CASE WHEN src_tag_id = ? THEN dst_tag_id ELSE src_tag_id END AS other_id,
                co_cnt_total,
                co_cnt_7d,
                decayed_weight
            FROM tag_cooccurrence
            WHERE src_tag_id = ? OR dst_tag_id = ?
            ORDER BY decayed_weight DESC
            LIMIT ?
            """,
            (tag_id, tag_id, tag_id, top_k),
        ).fetchall()

        result = []
        for row in rows:
            name_row = self._conn.execute(
                "SELECT canonical_name FROM canonical_tags WHERE canonical_tag_id = ?",
                (row["other_id"],),
            ).fetchone()
            if name_row:
                result.append({
                    "tag": name_row["canonical_name"],
                    "w_count": row["co_cnt_total"],
                    "w_recent": row["co_cnt_7d"],
                })
        return result

    def _build_search_seeds(
        self, tag_id: int, canonical_name: str, top_k: int
    ) -> dict[str, list[str]]:
        """用共现 top-k 标签名生成搜索词建议。"""
        cooccur = self._get_cooccur(tag_id, min(top_k, 10))
        related = [c["tag"] for c in cooccur[:5]]

        douyin_queries = [canonical_name] + [f"{canonical_name} {t}" for t in related[:3]]
        web_queries = [f"{canonical_name} 攻略"] + [f"{canonical_name} {t}" for t in related[:2]]

        return {
            "douyin_queries": douyin_queries,
            "web_queries": web_queries,
        }


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    """取文本第一句（以。！？\n 分割），最多 50 字。"""
    for sep in ("。", "！", "？", "\n"):
        idx = text.find(sep)
        if idx != -1:
            return text[: idx + 1][:50]
    return text[:50]
