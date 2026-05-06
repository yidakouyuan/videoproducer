#!/usr/bin/env python3
"""Core library for building and querying the standalone tag knowledge database."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import logging
import math
import re
import sqlite3
import sys
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# GraphRAG integration: add graphrag package to path and import hierarchical leiden
# ---------------------------------------------------------------------------
_GRAPHRAG_PKG = Path(__file__).resolve().parents[1] / "graphrag" / "packages" / "graphrag"
if _GRAPHRAG_PKG.is_dir() and str(_GRAPHRAG_PKG) not in sys.path:
    sys.path.insert(0, str(_GRAPHRAG_PKG))

try:
    from graphrag.graphs.hierarchical_leiden import hierarchical_leiden as _graphrag_hierarchical_leiden
    _HAS_GRAPHRAG_LEIDEN = True
except ImportError:
    try:
        import graspologic_native as _gn

        def _graphrag_hierarchical_leiden(
            edges: list[tuple[str, str, float]],
            max_cluster_size: int = 10,
            random_seed: int | None = 0xDEADBEEF,
        ):
            return _gn.hierarchical_leiden(
                edges=edges,
                max_cluster_size=max_cluster_size,
                seed=random_seed,
                starting_communities=None,
                resolution=1.0,
                randomness=0.001,
                use_modularity=True,
                iterations=1,
            )
        _HAS_GRAPHRAG_LEIDEN = True
    except ImportError:
        _HAS_GRAPHRAG_LEIDEN = False

logger = logging.getLogger(__name__)

HASHTAG_RE = re.compile(r"#([^\s#]+)")
PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)

CAMPAIGN_HINT_KEYWORDS = (
    "挑战",
    "活动",
    "征集",
    "大赛",
    "打卡",
    "抽奖",
    "福利",
    "开赛",
    "内容启发搜索",
    "热点",
    "话题",
    "模板",
    "挑战赛",
    "campaign",
    "challenge",
    "event",
)


@dataclass
class PairStats:
    co_cnt_total: int = 0
    co_cnt_7d: int = 0
    co_cnt_30d: int = 0
    decayed_weight: float = 0.0
    last_event: datetime = datetime.fromtimestamp(0, tz=timezone.utc)


# ------------------------------
# Generic helpers
# ------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()



def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            if "." in text:
                return int(float(text))
            return int(text)
        except ValueError:
            return None
    return None



def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None



def metric_max(existing: int | None, new_value: int | None) -> int | None:
    if existing is None:
        return new_value
    if new_value is None:
        return existing
    return max(existing, new_value)



def normalize_tag(raw_tag: Any) -> str | None:
    if raw_tag is None:
        return None
    text = str(raw_tag)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.strip()
    while text.startswith("#"):
        text = text[1:].strip()
    text = re.sub(r"\s+", "", text)
    text = text.strip()
    if not text:
        return None
    text = text.lower()
    if PUNCT_ONLY_RE.match(text):
        return None
    if len(text) > 64:
        text = text[:64]
    return text



def clean_display_tag(raw_tag: Any) -> str | None:
    if raw_tag is None:
        return None
    text = unicodedata.normalize("NFKC", str(raw_tag)).strip()
    while text.startswith("#"):
        text = text[1:].strip()
    if not text:
        return None
    if len(text) > 64:
        text = text[:64]
    return text



def infer_tag_kind_heuristic(canonical_name: str) -> tuple[str, float]:
    lowered = canonical_name.lower()
    for keyword in CAMPAIGN_HINT_KEYWORDS:
        if keyword in lowered:
            return "campaign", 0.65
    return "topic", 0.55



def video_event_time_from_row(create_time: int | None, captured_at: str | None, fallback: datetime) -> datetime:
    if create_time and create_time > 0:
        try:
            return datetime.fromtimestamp(create_time, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    captured = parse_iso_datetime(captured_at)
    if captured:
        return captured
    return fallback



def record_event_time(record: dict[str, Any], fallback: datetime) -> datetime:
    return video_event_time_from_row(
        create_time=safe_int(record.get("create_time")),
        captured_at=record.get("captured_at"),
        fallback=fallback,
    )



def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ------------------------------
# DB helpers
# ------------------------------


def connect_db(db_path: Path) -> sqlite3.Connection:
    ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn



def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply incremental column additions to existing databases."""
    new_columns = [
        ("communities", "report_title", "TEXT"),
        ("communities", "report_summary", "TEXT"),
        ("communities", "report_rating", "REAL"),
        ("communities", "report_findings_json", "TEXT"),
    ]
    for table, col, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # column already exists


def init_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    _migrate_schema(conn)
    conn.commit()



def insert_ingest_run(conn: sqlite3.Connection, run_id: str, input_dir: Path, started_at: str) -> None:
    conn.execute(
        """
        INSERT INTO ingest_runs (
          run_id, started_at, status, input_dir
        ) VALUES (?, ?, 'running', ?)
        """,
        (run_id, started_at, str(input_dir)),
    )
    conn.commit()



def finish_ingest_run(
    conn: sqlite3.Connection,
    run_id: str,
    ended_at: str,
    status: str,
    files_seen: int,
    files_processed: int,
    records_seen: int,
    records_ingested: int,
    message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE ingest_runs
        SET ended_at = ?,
            status = ?,
            files_seen = ?,
            files_processed = ?,
            records_seen = ?,
            records_ingested = ?,
            message = ?
        WHERE run_id = ?
        """,
        (
            ended_at,
            status,
            files_seen,
            files_processed,
            records_seen,
            records_ingested,
            message,
            run_id,
        ),
    )
    conn.commit()


# ------------------------------
# Ingestion
# ------------------------------


def extract_tags_from_record(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(tag, source)] from payload and title hashtags."""
    out: list[tuple[str, str]] = []

    tags = record.get("tags")
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, dict):
                tag_text = item.get("tag") or item.get("name")
            else:
                tag_text = item
            display = clean_display_tag(tag_text)
            if display:
                out.append((display, "payload"))

    title = record.get("title")
    if isinstance(title, str) and title:
        for matched in HASHTAG_RE.findall(title):
            display = clean_display_tag(matched)
            if display:
                out.append((display, "title_fallback"))

    # keep unique normalized tags with payload priority over title fallback
    chosen: dict[str, tuple[str, str]] = {}
    for display, source in out:
        norm = normalize_tag(display)
        if not norm:
            continue
        prev = chosen.get(norm)
        if prev is None:
            chosen[norm] = (display, source)
            continue
        if prev[1] != "payload" and source == "payload":
            chosen[norm] = (display, source)

    return [(display, source) for display, source in chosen.values()]



def upsert_video(conn: sqlite3.Connection, record: dict[str, Any], now_iso: str) -> str | None:
    aweme_id = str(record.get("aweme_id") or "").strip()
    if not aweme_id:
        return None

    title = record.get("title") if isinstance(record.get("title"), str) else None
    author_id = str(record.get("author_id") or "").strip() or None
    author_name = record.get("author_name") if isinstance(record.get("author_name"), str) else None
    page_url = record.get("page_url") if isinstance(record.get("page_url"), str) else None
    source_kind = record.get("source_kind") if isinstance(record.get("source_kind"), str) else None
    source_api_url = record.get("source_api_url") if isinstance(record.get("source_api_url"), str) else None
    create_time = safe_int(record.get("create_time"))
    captured_at = record.get("captured_at") if isinstance(record.get("captured_at"), str) else None

    row = conn.execute(
        "SELECT digg_count, comment_count, collect_count, share_count, play_count FROM videos WHERE aweme_id = ?",
        (aweme_id,),
    ).fetchone()

    digg_count = safe_int(record.get("digg_count"))
    comment_count = safe_int(record.get("comment_count"))
    collect_count = safe_int(record.get("collect_count"))
    share_count = safe_int(record.get("share_count"))
    play_count = safe_int(record.get("play_count"))

    if row:
        digg_count = metric_max(row["digg_count"], digg_count)
        comment_count = metric_max(row["comment_count"], comment_count)
        collect_count = metric_max(row["collect_count"], collect_count)
        share_count = metric_max(row["share_count"], share_count)
        play_count = metric_max(row["play_count"], play_count)

    conn.execute(
        """
        INSERT INTO videos (
          aweme_id, title, author_id, author_name, page_url, source_kind, source_api_url,
          create_time, captured_at, digg_count, comment_count, collect_count, share_count, play_count,
          first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(aweme_id) DO UPDATE SET
          title = COALESCE(excluded.title, videos.title),
          author_id = COALESCE(excluded.author_id, videos.author_id),
          author_name = COALESCE(excluded.author_name, videos.author_name),
          page_url = COALESCE(excluded.page_url, videos.page_url),
          source_kind = COALESCE(excluded.source_kind, videos.source_kind),
          source_api_url = COALESCE(excluded.source_api_url, videos.source_api_url),
          create_time = COALESCE(videos.create_time, excluded.create_time),
          captured_at = COALESCE(excluded.captured_at, videos.captured_at),
          digg_count = COALESCE(excluded.digg_count, videos.digg_count),
          comment_count = COALESCE(excluded.comment_count, videos.comment_count),
          collect_count = COALESCE(excluded.collect_count, videos.collect_count),
          share_count = COALESCE(excluded.share_count, videos.share_count),
          play_count = COALESCE(excluded.play_count, videos.play_count),
          last_seen_at = excluded.last_seen_at
        """,
        (
            aweme_id,
            title,
            author_id,
            author_name,
            page_url,
            source_kind,
            source_api_url,
            create_time,
            captured_at,
            digg_count,
            comment_count,
            collect_count,
            share_count,
            play_count,
            now_iso,
            now_iso,
        ),
    )
    return aweme_id



