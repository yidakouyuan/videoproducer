#!/usr/bin/env python3
"""Run pending LLM tasks with OpenAI GPT API and apply updates to the DB."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

# ---------------------------------------------------------------------------
# GraphRAG integration: community report prompt + response model
# ---------------------------------------------------------------------------
_GRAPHRAG_PKG = THIS_DIR.parent / "graphrag" / "packages" / "graphrag"
if _GRAPHRAG_PKG.is_dir() and str(_GRAPHRAG_PKG) not in sys.path:
    sys.path.insert(0, str(_GRAPHRAG_PKG))

try:
    from graphrag.prompts.index.community_report import COMMUNITY_REPORT_PROMPT as _GRAPHRAG_COMMUNITY_REPORT_PROMPT
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse as _CommunityReportResponse,
    )
    _HAS_GRAPHRAG_PROMPTS = True
except ImportError:
    _GRAPHRAG_COMMUNITY_REPORT_PROMPT = None
    _CommunityReportResponse = None
    _HAS_GRAPHRAG_PROMPTS = False

from tag_db_lib import apply_llm_decisions_and_rebuild, connect_db, export_llm_tasks, init_schema


DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_DECISIONS_OUT = THIS_DIR / "data" / "llm_decisions.generated.json"

SUPPORTED_TASK_TYPES = (
    "raw_tag_synonym_review",
    "canonical_tag_kind_review",
    "tag_card_review",
    "community_report_review",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("empty model response")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    left = text.find("{")
    right = text.rfind("}")
    if left >= 0 and right > left:
        parsed = json.loads(text[left : right + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("response is not a valid JSON object")


def normalize_model_tag_name(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    while text.startswith("#"):
        text = text[1:].strip()
    text = re.sub(r"\s+", "", text)
    return text if text else fallback


def call_openai_chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:500]}")

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("OpenAI response content is empty")

    parsed = parse_json_response(content)
    usage = data.get("usage") or {}
    usage_summary = {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    return parsed, usage_summary


def build_prompt_for_task(task: dict[str, Any]) -> tuple[str, str]:
    task_type = str(task.get("task_type"))
    payload = task.get("payload") or {}
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)

    system_prompt = (
        "You are a strict JSON-only data annotation assistant for a Chinese short-video tag knowledge graph. "
        "Return only one JSON object that matches the requested schema."
    )

    if task_type == "raw_tag_synonym_review":
        user_prompt = (
            "任务类型: raw_tag_synonym_review\n"
            "目标: 判断 raw_tag 是否应归并到新的 canonical_name。\n"
            "规则:\n"
            "1) canonical_name 必须是简短标签短语，不带 #，无多余空格。\n"
            "2) 如果不确定，不要乱合并，保持当前 canonical。\n"
            "3) confidence 范围 [0,1]。\n"
            "只输出 JSON:\n"
            "{\n"
            '  "decision": "keep|merge",\n'
            '  "canonical_name": "string",\n'
            '  "confidence": 0.0,\n'
            '  "reason": "string"\n'
            "}\n"
            f"输入 payload:\n{payload_text}"
        )
        return system_prompt, user_prompt

    if task_type == "canonical_tag_kind_review":
        user_prompt = (
            "任务类型: canonical_tag_kind_review\n"
            "目标: 仅判断标签类型。\n"
            "规则:\n"
            "1) tag_kind 只能是 topic 或 campaign。\n"
            "2) topic=稳定内容主题；campaign=活动/挑战/运营入口。\n"
            "3) confidence 范围 [0,1]。\n"
            "只输出 JSON:\n"
            "{\n"
            '  "tag_kind": "topic|campaign",\n'
            '  "confidence": 0.0,\n'
            '  "reason": "string"\n'
            "}\n"
            f"输入 payload:\n{payload_text}"
        )
        return system_prompt, user_prompt

    if task_type == "tag_card_review":
        user_prompt = (
            "任务类型: tag_card_review\n"
            "目标: 输出更准确的 Tag Card 文案。\n"
            "规则:\n"
            "1) card_text 用中文，1-2 句，简洁，不空话。\n"
            "2) 要体现 tag 的使用场景和方向。\n"
            "3) evidence.key_signals 为最多 5 条短语。\n"
            "只输出 JSON:\n"
            "{\n"
            '  "card_text": "string",\n'
            '  "evidence": {\n'
            '    "key_signals": ["string"]\n'
            "  }\n"
            "}\n"
            f"输入 payload:\n{payload_text}"
        )
        return system_prompt, user_prompt

    if task_type == "community_report_review":
        # Build GraphRAG-style structured input from payload
        tags = payload.get("tags") or []
        relationships = payload.get("relationships") or []

        # Format Entities in graphrag CSV format: human_readable_id,title,description
        entity_lines = ["human_readable_id,title,description"]
        for t in tags:
            titles_str = " | ".join(str(ti) for ti in (t.get("top_titles") or []))
            description = (
                f"Douyin内容标签，出现在 {t.get('video_count', 0)} 个视频中"
                f"（热度分 {t.get('score', 0.0):.1f}）"
                + (f"；代表性标题：{titles_str}" if titles_str else "")
            )
            entity_lines.append(
                f"{t.get('id', '')},{t.get('canonical_name', '')},{description}"
            )

        # Format Relationships in graphrag CSV format: human_readable_id,source,target,description
        rel_lines = ["human_readable_id,source,target,description"]
        for r in relationships:
            description = (
                f"共现 {r.get('co_cnt_total', 0)} 次"
                f"（近7天 {r.get('co_cnt_7d', 0)} 次，衰减权重 {r.get('decayed_weight', 0.0):.3f}）"
            )
            rel_lines.append(
                f"{r.get('id', '')},{r.get('source', '')},{r.get('target', '')},{description}"
            )

        input_text = (
            "Entities\n\n"
            + "\n".join(entity_lines)
            + "\n\nRelationships\n\n"
            + "\n".join(rel_lines)
        )

        max_report_length = 500

        if _HAS_GRAPHRAG_PROMPTS and _GRAPHRAG_COMMUNITY_REPORT_PROMPT:
            # Use graphrag's official community report prompt directly
            user_prompt = _GRAPHRAG_COMMUNITY_REPORT_PROMPT.format(
                input_text=input_text,
                max_report_length=max_report_length,
            )
        else:
            # Fallback prompt if graphrag import failed
            user_prompt = (
                f"Write a community report in JSON format with keys: title, summary, rating (0-10), "
                f"rating_explanation, findings (list of {{summary, explanation}}).\n\n"
                f"Input data:\n{input_text}\n\nOutput:"
            )

        return system_prompt, user_prompt

    raise ValueError(f"unsupported task_type: {task_type}")


def mock_decision(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    task_type = str(task.get("task_type"))
    payload = task.get("payload") or {}
    if task_type == "raw_tag_synonym_review":
        return (
            {
                "decision": "keep",
                "canonical_name": payload.get("current_canonical_name") or payload.get("raw_tag_norm") or "",
                "confidence": 0.5,
                "reason": "mock",
            },
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    if task_type == "canonical_tag_kind_review":
        current = str(payload.get("current_tag_kind") or "topic")
        if current not in {"topic", "campaign"}:
            current = "topic"
        return (
            {
                "tag_kind": current,
                "confidence": 0.5,
                "reason": "mock",
            },
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    if task_type == "tag_card_review":
        return (
            {
                "card_text": str(payload.get("template_card_text") or ""),
                "evidence": {"key_signals": ["mock"]},
            },
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    if task_type == "community_report_review":
        tags = payload.get("tags") or []
        top_names = "、".join(t.get("canonical_name", "") for t in tags[:3])
        return (
            {
                "title": f"{top_names}社区" if top_names else "内容社区",
                "summary": str(payload.get("template_report") or ""),
                "rating": 5.0,
                "rating_explanation": "mock评分，仅供测试。",
                "findings": [{"summary": "mock洞察", "explanation": "mock模式，无真实分析。"}],
            },
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
    raise ValueError(f"unsupported task_type: {task_type}")


def convert_model_output_to_decision(task: dict[str, Any], model_json: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("task_type"))
    task_key = str(task.get("task_key"))
    payload = task.get("payload") or {}

    out: dict[str, Any] = {
        "synonym_updates": [],
        "kind_updates": [],
        "tag_card_updates": [],
        "community_report_updates": [],
        "complete_task_keys": [task_key],
    }

    if task_type == "raw_tag_synonym_review":
        raw_tag = str(payload.get("raw_tag_norm") or "")
        current_name = str(payload.get("current_canonical_name") or raw_tag)
        decision = str(model_json.get("decision") or "keep").strip().lower()
        canonical_name = normalize_model_tag_name(model_json.get("canonical_name"), fallback=current_name)
        confidence = model_json.get("confidence")
        if decision in {"merge", "update", "change"}:
            out["synonym_updates"].append(
                {
                    "raw_tag": raw_tag,
                    "canonical_name": canonical_name,
                    "alias_source": "llm",
                    "confidence": confidence,
                }
            )
        return out

    if task_type == "canonical_tag_kind_review":
        canonical_name = normalize_model_tag_name(
            payload.get("canonical_name"),
            fallback=str(payload.get("canonical_name") or ""),
        )
        tag_kind = str(model_json.get("tag_kind") or "").strip().lower()
        if tag_kind not in {"topic", "campaign"}:
            fallback = str(payload.get("current_tag_kind") or "").strip().lower()
            tag_kind = fallback if fallback in {"topic", "campaign"} else "topic"
        out["kind_updates"].append(
            {
                "canonical_name": canonical_name,
                "tag_kind": tag_kind,
                "kind_source": "llm",
                "confidence": model_json.get("confidence"),
            }
        )
        return out

    if task_type == "tag_card_review":
        canonical_name = normalize_model_tag_name(
            payload.get("canonical_name"),
            fallback=str(payload.get("canonical_name") or ""),
        )
        card_text = model_json.get("card_text")
        if not isinstance(card_text, str) or not card_text.strip():
            card_text = str(payload.get("template_card_text") or "").strip()
        evidence = model_json.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        out["tag_card_updates"].append(
            {
                "canonical_name": canonical_name,
                "card_text": card_text,
                "source": "llm",
                "evidence": evidence,
            }
        )
        return out

    if task_type == "community_report_review":
        community_id = payload.get("community_id")

        # Validate with graphrag's CommunityReportResponse model when available
        parsed: _CommunityReportResponse | None = None
        if _HAS_GRAPHRAG_PROMPTS and _CommunityReportResponse is not None:
            try:
                parsed = _CommunityReportResponse.model_validate(model_json)
            except Exception:
                parsed = None

        if parsed is not None:
            title = parsed.title
            summary = parsed.summary
            rating = parsed.rating
            rating_explanation = parsed.rating_explanation
            findings = [{"summary": f.summary, "explanation": f.explanation} for f in parsed.findings]
        else:
            title = model_json.get("title")
            summary = model_json.get("summary")
            rating = model_json.get("rating")
            rating_explanation = model_json.get("rating_explanation")
            findings = model_json.get("findings")

        has_structured = (isinstance(title, str) and title.strip()) or (isinstance(summary, str) and summary.strip())
        if not has_structured:
            report_text = model_json.get("report_text") or str(payload.get("template_report") or "")
            out["community_report_updates"].append(
                {"community_id": community_id, "report_text": report_text, "source": "llm"}
            )
        else:
            out["community_report_updates"].append(
                {
                    "community_id": community_id,
                    "title": title,
                    "summary": summary,
                    "rating": rating,
                    "rating_explanation": rating_explanation,
                    "findings": findings if isinstance(findings, list) else [],
                    "source": "llm",
                }
            )
        return out

    raise ValueError(f"unsupported task_type: {task_type}")


def merge_decisions(all_decisions: dict[str, Any], one: dict[str, Any]) -> None:
    for key in (
        "synonym_updates",
        "kind_updates",
        "tag_card_updates",
        "community_report_updates",
        "complete_task_keys",
    ):
        all_decisions[key].extend(one.get(key, []))


def mark_task_failed(db_path: Path, schema_path: Path, task_id: int, error_message: str) -> None:
    conn = connect_db(db_path)
    try:
        init_schema(conn, schema_path=schema_path)
        conn.execute(
            """
            UPDATE llm_tasks
            SET status = 'failed',
                error_message = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (error_message[:1000], utc_now_iso(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pending llm_tasks with GPT API and apply updates.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")
    parser.add_argument("--status", default="pending", choices=["pending", "in_progress", "done", "failed"], help="Task status filter")
    parser.add_argument("--limit", type=int, default=50, help="Max tasks to process in one run")
    parser.add_argument(
        "--task-type",
        action="append",
        choices=list(SUPPORTED_TASK_TYPES),
        help="Only process this task type; repeatable",
    )
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL), help="OpenAI model name")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL), help="OpenAI API base URL")
    parser.add_argument("--api-key", default=None, help="OpenAI API key (or use OPENAI_API_KEY env)")
    parser.add_argument("--temperature", type=float, default=0.0, help="Model temperature")
    parser.add_argument("--timeout", type=int, default=90, help="HTTP timeout seconds")
    parser.add_argument("--decisions-out", default=str(DEFAULT_DECISIONS_OUT), help="Where to write generated decisions JSON")
    parser.add_argument("--no-apply", action="store_true", help="Do not apply decisions back into DB")
    parser.add_argument("--dry-run", action="store_true", help="Generate decisions without writing anything to DB")
    parser.add_argument("--mock", action="store_true", help="Use local mock model outputs (no API calls)")
    parser.add_argument("--half-life-days", type=float, default=14.0, help="Half-life days used when applying decisions")
    parser.add_argument("--community-min-edge", type=int, default=2, help="Community edge threshold used when applying decisions")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    load_dotenv(THIS_DIR.parent / ".env", override=False)
    load_dotenv(THIS_DIR / ".env", override=False)

    db_path = Path(args.db).expanduser()
    schema_path = Path(args.schema).expanduser()

    task_types = set(args.task_type) if args.task_type else set(SUPPORTED_TASK_TYPES)
    tasks = export_llm_tasks(
        db_path=db_path,
        schema_path=schema_path,
        status=args.status,
        limit=max(1, int(args.limit)),
    )
    tasks = [t for t in tasks if t.get("task_type") in task_types]

    if not tasks:
        print(json.dumps({"processed_tasks": 0, "message": "no tasks matched"}, ensure_ascii=False, indent=2))
        return

    if not args.mock:
        api_key = args.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required (or pass --api-key).")
    else:
        api_key = ""

    decisions: dict[str, Any] = {
        "synonym_updates": [],
        "kind_updates": [],
        "tag_card_updates": [],
        "community_report_updates": [],
        "complete_task_keys": [],
    }
    failed: list[dict[str, Any]] = []

    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for task in tasks:
        task_id = int(task["task_id"])
        try:
            if args.mock:
                model_json, usage = mock_decision(task)
            else:
                system_prompt, user_prompt = build_prompt_for_task(task)
                model_json, usage = call_openai_chat_completion(
                    api_key=api_key,
                    base_url=args.base_url,
                    model=args.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=float(args.temperature),
                    timeout=int(args.timeout),
                )
            usage_totals["prompt_tokens"] += usage["prompt_tokens"]
            usage_totals["completion_tokens"] += usage["completion_tokens"]
            usage_totals["total_tokens"] += usage["total_tokens"]

            one = convert_model_output_to_decision(task=task, model_json=model_json)
            merge_decisions(decisions, one)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            failed.append({"task_id": task_id, "task_key": task.get("task_key"), "error": error_message})
            if not args.dry_run and not args.no_apply:
                mark_task_failed(
                    db_path=db_path,
                    schema_path=schema_path,
                    task_id=task_id,
                    error_message=error_message,
                )

    decisions_out = Path(args.decisions_out).expanduser()
    decisions_out.parent.mkdir(parents=True, exist_ok=True)
    decisions_out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")

    apply_summary = None
    if not args.no_apply and not args.dry_run:
        apply_summary = apply_llm_decisions_and_rebuild(
            db_path=db_path,
            schema_path=schema_path,
            decisions=decisions,
            half_life_days=float(args.half_life_days),
            community_min_edge=int(args.community_min_edge),
        )

    summary = {
        "processed_tasks": len(tasks),
        "success_tasks": len(tasks) - len(failed),
        "failed_tasks": len(failed),
        "task_types": sorted(task_types),
        "model": args.model if not args.mock else "mock",
        "usage": usage_totals,
        "decisions_out": str(decisions_out),
        "apply_executed": not args.no_apply and not args.dry_run,
        "apply_summary": apply_summary,
        "failed_examples": failed[:10],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
