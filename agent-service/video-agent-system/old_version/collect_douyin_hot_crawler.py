#!/usr/bin/env python3
"""Collect Douyin hot board topics via web crawling into SQLite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page, sync_playwright
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "playwright is required. Run: pip install playwright && playwright install chromium"
    ) from exc

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_HOT_URL = "https://www.douyin.com/hot"


@dataclass
class CrawlResult:
    entries: list[dict[str, Any]]
    source_kind: str
    source_url: str | None
    raw_payload: dict[str, Any] | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_int(*values: Any) -> int | None:
    for value in values:
        parsed = to_int(value)
        if parsed is not None:
            return parsed
    return None


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def extract_candidate_lists(node: Any, path: str, out: list[tuple[int, int, str, list[dict[str, Any]]]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            extract_candidate_lists(value, f"{path}.{key}", out)
        return

    if isinstance(node, list):
        dict_items = [item for item in node if isinstance(item, dict)]
        if dict_items:
            with_word = 0
            with_hot = 0
            for item in dict_items:
                if any(k in item for k in ("word", "title", "sentence", "name")):
                    with_word += 1
                if any(k in item for k in ("hot_value", "position", "rank", "event_time")):
                    with_hot += 1
            score = with_word * 2 + with_hot
            if score > 0:
                out.append((score, len(dict_items), path, dict_items))

        for idx, value in enumerate(node):
            extract_candidate_lists(value, f"{path}[{idx}]", out)


def pick_hot_list(raw_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str] | None:
    candidates: list[tuple[int, int, str, list[dict[str, Any]]]] = []
    extract_candidate_lists(raw_payload, "$", candidates)
    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, _, best_path, best_list = candidates[0]
    if best_score <= 0:
        return None
    return best_list, best_path


def normalize_entry(item: dict[str, Any], rank_fallback: int, page_url: str) -> dict[str, Any] | None:
    word = str(
        item.get("word")
        or item.get("sentence")
        or item.get("title")
        or item.get("name")
        or ""
    ).strip()
    if not word:
        return None

    sentence_id = item.get("sentence_id")
    group_id = item.get("group_id") or item.get("aweme_id")
    topic_id = (
        str(sentence_id)
        if sentence_id is not None and str(sentence_id).strip()
        else str(group_id)
        if group_id is not None and str(group_id).strip()
        else hashlib.sha1(word.encode("utf-8")).hexdigest()[:24]
    )

    rank_num = first_int(item.get("position"), item.get("rank"), rank_fallback) or rank_fallback
    hot_value = first_int(
        item.get("hot_value"),
        item.get("hot"),
        item.get("hot_score"),
        item.get("score"),
    )

    raw_url = item.get("url") or item.get("link")
    if isinstance(raw_url, str) and raw_url.strip():
        if raw_url.startswith("/"):
            topic_url = f"https://www.douyin.com{raw_url}"
        else:
            topic_url = raw_url
    else:
        topic_url = page_url

    return {
        "topic_id": topic_id,
        "word": word,
        "sentence_id": str(sentence_id) if sentence_id is not None else None,
        "group_id": str(group_id) if group_id is not None else None,
        "event_time": to_int(item.get("event_time")) or to_int(item.get("create_time")),
        "rank_num": rank_num,
        "board": item.get("board_name") or item.get("billboard") or None,
        "hot_value": hot_value,
        "hot_desc": item.get("hot_desc") or item.get("desc") or item.get("label"),
        "sentence_tag": item.get("sentence_tag"),
        "url": topic_url,
        "raw": item,
    }


def normalize_entries(
    raw_items: list[dict[str, Any]], page_url: str, max_topics: int
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_topic_ids: set[str] = set()

    for idx, item in enumerate(raw_items, start=1):
        parsed = normalize_entry(item, rank_fallback=idx, page_url=page_url)
        if parsed is None:
            continue
        topic_id = parsed["topic_id"]
        if topic_id in seen_topic_ids:
            continue
        seen_topic_ids.add(topic_id)
        normalized.append(parsed)
        if len(normalized) >= max_topics:
            break

    normalized.sort(key=lambda row: row["rank_num"])
    return normalized


def extract_from_dom(page: Page, page_url: str, max_topics: int) -> list[dict[str, Any]]:
    dom_rows = page.evaluate(
        """
        () => {
          const rows = [];
          const links = [...document.querySelectorAll('a[href]')];
          for (const a of links) {
            const href = a.getAttribute('href') || '';
            if (!href.includes('/hot/')) continue;
            const text = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text) continue;
            rows.push({
              word: text,
              url: href.startsWith('http') ? href : `https://www.douyin.com${href}`
            });
          }
          return rows;
        }
        """
    )
    if not isinstance(dom_rows, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen_words: set[str] = set()
    for idx, row in enumerate(dom_rows, start=1):
        if not isinstance(row, dict):
            continue
        word = str(row.get("word") or "").strip()
        if not word or word in seen_words:
            continue
        seen_words.add(word)
        normalized.append(
            {
                "topic_id": hashlib.sha1(word.encode("utf-8")).hexdigest()[:24],
                "word": word,
                "sentence_id": None,
                "group_id": None,
                "event_time": None,
                "rank_num": idx,
                "board": None,
                "hot_value": None,
                "hot_desc": None,
                "sentence_tag": None,
                "url": str(row.get("url") or page_url),
                "raw": row,
            }
        )
        if len(normalized) >= max_topics:
            break

    return normalized


def crawl_hot_page(args: argparse.Namespace) -> CrawlResult:
    payloads: list[tuple[str, dict[str, Any]]] = []

    def on_response(resp: Any) -> None:
        url = resp.url.lower()
        if "hot" not in url and "billboard" not in url:
            return
        try:
            data = resp.json()
        except Exception:
            return
        if isinstance(data, dict):
            payloads.append((resp.url, data))

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
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
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", on_response)
        page.goto(args.hot_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(int(args.wait_seconds * 1000))

        best_entries: list[dict[str, Any]] = []
        best_url: str | None = None
        best_payload: dict[str, Any] | None = None
        for url, payload in payloads:
            picked = pick_hot_list(payload)
            if not picked:
                continue
            raw_items, _ = picked
            parsed = normalize_entries(raw_items, page_url=args.hot_url, max_topics=args.max_topics)
            if len(parsed) > len(best_entries):
                best_entries = parsed
                best_url = url
                best_payload = payload

        if len(best_entries) >= args.min_topics:
            context.close()
            return CrawlResult(
                entries=best_entries,
                source_kind="network_json",
                source_url=best_url,
                raw_payload=best_payload,
            )

        dom_entries = extract_from_dom(page, page_url=args.hot_url, max_topics=args.max_topics)
        context.close()
        return CrawlResult(
            entries=dom_entries,
            source_kind="dom_fallback",
            source_url=args.hot_url,
            raw_payload=None,
        )


def upsert_topic(conn: sqlite3.Connection, topic: dict[str, Any], seen_at: str) -> None:
    conn.execute(
        """
        INSERT INTO hot_topics(
          topic_id, word, sentence_id, group_id, event_time, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id) DO UPDATE SET
          word = excluded.word,
          sentence_id = excluded.sentence_id,
          group_id = excluded.group_id,
          event_time = excluded.event_time,
          last_seen_at = excluded.last_seen_at
        """,
        (
            topic["topic_id"],
            topic["word"],
            topic["sentence_id"],
            topic["group_id"],
            topic["event_time"],
            seen_at,
            seen_at,
        ),
    )


def insert_hot_snapshot(
    conn: sqlite3.Connection, run_id: str, topic: dict[str, Any], captured_at: str
) -> None:
    conn.execute(
        """
        INSERT INTO hot_topic_snapshots(
          run_id, rank_num, board, topic_id, word, hot_value, hot_desc,
          sentence_tag, url, captured_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            topic["rank_num"],
            topic["board"],
            topic["topic_id"],
            topic["word"],
            topic["hot_value"],
            topic["hot_desc"],
            topic["sentence_tag"],
            topic["url"],
            captured_at,
            json.dumps(topic["raw"], ensure_ascii=False),
        ),
    )