def upsert_raw_tag(conn: sqlite3.Connection, raw_tag_norm: str, raw_tag_display: str, now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO raw_tags (raw_tag_norm, raw_tag_display, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(raw_tag_norm) DO UPDATE SET
          raw_tag_display = CASE
            WHEN length(raw_tags.raw_tag_display) >= length(excluded.raw_tag_display)
              THEN raw_tags.raw_tag_display
            ELSE excluded.raw_tag_display
          END,
          last_seen_at = excluded.last_seen_at
        """,
        (raw_tag_norm, raw_tag_display, now_iso, now_iso),
    )



def ensure_alias_for_raw_tag(conn: sqlite3.Connection, raw_tag_norm: str, now_iso: str) -> int:
    row = conn.execute("SELECT canonical_tag_id FROM tag_aliases WHERE raw_tag_norm = ?", (raw_tag_norm,)).fetchone()
    if row:
        return int(row["canonical_tag_id"])

    conn.execute(
        """
        INSERT INTO canonical_tags (
          canonical_name, tag_kind, kind_source, kind_confidence,
          first_seen_at, last_seen_at, updated_at
        ) VALUES (?, 'unknown', 'pending', NULL, ?, ?, ?)
        ON CONFLICT(canonical_name) DO UPDATE SET
          last_seen_at = excluded.last_seen_at,
          updated_at = excluded.updated_at
        """,
        (raw_tag_norm, now_iso, now_iso, now_iso),
    )

    canonical_row = conn.execute(
        "SELECT canonical_tag_id FROM canonical_tags WHERE canonical_name = ?",
        (raw_tag_norm,),
    ).fetchone()
    if canonical_row is None:
        raise RuntimeError(f"failed to create canonical tag for: {raw_tag_norm}")

    canonical_tag_id = int(canonical_row["canonical_tag_id"])

    conn.execute(
        """
        INSERT INTO tag_aliases (raw_tag_norm, canonical_tag_id, alias_source, confidence, updated_at)
        VALUES (?, ?, 'auto_identity', 1.0, ?)
        ON CONFLICT(raw_tag_norm) DO NOTHING
        """,
        (raw_tag_norm, canonical_tag_id, now_iso),
    )

    return canonical_tag_id



def upsert_video_raw_tag(
    conn: sqlite3.Connection,
    aweme_id: str,
    raw_tag_norm: str,
    source: str,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO video_raw_tags (aweme_id, raw_tag_norm, source, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(aweme_id, raw_tag_norm) DO UPDATE SET
          source = CASE
            WHEN video_raw_tags.source = 'payload' THEN video_raw_tags.source
            WHEN excluded.source = 'payload' THEN excluded.source
            ELSE video_raw_tags.source
          END,
          last_seen_at = excluded.last_seen_at
        """,
        (aweme_id, raw_tag_norm, source, now_iso, now_iso),
    )



def read_records_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    records = data.get("records")
    if not isinstance(records, list):
        return []
    out: list[dict[str, Any]] = []
    for item in records:
        if isinstance(item, dict):
            out.append(item)
    return out



def process_source_file(
    conn: sqlite3.Connection,
    path: Path,
    now_iso: str,
    force_reprocess: bool,
) -> tuple[bool, int, int]:
    stat = path.stat()
    digest = file_sha1(path)

    existing = conn.execute(
        "SELECT file_mtime, file_size, file_sha1 FROM source_files WHERE source_file = ?",
        (str(path),),
    ).fetchone()

    if (
        existing
        and not force_reprocess
        and float(existing["file_mtime"]) == float(stat.st_mtime)
        and int(existing["file_size"]) == int(stat.st_size)
        and str(existing["file_sha1"]) == digest
    ):
        records = read_records_from_json(path)
        return False, len(records), 0

    records = read_records_from_json(path)
    ingested = 0

    for record in records:
        aweme_id = upsert_video(conn, record=record, now_iso=now_iso)
        if not aweme_id:
            continue

        tags = extract_tags_from_record(record)
        for display, source in tags:
            raw_tag_norm = normalize_tag(display)
            if not raw_tag_norm:
                continue
            upsert_raw_tag(conn, raw_tag_norm=raw_tag_norm, raw_tag_display=display, now_iso=now_iso)
            ensure_alias_for_raw_tag(conn, raw_tag_norm=raw_tag_norm, now_iso=now_iso)
            upsert_video_raw_tag(conn, aweme_id=aweme_id, raw_tag_norm=raw_tag_norm, source=source, now_iso=now_iso)

        ingested += 1

    conn.execute(
        """
        INSERT INTO source_files (
          source_file, file_mtime, file_size, file_sha1,
          first_processed_at, last_processed_at,
          input_record_count, output_record_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_file) DO UPDATE SET
          file_mtime = excluded.file_mtime,
          file_size = excluded.file_size,
          file_sha1 = excluded.file_sha1,
          last_processed_at = excluded.last_processed_at,
          input_record_count = excluded.input_record_count,
          output_record_count = excluded.output_record_count
        """,
        (
            str(path),
            float(stat.st_mtime),
            int(stat.st_size),
            digest,
            now_iso,
            now_iso,
            len(records),
            ingested,
        ),
    )

    return True, len(records), ingested



def refresh_raw_tag_video_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE raw_tags
        SET video_count = (
          SELECT COUNT(*)
          FROM video_raw_tags vrt
          WHERE vrt.raw_tag_norm = raw_tags.raw_tag_norm
        )
        """
    )



def apply_kind_heuristics(conn: sqlite3.Connection, now_iso: str) -> int:
    rows = conn.execute(
        """
        SELECT canonical_tag_id, canonical_name
        FROM canonical_tags
        WHERE merged_into IS NULL
          AND kind_source = 'pending'
        """
    ).fetchall()

    updated = 0
    for row in rows:
        tag_kind, confidence = infer_tag_kind_heuristic(str(row["canonical_name"]))
        conn.execute(
            """
            UPDATE canonical_tags
            SET tag_kind = ?,
                kind_source = 'heuristic',
                kind_confidence = ?,
                updated_at = ?
            WHERE canonical_tag_id = ?
            """,
            (tag_kind, confidence, now_iso, int(row["canonical_tag_id"])),
        )
        updated += 1
    return updated


# ------------------------------
# Materialization
# ------------------------------


def score_from_metrics(digg: int, collect: int, comment: int, share: int) -> float:
    return collect * 3.0 + digg * 1.0 + share * 2.0 + comment * 0.5



def load_video_tag_projection(conn: sqlite3.Connection, now_dt: datetime) -> tuple[dict[str, dict[str, Any]], dict[str, set[int]]]:
    rows = conn.execute(
        """
        SELECT
          v.aweme_id,
          v.title,
          v.create_time,
          v.captured_at,
          COALESCE(v.digg_count, 0) AS digg_count,
          COALESCE(v.collect_count, 0) AS collect_count,
          COALESCE(v.comment_count, 0) AS comment_count,
          COALESCE(v.share_count, 0) AS share_count,
          ta.canonical_tag_id
        FROM video_raw_tags vrt
        JOIN tag_aliases ta ON ta.raw_tag_norm = vrt.raw_tag_norm
        JOIN canonical_tags ct ON ct.canonical_tag_id = ta.canonical_tag_id
        JOIN videos v ON v.aweme_id = vrt.aweme_id
        WHERE ct.merged_into IS NULL
        """
    ).fetchall()

    video_meta: dict[str, dict[str, Any]] = {}
    video_tags: dict[str, set[int]] = defaultdict(set)

    for row in rows:
        aweme_id = str(row["aweme_id"])
        canonical_id = int(row["canonical_tag_id"])
        video_tags[aweme_id].add(canonical_id)

        if aweme_id not in video_meta:
            event_time = video_event_time_from_row(
                create_time=safe_int(row["create_time"]),
                captured_at=row["captured_at"],
                fallback=now_dt,
            )
            video_meta[aweme_id] = {
                "aweme_id": aweme_id,
                "title": row["title"] if isinstance(row["title"], str) else "",
                "digg_count": int(row["digg_count"] or 0),
                "collect_count": int(row["collect_count"] or 0),
                "comment_count": int(row["comment_count"] or 0),
                "share_count": int(row["share_count"] or 0),
                "event_time": event_time,
                "event_time_iso": event_time.isoformat(),
            }

    return video_meta, video_tags



def rebuild_canonical_tag_stats(
    conn: sqlite3.Connection,
    now_iso: str,
    video_meta: dict[str, dict[str, Any]],
    video_tags: dict[str, set[int]],
    title_sample_size: int = 10,
) -> tuple[dict[int, dict[str, Any]], dict[int, set[str]]]:
    tag_stats: dict[int, dict[str, Any]] = {}
    tag_to_videos: dict[int, set[str]] = defaultdict(set)

    for aweme_id, tag_ids in video_tags.items():
        meta = video_meta.get(aweme_id)
        if meta is None:
            continue

        for tag_id in tag_ids:
            stat = tag_stats.setdefault(
                tag_id,
                {
                    "digg_sum": 0,
                    "collect_sum": 0,
                    "comment_sum": 0,
                    "share_sum": 0,
                    "score": 0.0,
                    "samples": [],
                },
            )
            stat["digg_sum"] += meta["digg_count"]
            stat["collect_sum"] += meta["collect_count"]
            stat["comment_sum"] += meta["comment_count"]
            stat["share_sum"] += meta["share_count"]
            stat["score"] += score_from_metrics(
                digg=meta["digg_count"],
                collect=meta["collect_count"],
                comment=meta["comment_count"],
                share=meta["share_count"],
            )

            sample = {
                "aweme_id": aweme_id,
                "title": meta["title"],
                "event_time": meta["event_time_iso"],
                "digg_count": meta["digg_count"],
                "collect_count": meta["collect_count"],
                "comment_count": meta["comment_count"],
                "share_count": meta["share_count"],
            }
            stat["samples"].append(sample)
            tag_to_videos[tag_id].add(aweme_id)

    conn.execute("DELETE FROM canonical_tag_stats")

    for tag_id, stat in tag_stats.items():
        samples = sorted(
            stat["samples"],
            key=lambda x: (
                x["collect_count"] * 3 + x["digg_count"] + x["share_count"] * 2 + x["comment_count"],
                x["event_time"],
            ),
            reverse=True,
        )[:title_sample_size]

        conn.execute(
            """
            INSERT INTO canonical_tag_stats (
              canonical_tag_id, video_count,
              digg_sum, collect_sum, comment_sum, share_sum,
              score, title_samples_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tag_id,
                len(tag_to_videos[tag_id]),
                int(stat["digg_sum"]),
                int(stat["collect_sum"]),
                int(stat["comment_sum"]),
                int(stat["share_sum"]),
                float(stat["score"]),
                json.dumps(samples, ensure_ascii=False),
                now_iso,
            ),
        )

    return tag_stats, tag_to_videos



