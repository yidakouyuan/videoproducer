#!/usr/bin/env python3
"""Run an automated Douyin Jingxuan sampling pipeline.

Pipeline:
1. collect_douyin_jingxuan_swipe_crawler.py
2. collect_douyin_video_detail_enricher.py
3. export_video_detail_complete_metrics.py
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl


SCRIPT_JINGXUAN = Path("src/douyin_hot_db/collect_douyin_jingxuan_swipe_crawler.py")
SCRIPT_ENRICHER = Path("src/douyin_hot_db/collect_douyin_video_detail_enricher.py")
SCRIPT_EXPORT = Path("src/douyin_hot_db/export_video_detail_complete_metrics.py")


class PipelineError(RuntimeError):
    """Raised when pipeline execution fails."""


@dataclass
class RunInfo:
    run_id: str
    source: str
    status: str
    started_at: str | None
    ended_at: str | None
    message: str | None


class SingleInstanceLock:
    """Non-blocking process lock backed by flock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fp = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError(f"another pipeline process is running (lock: {self.path})") from exc
        self._fp.write(f"pid={os.getpid()} started_at={utc_now_iso()}\n")
        self._fp.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fp is None:
            return
        try:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
        finally:
            self._fp.close()
            self._fp = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_repo_path(repo_root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return repo_root / p


def connect_db_readonly(db_path: Path) -> sqlite3.Connection:
    db_uri_primary = f"file:{db_path.resolve()}?mode=ro"
    db_uri_fallback = f"file:{db_path.resolve()}?mode=ro&immutable=1"
    last_exc: Exception | None = None
    for uri in (db_uri_primary, db_uri_fallback):
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"failed to open db readonly: {db_path}") from last_exc


