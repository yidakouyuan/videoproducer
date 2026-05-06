#!/usr/bin/env python3
"""Run an automated Douyin sampling pipeline.

Pipeline:
1. collect_douyin_home_feed_crawler.py
2. collect_douyin_video_detail_enricher.py
3. export_video_detail_complete_metrics.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl


SCRIPT_HOME_FEED = Path("src/douyin_hot_db/collect_douyin_home_feed_crawler.py")
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


def run_command(cmd: list[str], cwd: Path, log_fp) -> int:
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
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        log_fp.write(line)
    proc.wait()
    log_fp.flush()
    return int(proc.returncode or 0)


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
    except Exception:
        raise PipelineError(f"invalid output_record_count in {output_json}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated Douyin video data pipeline.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python binary used for sub-commands.",
    )
    parser.add_argument(
        "--lock-file",
        default="data/locks/douyin_auto_pipeline.lock",
        help="Lock file path to prevent concurrent runs.",
    )
    parser.add_argument(
        "--log-dir",
        default="data/logs/auto_pipeline",
        help="Directory for pipeline logs and summary json.",
    )

    parser.add_argument("--home-rounds", type=int, default=5, help="Home feed crawler rounds.")
    parser.add_argument("--home-videos-per-round", type=int, default=20, help="Home feed videos per round.")
    parser.add_argument(
        "--home-include-related",
        action="store_true",
        help="Pass --include-related to home feed crawler.",
    )
    parser.add_argument(
        "--home-debug-dump-dir",
        default=None,
        help="Optional debug dump dir for home feed crawler.",
    )
    parser.add_argument(
        "--home-seed-aweme-id",
        default=None,
        help="Optional seed aweme_id passed to home feed crawler (crawler starts from this seed).",
    )
    parser.add_argument(
        "--home-seed-url",
        default=None,
        help="Optional seed video URL passed to home feed crawler (higher priority than home-seed-aweme-id).",
    )
    parser.add_argument(
        "--home-seed-next-mode",
        choices=("related", "swipe"),
        default="swipe",
        help=(
            "How seed-video mode advances each round in home crawler: "
            "'related' picks unseen related candidates; "
            "'swipe' advances one-by-one by swipe/ArrowDown."
        ),
    )
    parser.add_argument(
        "--min-home-videos",
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
    home_debug_dump_dir = resolve_repo_path(repo_root, args.home_debug_dump_dir)
    enrich_debug_dump_dir = resolve_repo_path(repo_root, args.enrich_debug_dump_dir)
    enrich_results_dir = resolve_repo_path(repo_root, args.enrich_results_dir)
    assert enrich_results_dir is not None
    complete_output_dir = resolve_repo_path(repo_root, args.complete_output_dir)
    assert complete_output_dir is not None
    complete_output_json = resolve_repo_path(repo_root, args.complete_output_json)

    if args.home_rounds < 0:
        raise PipelineError("--home-rounds must be >= 0")
    if args.home_videos_per_round <= 0:
        raise PipelineError("--home-videos-per-round must be > 0")
    if args.home_seed_aweme_id is not None and not str(args.home_seed_aweme_id).isdigit():
        raise PipelineError("--home-seed-aweme-id must be numeric")
    if args.enrich_limit <= 0:
        raise PipelineError("--enrich-limit must be > 0")
    if args.min_home_videos < 0 or args.min_enriched_records < 0 or args.min_complete_records < 0:
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

                # Step 1: Home feed crawler.
                home_source = "douyin_home_feed_crawler"
                home_prev = fetch_latest_run(db_path=db_path, source=home_source)
                home_cmd = [
                    args.python_bin,
                    str(repo_root / SCRIPT_HOME_FEED),
                    "--db",
                    str(db_path),
                    "--rounds",
                    str(args.home_rounds),
                    "--videos-per-round",
                    str(args.home_videos_per_round),
                ]
                if args.home_seed_aweme_id:
                    home_cmd.extend(["--seed-aweme-id", str(args.home_seed_aweme_id)])
                if args.home_seed_url:
                    home_cmd.extend(["--seed-url", str(args.home_seed_url)])
                if args.home_seed_next_mode:
                    home_cmd.extend(["--seed-next-mode", str(args.home_seed_next_mode)])
                if args.home_include_related:
                    home_cmd.append("--include-related")
                if home_debug_dump_dir is not None:
                    home_cmd.extend(["--debug-dump-dir", str(home_debug_dump_dir)])
                if args.headful:
                    home_cmd.append("--headful")

                rc = run_command(home_cmd, cwd=repo_root, log_fp=log_fp)
                if rc != 0:
                    raise PipelineError(f"home feed crawler failed, rc={rc}")

                home_run = fetch_new_run(
                    db_path=db_path,
                    source=home_source,
                    previous_run_id=home_prev.run_id if home_prev else None,
                )
                if home_run.status != "success":
                    raise PipelineError(f"home feed run status is not success: {home_run.status}")

                home_rows = count_rows_by_run(db_path, "home_feed_snapshots", home_run.run_id)
                home_unique = count_distinct_aweme_by_run(db_path, "home_feed_snapshots", home_run.run_id)
                if home_rows < args.min_home_videos:
                    raise PipelineError(
                        f"home feed health check failed: rows={home_rows} < min_home_videos={args.min_home_videos}"
                    )
                summary["steps"]["home_feed"] = {
                    "run_id": home_run.run_id,
                    "rows": home_rows,
                    "unique_aweme": home_unique,
                    "status": home_run.status,
                    "message": home_run.message,
                }
                write_log(log_fp, f"home_feed_run_id={home_run.run_id} rows={home_rows} unique_aweme={home_unique}")

                # Step 2: Video detail enricher.
                enrich_source = "douyin_video_detail_enricher"
                enrich_prev = fetch_latest_run(db_path=db_path, source=enrich_source)
                enrich_cmd = [
                    args.python_bin,
                    str(repo_root / SCRIPT_ENRICHER),
                    "--db",
                    str(db_path),
                    "--from-home-run-id",
                    home_run.run_id,
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

                rc = run_command(enrich_cmd, cwd=repo_root, log_fp=log_fp)
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

                rc = run_command(export_cmd, cwd=repo_root, log_fp=log_fp)
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
