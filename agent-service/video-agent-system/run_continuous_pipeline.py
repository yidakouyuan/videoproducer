#!/usr/bin/env python3
"""
Continuous pipeline: crawl a batch → ingest into tag DB → repeat.

Instead of crawling everything first then ingesting once, this script runs in
cycles so the tag knowledge DB is updated incrementally while the crawl runs
indefinitely.

Each cycle:
  1. Run the Douyin Jingxuan crawl for --cycle-crawl-seconds seconds
  2. Run the tag DB pipeline to ingest the new complete-metrics JSON files
  3. Sleep --cycle-interval-seconds, then repeat

The loop runs until:
  - --max-cycles is reached (0 = run forever, stop with Ctrl-C)
  - A cycle fails and --stop-on-error is set (default: log and continue)

Usage examples:
  # Crawl 10 min per cycle, skip LLM, run forever:
  python run_continuous_pipeline.py --cycle-crawl-seconds 600 --skip-llm

  # Crawl 5 min per cycle, run LLM, stop after 12 cycles (~1 hour of crawl):
  python run_continuous_pipeline.py --cycle-crawl-seconds 300 --max-cycles 12

  # Test mode (short cycle, mock LLM):
  python run_continuous_pipeline.py --cycle-crawl-seconds 60 --mock --max-cycles 2

  # With extra crawl/tag flags:
  python run_continuous_pipeline.py --cycle-crawl-seconds 300 --skip-llm \\
      --crawl-extra "--headful --enrich-limit 50" \\
      --tag-extra "--timestamped-snapshot"
"""

from __future__ import annotations

import argparse
import shlex
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CRAWL_SCRIPT = REPO_ROOT / "src" / "douyin_hot_db" / "run_auto_pipeline_jingxuan.py"
TAG_SCRIPT = REPO_ROOT / "tag_knowledge_db" / "run_pipeline.py"

DEFAULT_CRAWL_DB = REPO_ROOT / "data" / "douyin_hot.db"
DEFAULT_TAG_DB = REPO_ROOT / "tag_knowledge_db" / "data" / "tag_knowledge.db"
DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "raw" / "video_detail_results_complete"
DEFAULT_LOG_DIR = REPO_ROOT / "data" / "logs" / "auto_pipeline_jingxuan"

# Flag set by SIGINT/SIGTERM so the loop exits cleanly after the current cycle.
_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    if not _shutdown_requested:
        print(
            f"\n[continuous] received signal {signum}, "
            "will stop after current cycle completes...",
            flush=True,
        )
    _shutdown_requested = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _banner(text: str) -> None:
    line = "=" * 64
    print(f"\n{line}", flush=True)
    print(f"  {text}", flush=True)
    print(f"{line}", flush=True)