def fetch_latest_run(db_path: Path, source: str) -> RunInfo | None:
    conn = connect_db_readonly(db_path)
    try:
        row = conn.execute(
            """
            SELECT run_id, source, status, started_at, ended_at, message
            FROM runs
            WHERE source = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (source,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return RunInfo(
        run_id=str(row["run_id"]),
        source=str(row["source"]),
        status=str(row["status"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        message=row["message"],
    )


def fetch_new_run(db_path: Path, source: str, previous_run_id: str | None) -> RunInfo:
    latest = fetch_latest_run(db_path=db_path, source=source)
    if latest is None:
        raise PipelineError(f"no run found for source={source}")
    if previous_run_id and latest.run_id == previous_run_id:
        raise PipelineError(f"no new run generated for source={source}")
    return latest


def fetch_run_by_id(db_path: Path, run_id: str) -> RunInfo | None:
    conn = connect_db_readonly(db_path)
    try:
        row = conn.execute(
            """
            SELECT run_id, source, status, started_at, ended_at, message
            FROM runs
            WHERE run_id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return RunInfo(
        run_id=str(row["run_id"]),
        source=str(row["source"]),
        status=str(row["status"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        message=row["message"],
    )


def wait_for_run_status(
    db_path: Path,
    run_id: str,
    wait_seconds: float,
    poll_seconds: float = 2.0,
) -> RunInfo | None:
    if wait_seconds <= 0:
        return fetch_run_by_id(db_path, run_id)
    deadline = time.monotonic() + wait_seconds
    last = fetch_run_by_id(db_path, run_id)
    while last is not None and last.status == "running" and time.monotonic() < deadline:
        time.sleep(max(0.2, poll_seconds))
        last = fetch_run_by_id(db_path, run_id)
    return last


def count_rows_by_run(db_path: Path, table: str, run_id: str) -> int:
    conn = connect_db_readonly(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


def count_distinct_aweme_by_run(db_path: Path, table: str, run_id: str) -> int:
    conn = connect_db_readonly(db_path)
    try:
        row = conn.execute(
            f"SELECT COUNT(DISTINCT aweme_id) AS c FROM {table} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


def write_log(log_fp, text: str) -> None:
    log_fp.write(text)
    if not text.endswith("\n"):
        log_fp.write("\n")
    log_fp.flush()


def _stream_process_output(proc: subprocess.Popen[str], log_fp) -> None:
    if proc.stdout is None:
        return
    for line in proc.stdout:
        sys.stdout.write(line)
        log_fp.write(line)
    log_fp.flush()


def _send_signal_tree(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
        return
    except Exception:
        pass
    try:
        proc.send_signal(sig)
    except Exception:
        pass


def run_command(
    cmd: list[str],
    cwd: Path,
    log_fp,
    timeout_seconds: float | None = None,
    sigint_grace_seconds: float = 90.0,
    sigterm_grace_seconds: float = 15.0,
) -> tuple[int, bool]:
    cmd_text = " ".join(cmd)
    banner = f"\n$ {cmd_text}\n"
    sys.stdout.write(banner)
    sys.stdout.flush()
    write_log(log_fp, banner.rstrip("\n"))

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    output_thread = threading.Thread(target=_stream_process_output, args=(proc, log_fp), daemon=True)
    output_thread.start()

    start = time.monotonic()
    interrupted_by_timeout = False
    sigint_at: float | None = None
    sigterm_at: float | None = None
    while True:
        rc = proc.poll()
        if rc is not None:
            break

        now = time.monotonic()
        if timeout_seconds is not None and not interrupted_by_timeout and (now - start) >= timeout_seconds:
            interrupted_by_timeout = True
            sigint_at = now
            note = f"[pipeline] crawl timeout reached ({timeout_seconds}s), sending SIGINT"
            print(note)
            write_log(log_fp, note)
            _send_signal_tree(proc, signal.SIGINT)

        if interrupted_by_timeout and sigint_at is not None and proc.poll() is None and (now - sigint_at) >= sigint_grace_seconds:
            if sigterm_at is None:
                sigterm_at = now
                note = "[pipeline] process still alive after SIGINT grace, sending SIGTERM"
                print(note)
                write_log(log_fp, note)
                _send_signal_tree(proc, signal.SIGTERM)
            elif proc.poll() is None and (now - sigterm_at) >= sigterm_grace_seconds:
                note = "[pipeline] process still alive after SIGTERM grace, sending SIGKILL"
                print(note)
                write_log(log_fp, note)
                _send_signal_tree(proc, signal.SIGKILL)
        time.sleep(0.2)

    output_thread.join(timeout=3.0)
    if proc.stdout is not None:
        proc.stdout.close()
    log_fp.flush()
    return int(proc.returncode or 0), interrupted_by_timeout


def find_enricher_result_json(result_dir: Path, run_id: str) -> Path:
    expected = result_dir / f"{run_id}.json"
    if expected.exists():
        return expected
    candidates = sorted(result_dir.glob(f"{run_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    raise PipelineError(f"enricher result json not found for run_id={run_id} under {result_dir}")


def load_export_count(output_json: Path) -> int:
    try:
        data = json.loads(output_json.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineError(f"failed reading export output json: {output_json}") from exc
    value = data.get("output_record_count")
    try:
        return int(value)
    except Exception as exc:
        raise PipelineError(f"invalid output_record_count in {output_json}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated Douyin Jingxuan video data pipeline.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python binary used for sub-commands.",
    )
    parser.add_argument(
        "--lock-file",
        default="data/locks/douyin_auto_pipeline_jingxuan.lock",
        help="Lock file path to prevent concurrent runs.",
    )
    parser.add_argument(
        "--log-dir",
        default="data/logs/auto_pipeline_jingxuan",
        help="Directory for pipeline logs and summary json.",
    )

    parser.add_argument(
        "--jingxuan-start-url",
        default=None,
        help="Optional Jingxuan entry URL (e.g. https://www.douyin.com/jingxuan?modal_id=xxx).",
    )
    parser.add_argument(
        "--jingxuan-modal-id",
        default=None,
        help="Optional modal_id to build Jingxuan start URL (ignored if start-url is provided).",
    )
    parser.add_argument(
        "--jingxuan-jump-url-mode",
        choices=("jingxuan", "video"),
        default="jingxuan",
        help="Fallback jump URL mode when swipe cannot advance.",
    )
    parser.add_argument(
        "--jingxuan-rounds",
        type=int,
        default=0,
        help="Crawler rounds. 0 means endless loop (recommended with crawl-duration-seconds).",
    )
    parser.add_argument(
        "--jingxuan-crawl-duration-seconds",
        type=float,
        default=None,
        help="Optional crawl wall-clock duration in seconds. Pipeline sends SIGINT when exceeded.",
    )
    parser.add_argument(
        "--jingxuan-timeout-sigint-grace-seconds",
        type=float,
        default=90.0,
        help="After timeout SIGINT, how long to wait before SIGTERM.",
    )
    parser.add_argument(
        "--jingxuan-timeout-sigterm-grace-seconds",
        type=float,
        default=15.0,
        help="After timeout SIGTERM, how long to wait before SIGKILL.",
    )
    parser.add_argument(
        "--jingxuan-status-wait-seconds",
        type=float,
        default=45.0,
        help="After crawler exits, wait this long for runs.status to transition from running.",
    )
    parser.add_argument(
        "--jingxuan-allow-running-status-after-timeout",
        dest="jingxuan_allow_running_status_after_timeout",
        action="store_true",
        help="If timeout-triggered and rows pass health checks, allow runs.status=running temporarily.",
    )
    parser.add_argument(
        "--jingxuan-strict-status-after-timeout",
        dest="jingxuan_allow_running_status_after_timeout",
        action="store_false",
        help="Disable tolerance for runs.status=running after timeout.",
    )
    parser.add_argument(
        "--jingxuan-videos-per-round",
        type=int,
        default=20,
        help="Jingxuan crawler videos-per-round.",
    )
    parser.add_argument("--jingxuan-scroll-pixels", type=int, default=2200, help="Jingxuan scroll pixels per wheel.")
    parser.add_argument(
        "--jingxuan-startup-wait-seconds",
        type=float,
        default=6.0,
        help="Jingxuan startup wait seconds.",
    )
    parser.add_argument(
        "--jingxuan-action-wait-seconds",
        type=float,
        default=1.2,
        help="Jingxuan swipe action wait seconds.",
    )
    parser.add_argument(
        "--jingxuan-round-wait-seconds",
        type=float,
        default=2.0,
        help="Jingxuan per-round extra wait seconds.",
    )
    parser.add_argument(
        "--jingxuan-round-interval-seconds",
        type=float,
        default=0.5,
        help="Jingxuan sleep interval between rounds.",
    )
    parser.add_argument(
        "--jingxuan-max-swipe-attempts",
        type=int,
        default=4,
        help="Jingxuan max swipe attempts per round.",
    )
    parser.add_argument(
        "--jingxuan-max-empty-rounds-before-recover",
        type=int,
        default=3,
        help="Jingxuan max empty rounds before recovery reload.",
    )
    parser.add_argument(
        "--jingxuan-include-related",
        dest="jingxuan_include_related",
        action="store_true",
        help="Pass --include-related to Jingxuan crawler.",
    )
    parser.add_argument(
        "--jingxuan-no-include-related",
        dest="jingxuan_include_related",
        action="store_false",
        help="Pass --no-include-related to Jingxuan crawler.",
    )
    parser.add_argument(
        "--jingxuan-debug-dump-dir",
        default=None,
        help="Optional debug dump dir for Jingxuan crawler.",
    )
    parser.set_defaults(jingxuan_include_related=True, jingxuan_allow_running_status_after_timeout=True)
    parser.add_argument(
        "--min-jingxuan-videos",
        type=int,
        default=1,
        help="Health check: minimum rows in home_feed_snapshots for the run.",
    )

    parser.add_argument("--enrich-limit", type=int, default=100, help="Max videos for enricher.")
    parser.add_argument(
        "--enrich-force",
        action="store_true",
        help="Pass --force to enricher (re-enrich already processed videos).",
    )
    parser.add_argument(
        "--enrich-debug-dump-dir",
        default=None,
        help="Optional debug dump dir for enricher.",
    )
    parser.add_argument(
        "--enrich-results-dir",
        default="data/raw/video_detail_results",
        help="Directory containing enricher result json files.",
    )
    parser.add_argument(
        "--min-enriched-records",
        type=int,
        default=1,
        help="Health check: minimum rows in video_detail_snapshots for the run.",
    )

    parser.add_argument(
        "--complete-output-dir",
        default="data/raw/video_detail_results_complete",
        help="Output directory for complete-metrics json.",
    )
    parser.add_argument(
        "--complete-output-json",
        default=None,
        help="Explicit output json path for complete-metrics export.",
    )
    parser.add_argument(
        "--require-play",
        action="store_true",
        help="Require play_count in complete-metrics export.",
    )
    parser.add_argument(
        "--min-complete-records",
        type=int,
        default=1,
        help="Health check: minimum exported complete records.",
    )

    parser.add_argument("--headful", action="store_true", help="Run sub-commands with --headful.")
    return parser


def run_pipeline(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    db_path = resolve_repo_path(repo_root, args.db)
    assert db_path is not None
    lock_file = resolve_repo_path(repo_root, args.lock_file)
    assert lock_file is not None
    log_dir = resolve_repo_path(repo_root, args.log_dir)
    assert log_dir is not None
    jingxuan_debug_dump_dir = resolve_repo_path(repo_root, args.jingxuan_debug_dump_dir)
    enrich_debug_dump_dir = resolve_repo_path(repo_root, args.enrich_debug_dump_dir)
    enrich_results_dir = resolve_repo_path(repo_root, args.enrich_results_dir)
    assert enrich_results_dir is not None
    complete_output_dir = resolve_repo_path(repo_root, args.complete_output_dir)
    assert complete_output_dir is not None
    complete_output_json = resolve_repo_path(repo_root, args.complete_output_json)

    if args.jingxuan_rounds < 0:
        raise PipelineError("--jingxuan-rounds must be >= 0")
    if args.jingxuan_rounds == 0 and args.jingxuan_crawl_duration_seconds is None:
        raise PipelineError("--jingxuan-rounds=0 requires --jingxuan-crawl-duration-seconds")
    if args.jingxuan_crawl_duration_seconds is not None and args.jingxuan_crawl_duration_seconds <= 0:
        raise PipelineError("--jingxuan-crawl-duration-seconds must be > 0")
    if args.jingxuan_timeout_sigint_grace_seconds <= 0:
        raise PipelineError("--jingxuan-timeout-sigint-grace-seconds must be > 0")
    if args.jingxuan_timeout_sigterm_grace_seconds <= 0:
        raise PipelineError("--jingxuan-timeout-sigterm-grace-seconds must be > 0")
    if args.jingxuan_status_wait_seconds < 0:
        raise PipelineError("--jingxuan-status-wait-seconds must be >= 0")
    if args.jingxuan_videos_per_round <= 0:
        raise PipelineError("--jingxuan-videos-per-round must be > 0")
    if args.jingxuan_max_swipe_attempts <= 0:
        raise PipelineError("--jingxuan-max-swipe-attempts must be > 0")
    if args.jingxuan_max_empty_rounds_before_recover <= 0:
        raise PipelineError("--jingxuan-max-empty-rounds-before-recover must be > 0")
    if args.jingxuan_modal_id is not None and not str(args.jingxuan_modal_id).isdigit():
        raise PipelineError("--jingxuan-modal-id must be numeric")
    if args.enrich_limit <= 0:
        raise PipelineError("--enrich-limit must be > 0")
    if args.min_jingxuan_videos < 0 or args.min_enriched_records < 0 or args.min_complete_records < 0:
        raise PipelineError("health-check minimum values must be >= 0")

    log_dir.mkdir(parents=True, exist_ok=True)
    pipeline_run_id = uuid.uuid4().hex
    started_at = utc_now_iso()
    t0 = time.time()
    stamp = timestamp_compact_utc()
    log_path = log_dir / f"{stamp}_{pipeline_run_id}.log"
    summary_path = log_dir / f"{stamp}_{pipeline_run_id}.summary.json"

    summary: dict[str, Any] = {
        "pipeline_run_id": pipeline_run_id,
        "started_at": started_at,
        "status": "running",
        "repo_root": str(repo_root),
        "db_path": str(db_path),
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "steps": {},
    }
    try:
        with SingleInstanceLock(lock_file):
            with log_path.open("w", encoding="utf-8") as log_fp:
                write_log(log_fp, f"pipeline_run_id={pipeline_run_id}")
                write_log(log_fp, f"started_at={started_at}")
                write_log(log_fp, f"db_path={db_path}")

                # Step 1: Jingxuan swipe crawler.
                jingxuan_source = "douyin_jingxuan_swipe_crawler"
                jingxuan_prev = fetch_latest_run(db_path=db_path, source=jingxuan_source)
                jingxuan_cmd = [
                    args.python_bin,
                    str(repo_root / SCRIPT_JINGXUAN),
                    "--db",
                    str(db_path),
                    "--rounds",
                    str(args.jingxuan_rounds),
                    "--videos-per-round",
                    str(args.jingxuan_videos_per_round),
                    "--jump-url-mode",
                    str(args.jingxuan_jump_url_mode),
                    "--scroll-pixels",
                    str(args.jingxuan_scroll_pixels),
                    "--startup-wait-seconds",
                    str(args.jingxuan_startup_wait_seconds),
                    "--action-wait-seconds",
                    str(args.jingxuan_action_wait_seconds),
                    "--round-wait-seconds",
                    str(args.jingxuan_round_wait_seconds),
                    "--round-interval-seconds",
                    str(args.jingxuan_round_interval_seconds),
                    "--max-swipe-attempts",
                    str(args.jingxuan_max_swipe_attempts),
                    "--max-empty-rounds-before-recover",
                    str(args.jingxuan_max_empty_rounds_before_recover),
                ]
                if args.jingxuan_start_url:
                    jingxuan_cmd.extend(["--start-url", str(args.jingxuan_start_url)])
                if args.jingxuan_modal_id:
                    jingxuan_cmd.extend(["--modal-id", str(args.jingxuan_modal_id)])
                if args.jingxuan_include_related:
                    jingxuan_cmd.append("--include-related")
                else:
                    jingxuan_cmd.append("--no-include-related")
                if jingxuan_debug_dump_dir is not None:
                    jingxuan_cmd.extend(["--debug-dump-dir", str(jingxuan_debug_dump_dir)])
                if args.headful:
                    jingxuan_cmd.append("--headful")

                rc, interrupted_by_timeout = run_command(
                    jingxuan_cmd,
                    cwd=repo_root,
                    log_fp=log_fp,
                    timeout_seconds=args.jingxuan_crawl_duration_seconds,
                    sigint_grace_seconds=args.jingxuan_timeout_sigint_grace_seconds,
                    sigterm_grace_seconds=args.jingxuan_timeout_sigterm_grace_seconds,
                )
                if rc != 0 and not interrupted_by_timeout:
                    raise PipelineError(f"jingxuan swipe crawler failed, rc={rc}")

                jingxuan_run = fetch_new_run(
                    db_path=db_path,
                    source=jingxuan_source,
                    previous_run_id=jingxuan_prev.run_id if jingxuan_prev else None,
                )
                if args.jingxuan_status_wait_seconds > 0:
                    waited = wait_for_run_status(
                        db_path=db_path,
                        run_id=jingxuan_run.run_id,
                        wait_seconds=args.jingxuan_status_wait_seconds,
                    )
                    if waited is not None:
                        jingxuan_run = waited

                jingxuan_rows = count_rows_by_run(db_path, "home_feed_snapshots", jingxuan_run.run_id)
                jingxuan_unique = count_distinct_aweme_by_run(db_path, "home_feed_snapshots", jingxuan_run.run_id)
                if jingxuan_rows < args.min_jingxuan_videos:
                    raise PipelineError(
                        "jingxuan health check failed: "
                        f"rows={jingxuan_rows} < min_jingxuan_videos={args.min_jingxuan_videos}"
                    )
                status_tolerated = False
                if jingxuan_run.status != "success":
                    if (
                        interrupted_by_timeout
                        and args.jingxuan_allow_running_status_after_timeout
                        and jingxuan_run.status == "running"
                    ):
                        status_tolerated = True
                        note = (
                            "jingxuan run status is still running after timeout; "
                            f"continue because rows={jingxuan_rows} >= min_jingxuan_videos={args.min_jingxuan_videos}"
                        )
                        print(f"[pipeline] {note}")
                        write_log(log_fp, f"[pipeline] {note}")
                    else:
                        raise PipelineError(f"jingxuan run status is not success: {jingxuan_run.status}")
                summary["steps"]["jingxuan_swipe"] = {
                    "run_id": jingxuan_run.run_id,
                    "rows": jingxuan_rows,
                    "unique_aweme": jingxuan_unique,
                    "status": jingxuan_run.status,
                    "message": jingxuan_run.message,
                    "interrupted_by_timeout": int(interrupted_by_timeout),
                    "status_tolerated": int(status_tolerated),
                    "crawl_duration_seconds": args.jingxuan_crawl_duration_seconds,
                    "status_wait_seconds": args.jingxuan_status_wait_seconds,
                }
                write_log(
                    log_fp,
                    "jingxuan_run_id="
                    f"{jingxuan_run.run_id} rows={jingxuan_rows} unique_aweme={jingxuan_unique} "
                    f"interrupted_by_timeout={int(interrupted_by_timeout)} "
                    f"status_tolerated={int(status_tolerated)} rc={rc}",
                )

                # Step 2: Video detail enricher.
                enrich_source = "douyin_video_detail_enricher"
                enrich_prev = fetch_latest_run(db_path=db_path, source=enrich_source)
                enrich_cmd = [
                    args.python_bin,
                    str(repo_root / SCRIPT_ENRICHER),
                    "--db",
                    str(db_path),
                    "--from-home-run-id",
                    jingxuan_run.run_id,
                    "--limit",
                    str(args.enrich_limit),
                    "--no-only-missing-meta",
                ]
                if args.enrich_force:
                    enrich_cmd.append("--force")
                if enrich_debug_dump_dir is not None:
                    enrich_cmd.extend(["--debug-dump-dir", str(enrich_debug_dump_dir)])
                if args.headful:
                    enrich_cmd.append("--headful")

                rc, _ = run_command(enrich_cmd, cwd=repo_root, log_fp=log_fp, timeout_seconds=None)
                if rc != 0:
                    raise PipelineError(f"video detail enricher failed, rc={rc}")

                enrich_run = fetch_new_run(
                    db_path=db_path,
                    source=enrich_source,
                    previous_run_id=enrich_prev.run_id if enrich_prev else None,
                )
                if enrich_run.status != "success":
                    raise PipelineError(f"enricher run status is not success: {enrich_run.status}")

                enriched_rows = count_rows_by_run(db_path, "video_detail_snapshots", enrich_run.run_id)
                if enriched_rows < args.min_enriched_records:
                    raise PipelineError(
                        "enricher health check failed: "
                        f"rows={enriched_rows} < min_enriched_records={args.min_enriched_records}"
                    )
                enrich_result_json = find_enricher_result_json(enrich_results_dir, enrich_run.run_id)
                summary["steps"]["enricher"] = {
                    "run_id": enrich_run.run_id,
                    "rows": enriched_rows,
                    "status": enrich_run.status,
                    "message": enrich_run.message,
                    "result_json": str(enrich_result_json),
                }
                write_log(log_fp, f"enrich_run_id={enrich_run.run_id} rows={enriched_rows}")
                write_log(log_fp, f"enrich_result_json={enrich_result_json}")

                # Step 3: Export complete interaction metrics.
                complete_suffix = "complete5" if args.require_play else "complete4"
                export_output_json = (
                    complete_output_json
                    if complete_output_json is not None
                    else complete_output_dir / f"{enrich_run.run_id}.{complete_suffix}.json"
                )
                export_cmd = [
                    args.python_bin,
                    str(repo_root / SCRIPT_EXPORT),
                    "--input-json",
                    str(enrich_result_json),
                    "--output-json",
                    str(export_output_json),
                ]
                if args.require_play:
                    export_cmd.append("--require-play")

                rc, _ = run_command(export_cmd, cwd=repo_root, log_fp=log_fp, timeout_seconds=None)
                if rc != 0:
                    raise PipelineError(f"complete-metrics export failed, rc={rc}")

                exported_count = load_export_count(export_output_json)
                if exported_count < args.min_complete_records:
                    raise PipelineError(
                        "complete-metrics health check failed: "
                        f"rows={exported_count} < min_complete_records={args.min_complete_records}"
                    )
                summary["steps"]["complete_export"] = {
                    "output_json": str(export_output_json),
                    "output_record_count": exported_count,
                    "require_play": int(args.require_play),
                }
                write_log(log_fp, f"complete_output_json={export_output_json}")
                write_log(log_fp, f"complete_output_record_count={exported_count}")

        summary["status"] = "success"
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        raise
    finally:
        summary["ended_at"] = utc_now_iso()
        summary["duration_seconds"] = round(time.time() - t0, 3)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"auto pipeline summary: {summary_path}")
        print(f"auto pipeline log: {log_path}")

    print(f"auto pipeline success: pipeline_run_id={pipeline_run_id}")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        code = run_pipeline(args)
    except Exception as exc:
        print(f"auto pipeline failed: {exc}")
        raise SystemExit(1)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
