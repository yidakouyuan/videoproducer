#!/usr/bin/env python3
"""Export records with complete interaction metrics from video_detail result JSON."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = Path("data/raw/video_detail_results")
DEFAULT_OUTPUT_DIR = Path("data/raw/video_detail_results_complete")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_input_file(path_arg: str | None, input_dir: Path) -> Path:
    if path_arg:
        p = Path(path_arg).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"input json not found: {p}")
        return p

    if not input_dir.exists():
        raise FileNotFoundError(f"input dir not found: {input_dir}")

    files = sorted((p for p in input_dir.glob("*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no json files found under: {input_dir}")
    return files[0]


def metrics_complete(record: dict[str, Any], require_play: bool) -> bool:
    required = ("digg_count", "comment_count", "collect_count", "share_count")
    if any(record.get(key) is None for key in required):
        return False
    if require_play and record.get("play_count") is None:
        return False
    return True


def classify_missing(record: dict[str, Any], require_play: bool) -> list[str]:
    required = ["digg_count", "comment_count", "collect_count", "share_count"]
    if require_play:
        required.append("play_count")
    return [k for k in required if record.get(k) is None]


def build_default_output_path(output_dir: Path, input_file: Path, require_play: bool) -> Path:
    stem = input_file.stem
    suffix = "complete5" if require_play else "complete4"
    return output_dir / f"{stem}.{suffix}.json"


def run_export(args: argparse.Namespace) -> Path:
    input_dir = Path(args.input_dir).expanduser()
    output_dir = Path(args.output_dir).expanduser()
    input_file = resolve_input_file(args.input_json, input_dir=input_dir)

    data = json.loads(input_file.read_text(encoding="utf-8"))
    records = data.get("records") or []
    if not isinstance(records, list):
        raise ValueError('invalid input: "records" must be a list')

    kept: list[dict[str, Any]] = []
    missing_stats: dict[str, int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if metrics_complete(rec, require_play=args.require_play):
            kept.append(rec)
            continue
        for miss in classify_missing(rec, require_play=args.require_play):
            missing_stats[miss] = missing_stats.get(miss, 0) + 1

    output_path = (
        Path(args.output_json).expanduser()
        if args.output_json
        else build_default_output_path(output_dir=output_dir, input_file=input_file, require_play=args.require_play)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out = {
        "source": "video_detail_complete_metrics_exporter",
        "generated_at": utc_now_iso(),
        "input_file": str(input_file),
        "input_run_id": data.get("run_id"),
        "input_record_count": len(records),
        "output_record_count": len(kept),
        "require_play": int(args.require_play),
        "missing_field_counts": missing_stats,
        "records": kept,
    }
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter video_detail result JSON to records with complete interaction metrics."
    )
    parser.add_argument("--input-json", default=None, help="Specific input JSON file. Default: latest in --input-dir.")
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing video_detail result JSON files.",
    )
    parser.add_argument("--output-json", default=None, help="Explicit output JSON file path.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for auto-generated output file.",
    )
    parser.add_argument(
        "--require-play",
        action="store_true",
        help="Require play_count to be non-null in addition to like/comment/collect/share.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    output_path = run_export(args)
    print(f"complete metrics json: {output_path}")


if __name__ == "__main__":
    main()