def rebuild_cooccurrence(
    conn: sqlite3.Connection,
    now_dt: datetime,
    now_iso: str,
    video_meta: dict[str, dict[str, Any]],
    video_tags: dict[str, set[int]],
    half_life_days: float,
) -> dict[tuple[int, int], PairStats]:
    pair_stats: dict[tuple[int, int], PairStats] = {}

    cut_7d = now_dt - timedelta(days=7)
    cut_30d = now_dt - timedelta(days=30)

    for aweme_id, tag_ids in video_tags.items():
        if len(tag_ids) < 2:
            continue
        meta = video_meta.get(aweme_id)
        if meta is None:
            continue

        event_time = meta["event_time"]
        age_days = max(0.0, (now_dt - event_time).total_seconds() / 86400.0)
        decay = 1.0 if half_life_days <= 0 else math.pow(2.0, -age_days / half_life_days)
        is_7d = 1 if event_time >= cut_7d else 0
        is_30d = 1 if event_time >= cut_30d else 0

        for src, dst in itertools.combinations(sorted(tag_ids), 2):
            key = (src, dst)
            stat = pair_stats.get(key)
            if stat is None:
                stat = PairStats()
                pair_stats[key] = stat
            stat.co_cnt_total += 1
            stat.co_cnt_7d += is_7d
            stat.co_cnt_30d += is_30d
            stat.decayed_weight += decay
            if event_time > stat.last_event:
                stat.last_event = event_time

    conn.execute("DELETE FROM tag_cooccurrence")
    for (src, dst), stat in pair_stats.items():
        conn.execute(
            """
            INSERT INTO tag_cooccurrence (
              src_tag_id, dst_tag_id,
              co_cnt_total, co_cnt_7d, co_cnt_30d, decayed_weight,
              last_event_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src,
                dst,
                stat.co_cnt_total,
                stat.co_cnt_7d,
                stat.co_cnt_30d,
                float(stat.decayed_weight),
                stat.last_event.isoformat(),
                now_iso,
            ),
        )

    return pair_stats



def fetch_canonical_meta(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT canonical_tag_id, canonical_name, tag_kind, kind_source
        FROM canonical_tags
        WHERE merged_into IS NULL
        """
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        out[int(row["canonical_tag_id"])] = {
            "canonical_name": str(row["canonical_name"]),
            "tag_kind": str(row["tag_kind"]),
            "kind_source": str(row["kind_source"]),
        }
    return out



def _leiden_communities(
    topic_nodes: list[int],
    pair_stats: dict[tuple[int, int], "PairStats"],
    community_min_edge: int,
    leiden_max_cluster_size: int,
) -> dict[int, dict[str, list[int]]]:
    """Run graphrag hierarchical Leiden and return {level: {cluster_str: [tag_id, ...]}}.

    Falls back to connected-components (via Leiden on unweighted edges) when
    graspologic_native is unavailable.  Isolated nodes (no qualifying edges) are
    placed in singleton clusters at level 0.
    """
    topic_set = set(topic_nodes)
    leiden_edges: list[tuple[str, str, float]] = []
    for (a, b), stat in pair_stats.items():
        if stat.co_cnt_total < community_min_edge:
            continue
        if a not in topic_set or b not in topic_set:
            continue
        weight = float(stat.decayed_weight) if stat.decayed_weight > 0.0 else float(stat.co_cnt_total)
        leiden_edges.append((str(a), str(b), weight))

    level_clusters: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    nodes_in_leiden: set[str] = set()

    if leiden_edges and _HAS_GRAPHRAG_LEIDEN:
        try:
            hc_result = _graphrag_hierarchical_leiden(
                edges=leiden_edges,
                max_cluster_size=leiden_max_cluster_size,
            )
            for entry in hc_result:
                level_clusters[entry.level][str(entry.cluster)].append(int(entry.node))
                nodes_in_leiden.add(entry.node)
        except Exception:
            logger.exception("hierarchical_leiden failed; communities will be empty")

    # Singleton clusters for isolated nodes (not reached by leiden)
    isolated = [tid for tid in topic_nodes if str(tid) not in nodes_in_leiden]
    for tid in isolated:
        level_clusters[0][f"iso_{tid}"].append(tid)

    return {lvl: dict(clusters) for lvl, clusters in level_clusters.items()}



def build_community_report_text(
    tag_ids: list[int],
    canonical_meta: dict[int, dict[str, Any]],
    tag_stats: dict[int, dict[str, Any]],
    pair_stats: dict[tuple[int, int], PairStats],
) -> str:
    top_tags = sorted(
        tag_ids,
        key=lambda tid: tag_stats.get(tid, {}).get("score", 0.0),
        reverse=True,
    )[:8]
    top_tag_names = [canonical_meta[tid]["canonical_name"] for tid in top_tags if tid in canonical_meta]

    # collect strongest edges inside community
    candidate_edges: list[tuple[str, str, float]] = []
    tag_set = set(tag_ids)
    for (a, b), stat in pair_stats.items():
        if a in tag_set and b in tag_set:
            candidate_edges.append(
                (
                    canonical_meta.get(a, {}).get("canonical_name", str(a)),
                    canonical_meta.get(b, {}).get("canonical_name", str(b)),
                    stat.decayed_weight,
                )
            )
    candidate_edges.sort(key=lambda x: x[2], reverse=True)
    edge_lines = [f"{a} ↔ {b} (decayed_weight={w:.2f})" for a, b, w in candidate_edges[:5]]

    lines = [
        f"社区核心标签：{'、'.join(top_tag_names) if top_tag_names else '暂无'}。",
        "该社区适合作为同一主题方向的选题池，建议优先使用高共现标签组合进行脚本策划。",
        f"强共现关系：{'；'.join(edge_lines) if edge_lines else '暂无强边'}。",
    ]
    return "\n".join(lines)



def _snapshot_llm_community_reports(conn: sqlite3.Connection) -> dict[frozenset, dict[str, Any]]:
    """Return existing LLM-generated community reports keyed by their member tag-ID frozenset.

    Used to preserve reports across community rebuilds when member composition is unchanged.
    """
    rows = conn.execute(
        "SELECT community_id, report_text, report_source, report_title, report_summary, report_rating, report_findings_json FROM communities WHERE report_source != 'template'"
    ).fetchall()
    saved: dict[frozenset, dict[str, Any]] = {}
    for row in rows:
        cid = int(row["community_id"])
        member_ids = frozenset(
            int(r[0])
            for r in conn.execute(
                "SELECT canonical_tag_id FROM community_members WHERE community_id = ?", (cid,)
            ).fetchall()
        )
        saved[member_ids] = {
            "report_text": row["report_text"],
            "report_source": row["report_source"],
            "report_title": row["report_title"],
            "report_summary": row["report_summary"],
            "report_rating": row["report_rating"],
            "report_findings_json": row["report_findings_json"],
        }
    return saved


def rebuild_communities(
    conn: sqlite3.Connection,
    now_iso: str,
    community_min_edge: int,
    canonical_meta: dict[int, dict[str, Any]],
    tag_stats: dict[int, dict[str, Any]],
    pair_stats: dict[tuple[int, int], PairStats],
    leiden_max_cluster_size: int = 50,
) -> int:
    """Rebuild communities using graphrag hierarchical Leiden clustering.

    Stores one row per (level, cluster). Level 0 is the finest granularity.
    Queries should filter to ``level = 0`` for the most specific community.

    LLM-generated reports are preserved when community member composition is unchanged.
    """
    topic_nodes = [
        tag_id
        for tag_id, meta in canonical_meta.items()
        if meta.get("tag_kind") == "topic" and tag_id in tag_stats
    ]

    # Save LLM reports before clearing so we can restore them after rebuild
    llm_report_snapshot = _snapshot_llm_community_reports(conn)

    conn.execute("DELETE FROM community_members")
    conn.execute("DELETE FROM communities")

    if not topic_nodes:
        return 0

    level_clusters = _leiden_communities(
        topic_nodes=topic_nodes,
        pair_stats=pair_stats,
        community_min_edge=community_min_edge,
        leiden_max_cluster_size=leiden_max_cluster_size,
    )

    created = 0
    for level in sorted(level_clusters.keys()):
        for _cluster_key, tag_ids in level_clusters[level].items():
            members_sorted = sorted(
                tag_ids,
                key=lambda tid: (
                    tag_stats.get(tid, {}).get("score", 0.0),
                    canonical_meta.get(tid, {}).get("canonical_name", ""),
                ),
                reverse=True,
            )

            member_set = frozenset(members_sorted)
            prior = llm_report_snapshot.get(member_set)
            if prior:
                # Exact member match: restore the LLM report
                cur = conn.execute(
                    """
                    INSERT INTO communities
                        (algo, level, generated_at, topic_count,
                         report_text, report_source, report_title,
                         report_summary, report_rating, report_findings_json)
                    VALUES ('leiden', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        level, now_iso, len(members_sorted),
                        prior["report_text"], prior["report_source"],
                        prior["report_title"], prior["report_summary"],
                        prior["report_rating"], prior["report_findings_json"],
                    ),
                )
            else:
                report_text = build_community_report_text(
                    tag_ids=members_sorted,
                    canonical_meta=canonical_meta,
                    tag_stats=tag_stats,
                    pair_stats=pair_stats,
                )
                cur = conn.execute(
                    """
                    INSERT INTO communities (algo, level, generated_at, topic_count, report_text, report_source)
                    VALUES ('leiden', ?, ?, ?, ?, 'template')
                    """,
                    (level, now_iso, len(members_sorted), report_text),
                )

            community_id = int(cur.lastrowid)
            for idx, tag_id in enumerate(members_sorted, start=1):
                conn.execute(
                    """
                    INSERT INTO community_members (community_id, canonical_tag_id, member_rank, score)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        community_id,
                        tag_id,
                        idx,
                        float(tag_stats.get(tag_id, {}).get("score", 0.0)),
                    ),
                )
            created += 1

    return created



