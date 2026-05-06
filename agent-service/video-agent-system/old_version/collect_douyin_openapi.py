#!/usr/bin/env python3
"""Collect Douyin search videos via OpenAPI into SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
SEARCH_URL = "https://open.douyin.com/dy_open_api/v2/search/video/"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def load_keywords(keywords_file: Path) -> list[str]:
    if not keywords_file.exists():
        raise FileNotFoundError(f"keywords file not found: {keywords_file}")
    keywords: list[str] = []
    for raw_line in keywords_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keywords.append(line)
    if not keywords:
        raise ValueError(f"no valid keywords found in {keywords_file}")
    return keywords


def seed_search_tasks(conn: sqlite3.Connection, keywords: list[str]) -> None:
    now = utc_now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO search_tasks(keyword, enabled, created_at) VALUES (?, 1, ?)",
        [(kw, now) for kw in keywords],
    )
    conn.commit()


def load_enabled_keywords(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT keyword FROM search_tasks WHERE enabled = 1 ORDER BY id ASC"
    ).fetchall()
    return [row["keyword"] for row in rows]


def fetch_client_token(client_key: str, client_secret: str, timeout: int) -> str:
    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "client_credential",
    }
    resp = requests.post(TOKEN_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    body = data.get("data", {})
    if body.get("error_code", 0) != 0:
        raise RuntimeError(
            f"failed to get client_token: error_code={body.get('error_code')} "
            f"description={body.get('description')}"
        )
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"no access_token in response: {data}")
    return token


def search_videos(
    access_token: str,
    keyword: str,
    count: int,
    cursor: int,
    device_id: str,
    publish_time: int | None,
    timeout: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "keyword": keyword,
        "count": count,
        "cursor": cursor,
        "device_id": device_id,
    }
    if publish_time is not None:
        params["publish_time"] = publish_time

    headers = {"access-token": access_token}
    resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    body = data.get("data", {})
    if body.get("error_code", 0) != 0:
        raise RuntimeError(
            f"video search failed: keyword={keyword} cursor={cursor} "
            f"error_code={body.get('error_code')} description={body.get('description')}"
        )
    return body


def pick_first(items: list[Any] | None) -> str | None:
    if not items:
        return None
    value = items[0]
    if value is None:
        return None
    return str(value)


def upsert_video(conn: sqlite3.Connection, aweme: dict[str, Any], seen_at: str) -> str | None:
    aweme_id = aweme.get("aweme_id")
    if not aweme_id:
        return None

    author = aweme.get("author") or {}
    cover_url = pick_first((aweme.get("cover") or {}).get("url_list"))
    video = aweme.get("video") or {}
    video_url = pick_first((video.get("play_addr") or {}).get("url_list"))

    conn.execute(
        """
        INSERT INTO videos(
          aweme_id, "desc", create_time, author_id, author_name, author_sec_uid, author_unique_id,
          cover_url, video_url, duration, height, width, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(aweme_id) DO UPDATE SET
          "desc" = excluded."desc",
          create_time = excluded.create_time,
          author_id = excluded.author_id,
          author_name = excluded.author_name,
          author_sec_uid = excluded.author_sec_uid,
          author_unique_id = excluded.author_unique_id,
          cover_url = excluded.cover_url,
          video_url = excluded.video_url,
          duration = excluded.duration,
          height = excluded.height,
          width = excluded.width,
          last_seen_at = excluded.last_seen_at
        """,
        (
            aweme_id,
            aweme.get("desc"),
            aweme.get("create_time"),
            author.get("id"),
            author.get("name"),
            author.get("sec_uid"),
            author.get("unique_id"),
            cover_url,
            video_url,
            video.get("duration"),
            video.get("height"),
            video.get("width"),
            seen_at,
            seen_at,
        ),
    )
    return str(aweme_id)


def insert_snapshot(
    conn: sqlite3.Connection,
    run_id: str,
    keyword: str,
    aweme_id: str,
    cursor: int,
    rank_in_page: int,
    aweme: dict[str, Any],
    captured_at: str,
) -> None:
    stats = aweme.get("statistics") or {}
    conn.execute(
        """
        INSERT INTO video_snapshots(
          run_id, keyword, aweme_id, cursor, rank_in_page, comment_count, digg_count,
          download_count, play_count, share_count, captured_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            keyword,
            aweme_id,
            cursor,
            rank_in_page,
            stats.get("comment_count"),
            stats.get("digg_count"),
            stats.get("download_count"),
            stats.get("play_count"),
            stats.get("share_count"),
            captured_at,
            json.dumps(aweme, ensure_ascii=False),
        ),
    )


