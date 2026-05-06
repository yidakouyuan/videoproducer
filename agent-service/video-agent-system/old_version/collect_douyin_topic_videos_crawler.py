#!/usr/bin/env python3
"""Collect videos (and optional comments) for Douyin hot topics via web crawling."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import BrowserContext, Page, sync_playwright
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "playwright is required. Run: pip install playwright && playwright install chromium"
    ) from exc

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@dataclass
class TopicTask:
    topic_id: str
    word: str
    rank_num: int
    sentence_id: str | None
    group_id: str | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pick_first_url(value: Any) -> str | None:
    if isinstance(value, dict):
        candidates = value.get("url_list")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            return str(first) if first is not None else None
    if isinstance(value, list) and value:
        first = value[0]
        return str(first) if first is not None else None
    return None


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def get_latest_hot_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT run_id
        FROM runs
        WHERE source = 'douyin_hot_crawler' AND status = 'success'
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError("no successful douyin_hot_crawler run found")
    return str(row["run_id"])


def load_topics(conn: sqlite3.Connection, args: argparse.Namespace) -> tuple[str, list[TopicTask]]:
    hot_run_id = args.hot_run_id or get_latest_hot_run_id(conn)
    rows = conn.execute(
        """
        SELECT
          hts.topic_id,
          hts.word,
          hts.rank_num,
          ht.sentence_id AS sentence_id,
          ht.group_id AS group_id,
          hts.raw_json
        FROM hot_topic_snapshots hts
        LEFT JOIN hot_topics ht ON ht.topic_id = hts.topic_id
        WHERE hts.run_id = ?
          AND hts.rank_num >= ?
          AND hts.rank_num <= ?
        ORDER BY hts.rank_num ASC, hts.id ASC
        """,
        (hot_run_id, args.min_topic_rank, args.max_topic_rank),
    ).fetchall()

    topics: list[TopicTask] = []
    seen: set[str] = set()
    for row in rows:
        topic_id = str(row["topic_id"])
        if topic_id in seen:
            continue

        if args.only_ranked:
            try:
                raw = json.loads(row["raw_json"])
            except Exception:
                raw = {}
            if "position" not in raw:
                continue

        word = str(row["word"]).strip()
        if not word:
            continue

        task = TopicTask(
            topic_id=topic_id,
            word=word,
            rank_num=int(row["rank_num"]),
            sentence_id=str(row["sentence_id"]) if row["sentence_id"] else None,
            group_id=str(row["group_id"]) if row["group_id"] else None,
        )
        topics.append(task)
        seen.add(topic_id)
        if len(topics) >= args.topic_limit:
            break

    if not topics:
        raise RuntimeError(
            f"no topics selected from run_id={hot_run_id}. "
            "Try relaxing rank/topic filters or disable --only-ranked."
        )
    return hot_run_id, topics


def build_topic_url(topic: TopicTask) -> str:
    if topic.sentence_id:
        return f"https://www.douyin.com/hot/{quote(topic.sentence_id, safe='')}"
    if topic.group_id:
        return f"https://www.douyin.com/hot/{quote(topic.group_id, safe='')}"
    return f"https://www.douyin.com/search/{quote(topic.word, safe='')}?type=video"


def is_aweme_like(node: dict[str, Any]) -> bool:
    if "aweme_id" not in node:
        return False
    return any(k in node for k in ("video", "statistics", "desc", "author"))


def collect_aweme_nodes(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if is_aweme_like(node):
            out.append(node)
        for value in node.values():
            collect_aweme_nodes(value, out)
        return
    if isinstance(node, list):
        for value in node:
            collect_aweme_nodes(value, out)


def is_comment_like(node: dict[str, Any]) -> bool:
    comment_id = node.get("cid") or node.get("comment_id")
    if comment_id is None:
        return False
    return any(k in node for k in ("text", "content", "digg_count", "user"))


def collect_comment_nodes(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if is_comment_like(node):
            out.append(node)
        for value in node.values():
            collect_comment_nodes(value, out)
        return
    if isinstance(node, list):
        for value in node:
            collect_comment_nodes(value, out)


def extract_tags(aweme: dict[str, Any]) -> list[tuple[str, str]]:
    tags: list[tuple[str, str]] = []
    seen: set[str] = set()

    text_extra = aweme.get("text_extra")
    if isinstance(text_extra, list):
        for item in text_extra:
            if not isinstance(item, dict):
                continue
            tag_name = item.get("hashtag_name") or item.get("hashtag") or item.get("tag_name")
            if tag_name is None:
                continue
            tag = str(tag_name).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append((tag, "hashtag"))

    cha_list = aweme.get("cha_list")
    if isinstance(cha_list, list):
        for item in cha_list:
            if not isinstance(item, dict):
                continue
            cha_name = item.get("cha_name") or item.get("name")
            if cha_name is None:
                continue
            tag = str(cha_name).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append((tag, "challenge"))

    return tags


def normalize_aweme(aweme: dict[str, Any], rank_in_topic: int) -> dict[str, Any] | None:
    aweme_id = aweme.get("aweme_id")
    if aweme_id is None:
        return None

    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}

    cover_url = (
        pick_first_url(aweme.get("cover"))
        or pick_first_url(video.get("cover"))
        or pick_first_url(video.get("origin_cover"))
    )
    video_url = pick_first_url(video.get("play_addr"))

    return {
        "aweme_id": str(aweme_id),
        "desc": aweme.get("desc") or aweme.get("title"),
        "create_time": to_int(aweme.get("create_time")),
        "author_id": str(author.get("uid") or author.get("id")) if author else None,
        "author_name": author.get("nickname") or author.get("name"),
        "author_sec_uid": author.get("sec_uid"),
        "author_unique_id": author.get("unique_id"),
        "cover_url": cover_url,
        "video_url": video_url,
        "duration": to_int(video.get("duration")),
        "height": to_int(video.get("height")),
        "width": to_int(video.get("width")),
        "digg_count": to_int(stats.get("digg_count")),
        "comment_count": to_int(stats.get("comment_count")),
        "collect_count": to_int(stats.get("collect_count") or stats.get("collects")),
        "share_count": to_int(stats.get("share_count")),
        "play_count": to_int(stats.get("play_count")),
        "rank_in_topic": rank_in_topic,
        "tags": extract_tags(aweme),
        "raw": aweme,
    }


def normalize_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    comment_id = comment.get("cid") or comment.get("comment_id")
    if comment_id is None:
        return None

    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    text = comment.get("text") or comment.get("content") or comment.get("comment_text")
    if text is not None:
        text = str(text).strip()

    aweme_id = comment.get("aweme_id")
    return {
        "comment_id": str(comment_id),
        "aweme_id": str(aweme_id) if aweme_id is not None else None,
        "user_id": str(user.get("uid") or user.get("user_id")) if user else None,
        "user_name": user.get("nickname") or user.get("name"),
        "text": text,
        "digg_count": to_int(comment.get("digg_count")),
        "reply_total": to_int(
            comment.get("reply_comment_total") or comment.get("reply_total") or comment.get("reply_count")
        ),
        "create_time": to_int(comment.get("create_time")),
        "raw": comment,
    }


def parse_payloads_for_topic(
    payloads: list[tuple[str, dict[str, Any]]], args: argparse.Namespace
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    aweme_nodes: list[dict[str, Any]] = []
    comment_nodes: list[dict[str, Any]] = []

    for _, payload in payloads:
        collect_aweme_nodes(payload, aweme_nodes)
        if args.capture_comments:
            collect_comment_nodes(payload, comment_nodes)

    videos: list[dict[str, Any]] = []
    seen_aweme: set[str] = set()
    for aweme in aweme_nodes:
        normalized = normalize_aweme(aweme, rank_in_topic=len(videos) + 1)
        if normalized is None:
            continue
        aweme_id = normalized["aweme_id"]
        if aweme_id in seen_aweme:
            continue
        seen_aweme.add(aweme_id)
        videos.append(normalized)
        if len(videos) >= args.videos_per_topic:
            break

    comments: list[dict[str, Any]] = []
    seen_comments: set[str] = set()
    for comment in comment_nodes:
        normalized = normalize_comment(comment)
        if normalized is None:
            continue
        comment_id = normalized["comment_id"]
        if comment_id in seen_comments:
            continue
        seen_comments.add(comment_id)
        comments.append(normalized)
        if len(comments) >= args.comments_limit:
            break

    return videos, comments


def crawl_topic_page(
    context: BrowserContext,
    topic: TopicTask,
    args: argparse.Namespace,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    topic_url = build_topic_url(topic)
    payloads: list[tuple[str, dict[str, Any]]] = []
    page = context.new_page()

    def on_response(resp: Any) -> None:
        url = resp.url
        try:
            content_type = resp.headers.get("content-type", "").lower()
        except Exception:
            content_type = ""
        if "json" not in content_type and "aweme" not in url and "comment" not in url:
            return
        try:
            data = resp.json()
        except Exception:
            return
        if isinstance(data, dict):
            payloads.append((url, data))

    try:
        page.on("response", on_response)
        page.goto(topic_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(int(args.wait_seconds * 1000))

        for _ in range(args.scroll_times):
            page.mouse.wheel(0, args.scroll_pixels)
            page.wait_for_timeout(int(args.scroll_wait_seconds * 1000))

        if args.capture_comments:
            clicked = page.evaluate(
                """
                () => {
                  const candidate = document.querySelector('a[href*="/video/"]');
                  if (!candidate) return false;
                  candidate.click();
                  return true;
                }
                """
            )
            if clicked:
                page.wait_for_timeout(int(args.comment_wait_seconds * 1000))

        videos, comments = parse_payloads_for_topic(payloads, args)
        return topic_url, videos, comments, payloads
    finally:
        page.close()


def upsert_video(conn: sqlite3.Connection, video: dict[str, Any], seen_at: str) -> None:
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
            video["aweme_id"],
            video["desc"],
            video["create_time"],
            video["author_id"],
            video["author_name"],
            video["author_sec_uid"],
            video["author_unique_id"],
            video["cover_url"],
            video["video_url"],
            video["duration"],
            video["height"],
            video["width"],
            seen_at,
            seen_at,
        ),
    )


def insert_topic_video_snapshot(
    conn: sqlite3.Connection,
    run_id: str,
    topic: TopicTask,
    video: dict[str, Any],
    captured_at: str,
    source_url: str,
) -> None:
    conn.execute(
        """
        INSERT INTO topic_video_snapshots(
          run_id, topic_id, topic_word, topic_rank_num, sentence_id, group_id,
          aweme_id, rank_in_topic, digg_count, comment_count, collect_count,
          share_count, play_count, captured_at, source_url, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            topic.topic_id,
            topic.word,
            topic.rank_num,
            topic.sentence_id,
            topic.group_id,
            video["aweme_id"],
            video["rank_in_topic"],
            video["digg_count"],
            video["comment_count"],
            video["collect_count"],
            video["share_count"],
            video["play_count"],
            captured_at,
            source_url,
            json.dumps(video["raw"], ensure_ascii=False),
        ),
    )


