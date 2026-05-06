#!/usr/bin/env python3
"""Export pending LLM tasks from tag knowledge DB as JSON or JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from tag_db_lib import export_llm_tasks


DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export LLM tasks from tag knowledge DB")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")
    parser.add_argument("--status", default="pending", choices=["pending", "in_progress", "done", "failed"], help="Task status filter")
    parser.add_argument("--limit", type=int, default=200, help="Max tasks to export")
    parser.add_argument("--output", default=None, help="Output file path; default prints JSON to stdout")
    parser.add_argument("--jsonl", action="store_true", help="Write JSONL format when --output is provided")
    return parser



def main() -> None:
    args = build_parser().parse_args()

    tasks = export_llm_tasks(
        db_path=Path(args.db).expanduser(),
        schema_path=Path(args.schema).expanduser(),
        status=args.status,
        limit=int(args.limit),
    )

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if args.jsonl:
            with output_path.open("w", encoding="utf-8") as fp:
                for task in tasks:
                    fp.write(json.dumps(task, ensure_ascii=False) + "\n")
        else:
            output_path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(output_path))
        return

    print(json.dumps(tasks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