def update_run_status(
    conn: sqlite3.Connection, run_id: str, status: str, message: str | None = None
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET status = ?, message = ?, ended_at = ?
        WHERE run_id = ?
        """,
        (status, message, utc_now_iso(), run_id),
    )
    conn.commit()


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    client_key = os.getenv("DOUYIN_CLIENT_KEY", "").strip()
    client_secret = os.getenv("DOUYIN_CLIENT_SECRET", "").strip()
    device_id = os.getenv("DOUYIN_DEVICE_ID", "").strip() or "1234567890"

    if not client_key or not client_secret:
        raise RuntimeError("missing DOUYIN_CLIENT_KEY or DOUYIN_CLIENT_SECRET in environment")

    db_path = Path(args.db).expanduser()
    keywords_path = Path(args.keywords_file).expanduser()
    keywords = load_keywords(keywords_path)

    conn = ensure_db(db_path)
    run_id = uuid.uuid4().hex
    started_at = utc_now_iso()
    conn.execute(
        """
        INSERT INTO runs(run_id, source, started_at, status, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, "douyin_openapi_video_search", started_at, "running", None),
    )
    conn.commit()

    total_items = 0
    try:
        seed_search_tasks(conn, keywords)
        enabled_keywords = load_enabled_keywords(conn)
        if not enabled_keywords:
            raise RuntimeError("no enabled keywords found in search_tasks")

        access_token = fetch_client_token(client_key, client_secret, timeout=args.timeout)
        for keyword in enabled_keywords:
            cursor = 0
            for page_idx in range(1, args.max_pages + 1):
                body = search_videos(
                    access_token=access_token,
                    keyword=keyword,
                    count=args.count,
                    cursor=cursor,
                    device_id=device_id,
                    publish_time=args.publish_time,
                    timeout=args.timeout,
                )

                aweme_list = body.get("aweme_list") or []
                captured_at = utc_now_iso()
                for rank, aweme in enumerate(aweme_list, start=1):
                    aweme_id = upsert_video(conn, aweme, seen_at=captured_at)
                    if not aweme_id:
                        continue
                    insert_snapshot(
                        conn=conn,
                        run_id=run_id,
                        keyword=keyword,
                        aweme_id=aweme_id,
                        cursor=cursor,
                        rank_in_page=rank,
                        aweme=aweme,
                        captured_at=captured_at,
                    )
                    total_items += 1

                conn.commit()
                has_more = int(body.get("has_more", 0))
                next_cursor = int(body.get("cursor", cursor))
                print(
                    f"[{keyword}] page={page_idx} cursor={cursor} fetched={len(aweme_list)} "
                    f"has_more={has_more} next_cursor={next_cursor}"
                )

                if has_more != 1:
                    break
                cursor = next_cursor
                time.sleep(args.sleep_seconds)

        update_run_status(conn, run_id, status="success", message=f"items={total_items}")
        print(f"collection success: run_id={run_id}, items={total_items}, db={db_path}")
    except Exception as exc:
        update_run_status(conn, run_id, status="failed", message=str(exc))
        raise
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Douyin search data via OpenAPI.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite db path.")
    parser.add_argument(
        "--keywords-file",
        default="keywords.txt",
        help="Keyword file path. One keyword per line.",
    )
    parser.add_argument("--count", type=int, default=20, help="Per-page count, max 50.")
    parser.add_argument("--max-pages", type=int, default=3, help="Max pages per keyword.")
    parser.add_argument(
        "--publish-time",
        type=int,
        default=None,
        help="Optional publish_time filter. Common values: 0, 1, 7, 182.",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.3,
        help="Sleep between pages to avoid aggressive requests.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.count <= 0 or args.count > 50:
        raise ValueError("--count must be between 1 and 50")
    if args.max_pages <= 0:
        raise ValueError("--max-pages must be > 0")
    run_collection(args)


if __name__ == "__main__":
    main()
