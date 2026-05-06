#!/usr/bin/env python3
"""
Parallel pipeline: continuous crawl + periodic tag DB ingestion.

Architecture:
  crawl thread – runs indefinitely; each run lasts --cycle-crawl-seconds,
                 then restarts immediately. Crawl never pauses for tag DB.
  tag thread   – runs every --tag-interval-seconds, independent of crawl.
                 Each tag run is sequential internally (ingest → LLM → snapshot).

On Ctrl-C / SIGTERM:
  1. The active crawl subprocess receives SIGINT so it can finish enrichment
     and export gracefully (the crawl pipeline already handles SIGINT).
  2. Both threads finish their current operation, then the process exits.

Usage examples:
  # Crawl 10-min chunks continuously; update tag DB every 15 min; skip LLM:
  python run_parallel_pipeline.py \\
      --cycle-crawl-seconds 600 --tag-interval-seconds 900 --skip-llm

  # Tag DB first run after 5 min; then every 10 min; mock LLM:
  python run_parallel_pipeline.py \\
      --cycle-crawl-seconds 300 --tag-interval-seconds 600 \\
      --tag-initial-delay-seconds 300 --mock

  # Extra flags forwarded to sub-scripts (use quotes for multi-word values):
  python run_parallel_pipeline.py \\
      --cycle-crawl-seconds 600 --tag-interval-seconds 900 --skip-llm \\
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
import threading
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(prefix: str, msg: str) -> None:
    print(f"[{_now_iso()}][{prefix}] {msg}", flush=True)


def _banner(text: str) -> None:
    line = "=" * 64
    print(f"\n{line}", flush=True)
    print(f"  {text}", flush=True)
    print(f"{line}", flush=True)


# ---------------------------------------------------------------------------
# Thread-safe subprocess holder (for SIGINT forwarding)
# ---------------------------------------------------------------------------

class _ProcHolder:
    """Holds a reference to the currently running crawl subprocess so the
    signal handler can interrupt it without a race condition."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def set(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc

    def clear(self) -> None:
        with self._lock:
            self._proc = None

    def interrupt(self) -> None:
        """Send SIGINT to the active subprocess (if any)."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.send_signal(signal.SIGINT)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parallel pipeline: continuous crawl + periodic tag DB ingestion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Two independent threads:
              crawl – loops forever, restarting each --cycle-crawl-seconds run
              tag   – wakes every --tag-interval-seconds to ingest new JSON files

            Ctrl-C sends SIGINT to the active crawl process (graceful wind-down),
            then waits for both threads to finish before exiting.
            """
        ),
    )

    # --- crawl ---
    crawl = parser.add_argument_group("Crawl thread (continuous)")
    crawl.add_argument(
        "--cycle-crawl-seconds", type=float, required=True,
        help="Duration of each crawl run in seconds.",
    )
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
        help="Max videos for the enricher step per crawl run.",
    )
    crawl.add_argument(
        "--headful", action="store_true",
        help="Run browser sub-commands in headful mode.",
    )
    crawl.add_argument(
        "--crawl-restart-delay-seconds", type=float, default=2.0,
        help="Pause between crawl restarts (default: 2s). Avoids tight loops on error.",
    )
    crawl.add_argument(
        "--stop-crawl-on-error", action="store_true",
        help="Stop the crawl loop on non-zero exit (default: log and restart).",
    )
    crawl.add_argument(
        "--crawl-extra", default="",
        help="Extra flags forwarded verbatim to run_auto_pipeline_jingxuan.py (shlex-split).",
    )

    # --- tag DB ---
    tag = parser.add_argument_group("Tag DB thread (periodic)")
    tag.add_argument(
        "--tag-interval-seconds", type=float, required=True,
        help="Run the tag DB pipeline every N seconds.",
    )
    tag.add_argument(
        "--tag-initial-delay-seconds", type=float, default=0.0,
        help="Wait this long before the first tag DB run (default: 0 = start immediately).",
    )
    tag.add_argument(
        "--tag-db", default=str(DEFAULT_TAG_DB),
        help="Tag knowledge SQLite database path.",
    )
    tag.add_argument(
        "--tag-input-dir", default=str(DEFAULT_INPUT_DIR),
        help="Directory with complete-metrics JSON files (output of crawl).",
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
        help="Max LLM tasks per tag DB run.",
    )
    tag.add_argument(
        "--stop-tag-on-error", action="store_true",
        help="Stop the tag DB loop on non-zero exit (default: log and continue).",
    )
    tag.add_argument(
        "--tag-extra", default="",
        help="Extra flags forwarded verbatim to run_pipeline.py (shlex-split).",
    )

    return parser


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def _build_crawl_cmd(args: argparse.Namespace) -> list[str]:
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
    return cmd