def _run_step(cmd: list[str], step_name: str) -> int:
    print(f"\n[{step_name}] $ {' '.join(cmd)}\n", flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return proc.returncode


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous pipeline: crawl a batch → tag DB → repeat.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Each cycle:
              1. crawl  – Run Douyin Jingxuan swipe+enrich+export for --cycle-crawl-seconds
              2. tag    – Ingest new JSON files into the tag knowledge DB

            Stop cleanly with Ctrl-C (finishes the current cycle first).
            """
        ),
    )

    # --- cycle control ---
    cycle = parser.add_argument_group("Cycle control")
    cycle.add_argument(
        "--cycle-crawl-seconds", type=float, required=True,
        help="How long (seconds) to crawl per cycle.",
    )
    cycle.add_argument(
        "--max-cycles", type=int, default=0,
        help="Max cycles to run. 0 = run forever until Ctrl-C. (default: 0)",
    )
    cycle.add_argument(
        "--cycle-interval-seconds", type=float, default=5.0,
        help="Sleep between cycles (default: 5s).",
    )
    cycle.add_argument(
        "--stop-on-error", action="store_true",
        help="Stop the loop if any step fails (default: log error and continue).",
    )

    # --- crawl ---
    crawl = parser.add_argument_group("Crawl step (run_auto_pipeline_jingxuan.py)")
    crawl.add_argument(
        "--crawl-db", default=str(DEFAULT_CRAWL_DB),
        help="Douyin SQLite database path.",
    )
    crawl.add_argument(
        "--crawl-log-dir", default=str(DEFAULT_LOG_DIR),
        help="Directory for crawl pipeline logs.",
    )
    crawl.add_argument(
        "--crawl-enrich-limit", type=int, default=100,
        help="Max videos for the enricher step per cycle.",
    )
    crawl.add_argument(
        "--headful", action="store_true",
        help="Run browser sub-commands in headful mode.",
    )
    crawl.add_argument(
        "--crawl-extra", default="",
        help="Extra flags forwarded verbatim to run_auto_pipeline_jingxuan.py.",
    )

    # --- tag DB ---
    tag = parser.add_argument_group("Tag DB step (tag_knowledge_db/run_pipeline.py)")
    tag.add_argument(
        "--tag-db", default=str(DEFAULT_TAG_DB),
        help="Tag knowledge SQLite database path.",
    )
    tag.add_argument(
        "--tag-input-dir", default=str(DEFAULT_INPUT_DIR),
        help="Directory with complete-metrics JSON files (output of crawl step).",
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
        help="Extra flags forwarded verbatim to tag_knowledge_db/run_pipeline.py.",
    )

    return parser


# ---------------------------------------------------------------------------
# Step runners
# ---------------------------------------------------------------------------

def run_crawl_step(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable, str(CRAWL_SCRIPT),
        "--db", args.crawl_db,
        "--log-dir", args.crawl_log_dir,
        "--jingxuan-rounds", "0",
        "--jingxuan-crawl-duration-seconds", str(args.cycle_crawl_seconds),
        "--enrich-limit", str(args.crawl_enrich_limit),
    ]
    if args.headful:
        cmd.append("--headful")
    if args.crawl_extra:
        cmd.extend(shlex.split(args.crawl_extra))
    return _run_step(cmd, "CRAWL")


def run_tag_step(args: argparse.Namespace) -> int:
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
        cmd.extend(shlex.split(args.tag_extra))
    return _run_step(cmd, "TAG-DB")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cycle_crawl_seconds <= 0:
        parser.error("--cycle-crawl-seconds must be > 0")
    if args.max_cycles < 0:
        parser.error("--max-cycles must be >= 0")
    if args.cycle_interval_seconds < 0:
        parser.error("--cycle-interval-seconds must be >= 0")

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    loop_start = _now_iso()
    infinite = args.max_cycles == 0
    cycles_completed = 0  # incremented only after a full cycle body runs
    errors: list[str] = []

    print(f"\nContinuous Pipeline  –  started {loop_start}")
    print(f"  Crawl script      : {CRAWL_SCRIPT}")
    print(f"  Tag script        : {TAG_SCRIPT}")
    print(f"  Cycle crawl time  : {args.cycle_crawl_seconds}s")
    print(f"  Max cycles        : {'∞' if infinite else args.max_cycles}")
    print(f"  Tag input dir     : {args.tag_input_dir}")
    print(f"  Stop on error     : {args.stop_on_error}")
    print("  (Ctrl-C to stop cleanly after current cycle)\n", flush=True)

    while not _shutdown_requested:
        if not infinite and cycles_completed >= args.max_cycles:
            break

        cycle_num = cycles_completed + 1  # human-readable label, 1-based
        cycle_label = f"Cycle {cycle_num}" + ("" if infinite else f"/{args.max_cycles}")
        cycle_start = time.monotonic()
        _banner(f"{cycle_label}  –  {_now_iso()}")

        # ---- crawl ----
        print(f"[{cycle_label}] Starting crawl ({args.cycle_crawl_seconds}s)…", flush=True)
        rc_crawl = run_crawl_step(args)
        if rc_crawl != 0:
            msg = f"{cycle_label} crawl step failed (rc={rc_crawl})"
            print(f"\n[continuous] ERROR: {msg}", flush=True)
            errors.append(msg)
            if args.stop_on_error:
                cycles_completed += 1
                break
        else:
            print(f"\n[{cycle_label}] Crawl finished OK.", flush=True)

        # ---- tag DB — always run to completion even if Ctrl-C arrived during crawl ----
        print(f"[{cycle_label}] Starting tag DB update…", flush=True)
        rc_tag = run_tag_step(args)
        if rc_tag != 0:
            msg = f"{cycle_label} tag DB step failed (rc={rc_tag})"
            print(f"\n[continuous] ERROR: {msg}", flush=True)
            errors.append(msg)
            if args.stop_on_error:
                cycles_completed += 1
                break
        else:
            print(f"\n[{cycle_label}] Tag DB update finished OK.", flush=True)

        cycles_completed += 1
        elapsed = time.monotonic() - cycle_start
        print(f"\n[{cycle_label}] Cycle done in {elapsed:.1f}s.", flush=True)

        # ---- inter-cycle sleep (interruptible) ----
        if _shutdown_requested:
            break
        if args.cycle_interval_seconds > 0 and (infinite or cycles_completed < args.max_cycles):
            print(f"[continuous] Sleeping {args.cycle_interval_seconds}s before next cycle…", flush=True)
            deadline = time.monotonic() + args.cycle_interval_seconds
            while time.monotonic() < deadline and not _shutdown_requested:
                time.sleep(0.5)

    # ---- summary ----
    _banner("Continuous pipeline stopped")
    print(f"  Started   : {loop_start}")
    print(f"  Stopped   : {_now_iso()}")
    print(f"  Cycles run: {cycles_completed}")
    if errors:
        print(f"  Errors    : {len(errors)}")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  Errors    : 0")
    print()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
