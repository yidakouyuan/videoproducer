#!/usr/bin/env python3
"""
End-to-end pipeline for the tag knowledge database.

Steps:
  1. Build / incrementally update DB from raw JSON files  (build_tag_db.py)
  2. Run LLM tasks with GPT and apply decisions           (run_llm_tasks_gpt.py)  [optional]
  3. Export human-readable CSV snapshot                   (export_db_snapshot.py)

Usage examples:
  # Full pipeline — first configure your API key:
  #   cp tag_knowledge_db/.env.example tag_knowledge_db/.env
  #   vim tag_knowledge_db/.env   →  fill in OPENAI_API_KEY
  python run_pipeline.py

  # Skip LLM step (no API key needed)
  python run_pipeline.py --skip-llm

  # Force re-ingest all files, skip LLM
  python run_pipeline.py --force-reprocess --skip-llm

  # Mock LLM calls for testing
  python run_pipeline.py --mock

  # Snapshot goes to a timestamped subfolder (default: overwrites latest)
  python run_pipeline.py --skip-llm --timestamped-snapshot
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_DB = THIS_DIR / "data" / "tag_knowledge.db"
DEFAULT_INPUT_DIR = THIS_DIR.parent / "data" / "raw" / "video_detail_results_complete"
DEFAULT_SCHEMA = THIS_DIR / "schema.sql"
DEFAULT_SNAPSHOT_DIR = THIS_DIR / "data" / "db_snapshot"
DEFAULT_BYOG_DIR = THIS_DIR / "data" / "byog_export"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


def _run(cmd: list[str], step_name: str) -> dict:
    """Run a sub-command, stream its stdout/stderr, and return the last JSON object printed."""
    print(f"\n[{step_name}] Running: {' '.join(cmd)}\n")
    proc = subprocess.run(
        cmd,
        capture_output=False,   # let stdout/stderr stream to terminal
        text=True,
    )
    if proc.returncode != 0:
        print(f"\n[{step_name}] ERROR: process exited with code {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)
    return {}   # sub-scripts print their own JSON summaries


def _run_capture(cmd: list[str], step_name: str) -> dict:
    """Run a sub-command, capture output, parse final JSON block, and also print output."""
    print(f"\n[{step_name}] Running: {' '.join(cmd)}\n")
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Always print stdout / stderr so the user can see progress
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if proc.returncode != 0:
        print(f"\n[{step_name}] ERROR: process exited with code {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)

    # Try to extract the last JSON object from stdout
    stdout = proc.stdout or ""
    last_json: dict = {}
    # Walk backwards through lines to find last parseable JSON block
    lines = stdout.splitlines()
    json_lines: list[str] = []
    in_block = False
    for line in reversed(lines):
        stripped = line.strip()
        if stripped == "}":
            in_block = True
        if in_block:
            json_lines.insert(0, line)
        if stripped == "{" and in_block:
            break
    if json_lines:
        try:
            last_json = json.loads("\n".join(json_lines))
        except json.JSONDecodeError:
            pass
    if not last_json:
        # Fallback: try the whole stdout
        try:
            last_json = json.loads(stdout.strip())
        except (json.JSONDecodeError, ValueError):
            pass

    return last_json


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="End-to-end tag knowledge database pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Pipeline steps:
              1. build   – Ingest raw JSON → SQLite, rebuild materialized assets
              2. llm     – Run pending LLM tasks via GPT, apply decisions & rebuild
              3. snapshot– Export all tables as CSV for inspection

            Use --skip-llm to run only steps 1 and 3 (no API key required).
            """
        ),
    )

    # --- shared paths ---
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="Path to schema.sql")

    # --- step 1: build ---
    build_group = parser.add_argument_group("Step 1 – build_tag_db")
    build_group.add_argument(
        "--input-dir", default=str(DEFAULT_INPUT_DIR),
        help="Directory with raw video *.json files",
    )
    build_group.add_argument(
        "--half-life-days", type=float, default=14.0,
        help="Co-occurrence decay half-life (days)",
    )
    build_group.add_argument(
        "--community-min-edge", type=int, default=2,
        help="Minimum co_cnt threshold for community edges",
    )
    build_group.add_argument(
        "--leiden-max-cluster-size", type=int, default=50,
        help="Max cluster size for hierarchical Leiden",
    )
    build_group.add_argument(
        "--force-reprocess", action="store_true",
        help="Re-ingest all source files even if unchanged",
    )
    build_group.add_argument(
        "--export-byog", action="store_true",
        help="Also export BYOG entities/relationships CSVs",
    )
    build_group.add_argument(
        "--byog-dir", default=str(DEFAULT_BYOG_DIR),
        help="Output directory for BYOG CSV export",
    )

    # --- step 2: llm ---
    llm_group = parser.add_argument_group("Step 2 – run_llm_tasks_gpt")
    llm_group.add_argument(
        "--skip-llm", action="store_true",
        help="Skip the LLM step entirely",
    )
    llm_group.add_argument(
        "--mock", action="store_true",
        help="Use mock LLM outputs (no API calls, for testing)",
    )
    llm_group.add_argument(
        "--llm-limit", type=int, default=50,
        help="Max LLM tasks to process per run",
    )
    llm_group.add_argument(
        "--task-type", action="append",
        choices=["raw_tag_synonym_review", "canonical_tag_kind_review", "tag_card_review", "community_report_review"],
        help="LLM task types to process (repeatable); default: all",
    )
    llm_group.add_argument("--model", default=None, help="OpenAI model name (overrides .env)")
    llm_group.add_argument("--base-url", default=None, help="OpenAI API base URL (overrides .env)")
    # API key is intentionally NOT a CLI arg — set it in tag_knowledge_db/.env (see .env.example)

    # --- step 3: snapshot ---
    snap_group = parser.add_argument_group("Step 3 – export_db_snapshot")
    snap_group.add_argument(
        "--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR),
        help="Base output directory for CSV snapshots",
    )
    snap_group.add_argument(
        "--timestamped-snapshot", action="store_true",
        help="Write snapshot into a UTC-timestamped subdirectory",
    )

    return parser


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_build(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable, str(THIS_DIR / "build_tag_db.py"),
        "--db", args.db,
        "--schema", args.schema,
        "--input-dir", args.input_dir,
        "--half-life-days", str(args.half_life_days),
        "--community-min-edge", str(args.community_min_edge),
        "--leiden-max-cluster-size", str(args.leiden_max_cluster_size),
    ]
    if args.force_reprocess:
        cmd.append("--force-reprocess")
    if args.export_byog:
        cmd += ["--export-byog", "--byog-dir", args.byog_dir]
    _run(cmd, "BUILD")


