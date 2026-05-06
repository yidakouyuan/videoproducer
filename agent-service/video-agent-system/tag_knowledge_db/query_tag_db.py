#!/usr/bin/env python3
"""Query tag bundle for topic/campaign tags."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from tag_db_lib import connect_db, init_schema, query_tag_bundle


DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query a tag bundle from the standalone tag knowledge database.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")
    parser.add_argument("--tag", required=True, help="Input tag (raw or canonical)")
    parser.add_argument("--topk", type=int, default=10, help="Top-K co-tags")
    parser.add_argument("--top-titles", type=int, default=10, help="Top title samples in evidence pack")
    return parser



def main() -> None:
    args = build_parser().parse_args()

    conn = connect_db(Path(args.db).expanduser())
    try:
        init_schema(conn, schema_path=Path(args.schema).expanduser())
        bundle = query_tag_bundle(
            conn=conn,
            input_tag=args.tag,
            topk=int(args.topk),
            top_titles=int(args.top_titles),
        )
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