def upsert_video_tags(
    conn: sqlite3.Connection, aweme_id: str, tags: list[tuple[str, str]], captured_at: str
) -> int:
    inserted = 0
    for tag, tag_type in tags:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO video_tags(aweme_id, tag, tag_type, captured_at)
            VALUES (?, ?, ?, ?)
            """,
            (aweme_id, tag, tag_type, captured_at),
        )
        inserted += cur.rowcount
    return inserted


def insert_video_comments(
    conn: sqlite3.Connection,
    run_id: str,
    topic: TopicTask,
    comments: list[dict[str, Any]],
    captured_at: str,
) -> int:
    inserted = 0
    for comment in comments:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO video_comments(
              run_id, topic_id, aweme_id, comment_id, user_id, user_name, text,
              digg_count, reply_total, create_time, captured_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                topic.topic_id,
                comment["aweme_id"],
                comment["comment_id"],
                comment["user_id"],
                comment["user_name"],
                comment["text"],
                comment["digg_count"],
                comment["reply_total"],
                comment["create_time"],
                captured_at,
                json.dumps(comment["raw"], ensure_ascii=False),
            ),
        )
        inserted += cur.rowcount
    return inserted


def update_run_status(
    conn: sqlite3.Connection, run_id: str, status: str, message: str | None = None
) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, message = ?, ended_at = ? WHERE run_id = ?",
        (status, message, utc_now_iso(), run_id),
    )
    conn.commit()


def launch_context(args: argparse.Namespace):
    return sync_playwright().start()


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    db_path = Path(args.db).expanduser()
    conn = ensure_db(db_path)

    hot_run_id, topics = load_topics(conn, args)
    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO runs(run_id, source, started_at, status, message) VALUES (?, ?, ?, ?, ?)",
        (run_id, "douyin_topic_video_crawler", utc_now_iso(), "running", f"hot_run_id={hot_run_id}"),
    )
    conn.commit()

    topics_with_videos = 0
    total_videos = 0
    total_tags = 0
    total_comments = 0
    payload_saved = 0

    pw = None
    context = None
    try:
        pw = launch_context(args)
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(Path(args.user_data_dir).expanduser()),
                headless=args.headless,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
        except PlaywrightError as exc:
            err = str(exc)
            if (not args.headless) and (
                "Missing X server" in err
                or "$DISPLAY" in err
                or "headed browser without having a XServer" in err
            ):
                raise RuntimeError(
                    "headful mode requires an X server. "
                    "Use headless mode on servers: remove --headful. "
                    "If needed, run with virtual display: xvfb-run -a python ..."
                ) from exc
            raise

        for idx, topic in enumerate(topics, start=1):
            topic_url, videos, comments, payloads = crawl_topic_page(context, topic, args)
            captured_at = utc_now_iso()
            if videos:
                topics_with_videos += 1

            for video in videos:
                upsert_video(conn, video, seen_at=captured_at)
                insert_topic_video_snapshot(
                    conn=conn,
                    run_id=run_id,
                    topic=topic,
                    video=video,
                    captured_at=captured_at,
                    source_url=topic_url,
                )
                total_videos += 1
                total_tags += upsert_video_tags(
                    conn, aweme_id=video["aweme_id"], tags=video["tags"], captured_at=captured_at
                )

            if args.capture_comments and comments:
                total_comments += insert_video_comments(
                    conn=conn,
                    run_id=run_id,
                    topic=topic,
                    comments=comments,
                    captured_at=captured_at,
                )

            if args.dump_payloads_dir:
                dump_dir = Path(args.dump_payloads_dir).expanduser()
                dump_dir.mkdir(parents=True, exist_ok=True)
                dump_path = dump_dir / f"{topic.rank_num:02d}_{topic.topic_id}.json"
                dump_path.write_text(
                    json.dumps(
                        {
                            "topic": {
                                "topic_id": topic.topic_id,
                                "word": topic.word,
                                "rank_num": topic.rank_num,
                                "sentence_id": topic.sentence_id,
                                "group_id": topic.group_id,
                            },
                            "topic_url": topic_url,
                            "payload_count": len(payloads),
                            "payloads": [{"url": u, "data": d} for u, d in payloads],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                payload_saved += 1

            conn.commit()
            print(
                f"[{idx}/{len(topics)}] rank={topic.rank_num} topic={topic.word} "
                f"videos={len(videos)} comments={len(comments)}"
            )

        message = (
            f"hot_run_id={hot_run_id}, topics={len(topics)}, topics_with_videos={topics_with_videos}, "
            f"videos={total_videos}, tags={total_tags}, comments={total_comments}, "
            f"payload_dumps={payload_saved}"
        )
        update_run_status(conn, run_id, "success", message=message)
        print(f"topic video crawler success: run_id={run_id}, {message}, db={db_path}")
    except Exception as exc:
        update_run_status(conn, run_id, "failed", message=str(exc))
        raise
    finally:
        if context is not None:
            context.close()
        if pw is not None:
            pw.stop()
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect videos for Douyin hot topics via crawler.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument(
        "--user-data-dir",
        default="data/browser_profile",
        help="Persistent browser profile dir for session reuse.",
    )
    parser.add_argument("--hot-run-id", default=None, help="Optional source run_id in hot_topic_snapshots.")
    parser.add_argument("--topic-limit", type=int, default=10, help="How many topics to crawl.")
    parser.add_argument("--min-topic-rank", type=int, default=1, help="Min topic rank (inclusive).")
    parser.add_argument("--max-topic-rank", type=int, default=50, help="Max topic rank (inclusive).")
    parser.add_argument(
        "--only-ranked",
        action="store_true",
        help="Only crawl entries that have ranking position in hot raw payload.",
    )
    parser.add_argument("--videos-per-topic", type=int, default=20, help="Max videos per topic.")
    parser.add_argument(
        "--capture-comments",
        action="store_true",
        help="Try to capture comment payloads while opening/clicking topic videos.",
    )
    parser.add_argument("--comments-limit", type=int, default=200, help="Max comments to store in one run.")
    parser.add_argument("--wait-seconds", type=float, default=6.0, help="Wait after opening topic page.")
    parser.add_argument("--scroll-times", type=int, default=2, help="How many scroll actions per topic.")
    parser.add_argument("--scroll-pixels", type=int, default=2200, help="Pixels per scroll action.")
    parser.add_argument(
        "--scroll-wait-seconds",
        type=float,
        default=1.2,
        help="Wait after each scroll action.",
    )
    parser.add_argument(
        "--comment-wait-seconds",
        type=float,
        default=4.0,
        help="Wait after clicking first video for comment payloads.",
    )
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Page timeout in milliseconds.")
    parser.add_argument("--dump-payloads-dir", default=None, help="Optional directory for raw payload dumps.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default).")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode.")
    parser.set_defaults(headless=True, only_ranked=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.headful:
        args.headless = False
    if not args.headless and not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "No DISPLAY found. This host has no GUI session for --headful. "
            "Use default headless mode, or run with xvfb-run."
        )
    if args.topic_limit <= 0:
        raise ValueError("--topic-limit must be > 0")
    if args.videos_per_topic <= 0:
        raise ValueError("--videos-per-topic must be > 0")
    if args.comments_limit <= 0:
        raise ValueError("--comments-limit must be > 0")
    run_collection(args)


if __name__ == "__main__":
    main()