def _build_tag_cmd(args: argparse.Namespace) -> list[str]:
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
    return cmd


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def crawl_worker(
    args: argparse.Namespace,
    shutdown: threading.Event,
    errors: list[str],
    proc_holder: _ProcHolder,
) -> None:
    cmd = _build_crawl_cmd(args)
    run_num = 0

    while not shutdown.is_set():
        run_num += 1
        _log("CRAWL", f"Starting run #{run_num}  ({args.cycle_crawl_seconds}s)…")

        proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT))
        proc_holder.set(proc)
        rc = proc.wait()
        proc_holder.clear()

        if shutdown.is_set():
            # Normal shutdown path — rc may be non-zero due to our own SIGINT.
            _log("CRAWL", f"Run #{run_num} ended (shutdown in progress, rc={rc}).")
            break

        if rc != 0:
            msg = f"crawl run #{run_num} failed (rc={rc})"
            _log("CRAWL", f"ERROR: {msg}")
            errors.append(msg)
            if args.stop_crawl_on_error:
                shutdown.set()
                break
            # Brief pause before restarting to avoid hammering on persistent failures.
            _log("CRAWL", f"Restarting in {args.crawl_restart_delay_seconds}s…")
            shutdown.wait(timeout=args.crawl_restart_delay_seconds)
        else:
            _log("CRAWL", f"Run #{run_num} finished OK. Restarting immediately.")

    _log("CRAWL", "Worker stopped.")


def tag_worker(
    args: argparse.Namespace,
    shutdown: threading.Event,
    errors: list[str],
) -> None:
    cmd = _build_tag_cmd(args)
    run_num = 0

    # Optional initial delay before the first run.
    if args.tag_initial_delay_seconds > 0 and not shutdown.is_set():
        _log("TAG-DB", f"Initial delay: waiting {args.tag_initial_delay_seconds}s before first run…")
        shutdown.wait(timeout=args.tag_initial_delay_seconds)

    while not shutdown.is_set():
        run_num += 1
        _log("TAG-DB", f"Starting run #{run_num}…")
        t0 = time.monotonic()

        proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT))
        rc = proc.wait()

        elapsed = time.monotonic() - t0

        if rc != 0:
            msg = f"tag DB run #{run_num} failed (rc={rc})"
            _log("TAG-DB", f"ERROR: {msg}")
            errors.append(msg)
            if args.stop_tag_on_error:
                shutdown.set()
                break
        else:
            _log("TAG-DB", f"Run #{run_num} finished OK in {elapsed:.1f}s.")

        # Sleep until the next scheduled run.  If the run itself took longer
        # than the interval, start the next one immediately (no accumulated drift).
        wait = args.tag_interval_seconds - (time.monotonic() - t0)
        if wait > 0 and not shutdown.is_set():
            _log("TAG-DB", f"Next run in {wait:.0f}s…")
            shutdown.wait(timeout=wait)

    _log("TAG-DB", "Worker stopped.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cycle_crawl_seconds <= 0:
        parser.error("--cycle-crawl-seconds must be > 0")
    if args.tag_interval_seconds <= 0:
        parser.error("--tag-interval-seconds must be > 0")
    if args.tag_initial_delay_seconds < 0:
        parser.error("--tag-initial-delay-seconds must be >= 0")
    if args.crawl_restart_delay_seconds < 0:
        parser.error("--crawl-restart-delay-seconds must be >= 0")

    shutdown = threading.Event()
    errors: list[str] = []
    crawl_proc = _ProcHolder()

    def _on_signal(signum, _frame) -> None:
        if not shutdown.is_set():
            _log("MAIN", f"Signal {signum} received — finishing current operations and shutting down…")
        shutdown.set()
        crawl_proc.interrupt()   # ask crawl to wind down gracefully via SIGINT

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    started_at = _now_iso()
    _banner(f"Parallel Pipeline  –  started {started_at}")
    print(f"  Crawl cycle      : {args.cycle_crawl_seconds}s per run, continuous", flush=True)
    print(
        f"  Tag DB interval  : every {args.tag_interval_seconds}s"
        + (f"  (first run after {args.tag_initial_delay_seconds}s)" if args.tag_initial_delay_seconds else ""),
        flush=True,
    )
    print(f"  Tag input dir    : {args.tag_input_dir}", flush=True)
    print("  Ctrl-C to stop gracefully.\n", flush=True)

    t_crawl = threading.Thread(
        target=crawl_worker,
        args=(args, shutdown, errors, crawl_proc),
        name="crawl",
        daemon=False,
    )
    t_tag = threading.Thread(
        target=tag_worker,
        args=(args, shutdown, errors),
        name="tag",
        daemon=False,
    )

    t_crawl.start()
    t_tag.start()

    # Block main thread until both workers finish.
    t_crawl.join()
    t_tag.join()

    _banner("Parallel pipeline stopped")
    print(f"  Started  : {started_at}")
    print(f"  Stopped  : {_now_iso()}")
    if errors:
        print(f"  Errors   : {len(errors)}")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  Errors   : 0")
    print()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