def sync_keywords(conn: sqlite3.Connection, words: list[str]) -> int:
    now = utc_now_iso()
    rows = [(word, 1, now) for word in words]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO search_tasks(keyword, enabled, created_at) VALUES (?, ?, ?)",
        rows,
    )
    return conn.total_changes - before


def update_run_status(
    conn: sqlite3.Connection, run_id: str, status: str, message: str | None = None
) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, message = ?, ended_at = ? WHERE run_id = ?",
        (status, message, utc_now_iso(), run_id),
    )
    conn.commit()


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    db_path = Path(args.db).expanduser()
    conn = ensure_db(db_path)

    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO runs(run_id, source, started_at, status, message) VALUES (?, ?, ?, ?, ?)",
        (run_id, "douyin_hot_crawler", utc_now_iso(), "running", None),
    )
    conn.commit()

    try:
        result = crawl_hot_page(args)
        if not result.entries:
            raise RuntimeError("no topics captured from hot page")

        captured_at = utc_now_iso()
        for topic in result.entries:
            upsert_topic(conn, topic, seen_at=captured_at)
            insert_hot_snapshot(conn, run_id=run_id, topic=topic, captured_at=captured_at)

        inserted_keywords = 0
        if args.sync_keywords:
            inserted_keywords = sync_keywords(conn, [row["word"] for row in result.entries])

        conn.commit()
        message = (
            f"topics={len(result.entries)}, source_kind={result.source_kind}, "
            f"source_url={result.source_url}, keyword_changes={inserted_keywords}"
        )
        update_run_status(conn, run_id, "success", message=message)

        if args.dump_raw_json and result.raw_payload is not None:
            dump_path = Path(args.dump_raw_json).expanduser()
            dump_path.parent.mkdir(parents=True, exist_ok=True)
            dump_path.write_text(
                json.dumps(result.raw_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        print(f"crawler success: run_id={run_id}, {message}, db={db_path}")
    except Exception as exc:
        update_run_status(conn, run_id, "failed", message=str(exc))
        raise
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Douyin hot board into SQLite.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument("--hot-url", default=DEFAULT_HOT_URL, help="Douyin hot page URL.")
    parser.add_argument(
        "--user-data-dir",
        default="data/browser_profile",
        help="Persistent browser profile dir for login/session reuse.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (default).",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in headed mode for manual login/debug.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=8.0,
        help="How long to wait after opening hot page.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=45000,
        help="Page navigation timeout in milliseconds.",
    )
    parser.add_argument(
        "--min-topics",
        type=int,
        default=8,
        help="Min topics needed from network JSON before fallback to DOM parse.",
    )
    parser.add_argument("--max-topics", type=int, default=50, help="Max topics to keep.")
    parser.add_argument(
        "--sync-keywords",
        action="store_true",
        help="Write captured hot words into search_tasks for downstream collection.",
    )
    parser.add_argument(
        "--dump-raw-json",
        default=None,
        help="Optional path to dump captured network JSON payload.",
    )
    parser.set_defaults(headless=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.headful:
        args.headless = False
    if not args.headless and (not os.environ.get("DISPLAY")):
        raise RuntimeError(
            "No DISPLAY found. This host has no GUI session for --headful. "
            "Use default headless mode, or run with xvfb-run."
        )
    if args.min_topics <= 0:
        raise ValueError("--min-topics must be > 0")
    if args.max_topics <= 0:
        raise ValueError("--max-topics must be > 0")
    run_collection(args)


if __name__ == "__main__":
    main()
