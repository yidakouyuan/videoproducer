#!/usr/bin/env python3
"""
Full end-to-end pipeline: Douyin crawl → Tag Knowledge DB.

Steps:
  1. Douyin Jingxuan crawl pipeline  (src/douyin_hot_db/run_auto_pipeline_jingxuan.py)
     Crawls videos, enriches details, exports complete-metrics JSON files into
     data/raw/video_detail_results_complete/
  2. Tag Knowledge DB pipeline       (tag_knowledge_db/run_pipeline.py)
     Ingests those JSON files, builds/updates the tag graph, runs LLM tasks,
     exports a CSV snapshot.

Usage examples:
  # Crawl for 5 minutes, then update tag DB (skip LLM):
  python run_full_pipeline.py --crawl-duration-seconds 300 --skip-llm

  # Crawl for 10 minutes, run LLM step too:
  python run_full_pipeline.py --crawl-duration-seconds 600

  # Skip crawl entirely, only refresh tag DB:
  python run_full_pipeline.py --skip-crawl --skip-llm

  # Mock LLM (for testing without API key):
  python run_full_pipeline.py --crawl-duration-seconds 60 --mock

  # Pass extra crawl / tag flags:
  python run_full_pipeline.py --crawl-duration-seconds 300 \\
      --crawl-extra "--headful --enrich-limit 50" \\
      --tag-extra "--timestamped-snapshot"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CRAWL_SCRIPT = REPO_ROOT / "src" / "douyin_hot_db" / "run_auto_pipeline_jingxuan.py"
TAG_SCRIPT = REPO_ROOT / "tag_knowledge_db" / "run_pipeline.py"

DEFAULT_DB = REPO_ROOT / "data" / "douyin_hot.db"
DEFAULT_TAG_DB = REPO_ROOT / "tag_knowledge_db" / "data" / "tag_knowledge.db"
DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "raw" / "video_detail_results_complete"
DEFAULT_LOG_DIR = REPO_ROOT / "data" / "logs" / "auto_pipeline_jingxuan"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text: str) -> None:
    line = "=" * 64
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


def _run_step(cmd: list[str], step_name: str) -> int:
    """Run a sub-command streaming output; return its exit code."""
    print(f"\n[{step_name}] $ {' '.join(cmd)}\n", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return proc.returncode


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full pipeline: Douyin crawl → Tag Knowledge DB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Pipeline:
              1. crawl  – Douyin Jingxuan swipe + enrich + export complete metrics
              2. tag    – Ingest metrics JSON → tag graph → LLM review → CSV snapshot

            Pass --crawl-extra / --tag-extra to forward arbitrary flags to sub-pipelines.
            """
        ),
    )

    # --- crawl step ---
    crawl = parser.add_argument_group("Step 1 – Douyin crawl pipeline")
    crawl.add_argument(
        "--skip-crawl", action="store_true",
        help="Skip the crawl step; only run the tag DB pipeline.",
    )
    crawl.add_argument(
        "--crawl-duration-seconds", type=float, default=None,
        help="Wall-clock crawl time in seconds (required unless --skip-crawl or --crawl-rounds > 0).",
    )
    crawl.add_argument(
        "--crawl-rounds", type=int, default=0,
        help="Crawler rounds (0 = endless loop, requires --crawl-duration-seconds).",
    )
    crawl.add_argument(
        "--crawl-db", default=str(DEFAULT_DB),
        help="Douyin SQLite database path.",
    )
    crawl.add_argument(
        "--crawl-log-dir", default=str(DEFAULT_LOG_DIR),
        help="Directory for crawl pipeline logs.",
    )
    crawl.add_argument(
        "--crawl-enrich-limit", type=int, default=100,
        help="Max videos for the enricher step.",
    )
    crawl.add_argument(
        "--headful", action="store_true",
        help="Run browser sub-commands in headful mode.",
    )
    crawl.add_argument(
        "--crawl-extra", default="",
        help="Extra flags forwarded verbatim to run_auto_pipeline_jingxuan.py (space-separated).",
    )

    # --- tag step ---
    tag = parser.add_argument_group("Step 2 – Tag Knowledge DB pipeline")
    tag.add_argument(
        "--skip-tag", action="store_true",
        help="Skip the tag DB step.",
    )
    tag.add_argument(
        "--tag-db", default=str(DEFAULT_TAG_DB),
        help="Tag knowledge SQLite database path.",
    )
    tag.add_argument(
        "--tag-input-dir", default=str(DEFAULT_INPUT_DIR),
        help="Directory with complete-metrics JSON files (output of crawl pipeline).",
    )
    tag.add_argument(
        "--skip-llm", action="store_true",
        help="Skip LLM tasks in the tag DB pipeline.",
    )
    tag.add_argument(
        "--mock", action="store_true",
        help="Use mock LLM outputs (no API calls, for testing).",
    )
    tag.add_argument(
        "--llm-limit", type=int, default=50,
        help="Max LLM tasks per tag pipeline run.",
    )
    tag.add_argument(
        "--tag-extra", default="",
        help="Extra flags forwarded verbatim to tag_knowledge_db/run_pipeline.py (space-separated).",
    )

    return parser


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_crawl(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable, str(CRAWL_SCRIPT),
        "--db", args.crawl_db,
        "--log-dir", args.crawl_log_dir,
        "--jingxuan-rounds", str(args.crawl_rounds),
        "--enrich-limit", str(args.crawl_enrich_limit),
    ]
    if args.crawl_duration_seconds is not None:
        cmd += ["--jingxuan-crawl-duration-seconds", str(args.crawl_duration_seconds)]
    if args.headful:
        cmd.append("--headful")
    if args.crawl_extra:
        cmd.extend(args.crawl_extra.split())
    return _run_step(cmd, "CRAWL")