def build_tag_card_text(
    tag_name: str,
    tag_kind: str,
    top_co_tags: list[dict[str, Any]],
) -> str:
    if top_co_tags:
        co_names = "、".join(item["canonical_name"] for item in top_co_tags[:3])
    else:
        co_names = "暂无明显共现标签"

    if tag_kind == "campaign":
        return f"{tag_name} 更偏活动入口标签，常与 {co_names} 联动，适合先定活动切口再下钻主题内容。"
    return f"{tag_name} 是稳定主题标签，常与 {co_names} 同时出现，可直接作为脚本选题方向。"



def fetch_top_co_tags_from_pairs(
    tag_id: int,
    pair_stats: dict[tuple[int, int], PairStats],
    canonical_meta: dict[int, dict[str, Any]],
    topk: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for (a, b), stat in pair_stats.items():
        if a == tag_id:
            other = b
        elif b == tag_id:
            other = a
        else:
            continue
        items.append(
            {
                "canonical_tag_id": other,
                "canonical_name": canonical_meta.get(other, {}).get("canonical_name", str(other)),
                "tag_kind": canonical_meta.get(other, {}).get("tag_kind", "unknown"),
                "co_cnt_total": stat.co_cnt_total,
                "co_cnt_7d": stat.co_cnt_7d,
                "co_cnt_30d": stat.co_cnt_30d,
                "decayed_weight": stat.decayed_weight,
            }
        )

    items.sort(key=lambda x: (x["decayed_weight"], x["co_cnt_total"]), reverse=True)
    return items[:topk]



def rebuild_tag_cards(
    conn: sqlite3.Connection,
    now_iso: str,
    canonical_meta: dict[int, dict[str, Any]],
    tag_stats: dict[int, dict[str, Any]],
    pair_stats: dict[tuple[int, int], PairStats],
) -> int:
    updated = 0
    for tag_id, meta in canonical_meta.items():
        if tag_id not in tag_stats:
            continue

        samples_json = conn.execute(
            "SELECT title_samples_json FROM canonical_tag_stats WHERE canonical_tag_id = ?",
            (tag_id,),
        ).fetchone()
        if not samples_json:
            continue
        top_titles = json.loads(samples_json["title_samples_json"])

        top_co_tags = fetch_top_co_tags_from_pairs(
            tag_id=tag_id,
            pair_stats=pair_stats,
            canonical_meta=canonical_meta,
            topk=10,
        )
        card_text = build_tag_card_text(
            tag_name=meta["canonical_name"],
            tag_kind=meta["tag_kind"],
            top_co_tags=top_co_tags,
        )
        evidence = {
            "top_titles": top_titles[:8],
            "top_co_tags": top_co_tags,
        }

        conn.execute(
            """
            INSERT INTO tag_cards (canonical_tag_id, card_text, evidence_json, generated_at, source)
            VALUES (?, ?, ?, ?, 'template')
            ON CONFLICT(canonical_tag_id) DO UPDATE SET
              card_text = excluded.card_text,
              evidence_json = excluded.evidence_json,
              generated_at = excluded.generated_at,
              source = excluded.source
            WHERE tag_cards.source = 'template'
            """,
            (tag_id, card_text, json.dumps(evidence, ensure_ascii=False), now_iso),
        )
        updated += 1

    return updated


# ------------------------------
# LLM tasks
# ------------------------------


def upsert_pending_task(
    conn: sqlite3.Connection,
    task_type: str,
    task_key: str,
    payload: dict[str, Any],
    priority: int,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO llm_tasks (
          task_type, task_key, status, priority, payload_json, created_at, updated_at
        ) VALUES (?, ?, 'pending', ?, ?, ?, ?)
        ON CONFLICT(task_key) DO UPDATE SET
          payload_json = excluded.payload_json,
          priority = excluded.priority,
          updated_at = excluded.updated_at
        WHERE llm_tasks.status = 'pending'
        """,
        (
            task_type,
            task_key,
            priority,
            json.dumps(payload, ensure_ascii=False),
            now_iso,
            now_iso,
        ),
    )



def enqueue_llm_tasks(
    conn: sqlite3.Connection,
    now_iso: str,
    canonical_meta: dict[int, dict[str, Any]],
    pair_stats: dict[tuple[int, int], PairStats],
) -> dict[str, int]:
    counts = {
        "raw_tag_synonym_review": 0,
        "canonical_tag_kind_review": 0,
        "tag_card_review": 0,
        "community_report_review": 0,
    }

    # raw tag synonym tasks
    raw_rows = conn.execute(
        """
        SELECT r.raw_tag_norm, r.raw_tag_display, a.canonical_tag_id
        FROM raw_tags r
        JOIN tag_aliases a ON a.raw_tag_norm = r.raw_tag_norm
        WHERE a.alias_source IN ('auto_identity', 'heuristic')
        """
    ).fetchall()

    for row in raw_rows:
        raw_tag_norm = str(row["raw_tag_norm"])
        canonical_id = int(row["canonical_tag_id"])
        title_rows = conn.execute(
            """
            SELECT v.title, v.aweme_id,
                   COALESCE(v.collect_count, 0) AS collect_count,
                   COALESCE(v.digg_count, 0) AS digg_count
            FROM video_raw_tags vrt
            JOIN videos v ON v.aweme_id = vrt.aweme_id
            WHERE vrt.raw_tag_norm = ?
            ORDER BY (COALESCE(v.collect_count, 0) * 3 + COALESCE(v.digg_count, 0)) DESC
            LIMIT 8
            """,
            (raw_tag_norm,),
        ).fetchall()

        payload = {
            "raw_tag_norm": raw_tag_norm,
            "raw_tag_display": row["raw_tag_display"],
            "current_canonical_tag_id": canonical_id,
            "current_canonical_name": canonical_meta.get(canonical_id, {}).get("canonical_name"),
            "title_samples": [
                {
                    "aweme_id": str(tr["aweme_id"]),
                    "title": str(tr["title"] or ""),
                    "collect_count": int(tr["collect_count"] or 0),
                    "digg_count": int(tr["digg_count"] or 0),
                }
                for tr in title_rows
            ],
        }
        upsert_pending_task(
            conn,
            task_type="raw_tag_synonym_review",
            task_key=f"raw:{raw_tag_norm}",
            payload=payload,
            priority=40,
            now_iso=now_iso,
        )
        counts["raw_tag_synonym_review"] += 1

    # kind review tasks
    kind_rows = conn.execute(
        """
        SELECT c.canonical_tag_id, c.canonical_name, c.tag_kind, c.kind_source,
               s.video_count, s.title_samples_json
        FROM canonical_tags c
        JOIN canonical_tag_stats s ON s.canonical_tag_id = c.canonical_tag_id
        WHERE c.merged_into IS NULL
          AND c.kind_source IN ('pending', 'heuristic')
          AND (c.kind_confidence IS NULL OR c.kind_confidence < 0.65)
        """
    ).fetchall()

    for row in kind_rows:
        tag_id = int(row["canonical_tag_id"])
        payload = {
            "canonical_tag_id": tag_id,
            "canonical_name": str(row["canonical_name"]),
            "current_tag_kind": str(row["tag_kind"]),
            "kind_source": str(row["kind_source"]),
            "video_count": int(row["video_count"]),
            "title_samples": json.loads(row["title_samples_json"]),
            "top_co_tags": fetch_top_co_tags_from_pairs(
                tag_id=tag_id,
                pair_stats=pair_stats,
                canonical_meta=canonical_meta,
                topk=10,
            ),
        }
        upsert_pending_task(
            conn,
            task_type="canonical_tag_kind_review",
            task_key=f"kind:{tag_id}",
            payload=payload,
            priority=50,
            now_iso=now_iso,
        )
        counts["canonical_tag_kind_review"] += 1

    # tag card review tasks
    card_rows = conn.execute(
        """
        SELECT c.canonical_tag_id, c.canonical_name, c.tag_kind, tc.card_text, tc.evidence_json
        FROM tag_cards tc
        JOIN canonical_tags c ON c.canonical_tag_id = tc.canonical_tag_id
        WHERE tc.source = 'template'
        """
    ).fetchall()

    for row in card_rows:
        tag_id = int(row["canonical_tag_id"])
        payload = {
            "canonical_tag_id": tag_id,
            "canonical_name": str(row["canonical_name"]),
            "tag_kind": str(row["tag_kind"]),
            "template_card_text": str(row["card_text"]),
            "evidence": json.loads(row["evidence_json"]),
        }
        upsert_pending_task(
            conn,
            task_type="tag_card_review",
            task_key=f"card:{tag_id}",
            payload=payload,
            priority=80,
            now_iso=now_iso,
        )
        counts["tag_card_review"] += 1

    # community report review tasks
    comm_rows = conn.execute(
        """
        SELECT community_id, topic_count, report_text
        FROM communities
        WHERE report_source = 'template'
        """
    ).fetchall()
    for row in comm_rows:
        community_id = int(row["community_id"])
        tag_stat_rows = conn.execute(
            """
            SELECT cm.canonical_tag_id, c.canonical_name, cm.member_rank, cm.score,
                   COALESCE(s.video_count, 0) AS video_count,
                   COALESCE(s.score, 0.0) AS tag_score,
                   COALESCE(s.title_samples_json, '[]') AS title_samples_json
            FROM community_members cm
            JOIN canonical_tags c ON c.canonical_tag_id = cm.canonical_tag_id
            LEFT JOIN canonical_tag_stats s ON s.canonical_tag_id = cm.canonical_tag_id
            WHERE cm.community_id = ?
            ORDER BY cm.member_rank ASC
            LIMIT 20
            """,
            (community_id,),
        ).fetchall()

        member_ids = [int(r["canonical_tag_id"]) for r in tag_stat_rows]
        tags_for_payload: list[dict[str, Any]] = []
        for r in tag_stat_rows:
            try:
                titles = json.loads(r["title_samples_json"] or "[]")
            except Exception:
                titles = []
            top3_titles = [t.get("title", "") for t in titles[:3] if isinstance(t, dict)]
            tags_for_payload.append({
                "id": int(r["canonical_tag_id"]),
                "canonical_name": str(r["canonical_name"]),
                "member_rank": int(r["member_rank"]),
                "video_count": int(r["video_count"]),
                "score": float(r["tag_score"]),
                "top_titles": top3_titles,
            })

        # co-occurrence edges within community
        edges_for_payload: list[dict[str, Any]] = []
        if len(member_ids) >= 2:
            placeholders = ",".join("?" * len(member_ids))
            edge_rows = conn.execute(
                f"""
                SELECT e.src_tag_id, e.dst_tag_id,
                       e.co_cnt_total, e.co_cnt_7d, e.decayed_weight,
                       s.canonical_name AS src_name, d.canonical_name AS dst_name
                FROM tag_cooccurrence e
                JOIN canonical_tags s ON s.canonical_tag_id = e.src_tag_id
                JOIN canonical_tags d ON d.canonical_tag_id = e.dst_tag_id
                WHERE e.src_tag_id IN ({placeholders})
                  AND e.dst_tag_id IN ({placeholders})
                ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
                LIMIT 20
                """,
                member_ids + member_ids,
            ).fetchall()
            for idx, er in enumerate(edge_rows, start=1):
                edges_for_payload.append({
                    "id": idx,
                    "source": str(er["src_name"]),
                    "target": str(er["dst_name"]),
                    "co_cnt_total": int(er["co_cnt_total"]),
                    "co_cnt_7d": int(er["co_cnt_7d"]),
                    "decayed_weight": round(float(er["decayed_weight"]), 4),
                })

        payload = {
            "community_id": community_id,
            "topic_count": int(row["topic_count"]),
            "tags": tags_for_payload,
            "relationships": edges_for_payload,
            "template_report": str(row["report_text"] or ""),
        }
        upsert_pending_task(
            conn,
            task_type="community_report_review",
            task_key=f"community:{community_id}",
            payload=payload,
            priority=90,
            now_iso=now_iso,
        )
        counts["community_report_review"] += 1

    return counts


# ------------------------------
# Query helpers
# ------------------------------


def resolve_tag(conn: sqlite3.Connection, input_tag: str) -> sqlite3.Row | None:
    norm = normalize_tag(input_tag)
    if not norm:
        return None

    row = conn.execute(
        """
        SELECT c.canonical_tag_id, c.canonical_name, c.tag_kind, c.kind_source
        FROM tag_aliases a
        JOIN canonical_tags c ON c.canonical_tag_id = a.canonical_tag_id
        WHERE a.raw_tag_norm = ?
          AND c.merged_into IS NULL
        """,
        (norm,),
    ).fetchone()
    if row:
        return row

    return conn.execute(
        """
        SELECT canonical_tag_id, canonical_name, tag_kind, kind_source
        FROM canonical_tags
        WHERE canonical_name = ?
          AND merged_into IS NULL
        """,
        (norm,),
    ).fetchone()


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _similarity_score(query_norm: str, candidate_norm: str) -> float:
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0

    seq_ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    query_grams = _char_ngrams(query_norm, 2)
    cand_grams = _char_ngrams(candidate_norm, 2)
    gram_union = query_grams | cand_grams
    gram_jaccard = len(query_grams & cand_grams) / len(gram_union) if gram_union else 0.0

    query_chars = set(query_norm)
    cand_chars = set(candidate_norm)
    char_union = query_chars | cand_chars
    char_jaccard = len(query_chars & cand_chars) / len(char_union) if char_union else 0.0

    contains = 1.0 if (query_norm in candidate_norm or candidate_norm in query_norm) else 0.0
    prefix = 1.0 if (candidate_norm.startswith(query_norm) or query_norm.startswith(candidate_norm)) else 0.0

    score = (
        seq_ratio * 0.45
        + gram_jaccard * 0.25
        + char_jaccard * 0.20
        + max(contains, prefix) * 0.10
    )
    if len(query_norm) <= 2 and contains == 0.0:
        # 两字短查询共享单个汉字（如"旅游"vs"游戏"）会产生误导性的高分，加重惩罚
        score *= 0.50
    return max(0.0, min(1.0, score))


def _recall_lexical_threshold(query_norm: str) -> float:
    q_len = len(query_norm)
    if q_len >= 6:
        return 0.25
    if q_len >= 4:
        return 0.30
    if q_len >= 3:
        return 0.35
    return 0.45


def recall_similar_tags(conn: sqlite3.Connection, input_tag: str, topk: int = 10) -> list[dict[str, Any]]:
    query_norm = normalize_tag(input_tag)
    if not query_norm:
        return []

    tag_rows = conn.execute(
        """
        SELECT
          c.canonical_tag_id,
          c.canonical_name,
          c.tag_kind,
          c.kind_source,
          COALESCE(s.video_count, 0) AS video_count,
          COALESCE(s.score, 0) AS score
        FROM canonical_tags c
        LEFT JOIN canonical_tag_stats s ON s.canonical_tag_id = c.canonical_tag_id
        WHERE c.merged_into IS NULL
        """
    ).fetchall()

    alias_rows = conn.execute(
        """
        SELECT
          a.canonical_tag_id,
          r.raw_tag_norm,
          r.raw_tag_display,
          COALESCE(r.video_count, 0) AS video_count
        FROM tag_aliases a
        JOIN raw_tags r ON r.raw_tag_norm = a.raw_tag_norm
        ORDER BY a.canonical_tag_id ASC, r.video_count DESC
        """
    ).fetchall()

    alias_map: dict[int, list[str]] = defaultdict(list)
    for row in alias_rows:
        canonical_id = int(row["canonical_tag_id"])
        norm_from_display = normalize_tag(row["raw_tag_display"])
        norm_alias = norm_from_display or str(row["raw_tag_norm"])
        if not norm_alias:
            continue
        slots = alias_map[canonical_id]
        if norm_alias in slots:
            continue
        if len(slots) >= 8:
            continue
        slots.append(norm_alias)

    threshold = _recall_lexical_threshold(query_norm)
    candidates: list[dict[str, Any]] = []
    all_scored: list[dict[str, Any]] = []

    for row in tag_rows:
        canonical_id = int(row["canonical_tag_id"])
        canonical_name = str(row["canonical_name"])
        canonical_norm = normalize_tag(canonical_name) or canonical_name

        best_lexical = _similarity_score(query_norm, canonical_norm)
        best_match_norm = canonical_norm
        match_source = "canonical_name"

        for alias_norm in alias_map.get(canonical_id, []):
            score = _similarity_score(query_norm, alias_norm)
            if score > best_lexical:
                best_lexical = score
                best_match_norm = alias_norm
                match_source = "raw_alias"

        pop_raw = float(row["score"] or 0.0)
        pop_boost = min(1.0, math.log1p(max(0.0, pop_raw)) / 16.0)
        retrieval_score = best_lexical * 0.86 + pop_boost * 0.14

        item = {
            "canonical_tag_id": canonical_id,
            "canonical_name": canonical_name,
            "tag_kind": str(row["tag_kind"]),
            "kind_source": str(row["kind_source"]),
            "video_count": int(row["video_count"] or 0),
            "tag_score": pop_raw,
            "retrieval_score": retrieval_score,
            "lexical_score": best_lexical,
            "popularity_score": pop_boost,
            "match_source": match_source,
            "matched_alias_norm": best_match_norm,
        }
        all_scored.append(item)
        if best_lexical >= threshold:
            candidates.append(item)

    if not candidates:
        # 无候选时用相对阈值兜底，避免低相关度（如"旅游"→"游戏"靠共享一个字入选）的 tag 混入
        fallback_threshold = max(threshold * 0.55, 0.20)
        relaxed = [item for item in all_scored if float(item["lexical_score"]) >= fallback_threshold]
        relaxed.sort(key=lambda x: (x["retrieval_score"], x["video_count"]), reverse=True)
        return relaxed[:topk]

    if len(candidates) < topk:
        existing_ids = {int(item["canonical_tag_id"]) for item in candidates}
        relaxed_threshold = max(0.12, threshold * 0.70)
        extras = [
            item
            for item in all_scored
            if int(item["canonical_tag_id"]) not in existing_ids and float(item["lexical_score"]) >= relaxed_threshold
        ]
        extras.sort(key=lambda x: (x["retrieval_score"], x["video_count"]), reverse=True)
        needed = topk - len(candidates)
        for item in extras[:needed]:
            item = dict(item)
            if item["match_source"] == "canonical_name":
                item["match_source"] = "canonical_name_relaxed"
            candidates.append(item)

    candidates.sort(
        key=lambda x: (
            x["retrieval_score"],
            x["lexical_score"],
            x["video_count"],
        ),
        reverse=True,
    )
    return candidates[:topk]


def _community_brief(community: dict[str, Any] | None) -> dict[str, Any] | None:
    if not community:
        return None
    return {
        "community_id": community.get("community_id"),
        "topic_count": community.get("topic_count"),
        "top_tags": [item.get("canonical_name") for item in (community.get("top_tags") or [])[:8]],
        "community_report": community.get("community_report", ""),
    }


def _campaign_related_communities_brief(related: list[dict[str, Any]], topk: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in related[:topk]:
        topics = item.get("topics") or []
        out.append(
            {
                "community_id": item.get("community_id"),
                "score": float(item.get("score") or 0.0),
                "top_topics": [topic.get("topic_name") for topic in topics[:6]],
                "community_report": item.get("community_report", ""),
            }
        )
    return out


def build_recall_bundle(conn: sqlite3.Connection, input_tag: str, topk: int = 10) -> dict[str, Any]:
    candidates = recall_similar_tags(conn, input_tag=input_tag, topk=max(3, topk * 2))
    suggested_tags: list[dict[str, Any]] = []

    community_acc: dict[int, dict[str, Any]] = {}
    campaign_bucket: list[dict[str, Any]] = []

    for cand in candidates[:topk]:
        canonical_tag_id = int(cand["canonical_tag_id"])
        tag_kind = str(cand["tag_kind"])
        co_tags = fetch_top_co_tags(conn, canonical_tag_id=canonical_tag_id, topk=min(5, topk))

        tag_item: dict[str, Any] = {
            "canonical_tag_id": canonical_tag_id,
            "canonical_name": cand["canonical_name"],
            "tag_kind": tag_kind,
            "kind_source": cand["kind_source"],
            "retrieval_score": round(float(cand["retrieval_score"]), 6),
            "lexical_score": round(float(cand["lexical_score"]), 6),
            "match_source": cand["match_source"],
            "video_count": int(cand["video_count"]),
            "co_tags": co_tags,
        }

        if tag_kind == "topic":
            community = _community_brief(fetch_topic_community(conn, canonical_tag_id))
            tag_item["community"] = community
            if community and community.get("community_id") is not None:
                cid = int(community["community_id"])
                slot = community_acc.setdefault(
                    cid,
                    {
                        "community_id": cid,
                        "score": 0.0,
                        "seed_tags": [],
                        "topic_count": int(community.get("topic_count") or 0),
                        "top_tags": community.get("top_tags") or [],
                        "community_report": community.get("community_report", ""),
                    },
                )
                slot["score"] += float(cand["retrieval_score"])
                slot["seed_tags"].append(cand["canonical_name"])
        else:
            related = fetch_campaign_related_communities(conn, campaign_tag_id=canonical_tag_id, topk=3)
            related_brief = _campaign_related_communities_brief(related, topk=3)
            tag_item["related_topic_communities"] = related_brief
            for rc in related_brief:
                cid = rc.get("community_id")
                if cid is None:
                    campaign_bucket.append(
                        {
                            "source_campaign": cand["canonical_name"],
                            "score": float(rc.get("score") or 0.0) * float(cand["retrieval_score"]),
                            "top_topics": rc.get("top_topics") or [],
                        }
                    )
                    continue
                slot = community_acc.setdefault(
                    int(cid),
                    {
                        "community_id": int(cid),
                        "score": 0.0,
                        "seed_tags": [],
                        "topic_count": 0,
                        "top_tags": [],
                        "community_report": rc.get("community_report", ""),
                    },
                )
                slot["score"] += float(rc.get("score") or 0.0) * float(cand["retrieval_score"])
                slot["seed_tags"].append(cand["canonical_name"])

        suggested_tags.append(tag_item)

    suggested_communities = sorted(community_acc.values(), key=lambda x: x["score"], reverse=True)[:topk]
    if campaign_bucket:
        campaign_bucket.sort(key=lambda x: x["score"], reverse=True)

    return {
        "suggested_tags": suggested_tags,
        "suggested_communities": suggested_communities,
        "campaign_related_without_community": campaign_bucket[:topk],
    }


def fetch_top_co_tags(conn: sqlite3.Connection, canonical_tag_id: int, topk: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH edges AS (
          SELECT dst_tag_id AS other_tag_id, co_cnt_total, co_cnt_7d, co_cnt_30d, decayed_weight
          FROM tag_cooccurrence
          WHERE src_tag_id = ?
          UNION ALL
          SELECT src_tag_id AS other_tag_id, co_cnt_total, co_cnt_7d, co_cnt_30d, decayed_weight
          FROM tag_cooccurrence
          WHERE dst_tag_id = ?
        )
        SELECT c.canonical_tag_id, c.canonical_name, c.tag_kind,
               e.co_cnt_total, e.co_cnt_7d, e.co_cnt_30d, e.decayed_weight
        FROM edges e
        JOIN canonical_tags c ON c.canonical_tag_id = e.other_tag_id
        WHERE c.merged_into IS NULL
        ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
        LIMIT ?
        """,
        (canonical_tag_id, canonical_tag_id, topk),
    ).fetchall()

    return [
        {
            "canonical_tag_id": int(r["canonical_tag_id"]),
            "canonical_name": str(r["canonical_name"]),
            "tag_kind": str(r["tag_kind"]),
            "co_cnt_total": int(r["co_cnt_total"]),
            "co_cnt_7d": int(r["co_cnt_7d"]),
            "co_cnt_30d": int(r["co_cnt_30d"]),
            "decayed_weight": float(r["decayed_weight"]),
        }
        for r in rows
    ]



def fetch_topic_community(conn: sqlite3.Connection, canonical_tag_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT c.community_id, c.algo, c.level, c.report_text, c.topic_count, c.generated_at,
               c.report_title, c.report_summary, c.report_rating, c.report_findings_json,
               c.report_source
        FROM community_members cm
        JOIN communities c ON c.community_id = cm.community_id
        WHERE cm.canonical_tag_id = ?
        ORDER BY c.level ASC, c.topic_count ASC, c.community_id ASC
        LIMIT 1
        """,
        (canonical_tag_id,),
    ).fetchone()
    if not row:
        return None

    community_id = int(row["community_id"])
    members = conn.execute(
        """
        SELECT ct.canonical_name, cm.member_rank, cm.score
        FROM community_members cm
        JOIN canonical_tags ct ON ct.canonical_tag_id = cm.canonical_tag_id
        WHERE cm.community_id = ?
        ORDER BY cm.member_rank ASC
        LIMIT 20
        """,
        (community_id,),
    ).fetchall()

    try:
        findings = json.loads(row["report_findings_json"] or "null")
    except Exception:
        findings = None

    return {
        "community_id": community_id,
        "algo": str(row["algo"]),
        "level": int(row["level"]),
        "topic_count": int(row["topic_count"]),
        "generated_at": str(row["generated_at"]),
        "report_source": str(row["report_source"] or "template"),
        "top_tags": [
            {
                "canonical_name": str(m["canonical_name"]),
                "member_rank": int(m["member_rank"]),
                "score": float(m["score"]),
            }
            for m in members
        ],
        "community_report": str(row["report_text"] or ""),
        "report_title": row["report_title"],
        "report_summary": row["report_summary"],
        "report_rating": float(row["report_rating"]) if row["report_rating"] is not None else None,
        "report_findings": findings,
    }



def fetch_campaign_related_communities(
    conn: sqlite3.Connection,
    campaign_tag_id: int,
    topk: int = 5,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          e.topic_tag_id,
          ct.canonical_name AS topic_name,
          e.co_cnt_total,
          e.co_cnt_7d,
          e.co_cnt_30d,
          e.decayed_weight,
          cm.community_id,
          c.report_text
        FROM campaign_topic_edges e
        JOIN canonical_tags ct ON ct.canonical_tag_id = e.topic_tag_id
        LEFT JOIN community_members cm ON cm.canonical_tag_id = e.topic_tag_id
        LEFT JOIN communities c ON c.community_id = cm.community_id AND c.level = 0
        WHERE e.campaign_tag_id = ?
        ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
        LIMIT 200
        """,
        (campaign_tag_id,),
    ).fetchall()

    groups: dict[int, dict[str, Any]] = {}
    no_comm: list[dict[str, Any]] = []

    for r in rows:
        community_id = r["community_id"]
        topic_item = {
            "topic_tag_id": int(r["topic_tag_id"]),
            "topic_name": str(r["topic_name"]),
            "co_cnt_total": int(r["co_cnt_total"]),
            "co_cnt_7d": int(r["co_cnt_7d"]),
            "co_cnt_30d": int(r["co_cnt_30d"]),
            "decayed_weight": float(r["decayed_weight"]),
        }
        if community_id is None:
            no_comm.append(topic_item)
            continue

        cid = int(community_id)
        entry = groups.setdefault(
            cid,
            {
                "community_id": cid,
                "score": 0.0,
                "topics": [],
                "community_report": str(r["report_text"] or ""),
            },
        )
        entry["score"] += float(r["decayed_weight"])
        entry["topics"].append(topic_item)

    ranked = sorted(groups.values(), key=lambda x: x["score"], reverse=True)
    for entry in ranked:
        entry["topics"] = sorted(
            entry["topics"], key=lambda x: (x["decayed_weight"], x["co_cnt_total"]), reverse=True
        )[:10]

    if no_comm:
        ranked.append(
            {
                "community_id": None,
                "score": sum(item["decayed_weight"] for item in no_comm),
                "topics": sorted(no_comm, key=lambda x: (x["decayed_weight"], x["co_cnt_total"]), reverse=True)[:10],
                "community_report": "",
            }
        )

    return ranked[:topk]



def build_evidence_pack(conn: sqlite3.Connection, canonical_tag_id: int, top_titles: int, top_co_tags: int) -> dict[str, Any]:
    stats_row = conn.execute(
        """
        SELECT title_samples_json, video_count, digg_sum, collect_sum, comment_sum, share_sum
        FROM canonical_tag_stats
        WHERE canonical_tag_id = ?
        """,
        (canonical_tag_id,),
    ).fetchone()

    title_samples: list[dict[str, Any]] = []
    if stats_row and stats_row["title_samples_json"]:
        title_samples = json.loads(stats_row["title_samples_json"])[:top_titles]

    return {
        "top_titles": title_samples,
        "top_co_tags": fetch_top_co_tags(conn, canonical_tag_id=canonical_tag_id, topk=top_co_tags),
        "metrics_summary": {
            "video_count": int(stats_row["video_count"] if stats_row else 0),
            "digg_sum": int(stats_row["digg_sum"] if stats_row else 0),
            "collect_sum": int(stats_row["collect_sum"] if stats_row else 0),
            "comment_sum": int(stats_row["comment_sum"] if stats_row else 0),
            "share_sum": int(stats_row["share_sum"] if stats_row else 0),
        },
    }



def query_tag_bundle(
    conn: sqlite3.Connection,
    input_tag: str,
    topk: int = 10,
    top_titles: int = 10,
) -> dict[str, Any]:
    resolved = resolve_tag(conn, input_tag)
    if resolved is None:
        recall = build_recall_bundle(conn, input_tag=input_tag, topk=topk)
        return {
            "found": False,
            "input_tag": input_tag,
            "message": "tag not found by exact match; returned recall candidates",
            "recall_enabled": True,
            "suggested_tags": recall["suggested_tags"],
            "suggested_communities": recall["suggested_communities"],
            "campaign_related_without_community": recall["campaign_related_without_community"],
        }

    canonical_tag_id = int(resolved["canonical_tag_id"])
    canonical_name = str(resolved["canonical_name"])
    tag_kind = str(resolved["tag_kind"])

    card_row = conn.execute(
        "SELECT card_text, source FROM tag_cards WHERE canonical_tag_id = ?",
        (canonical_tag_id,),
    ).fetchone()

    result: dict[str, Any] = {
        "found": True,
        "input_tag": input_tag,
        "resolved": {
            "canonical_tag_id": canonical_tag_id,
            "canonical_name": canonical_name,
            "tag_kind": tag_kind,
            "kind_source": str(resolved["kind_source"]),
        },
        "tag_card": {
            "text": str(card_row["card_text"]) if card_row else "",
            "source": str(card_row["source"]) if card_row else "",
        },
        "co_tags": fetch_top_co_tags(conn, canonical_tag_id, topk=topk),
        "evidence_pack": build_evidence_pack(conn, canonical_tag_id, top_titles=top_titles, top_co_tags=topk),
    }

    if tag_kind == "topic":
        result["community"] = fetch_topic_community(conn, canonical_tag_id)
    elif tag_kind == "campaign":
        result["related_topic_communities"] = fetch_campaign_related_communities(conn, campaign_tag_id=canonical_tag_id, topk=topk)

    # Even on exact hit, provide extra recall candidates for broad/fuzzy queries.
    result["recall_enabled"] = True
    result["suggested_tags"] = recall_similar_tags(conn, input_tag=input_tag, topk=topk)

    return result


# ------------------------------
# LLM decision apply
# ------------------------------


def ensure_canonical_by_name(conn: sqlite3.Connection, canonical_name: str, now_iso: str) -> int:
    conn.execute(
        """
        INSERT INTO canonical_tags (
          canonical_name, tag_kind, kind_source, first_seen_at, last_seen_at, updated_at
        ) VALUES (?, 'unknown', 'pending', ?, ?, ?)
        ON CONFLICT(canonical_name) DO UPDATE SET
          last_seen_at = excluded.last_seen_at,
          updated_at = excluded.updated_at
        """,
        (canonical_name, now_iso, now_iso, now_iso),
    )
    row = conn.execute(
        "SELECT canonical_tag_id FROM canonical_tags WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()
    if not row:
        raise RuntimeError(f"failed to ensure canonical: {canonical_name}")
    return int(row["canonical_tag_id"])



def mark_task_done(conn: sqlite3.Connection, task_key: str, now_iso: str, result: dict[str, Any] | None = None) -> None:
    conn.execute(
        """
        UPDATE llm_tasks
        SET status = 'done',
            result_json = ?,
            updated_at = ?
        WHERE task_key = ?
        """,
        (json.dumps(result, ensure_ascii=False) if result is not None else None, now_iso, task_key),
    )



def apply_llm_decisions(conn: sqlite3.Connection, payload: dict[str, Any], now_iso: str) -> dict[str, int]:
    counts = {
        "synonym_updates": 0,
        "kind_updates": 0,
        "tag_card_updates": 0,
        "community_report_updates": 0,
        "completed_tasks": 0,
    }

    synonym_updates = payload.get("synonym_updates") or []
    for item in synonym_updates:
        if not isinstance(item, dict):
            continue
        raw_tag_norm = normalize_tag(item.get("raw_tag"))
        canonical_name = normalize_tag(item.get("canonical_name"))
        if not raw_tag_norm or not canonical_name:
            continue

        raw_display = clean_display_tag(item.get("raw_tag")) or raw_tag_norm
        upsert_raw_tag(conn, raw_tag_norm=raw_tag_norm, raw_tag_display=raw_display, now_iso=now_iso)

        canonical_id = ensure_canonical_by_name(conn, canonical_name=canonical_name, now_iso=now_iso)
        alias_source = str(item.get("alias_source") or "llm")
        confidence = safe_float(item.get("confidence"))

        conn.execute(
            """
            INSERT INTO tag_aliases (raw_tag_norm, canonical_tag_id, alias_source, confidence, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(raw_tag_norm) DO UPDATE SET
              canonical_tag_id = excluded.canonical_tag_id,
              alias_source = excluded.alias_source,
              confidence = excluded.confidence,
              updated_at = excluded.updated_at
            """,
            (raw_tag_norm, canonical_id, alias_source, confidence, now_iso),
        )

        mark_task_done(
            conn,
            task_key=f"raw:{raw_tag_norm}",
            now_iso=now_iso,
            result={"canonical_tag_id": canonical_id, "canonical_name": canonical_name},
        )
        counts["synonym_updates"] += 1

    kind_updates = payload.get("kind_updates") or []
    for item in kind_updates:
        if not isinstance(item, dict):
            continue
        canonical_name = normalize_tag(item.get("canonical_name"))
        tag_kind = str(item.get("tag_kind") or "").strip().lower()
        if not canonical_name or tag_kind not in {"topic", "campaign"}:
            continue

        canonical_id = ensure_canonical_by_name(conn, canonical_name=canonical_name, now_iso=now_iso)
        kind_source = str(item.get("kind_source") or "llm")
        confidence = safe_float(item.get("confidence"))

        conn.execute(
            """
            UPDATE canonical_tags
            SET tag_kind = ?,
                kind_source = ?,
                kind_confidence = ?,
                updated_at = ?
            WHERE canonical_tag_id = ?
            """,
            (tag_kind, kind_source, confidence, now_iso, canonical_id),
        )
        mark_task_done(
            conn,
            task_key=f"kind:{canonical_id}",
            now_iso=now_iso,
            result={"tag_kind": tag_kind, "kind_source": kind_source, "confidence": confidence},
        )
        counts["kind_updates"] += 1

    tag_card_updates = payload.get("tag_card_updates") or []
    for item in tag_card_updates:
        if not isinstance(item, dict):
            continue
        canonical_name = normalize_tag(item.get("canonical_name"))
        card_text = item.get("card_text")
        if not canonical_name or not isinstance(card_text, str) or not card_text.strip():
            continue

        canonical_id = ensure_canonical_by_name(conn, canonical_name=canonical_name, now_iso=now_iso)
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        source = str(item.get("source") or "llm")
        conn.execute(
            """
            INSERT INTO tag_cards (canonical_tag_id, card_text, evidence_json, generated_at, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(canonical_tag_id) DO UPDATE SET
              card_text = excluded.card_text,
              evidence_json = excluded.evidence_json,
              generated_at = excluded.generated_at,
              source = excluded.source
            """,
            (canonical_id, card_text.strip(), json.dumps(evidence, ensure_ascii=False), now_iso, source),
        )
        mark_task_done(
            conn,
            task_key=f"card:{canonical_id}",
            now_iso=now_iso,
            result={"source": source},
        )
        counts["tag_card_updates"] += 1

    community_report_updates = payload.get("community_report_updates") or []
    for item in community_report_updates:
        if not isinstance(item, dict):
            continue
        community_id = safe_int(item.get("community_id"))
        if not community_id:
            continue
        source = str(item.get("source") or "llm")

        report_title = item.get("title") or item.get("report_title")
        report_summary = item.get("summary") or item.get("report_summary")
        report_rating = safe_float(item.get("rating") if item.get("rating") is not None else item.get("report_rating"))
        report_rating_explanation = item.get("rating_explanation") or ""
        findings = item.get("findings")
        findings_json = json.dumps(findings, ensure_ascii=False) if isinstance(findings, list) else None

        # Build full_content text from structured parts (GraphRAG style)
        full_content_parts: list[str] = []
        if report_title:
            full_content_parts.append(f"# {report_title}")
        if report_summary:
            full_content_parts.append(report_summary)
        if isinstance(findings, list):
            for f in findings:
                if isinstance(f, dict):
                    s = f.get("summary", "")
                    e = f.get("explanation", "")
                    if s:
                        full_content_parts.append(f"## {s}")
                    if e:
                        full_content_parts.append(e)
        full_content = "\n\n".join(full_content_parts).strip()

        # Fallback: old-style plain report_text
        if not full_content:
            report_text = item.get("report_text")
            full_content = report_text.strip() if isinstance(report_text, str) else ""
        if not full_content:
            continue

        conn.execute(
            """
            UPDATE communities
            SET report_text = ?,
                report_source = ?,
                generated_at = ?,
                report_title = ?,
                report_summary = ?,
                report_rating = ?,
                report_findings_json = ?
            WHERE community_id = ?
            """,
            (
                full_content,
                source,
                now_iso,
                report_title,
                report_summary,
                report_rating,
                findings_json,
                community_id,
            ),
        )
        mark_task_done(
            conn,
            task_key=f"community:{community_id}",
            now_iso=now_iso,
            result={"source": source, "title": report_title},
        )
        counts["community_report_updates"] += 1

    complete_task_keys = payload.get("complete_task_keys") or []
    for key in complete_task_keys:
        if not isinstance(key, str) or not key.strip():
            continue
        mark_task_done(conn, task_key=key.strip(), now_iso=now_iso)
        counts["completed_tasks"] += 1

    return counts


# ------------------------------
# BYOG export
# ------------------------------


def export_byog_csv(conn: sqlite3.Connection, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    entities_path = output_dir / "entities.csv"
    relationships_path = output_dir / "relationships.csv"

    ent_rows = conn.execute(
        """
        SELECT c.canonical_tag_id, c.canonical_name, c.tag_kind,
               COALESCE(s.video_count, 0) AS video_count,
               COALESCE(s.score, 0) AS score,
               COALESCE(tc.card_text, '') AS card_text
        FROM canonical_tags c
        LEFT JOIN canonical_tag_stats s ON s.canonical_tag_id = c.canonical_tag_id
        LEFT JOIN tag_cards tc ON tc.canonical_tag_id = c.canonical_tag_id
        WHERE c.merged_into IS NULL
        ORDER BY s.score DESC, c.canonical_tag_id ASC
        """
    ).fetchall()

    with entities_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["entity_id", "title", "type", "description", "video_count", "score"])
        for r in ent_rows:
            writer.writerow(
                [
                    int(r["canonical_tag_id"]),
                    str(r["canonical_name"]),
                    str(r["tag_kind"]),
                    str(r["card_text"]),
                    int(r["video_count"]),
                    float(r["score"]),
                ]
            )

    rel_rows = conn.execute(
        """
        SELECT
          e.src_tag_id,
          s.canonical_name AS src_name,
          s.tag_kind AS src_kind,
          e.dst_tag_id,
          d.canonical_name AS dst_name,
          d.tag_kind AS dst_kind,
          e.co_cnt_total,
          e.co_cnt_7d,
          e.co_cnt_30d,
          e.decayed_weight
        FROM tag_cooccurrence e
        JOIN canonical_tags s ON s.canonical_tag_id = e.src_tag_id
        JOIN canonical_tags d ON d.canonical_tag_id = e.dst_tag_id
        WHERE s.merged_into IS NULL
          AND d.merged_into IS NULL
        ORDER BY e.decayed_weight DESC, e.co_cnt_total DESC
        """
    ).fetchall()

    with relationships_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "source_id",
                "source_name",
                "target_id",
                "target_name",
                "relationship_type",
                "co_cnt_total",
                "co_cnt_7d",
                "co_cnt_30d",
                "decayed_weight",
            ]
        )
        for r in rel_rows:
            src_kind = str(r["src_kind"])
            dst_kind = str(r["dst_kind"])
            if src_kind == "topic" and dst_kind == "topic":
                rel_type = "topic_topic"
            elif {src_kind, dst_kind} == {"topic", "campaign"}:
                rel_type = "campaign_topic"
            else:
                rel_type = "mixed"

            writer.writerow(
                [
                    int(r["src_tag_id"]),
                    str(r["src_name"]),
                    int(r["dst_tag_id"]),
                    str(r["dst_name"]),
                    rel_type,
                    int(r["co_cnt_total"]),
                    int(r["co_cnt_7d"]),
                    int(r["co_cnt_30d"]),
                    float(r["decayed_weight"]),
                ]
            )

    return {
        "entities_csv": str(entities_path),
        "relationships_csv": str(relationships_path),
    }


