"""
Local script-pack fallback for tag-matcher development.

This helper mirrors the prompt-level fallback that tag-matcher can perform by
reading workspace-tag-matcher/data/script_packs.json when tag_get_script_pack is
unregistered or the HTTP backend is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

DEFAULT_SCRIPT_PACK_PATH = Path(__file__).resolve().parents[1] / "data" / "script_packs.json"


def ground_topic(
    query: str,
    *,
    http_tool: Callable[[str], dict[str, Any]] | None = None,
    script_pack_path: str | Path = DEFAULT_SCRIPT_PACK_PATH,
) -> dict[str, Any]:
    text = query.strip()
    if not text:
        return {
            "ok": False,
            "error": "empty_input",
            "message": "用户输入为空，无法进行选题 grounding。",
        }

    candidates = _candidate_tags(text)
    warnings: list[str] = []

    if http_tool is not None:
        try:
            return _from_http_result(text, candidates[0], http_tool(candidates[0]), warnings)
        except Exception as exc:
            warnings.append(f"tag_get_script_pack unavailable: {exc}")

    local_pack = _match_local_pack(text, Path(script_pack_path))
    if local_pack is not None:
        return _from_local_pack(text, local_pack, "local_script_pack", warnings)

    warnings.append("local script_packs.json unavailable or no matching pack; generated minimal fallback")
    return _minimal_fallback(text, candidates[0], warnings)


def _candidate_tags(text: str) -> list[str]:
    candidates: list[str] = []
    keyword_map = [
        ("露营", "露营美食"),
        ("营地", "露营美食"),
        ("户外", "户外美食"),
        ("烧烤", "户外烧烤"),
        ("烤肉", "户外烧烤"),
        ("探店", "城市探店"),
        ("餐厅", "城市探店"),
    ]
    for keyword, tag in keyword_map:
        if keyword in text and tag not in candidates:
            candidates.append(tag)
    if not candidates:
        candidates.append(text[:24])
    return candidates


def _match_local_pack(text: str, path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    packs = json.loads(path.read_text(encoding="utf-8"))
    best_pack: dict[str, Any] | None = None
    best_score = 0
    for pack in packs:
        terms = [pack.get("canonical_topic", ""), *pack.get("tags", [])]
        score = sum(1 for term in terms if term and (term in text or any(ch in text for ch in term[:2])))
        if score > best_score:
            best_score = score
            best_pack = pack
    return best_pack if best_score > 0 else None


def _from_http_result(
    query: str,
    requested_tag: str,
    result: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    data = result.get("data", result)
    canonical_topic = data.get("canonical_topic") or requested_tag
    search_seeds = data.get("search_seeds") or {}
    grounding = {
        "requested_tag": requested_tag,
        "grounding_strength": "strong",
        "canonical_topic": canonical_topic,
        "tag_card": data.get("tag_card") or {},
        "community_reports": data.get("community_reports") or [],
        "evidence_packs": data.get("evidence_packs") or [],
        "search_seeds": search_seeds,
        "ambiguity_notes": [],
        "weaknesses": [],
        "source": "tag_get_script_pack",
    }
    return _result(query, [grounding], [canonical_topic], warnings)


def _from_local_pack(
    query: str,
    pack: dict[str, Any],
    source: str,
    warnings: list[str],
) -> dict[str, Any]:
    canonical_topic = pack["canonical_topic"]
    grounding = {
        "requested_tag": canonical_topic,
        "grounding_strength": "usable_but_broad",
        "canonical_topic": canonical_topic,
        "tag_card": {"tags": pack.get("tags", []), "summary": canonical_topic},
        "community_reports": [],
        "evidence_packs": [{"evidence_notes": pack.get("evidence_notes", [])}],
        "search_seeds": {
            "douyin_queries": pack.get("douyin_queries", []),
            "web_queries": pack.get("web_queries", []),
            "hook_examples": pack.get("hook_examples", []),
            "shot_suggestions": pack.get("shot_suggestions", []),
        },
        "ambiguity_notes": [],
        "weaknesses": ["本地 fallback 数据较小，覆盖面有限。"],
        "source": source,
    }
    return _result(query, [grounding], [canonical_topic], warnings)


def _minimal_fallback(query: str, tag: str, warnings: list[str]) -> dict[str, Any]:
    pack = {
        "canonical_topic": tag,
        "tags": [tag],
        "douyin_queries": [tag, query],
        "web_queries": [f"{tag} 短视频 脚本", f"{tag} 内容趋势"],
        "hook_examples": [f"30 秒看懂{tag}为什么值得拍"],
        "shot_suggestions": ["开场给主题场景", "中段展示关键动作或信息", "结尾给结果和记忆点"],
        "evidence_notes": ["minimal fallback，由用户输入直接生成，缺少外部证据。"],
    }
    result = _from_local_pack(query, pack, "minimal_fallback", warnings)
    result["grounding_results"][0]["grounding_strength"] = "usable_but_broad"
    return result


def _result(
    query: str,
    grounding_results: list[dict[str, Any]],
    best_matches: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok": True,
        "input_summary": {
            "full_user_query": query,
            "topic": best_matches[0] if best_matches else query,
            "language": "zh",
            "constraints": [],
        },
        "grounding_results": grounding_results,
        "best_matches": best_matches,
        "recommendation": best_matches[0] if best_matches else query,
        "notes_for_orchestrator": warnings,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--script-pack-path", default=str(DEFAULT_SCRIPT_PACK_PATH))
    args = parser.parse_args()
    print(json.dumps(ground_topic(args.query, script_pack_path=args.script_pack_path), ensure_ascii=False, indent=2))
