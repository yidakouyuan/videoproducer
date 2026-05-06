#!/usr/bin/env python3
"""Apply LLM decision results and rebuild tag knowledge assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from tag_db_lib import apply_llm_decisions_and_rebuild


DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply LLM decisions (synonyms/kinds/cards/reports) and rebuild assets")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")
    parser.add_argument("--input", required=True, help="Decision JSON file path")
    parser.add_argument("--half-life-days", type=float, default=14.0, help="Half-life days for decayed cooccurrence")
    parser.add_argument("--community-min-edge", type=int, default=2, help="Minimum edge co_cnt for topic community")
    return parser



def main() -> None:
    args = build_parser().parse_args()

    input_path = Path(args.input).expanduser()
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    summary = apply_llm_decisions_and_rebuild(
        db_path=Path(args.db).expanduser(),
        schema_path=Path(args.schema).expanduser(),
        decisions=payload,
        half_life_days=float(args.half_life_days),
        community_min_edge=int(args.community_min_edge),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
