"""
Mock ScriptPack Provider。

行为：
- tag 存在于 MOCK_DB 时返回对应数据
- tag 不存在时抛出 NotFoundError（模拟真实 GraphRAG 查库的行为）
- top_k_communities / top_k_cooccur 参数会对结果做截断，贴近真实语义

替换成真实实现时：
1. 新建 app/providers/graphrag_provider.py，实现相同方法签名
2. 在 app/routes/tag.py 的 get_script_pack_provider() 里换掉实例
3. 本文件保留，供测试使用
"""
from __future__ import annotations

from app.domain.models import (
    CommunityReport,
    EvidencePack,
    ScriptPack,
    TagCard,
)
from app.infra.exceptions import NotFoundError

# ---------------------------------------------------------------------------
# Mock 数据库（tag → ScriptPack 原始数据）
# ---------------------------------------------------------------------------

_MOCK_DB: dict[str, dict] = {
    "清迈旅行": {
        "canonical_topic": "清迈旅行",
        "tag_card": TagCard(
            tag="清迈旅行",
            summary_1_2_sentences="适合做路线清单、避坑、预算拆解类视频。",
        ),
        "community_reports": [
            CommunityReport(
                community_id="L2-001",
                title="清迈咖啡馆与拍照路线",
                summary="适合路线规划、拍照打卡类选题。",
                member_tags=["清迈咖啡馆", "清迈拍照", "ins风"],
            ),
            CommunityReport(
                community_id="L2-002",
                title="清迈美食与夜市攻略",
                summary="美食推荐与夜市地图类内容热度高。",
                member_tags=["清迈美食", "清迈夜市", "泰国美食"],
            ),
            CommunityReport(
                community_id="L2-003",
                title="清迈预算与交通全攻略",
                summary="预算拆解与交通住宿信息需求旺盛。",
                member_tags=["清迈预算", "清迈交通", "穷游"],
            ),
        ],
        "evidence_packs": [
            EvidencePack(
                tag="清迈咖啡馆",
                top_titles=["清迈最美咖啡馆合集", "清迈ins风咖啡馆TOP10"],
                stats_snapshot={"post_count": 1234, "hot_score": 0.81},
                cooccur_topk=[
                    {"tag": "清迈拍照", "w_count": 42, "w_recent": 7},
                    {"tag": "泰国旅行", "w_count": 38, "w_recent": 5},
                    {"tag": "东南亚穷游", "w_count": 27, "w_recent": 3},
                ],
            ),
            EvidencePack(
                tag="清迈美食",
                top_titles=["清迈必吃美食清单", "清迈夜市避坑指南"],
                stats_snapshot={"post_count": 987, "hot_score": 0.74},
                cooccur_topk=[
                    {"tag": "泰国美食", "w_count": 55, "w_recent": 9},
                    {"tag": "清迈旅行", "w_count": 44, "w_recent": 6},
                ],
            ),
        ],
        "search_seeds": {
            "douyin_queries": [
                "清迈 3天2夜 路线",
                "清迈 咖啡馆 拍照",
                "清迈 美食 避坑",
            ],
            "web_queries": [
                "清迈 旅行 攻略 避坑",
                "清迈 必去景点 2026",
                "清迈 预算 穷游",
            ],
        },
    },
    "泰国旅行": {
        "canonical_topic": "泰国旅行",
        "tag_card": TagCard(
            tag="泰国旅行",
            summary_1_2_sentences="适合做城市对比、签证攻略、出行季节推荐类视频。",
        ),
        "community_reports": [
            CommunityReport(
                community_id="L2-010",
                title="泰国热门城市对比",
                summary="城市对比选题适合推荐流，数据显示高完播率。",
                member_tags=["曼谷", "清迈", "普吉岛", "芭提雅"],
            ),
        ],
        "evidence_packs": [
            EvidencePack(
                tag="泰国签证",
                top_titles=["泰国落地签攻略2026", "泰国免签最新政策"],
                stats_snapshot={"post_count": 2100, "hot_score": 0.91},
                cooccur_topk=[
                    {"tag": "东南亚旅行", "w_count": 88, "w_recent": 12},
                ],
            ),
        ],
        "search_seeds": {
            "douyin_queries": ["泰国 签证 攻略", "泰国 最佳旅游季节"],
            "web_queries": ["泰国 免签 2026", "泰国旅游 花费"],
        },
    },
}


# ---------------------------------------------------------------------------
# Mock Provider 实现
# ---------------------------------------------------------------------------


class MockScriptPackProvider:
    """结构严格对齐 ScriptPackProvider Protocol。"""

    async def get_script_pack(
        self,
        tag: str,
        top_k_communities: int,
        top_k_cooccur: int,
        lang: str,
        version: str,
    ) -> ScriptPack:
        entry = _MOCK_DB.get(tag)
        if entry is None:
            raise NotFoundError(f"tag '{tag}' not found in GraphRAG knowledge base")

        # 按参数截断，模拟真实查询语义
        community_reports = entry["community_reports"][:top_k_communities]

        evidence_packs: list[EvidencePack] = []
        for ep in entry["evidence_packs"]:
            trimmed = EvidencePack(
                tag=ep.tag,
                top_titles=ep.top_titles,
                stats_snapshot=ep.stats_snapshot,
                cooccur_topk=ep.cooccur_topk[:top_k_cooccur],
            )
            evidence_packs.append(trimmed)

        return ScriptPack(
            canonical_topic=entry["canonical_topic"],
            tag_card=entry["tag_card"],
            community_reports=community_reports,
            evidence_packs=evidence_packs,
            search_seeds=entry["search_seeds"],
        )