# ------------------------------
# End-to-end build
# ------------------------------


def rebuild_materialized_assets(
    conn: sqlite3.Connection,
    now_dt: datetime,
    now_iso: str,
    half_life_days: float,
    community_min_edge: int,
    leiden_max_cluster_size: int = 50,
) -> dict[str, Any]:
    video_meta, video_tags = load_video_tag_projection(conn=conn, now_dt=now_dt)
    tag_stats, _tag_to_videos = rebuild_canonical_tag_stats(
        conn=conn,
        now_iso=now_iso,
        video_meta=video_meta,
        video_tags=video_tags,
    )
    pair_stats = rebuild_cooccurrence(
        conn=conn,
        now_dt=now_dt,
        now_iso=now_iso,
        video_meta=video_meta,
        video_tags=video_tags,
        half_life_days=half_life_days,
    )
    canonical_meta = fetch_canonical_meta(conn)
    communities = rebuild_communities(
        conn=conn,
        now_iso=now_iso,
        community_min_edge=community_min_edge,
        canonical_meta=canonical_meta,
        tag_stats=tag_stats,
        pair_stats=pair_stats,
        leiden_max_cluster_size=leiden_max_cluster_size,
    )
    tag_cards = rebuild_tag_cards(
        conn=conn,
        now_iso=now_iso,
        canonical_meta=canonical_meta,
        tag_stats=tag_stats,
        pair_stats=pair_stats,
    )
    llm_task_counts = enqueue_llm_tasks(
        conn=conn,
        now_iso=now_iso,
        canonical_meta=canonical_meta,
        pair_stats=pair_stats,
    )

    return {
        "videos_with_tags": len(video_tags),
        "canonical_tags_with_stats": len(tag_stats),
        "cooccurrence_edges": len(pair_stats),
        "communities": communities,
        "tag_cards": tag_cards,
        "llm_tasks_enqueued": llm_task_counts,
    }



