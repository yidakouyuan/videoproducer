#!/usr/bin/env python3
"""Collect Douyin videos by swiping from Jingxuan modal pages."""

from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "playwright is required. Run: pip install playwright && playwright install chromium"
    ) from exc

from collect_douyin_home_feed_crawler import (
    DEFAULT_UA,
    dump_round_debug,
    ensure_db,
    extract_aweme_id_from_url,
    extract_dom_visible_items,
    extract_page_visible_aweme_id,
    extract_response_payload,
    inspect_page_state,
    is_candidate_response_url,
    is_home_feed_payload_url,
    normalize_dom_item,
    parse_payloads_for_round,
    pick_seed_swipe_video,
    pick_unseen_candidate_aweme_id,
    shorten_url,
    stealth_script,
    update_run_status,
    upsert_video,
    upsert_video_tags,
    insert_home_feed_snapshot,
    utc_now_iso,
    dismiss_common_popups,
)

SOURCE_NAME = "douyin_jingxuan_swipe_crawler"
DEFAULT_JINGXUAN_URL = "https://www.douyin.com/jingxuan?modal_id=7606587500164910386"


def extract_modal_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = None
    try:
        import re

        m = re.search(r"(?:[?&]modal_id=)(\d+)", str(url))
    except Exception:
        m = None
    if m:
        return m.group(1)
    return None


def build_jingxuan_url(modal_id: str) -> str:
    return f"https://www.douyin.com/jingxuan?modal_id={modal_id}"


def resolve_start_url(args: argparse.Namespace) -> str:
    if args.start_url:
        return str(args.start_url).strip()
    if args.modal_id:
        return build_jingxuan_url(str(args.modal_id).strip())
    return DEFAULT_JINGXUAN_URL


def first_aweme_id(videos: list[Any]) -> str | None:
    for video in videos:
        aweme_id = str(getattr(video, "aweme_id", "") or "").strip()
        if aweme_id:
            return aweme_id
    return None


def resolve_current_aweme_id(
    page_url: str | None,
    payload_videos: list[Any],
    dom_candidates: list[Any],
    page=None,
) -> str | None:
    modal_id = extract_modal_id_from_url(page_url)
    if modal_id:
        return modal_id
    url_aweme_id = extract_aweme_id_from_url(page_url)
    if url_aweme_id:
        return url_aweme_id
    dom_aweme_id = first_aweme_id(dom_candidates)
    if dom_aweme_id:
        return dom_aweme_id
    payload_aweme_id = first_aweme_id(payload_videos)
    if payload_aweme_id:
        return payload_aweme_id
    if page is not None:
        page_aweme_id = extract_page_visible_aweme_id(page)
        if page_aweme_id:
            return page_aweme_id
    return None


