#!/usr/bin/env python3
"""Build and incrementally update the standalone tag knowledge database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from tag_db_lib import build_tag_database


DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_INPUT_DIR = THIS_DIR.parent / "data" / "raw" / "video_detail_results_complete"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"
DEFAULT_BYOG_DIR = THIS_DIR / "data" / "byog_export"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build standalone tag knowledge database from raw video detail JSON files.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Input directory containing *.json files")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")
    parser.add_argument("--half-life-days", type=float, default=14.0, help="Half-life days for decayed cooccurrence")
    parser.add_argument("--community-min-edge", type=int, default=2, help="Minimum co_cnt edge threshold to connect topics")
    parser.add_argument("--leiden-max-cluster-size", type=int, default=50, help="Max cluster size for graphrag hierarchical Leiden")
    parser.add_argument("--force-reprocess", action="store_true", help="Reprocess source files even if checksum is unchanged")
    parser.add_argument("--export-byog", action="store_true", help="Export BYOG entities/relationships CSV after build")
    parser.add_argument("--byog-dir", default=str(DEFAULT_BYOG_DIR), help="Output dir for BYOG CSV export")
    return parser



def main() -> None:
    args = build_parser().parse_args()

    summary = build_tag_database(
        db_path=Path(args.db).expanduser(),
        input_dir=Path(args.input_dir).expanduser(),
        schema_path=Path(args.schema).expanduser(),
        half_life_days=float(args.half_life_days),
        community_min_edge=int(args.community_min_edge),
        leiden_max_cluster_size=int(args.leiden_max_cluster_size),
        force_reprocess=bool(args.force_reprocess),
        export_byog_dir=Path(args.byog_dir).expanduser() if args.export_byog else None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