def build_tag_database(
    db_path: Path,
    input_dir: Path,
    schema_path: Path,
    half_life_days: float = 14.0,
    community_min_edge: int = 2,
    leiden_max_cluster_size: int = 50,
    force_reprocess: bool = False,
    export_byog_dir: Path | None = None,
) -> dict[str, Any]:
    now_dt = utc_now()
    now_iso = now_dt.isoformat()
    run_id = uuid.uuid4().hex

    conn = connect_db(db_path)
    init_schema(conn, schema_path=schema_path)
    insert_ingest_run(conn, run_id=run_id, input_dir=input_dir, started_at=now_iso)

    files_seen = 0
    files_processed = 0
    records_seen = 0
    records_ingested = 0

    try:
        files = sorted(input_dir.glob("*.json"))
        files_seen = len(files)

        for path in files:
            processed, seen, ingested = process_source_file(
                conn=conn,
                path=path,
                now_iso=now_iso,
                force_reprocess=force_reprocess,
            )
            records_seen += seen
            records_ingested += ingested
            if processed:
                files_processed += 1

        refresh_raw_tag_video_counts(conn)
        heuristics_updated = apply_kind_heuristics(conn=conn, now_iso=now_iso)

        materialized = rebuild_materialized_assets(
            conn=conn,
            now_dt=now_dt,
            now_iso=now_iso,
            half_life_days=half_life_days,
            community_min_edge=community_min_edge,
            leiden_max_cluster_size=leiden_max_cluster_size,
        )

        byog = None
        if export_byog_dir is not None:
            byog = export_byog_csv(conn=conn, output_dir=export_byog_dir)

        conn.commit()
        finish_ingest_run(
            conn,
            run_id=run_id,
            ended_at=utc_now_iso(),
            status="success",
            files_seen=files_seen,
            files_processed=files_processed,
            records_seen=records_seen,
            records_ingested=records_ingested,
            message="ok",
        )

        return {
            "run_id": run_id,
            "db_path": str(db_path),
            "input_dir": str(input_dir),
            "files_seen": files_seen,
            "files_processed": files_processed,
            "records_seen": records_seen,
            "records_ingested": records_ingested,
            "heuristics_updated": heuristics_updated,
            "materialized": materialized,
            "byog": byog,
        }
    except Exception as exc:
        conn.rollback()
        finish_ingest_run(
            conn,
            run_id=run_id,
            ended_at=utc_now_iso(),
            status="failed",
            files_seen=files_seen,
            files_processed=files_processed,
            records_seen=records_seen,
            records_ingested=records_ingested,
            message=str(exc),
        )
        raise
    finally:
        conn.close()