def step_llm(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable, str(THIS_DIR / "run_llm_tasks_gpt.py"),
        "--db", args.db,
        "--schema", args.schema,
        "--limit", str(args.llm_limit),
        "--half-life-days", str(args.half_life_days),
        "--community-min-edge", str(args.community_min_edge),
    ]
    if args.mock:
        cmd.append("--mock")
    if args.task_type:
        for tt in args.task_type:
            cmd += ["--task-type", tt]
    if args.model:
        cmd += ["--model", args.model]
    if args.base_url:
        cmd += ["--base-url", args.base_url]
    # API key is read from .env by run_llm_tasks_gpt.py directly — never passed via CLI
    _run(cmd, "LLM")


def step_snapshot(args: argparse.Namespace) -> dict:
    cmd = [
        sys.executable, str(THIS_DIR / "export_db_snapshot.py"),
        "--db", args.db,
        "--schema", args.schema,
        "--output-dir", args.snapshot_dir,
    ]
    if args.timestamped_snapshot:
        cmd.append("--timestamped")
    return _run_capture(cmd, "SNAPSHOT")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nTag Knowledge DB Pipeline  –  started {started_at}")

    # ------------------------------------------------------------------
    # Step 1: Build / ingest
    # ------------------------------------------------------------------
    _banner("Step 1/3 – Build DB (ingest + materialize)")
    step_build(args)

    # ------------------------------------------------------------------
    # Step 2: LLM tasks (optional)
    # ------------------------------------------------------------------
    if args.skip_llm:
        _banner("Step 2/3 – LLM tasks  [SKIPPED]")
        print("  (pass --mock to run with mock outputs, or remove --skip-llm to use the real API)")
    else:
        _banner("Step 2/3 – LLM tasks (GPT + apply decisions)")
        step_llm(args)

    # ------------------------------------------------------------------
    # Step 3: Export snapshot
    # ------------------------------------------------------------------
    _banner("Step 3/3 – Export DB snapshot (CSV)")
    snap_summary = step_snapshot(args)

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    finished_at = datetime.now(timezone.utc).isoformat()
    _banner("Pipeline complete")
    print(f"  Started  : {started_at}")
    print(f"  Finished : {finished_at}")
    print(f"  DB path  : {args.db}")

    if snap_summary:
        output_dir = snap_summary.get("output_dir", args.snapshot_dir)
        print(f"  Snapshot : {output_dir}")
        table_counts = snap_summary.get("table_counts", {})
        if table_counts:
            print("\n  Table row counts:")
            for table, cnt in table_counts.items():
                print(f"    {table:<30} {cnt:>8}")
        csv_rows = snap_summary.get("csv_rows", {})
        if csv_rows:
            print("\n  Exported CSV files:")
            for fname, rows in csv_rows.items():
                print(f"    {fname:<40} {rows:>8} rows")
    else:
        print(f"  Snapshot : {args.snapshot_dir}")

    print()


if __name__ == "__main__":
    main()
