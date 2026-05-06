#!/usr/bin/env python3
"""Export tag knowledge DB into CSV snapshots for manual inspection."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tag_db_lib import connect_db, init_schema


THIS_DIR = Path(__file__).resolve().parent
DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"
DEFAULT_OUTPUT_DIR = THIS_DIR / "data" / "db_snapshot"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_query_to_csv(conn, sql: str, out_path: Path, params: tuple[Any, ...] = ()) -> int:
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    fields = [col[0] for col in cur.description] if cur.description else []

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (row[k] if row[k] is not None else "") for k in fields})
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export DB snapshot as CSV files.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="schema.sql path")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for CSV files")
    parser.add_argument(
        "--timestamped",
        action="store_true",
        help="Write into output-dir/<UTC timestamp>/",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    db_path = Path(args.db).expanduser()
    schema_path = Path(args.schema).expanduser()
    base_output = Path(args.output_dir).expanduser()
    output_dir = base_output / utc_stamp() if args.timestamped else base_output
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_db(db_path)
    try:
        init_schema(conn, schema_path=schema_path)

        exports: dict[str, int] = {}

        exports["canonical_tags.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              c.canonical_tag_id,
              c.canonical_name,
              c.tag_kind,
              c.kind_source,
              c.kind_confidence,
              c.first_seen_at,
              c.last_seen_at,
              c.updated_at,
              COALESCE(s.video_count, 0) AS video_count,
              COALESCE(s.score, 0) AS score,
              COALESCE(s.digg_sum, 0) AS digg_sum,
              COALESCE(s.collect_sum, 0) AS collect_sum,
              COALESCE(s.comment_sum, 0) AS comment_sum,
              COALESCE(s.share_sum, 0) AS share_sum,
              COALESCE(tc.card_text, '') AS card_text,
              COALESCE(tc.source, '') AS card_source
            FROM canonical_tags c
            LEFT JOIN canonical_tag_stats s ON s.canonical_tag_id = c.canonical_tag_id
            LEFT JOIN tag_cards tc ON tc.canonical_tag_id = c.canonical_tag_id
            WHERE c.merged_into IS NULL
            ORDER BY s.score DESC, c.canonical_tag_id ASC
            """,
            output_dir / "canonical_tags.csv",
        )

        exports["raw_tags.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              r.raw_tag_norm,
              r.raw_tag_display,
              r.video_count,
              r.first_seen_at,
              r.last_seen_at,
              a.canonical_tag_id,
              COALESCE(c.canonical_name, '') AS canonical_name,
              COALESCE(c.tag_kind, '') AS canonical_kind,
              COALESCE(a.alias_source, '') AS alias_source,
              COALESCE(a.confidence, '') AS alias_confidence,
              COALESCE(a.updated_at, '') AS alias_updated_at
            FROM raw_tags r
            LEFT JOIN tag_aliases a ON a.raw_tag_norm = r.raw_tag_norm
            LEFT JOIN canonical_tags c ON c.canonical_tag_id = a.canonical_tag_id
            ORDER BY r.video_count DESC, r.raw_tag_norm ASC
            """,
            output_dir / "raw_tags.csv",
        )

        exports["tag_aliases.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              a.raw_tag_norm,
              a.canonical_tag_id,
              c.canonical_name,
              c.tag_kind,
              a.alias_source,
              a.confidence,
              a.updated_at
            FROM tag_aliases a
            JOIN canonical_tags c ON c.canonical_tag_id = a.canonical_tag_id
            ORDER BY a.raw_tag_norm ASC
            """,
            output_dir / "tag_aliases.csv",
        )

        exports["tag_cooccurrence.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              e.src_tag_id,
              s.canonical_name AS src_tag,
              s.tag_kind AS src_kind,
              e.dst_tag_id,
              d.canonical_name AS dst_tag,
              d.tag_kind AS dst_kind,
              e.co_cnt_total,
              e.co_cnt_7d,
              e.co_cnt_30d,
              ROUND(e.decayed_weight, 6) AS decayed_weight,
              e.last_event_at,
              e.updated_at
            FROM tag_cooccurrence e
            JOIN canonical_tags s ON s.canonical_tag_id = e.src_tag_id
            JOIN canonical_tags d ON d.canonical_tag_id = e.dst_tag_id
            ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
            """,
            output_dir / "tag_cooccurrence.csv",
        )

        exports["topic_topic_edges.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              t.src_tag_id,
              s.canonical_name AS src_tag,
              t.dst_tag_id,
              d.canonical_name AS dst_tag,
              t.co_cnt_total,
              t.co_cnt_7d,
              t.co_cnt_30d,
              ROUND(t.decayed_weight, 6) AS decayed_weight,
              t.last_event_at
            FROM topic_topic_edges t
            JOIN canonical_tags s ON s.canonical_tag_id = t.src_tag_id
            JOIN canonical_tags d ON d.canonical_tag_id = t.dst_tag_id
            ORDER BY t.decayed_weight DESC, t.co_cnt_total DESC
            """,
            output_dir / "topic_topic_edges.csv",
        )

        exports["campaign_topic_edges.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              e.campaign_tag_id,
              c.canonical_name AS campaign_tag,
              e.topic_tag_id,
              t.canonical_name AS topic_tag,
              e.co_cnt_total,
              e.co_cnt_7d,
              e.co_cnt_30d,
              ROUND(e.decayed_weight, 6) AS decayed_weight,
              e.last_event_at
            FROM campaign_topic_edges e
            JOIN canonical_tags c ON c.canonical_tag_id = e.campaign_tag_id
            JOIN canonical_tags t ON t.canonical_tag_id = e.topic_tag_id
            ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
            """,
            output_dir / "campaign_topic_edges.csv",
        )

        exports["communities.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              community_id,
              algo,
              level,
              generated_at,
              topic_count,
              report_source,
              report_text
            FROM communities
            ORDER BY topic_count DESC, community_id ASC
            """,
            output_dir / "communities.csv",
        )

        exports["community_members.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              cm.community_id,
              cm.member_rank,
              cm.canonical_tag_id,
              c.canonical_name,
              c.tag_kind,
              ROUND(cm.score, 3) AS score
            FROM community_members cm
            JOIN canonical_tags c ON c.canonical_tag_id = cm.canonical_tag_id
            ORDER BY cm.community_id ASC, cm.member_rank ASC
            """,
            output_dir / "community_members.csv",
        )

        exports["videos.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              aweme_id,
              title,
              author_id,
              author_name,
              create_time,
              captured_at,
              digg_count,
              collect_count,
              comment_count,
              share_count,
              play_count,
              first_seen_at,
              last_seen_at
            FROM videos
            ORDER BY COALESCE(create_time, 0) DESC, aweme_id ASC
            """,
            output_dir / "videos.csv",
        )

        exports["ingest_runs.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              run_id,
              started_at,
              ended_at,
              status,
              input_dir,
              files_seen,
              files_processed,
              records_seen,
              records_ingested,
              message
            FROM ingest_runs
            ORDER BY started_at DESC
            """,
            output_dir / "ingest_runs.csv",
        )

        exports["llm_tasks.csv"] = export_query_to_csv(
            conn,
            """
            SELECT
              task_id,
              task_type,
              task_key,
              status,
              priority,
              created_at,
              updated_at,
              error_message,
              payload_json,
              result_json
            FROM llm_tasks
            ORDER BY task_id ASC
            """,
            output_dir / "llm_tasks.csv",
        )

        table_counts = {}
        for table in (
            "videos",
            "raw_tags",
            "canonical_tags",
            "tag_aliases",
            "canonical_tag_stats",
            "tag_cooccurrence",
            "communities",
            "community_members",
            "tag_cards",
            "llm_tasks",
            "ingest_runs",
        ):
            row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
            table_counts[table] = int(row["cnt"]) if row else 0

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "output_dir": str(output_dir),
            "table_counts": table_counts,
            "csv_rows": exports,
        }

        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