def apply_llm_decisions_and_rebuild(
    db_path: Path,
    schema_path: Path,
    decisions: dict[str, Any],
    half_life_days: float = 14.0,
    community_min_edge: int = 2,
    leiden_max_cluster_size: int = 50,
) -> dict[str, Any]:
    now_dt = utc_now()
    now_iso = now_dt.isoformat()

    conn = connect_db(db_path)
    init_schema(conn, schema_path=schema_path)

    try:
        counts = apply_llm_decisions(conn=conn, payload=decisions, now_iso=now_iso)
        materialized = rebuild_materialized_assets(
            conn=conn,
            now_dt=now_dt,
            now_iso=now_iso,
            half_life_days=half_life_days,
            community_min_edge=community_min_edge,
            leiden_max_cluster_size=leiden_max_cluster_size,
        )
        conn.commit()
        return {
            "decision_updates": counts,
            "materialized": materialized,
        }
    finally:
        conn.close()



def export_llm_tasks(
    db_path: Path,
    schema_path: Path,
    status: str = "pending",
    limit: int = 200,
) -> list[dict[str, Any]]:
    conn = connect_db(db_path)
    init_schema(conn, schema_path=schema_path)
    rows = conn.execute(
        """
        SELECT task_id, task_type, task_key, status, priority, payload_json, created_at, updated_at
        FROM llm_tasks
        WHERE status = ?
        ORDER BY priority ASC, task_id ASC
        LIMIT ?
        """,
        (status, limit),
    ).fetchall()
    conn.close()

    out = []
    for row in rows:
        out.append(
            {
                "task_id": int(row["task_id"]),
                "task_type": str(row["task_type"]),
                "task_key": str(row["task_key"]),
                "status": str(row["status"]),
                "priority": int(row["priority"]),
                "payload": json.loads(row["payload_json"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )
    return out


__all__ = [
    "apply_llm_decisions_and_rebuild",
    "build_tag_database",
    "connect_db",
    "export_byog_csv",
    "export_llm_tasks",
    "normalize_tag",
    "query_tag_bundle",
]