def advance_by_swipe(
    page,
    current_aweme_id: str | None,
    action_wait_seconds: float,
    round_wait_seconds: float,
    scroll_pixels: int,
    max_swipe_attempts: int,
) -> str | None:
    baseline_aweme_id = current_aweme_id or resolve_current_aweme_id(page.url, [], [], page=page)
    for _ in range(max(1, max_swipe_attempts)):
        dismiss_common_popups(page)
        page.mouse.click(720, 420)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(int(max(action_wait_seconds, 0.6) * 1000))
        page.keyboard.press("PageDown")
        page.wait_for_timeout(int(max(action_wait_seconds, 0.6) * 600))
        page.mouse.wheel(0, scroll_pixels)
        page.wait_for_timeout(int(max(round_wait_seconds, 0.8) * 1000))
        dismiss_common_popups(page)
        page.mouse.click(720, 420)
        next_aweme_id = resolve_current_aweme_id(page.url, [], [], page=page)
        if next_aweme_id and next_aweme_id != baseline_aweme_id:
            return next_aweme_id
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect videos by swiping from Douyin Jingxuan modal pages.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument(
        "--user-data-dir",
        default="data/browser_profile",
        help="Persistent browser profile dir for session reuse.",
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_JINGXUAN_URL,
        help="Jingxuan entry URL (e.g. https://www.douyin.com/jingxuan?modal_id=xxx).",
    )
    parser.add_argument("--modal-id", default=None, help="Optional modal_id used to build start URL.")
    parser.add_argument(
        "--jump-url-mode",
        choices=("jingxuan", "video"),
        default="jingxuan",
        help="Fallback jump URL mode when swipe cannot advance.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=20,
        help="How many rounds to crawl. 0 means endless loop until Ctrl+C.",
    )
    parser.add_argument(
        "--videos-per-round",
        type=int,
        default=20,
        help="Max parsed candidates per round (swipe mode still stores one current video per round).",
    )
    parser.add_argument("--scroll-pixels", type=int, default=2200, help="Pixels per wheel action.")
    parser.add_argument("--startup-wait-seconds", type=float, default=6.0, help="Initial wait after opening page.")
    parser.add_argument("--action-wait-seconds", type=float, default=1.2, help="Wait after each swipe action.")
    parser.add_argument(
        "--round-wait-seconds",
        type=float,
        default=2.0,
        help="Additional wait before collecting payloads in each round.",
    )
    parser.add_argument(
        "--round-interval-seconds",
        type=float,
        default=0.5,
        help="Sleep interval between rounds.",
    )
    parser.add_argument(
        "--max-swipe-attempts",
        type=int,
        default=4,
        help="Max attempts in each round to swipe to next video.",
    )
    parser.add_argument(
        "--max-empty-rounds-before-recover",
        type=int,
        default=3,
        help="If reached, reload Jingxuan URL to recover from blank state.",
    )
    parser.add_argument(
        "--include-related",
        dest="include_related",
        action="store_true",
        help="Also accept related/mix/detail aweme APIs (recommended for Jingxuan).",
    )
    parser.add_argument(
        "--no-include-related",
        dest="include_related",
        action="store_false",
        help="Only accept strict feed API URLs.",
    )
    parser.add_argument("--debug-dump-dir", default=None, help="Optional per-round debug dump directory.")
    parser.add_argument("--stealth", action="store_true", help="Enable anti-automation fingerprint masking.")
    parser.add_argument("--user-agent", default=DEFAULT_UA, help="Browser user-agent for requests.")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Page timeout in milliseconds.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default).")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode.")
    parser.set_defaults(headless=True, stealth=True, include_related=True)
    return parser


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    db_path = Path(args.db).expanduser()
    conn = ensure_db(db_path)

    run_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO runs(run_id, source, started_at, status, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, SOURCE_NAME, utc_now_iso(), "running", None),
    )
    conn.commit()

    total_rounds = 0
    total_videos = 0
    total_tags = 0
    traversed_jumps = 0
    empty_recoveries = 0
    seen_aweme_ids_in_run: set[str] = set()
    visited_seed_pages: set[str] = set()
    round_payload_counts: dict[int, int] = {}
    stopped_by_user = False
    consecutive_empty_rounds = 0

    start_url = resolve_start_url(args)

    pw = None
    context = None
    page = None
    try:
        pw = sync_playwright().start()
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(Path(args.user_data_dir).expanduser()),
                headless=args.headless,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                user_agent=args.user_agent,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--lang=zh-CN",
                ],
            )
        except PlaywrightError as exc:
            err = str(exc)
            if (not args.headless) and (
                "Missing X server" in err
                or "$DISPLAY" in err
                or "headed browser without having a XServer" in err
            ):
                raise RuntimeError(
                    "headful mode requires an X server. Remove --headful or use xvfb-run."
                ) from exc
            raise

        if args.stealth:
            context.add_init_script(stealth_script())
            context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

        page = context.pages[0] if context.pages else context.new_page()
        response_log: list[tuple[str, Any]] = []

        def on_response(resp: Any) -> None:
            url = resp.url
            lower_url = url.lower()
            try:
                content_type = resp.headers.get("content-type", "").lower()
            except Exception:
                content_type = ""
            if not is_candidate_response_url(url):
                if "json" not in content_type:
                    return
                if not any(host in lower_url for host in ("douyin.com", "zijieapi.com", "snssdk.com")):
                    return
            data = extract_response_payload(resp)
            if data is None:
                return
            response_log.append((url, data))

        context.on("response", on_response)
        page.goto(start_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(int(args.startup_wait_seconds * 1000))
        dismiss_common_popups(page)
        page.mouse.click(720, 420)
        start_aweme_id = resolve_current_aweme_id(page.url, [], [], page=page)
        if start_aweme_id:
            visited_seed_pages.add(start_aweme_id)
        print(f"[jingxuan] start_url={shorten_url(start_url, 180)}")

        log_cursor = 0
        round_idx = 1
        while args.rounds == 0 or round_idx <= args.rounds:
            dismiss_common_popups(page)
            page.wait_for_timeout(int(args.round_wait_seconds * 1000))

            payloads = response_log[log_cursor:]
            log_cursor = len(response_log)
            round_payload_counts[round_idx] = len(payloads)

            feed_api_seen = sum(
                1 for url, _ in payloads if is_home_feed_payload_url(url, include_related=args.include_related)
            )

            payload_videos = parse_payloads_for_round(
                payloads=payloads,
                videos_per_round=max(args.videos_per_round, 1),
                include_related=args.include_related,
            )
            dom_items, dom_captcha_detected = extract_dom_visible_items(page, max_cards=max(args.videos_per_round, 1))
            page_state = inspect_page_state(page)
            page_url = str(page_state.get("page_url") or page.url)
            captcha_detected = bool(dom_captcha_detected or page_state.get("captcha_detected"))
            login_detected = bool(page_state.get("login_detected"))

            if args.debug_dump_dir:
                dump_round_debug(
                    debug_dump_dir=Path(args.debug_dump_dir).expanduser(),
                    run_id=run_id,
                    round_idx=round_idx,
                    page_state=page_state,
                    payloads=payloads,
                )

            dom_candidates: list[Any] = []
            start_seq = len(payload_videos)
            for idx, item in enumerate(dom_items, start=start_seq + 1):
                parsed = normalize_dom_item(item, first_seen_seq=idx)
                if parsed is None:
                    continue
                dom_candidates.append(parsed)

            page_aweme_id = resolve_current_aweme_id(page_url, payload_videos, dom_candidates, page=page)
            current_video = pick_seed_swipe_video(payload_videos, dom_candidates, page_aweme_id=page_aweme_id)
            videos: list[Any] = [current_video] if current_video is not None else []

            if page_aweme_id:
                visited_seed_pages.add(page_aweme_id)

            if videos and (page_state.get("visible_video_count") or 0) > 0:
                consecutive_empty_rounds = 0
            else:
                consecutive_empty_rounds += 1

            unique_new_count = 0
            captured_at = utc_now_iso()
            for rank_in_round, video in enumerate(videos, start=1):
                if video.aweme_id not in seen_aweme_ids_in_run:
                    unique_new_count += 1
                    seen_aweme_ids_in_run.add(video.aweme_id)
                upsert_video(conn, video, seen_at=captured_at)
                insert_home_feed_snapshot(
                    conn=conn,
                    run_id=run_id,
                    round_num=round_idx,
                    rank_in_round=rank_in_round,
                    video=video,
                    captured_at=captured_at,
                    page_url=page_url,
                )
                total_tags += upsert_video_tags(
                    conn=conn,
                    aweme_id=video.aweme_id,
                    tags=video.tags,
                    captured_at=captured_at,
                )

            conn.commit()
            total_rounds += 1
            total_videos += len(videos)

            next_aweme_id = advance_by_swipe(
                page=page,
                current_aweme_id=page_aweme_id,
                action_wait_seconds=args.action_wait_seconds,
                round_wait_seconds=args.round_wait_seconds,
                scroll_pixels=args.scroll_pixels,
                max_swipe_attempts=args.max_swipe_attempts,
            )
            jumped_to_next = False
            if next_aweme_id:
                visited_seed_pages.add(next_aweme_id)
                traversed_jumps += 1
                jumped_to_next = True
            else:
                candidate_id = pick_unseen_candidate_aweme_id(
                    dom_candidates=dom_candidates,
                    payload_videos=payload_videos,
                    current_aweme_id=page_aweme_id,
                    visited_seed_pages=visited_seed_pages,
                )
                if candidate_id:
                    next_url = (
                        build_jingxuan_url(candidate_id)
                        if args.jump_url_mode == "jingxuan"
                        else f"https://www.douyin.com/video/{candidate_id}"
                    )
                    try:
                        page.goto(next_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                        page.wait_for_timeout(int(args.startup_wait_seconds * 1000))
                        dismiss_common_popups(page)
                        page.mouse.click(720, 420)
                        response_log.clear()
                        log_cursor = 0
                        visited_seed_pages.add(candidate_id)
                        next_aweme_id = candidate_id
                        traversed_jumps += 1
                        jumped_to_next = True
                    except Exception as exc:
                        print(f"[jump] switch_to_next=0 next_aweme_id={candidate_id} reason={exc}")

            if consecutive_empty_rounds >= max(1, args.max_empty_rounds_before_recover):
                recover_aweme_id = next_aweme_id or page_aweme_id
                if recover_aweme_id:
                    recover_url = build_jingxuan_url(recover_aweme_id)
                else:
                    recover_url = start_url
                print(
                    f"[recover] empty_rounds={consecutive_empty_rounds} "
                    f"reload={shorten_url(recover_url, 160)}"
                )
                page.goto(recover_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                page.wait_for_timeout(int(args.startup_wait_seconds * 1000))
                dismiss_common_popups(page)
                page.mouse.click(720, 420)
                response_log.clear()
                log_cursor = 0
                consecutive_empty_rounds = 0
                empty_recoveries += 1

            sample_urls = [shorten_url(url, 180) for url, _ in payloads[:3]]
            sample_text = "none" if not sample_urls else " | ".join(sample_urls)
            next_aweme_text = next_aweme_id or "none"
            print(
                f"[round {round_idx}] feed_api_seen={feed_api_seen} payloads={len(payloads)} "
                f"videos={len(videos)} unique_new={unique_new_count} "
                f"login={int(login_detected)} captcha={int(captcha_detected)} "
                f"visible_video={int(page_state.get('visible_video_count') or 0)} "
                f"jumped={int(jumped_to_next)} current_aweme_id={page_aweme_id or 'none'} "
                f"next_aweme_id={next_aweme_text} "
                f"page_url={shorten_url(page_url, 120)} payload_sample={sample_text}"
            )

            round_idx += 1
            if args.round_interval_seconds > 0:
                time.sleep(args.round_interval_seconds)

    except KeyboardInterrupt:
        stopped_by_user = True
    except Exception as exc:
        update_run_status(conn, run_id, "failed", message=str(exc))
        raise
    finally:
        if page is not None:
            page.close()
        if context is not None:
            context.close()
        if pw is not None:
            pw.stop()

        if conn:
            payload_total = sum(round_payload_counts.values())
            message = (
                f"rounds={total_rounds}, videos={total_videos}, tags={total_tags}, "
                f"payload_total={payload_total}, unique_aweme={len(seen_aweme_ids_in_run)}, "
                f"traversed_jumps={traversed_jumps}, empty_recoveries={empty_recoveries}, "
                f"include_related={int(args.include_related)}, stopped_by_user={int(stopped_by_user)}"
            )
            if stopped_by_user:
                update_run_status(conn, run_id, "success", message=message)
                print(f"jingxuan swipe crawler stopped by user: run_id={run_id}, {message}, db={db_path}")
            else:
                row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                if row and row["status"] == "running":
                    update_run_status(conn, run_id, "success", message=message)
                    print(f"jingxuan swipe crawler success: run_id={run_id}, {message}, db={db_path}")
            conn.close()


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
    if args.rounds < 0:
        raise ValueError("--rounds must be >= 0")
    if args.videos_per_round <= 0:
        raise ValueError("--videos-per-round must be > 0")
    if args.max_swipe_attempts <= 0:
        raise ValueError("--max-swipe-attempts must be > 0")
    if args.max_empty_rounds_before_recover <= 0:
        raise ValueError("--max-empty-rounds-before-recover must be > 0")
    run_collection(args)


if __name__ == "__main__":
    main()