def step_tag(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable, str(TAG_SCRIPT),
        "--db", args.tag_db,
        "--input-dir", args.tag_input_dir,
        "--llm-limit", str(args.llm_limit),
    ]
    if args.skip_llm:
        cmd.append("--skip-llm")
    if args.mock:
        cmd.append("--mock")
    if args.tag_extra:
        cmd.extend(args.tag_extra.split())
    return _run_step(cmd, "TAG-DB")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate crawl args early
    if not args.skip_crawl:
        if args.crawl_rounds == 0 and args.crawl_duration_seconds is None:
            parser.error(
                "--crawl-duration-seconds is required when --crawl-rounds=0 "
                "(use --skip-crawl to skip the crawl step)."
            )

    if args.skip_crawl and args.skip_tag:
        parser.error("Both --skip-crawl and --skip-tag specified — nothing to do.")

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\nFull Pipeline  –  started {started_at}")
    print(f"  Crawl script : {CRAWL_SCRIPT}")
    print(f"  Tag script   : {TAG_SCRIPT}")
    print(f"  Input dir    : {args.tag_input_dir}")

    results: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Step 1: Crawl
    # ------------------------------------------------------------------
    if args.skip_crawl:
        _banner("Step 1/2 – Douyin crawl  [SKIPPED]")
        results["crawl"] = "skipped"
    else:
        _banner("Step 1/2 – Douyin crawl (swipe + enrich + export)")
        rc = step_crawl(args)
        if rc != 0:
            _banner("FAILED at crawl step")
            print(f"  Crawl pipeline exited with code {rc}.")
            sys.exit(rc)
        results["crawl"] = "success"

    # ------------------------------------------------------------------
    # Step 2: Tag DB
    # ------------------------------------------------------------------
    if args.skip_tag:
        _banner("Step 2/2 – Tag Knowledge DB  [SKIPPED]")
        results["tag"] = "skipped"
    else:
        _banner("Step 2/2 – Tag Knowledge DB (ingest + LLM + snapshot)")
        rc = step_tag(args)
        if rc != 0:
            _banner("FAILED at tag DB step")
            print(f"  Tag DB pipeline exited with code {rc}.")
            sys.exit(rc)
        results["tag"] = "success"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    finished_at = datetime.now(timezone.utc).isoformat()
    _banner("Full pipeline complete")
    print(f"  Started  : {started_at}")
    print(f"  Finished : {finished_at}")
    for step, status in results.items():
        print(f"  {step:<10}: {status}")
    print(f"  Tag DB   : {args.tag_db}")
    print()


if __name__ == "__main__":
    main()
