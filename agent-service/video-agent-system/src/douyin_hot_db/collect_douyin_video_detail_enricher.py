#!/usr/bin/env python3
"""Enrich Douyin video metadata by revisiting video detail pages."""

from __future__ import annotations

import argparse
import json
import os
import re
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
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

DETAIL_URL_HINTS = (
    "/aweme/v1/web/aweme/detail/",
    "/aweme/v1/web/aweme/post/",
    "/aweme/v1/web/mix/aweme/",
    "/aweme/v1/web/feed/",
    "/aweme/v1/web/recommend/feed/",
    "/aweme/v1/web/recommend/list/",
)

GENERIC_AWEME_HINT = "/aweme/v1/web/"

AWEME_BLOCKLIST_HINTS = (
    "/aweme/v1/web/social/count",
    "/aweme/v1/web/query/user/",
    "/aweme/v1/web/emoji/list",
    "/aweme/v1/web/get/user/settings",
    "/aweme/v1/web/api/suggest_words/",
    "/aweme/v1/web/seo/",
    "/aweme/v1/web/solution/resource/",
    "/aweme/v1/web/page/turn/offline",
    "/aweme/v1/web/danmaku/",
)

RESPONSE_NOISE_HINTS = (
    "/monitor_web/settings/",
    "/vc/setting",
    "/captcha/",
    "/passport/web/check_qrconnect/",
    "mcs.zijieapi.com/list",
)


@dataclass
class TargetVideo:
    aweme_id: str
    page_url: str


@dataclass
class DetailVideo:
    aweme_id: str
    desc: str | None
    create_time: int | None
    author_id: str | None
    author_name: str | None
    author_sec_uid: str | None
    author_unique_id: str | None
    cover_url: str | None
    video_url: str | None
    duration: int | None
    height: int | None
    width: int | None
    digg_count: int | None
    comment_count: int | None
    collect_count: int | None
    share_count: int | None
    play_count: int | None
    tags: list[tuple[str, str]]
    source_kind: str
    source_api_url: str
    raw: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_count_text(text: str | None) -> int | None:
    if text is None:
        return None
    t = str(text).strip().replace(",", "").replace("+", "")
    if not t:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)([万亿wW]?)$", t)
    if not m:
        return to_int(t)
    base = float(m.group(1))
    unit = m.group(2)
    if unit in ("万", "w", "W"):
        base *= 10_000
    elif unit == "亿":
        base *= 100_000_000
    return int(base)


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


def parse_json_like_text(text: str) -> Any | None:
    raw = text.strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.startswith("for (;;);"):
        candidates.append(raw[len("for (;;);") :].strip())

    for first in ("{", "["):
        idx = raw.find(first)
        if idx > 0:
            candidates.append(raw[idx:].strip())

    for cand in candidates:
        if not cand:
            continue
        try:
            parsed = json.loads(cand)
        except Exception:
            continue
        if isinstance(parsed, str):
            nested = parsed.strip()
            if nested.startswith("{") or nested.startswith("["):
                try:
                    parsed = json.loads(nested)
                except Exception:
                    pass
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def extract_response_payload(resp: Any) -> Any | None:
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, (dict, list)):
        return data
    try:
        text = resp.text()
    except Exception:
        return None
    return parse_json_like_text(text)


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def stealth_script() -> str:
    return """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'language', { get: () => 'zh-CN' });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    if (!window.chrome) {
      Object.defineProperty(window, 'chrome', { value: { runtime: {} } });
    }
    const originalQuery = navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
      navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : originalQuery(parameters)
      );
    }
  } catch (_) {}
})();
"""


def dismiss_common_popups(page: Page) -> bool:
    clicked = page.evaluate(
        """
        () => {
          const closeSelectors = [
            '[aria-label="关闭"]',
            '[class*="close"]',
            'button[title*="关闭"]',
            'div[role="button"][aria-label*="关闭"]',
          ];
          const clickIfVisible = (n) => {
            if (!(n instanceof HTMLElement)) return false;
            const style = window.getComputedStyle(n);
            if (style.visibility === 'hidden' || style.display === 'none') return false;
            const rect = n.getBoundingClientRect();
            if (rect.width < 8 || rect.height < 8) return false;
            n.click();
            return true;
          };
          for (const sel of closeSelectors) {
            const nodes = Array.from(document.querySelectorAll(sel));
            for (const n of nodes) {
              if (clickIfVisible(n)) return true;
            }
          }
          const textTargets = ['知道了', '稍后', '以后再说', '关闭'];
          const textNodes = Array.from(document.querySelectorAll('button,div[role="button"],span'));
          for (const node of textNodes) {
            const txt = (node.textContent || '').trim();
            if (!txt) continue;
            if (!textTargets.some((k) => txt.includes(k))) continue;
            if (clickIfVisible(node)) return true;
          }
          return false;
        }
        """
    )
    return bool(clicked)


def inspect_page_state(page: Page) -> dict[str, Any]:
    data = page.evaluate(
        """
        () => {
          const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const bodyText = normalize(document.body ? document.body.innerText : '');
          const title = normalize(document.title || '');
          const loginDetected =
            /(扫码登录|登录后|请登录|手机号登录|二维码登录|账号登录)/i.test(bodyText) ||
            /passport|login/i.test(window.location.href);
          const captchaDetected = /(captcha|安全验证|滑块|请完成验证|验证后继续)/i.test(bodyText);
          const videoLinks = document.querySelectorAll('a[href*="/video/"]').length;
          return {
            page_url: window.location.href,
            title: title,
            login_detected: loginDetected,
            captcha_detected: captchaDetected,
            video_link_count: videoLinks,
            body_preview: bodyText.slice(0, 120),
          };
        }
        """
    )
    if not isinstance(data, dict):
        return {
            "page_url": page.url,
            "title": "",
            "login_detected": False,
            "captcha_detected": False,
            "video_link_count": 0,
            "body_preview": "",
        }
    return data


def extract_aweme_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/(?:video|note)/(\d+)", str(url))
    if not m:
        return None
    return m.group(1)


def source_priority(source_api_url: str) -> int:
    lower = source_api_url.lower()
    if "render_data://" in lower:
        return 2
    if "dom://" in lower:
        return 1
    if "/aweme/v1/web/aweme/detail/" in lower:
        return 6
    if "/aweme/v1/web/aweme/post/" in lower:
        return 5
    if "/aweme/v1/web/recommend/feed/" in lower:
        return 4
    if "/aweme/v1/web/feed/" in lower:
        return 3
    if GENERIC_AWEME_HINT in lower:
        return 3
    return 0


def is_candidate_detail_response_url(url: str) -> bool:
    lower = url.lower()
    if any(hint in lower for hint in RESPONSE_NOISE_HINTS):
        return False
    if any(hint in lower for hint in DETAIL_URL_HINTS):
        return True
    if GENERIC_AWEME_HINT in lower and not any(h in lower for h in AWEME_BLOCKLIST_HINTS):
        return True
    return False


def is_aweme_like(node: dict[str, Any]) -> bool:
    aweme_id = node.get("aweme_id") or node.get("awemeId")
    if aweme_id is None:
        return False
    return any(k in node for k in ("video", "statistics", "desc", "author", "aweme_info", "aweme"))


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


def extract_tags_from_title(title: str | None) -> list[tuple[str, str]]:
    if not title:
        return []
    seen: set[str] = set()
    tags: list[tuple[str, str]] = []
    for m in re.finditer(r"#([^\s#]{1,30})", title):
        tag = m.group(1).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append((tag, "hashtag"))
    return tags


def normalize_aweme(aweme: dict[str, Any], source_api_url: str, source_kind: str) -> DetailVideo | None:
    nested_aweme = aweme.get("aweme_info") or aweme.get("aweme")
    if isinstance(nested_aweme, dict):
        nested_aweme_id = nested_aweme.get("aweme_id") or nested_aweme.get("awemeId")
        if nested_aweme_id is not None:
            aweme = nested_aweme

    aweme_id = aweme.get("aweme_id") or aweme.get("awemeId")
    if aweme_id is None:
        return None

    author_raw = aweme.get("author") or aweme.get("author_info")
    video_raw = aweme.get("video") or aweme.get("video_info")
    stats_raw = aweme.get("statistics") or aweme.get("stats")

    author = author_raw if isinstance(author_raw, dict) else {}
    video = video_raw if isinstance(video_raw, dict) else {}
    stats = stats_raw if isinstance(stats_raw, dict) else {}

    cover_url = (
        pick_first_url(aweme.get("cover"))
        or pick_first_url(video.get("cover"))
        or pick_first_url(video.get("origin_cover"))
    )
    video_url = pick_first_url(video.get("play_addr")) or pick_first_url(video.get("download_addr"))

    return DetailVideo(
        aweme_id=str(aweme_id),
        desc=aweme.get("desc") or aweme.get("title") or aweme.get("aweme_title"),
        create_time=to_int(aweme.get("create_time")),
        author_id=str(author.get("uid") or author.get("id")) if author else None,
        author_name=author.get("nickname") or author.get("name") or author.get("author_name"),
        author_sec_uid=author.get("sec_uid"),
        author_unique_id=author.get("unique_id"),
        cover_url=cover_url,
        video_url=video_url,
        duration=to_int(video.get("duration")),
        height=to_int(video.get("height")),
        width=to_int(video.get("width")),
        digg_count=to_int(stats.get("digg_count") or stats.get("diggCount")),
        comment_count=to_int(stats.get("comment_count") or stats.get("commentCount")),
        collect_count=to_int(stats.get("collect_count") or stats.get("collects")),
        share_count=to_int(stats.get("share_count") or stats.get("shareCount")),
        play_count=to_int(stats.get("play_count") or stats.get("playCount")),
        tags=extract_tags(aweme),
        source_kind=source_kind,
        source_api_url=source_api_url,
        raw=aweme,
    )


def completeness_score(video: DetailVideo) -> int:
    score = 0
    if video.desc:
        score += 8
    if video.author_name:
        score += 5
    if video.video_url:
        score += 3
    if video.cover_url:
        score += 2
    if video.create_time is not None:
        score += 2
    if video.digg_count is not None:
        score += 2
    if video.comment_count is not None:
        score += 2
    if video.collect_count is not None:
        score += 1
    if video.share_count is not None:
        score += 1
    if video.play_count is not None:
        score += 1
    score += min(3, len(video.tags))
    return score


def choose_best_candidate(candidates: list[DetailVideo], target_aweme_id: str) -> DetailVideo | None:
    if not candidates:
        return None
    exact = [x for x in candidates if x.aweme_id == target_aweme_id]
    pool = exact if exact else candidates
    pool.sort(
        key=lambda x: (source_priority(x.source_api_url), completeness_score(x)),
        reverse=True,
    )
    return pool[0]


def extract_from_payloads(
    payloads: list[tuple[str, Any]], target_aweme_id: str, max_payload_scan: int
) -> DetailVideo | None:
    candidates: list[DetailVideo] = []
    for source_api_url, payload in payloads[:max_payload_scan]:
        aweme_nodes: list[dict[str, Any]] = []
        collect_aweme_nodes(payload, aweme_nodes)
        if not aweme_nodes:
            continue
        for aweme in aweme_nodes:
            parsed = normalize_aweme(
                aweme=aweme,
                source_api_url=source_api_url,
                source_kind="network_aweme",
            )
            if parsed is None:
                continue
            candidates.append(parsed)
    return choose_best_candidate(candidates, target_aweme_id)


def extract_render_payload_text(page: Page) -> str | None:
    text = page.evaluate(
        """
        () => {
          const el = document.getElementById('RENDER_DATA');
          if (!el) return null;
          const raw = (el.textContent || '').trim();
          if (!raw) return null;
          try {
            return decodeURIComponent(raw);
          } catch (_) {
            return raw;
          }
        }
        """
    )
    if text is None:
        return None
    t = str(text).strip()
    return t if t else None


def extract_from_render_data(page: Page, target_aweme_id: str) -> DetailVideo | None:
    payload_text = extract_render_payload_text(page)
    if payload_text is None:
        return None
    payload = parse_json_like_text(payload_text)
    if payload is None:
        return None
    aweme_nodes: list[dict[str, Any]] = []
    collect_aweme_nodes(payload, aweme_nodes)
    candidates: list[DetailVideo] = []
    for aweme in aweme_nodes:
        parsed = normalize_aweme(
            aweme=aweme,
            source_api_url="render_data://page",
            source_kind="render_data",
        )
        if parsed is None:
            continue
        candidates.append(parsed)
    return choose_best_candidate(candidates, target_aweme_id)


def extract_from_dom(page: Page, target_aweme_id: str, page_url: str) -> DetailVideo | None:
    data = page.evaluate(
        """
        () => {
          const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const countRegex = /\\d+(?:\\.\\d+)?(?:万|亿|w|W)?/;
          const pickCount = (keys) => {
            const nodes = Array.from(document.querySelectorAll('button,div,span'));
            for (const node of nodes) {
              const meta = [
                node.getAttribute('aria-label') || '',
                node.getAttribute('title') || '',
                node.getAttribute('data-e2e') || '',
                node.className || '',
              ].join(' ').toLowerCase();
              if (!keys.some((k) => meta.includes(k))) continue;
              const txt = normalize(node.innerText || node.textContent || '');
              const m = txt.match(countRegex);
              if (m) return m[0];
            }
            return '';
          };

          const href = window.location.href;
          let awemeId = '';
          const m = href.match(/\\/(?:video|note)\\/(\\d+)/);
          if (m) awemeId = m[1];

          const titleSelectors = [
            '[data-e2e="video-desc"]',
            '[class*="video-desc"]',
            '[class*="title"]',
            'h1',
          ];
          let title = '';
          for (const sel of titleSelectors) {
            const node = document.querySelector(sel);
            if (!node) continue;
            const txt = normalize(node.textContent || '');
            if (txt.length >= 2) {
              title = txt;
              break;
            }
          }
          if (!title) {
            const og = document.querySelector('meta[property="og:title"]');
            if (og) {
              title = normalize(og.getAttribute('content') || '');
            }
          }
          if (!title) {
            const titleText = normalize(document.title || '');
            title = titleText.replace(/\\s*-\\s*抖音$/, '');
          }

          const authorSelectors = [
            '[data-e2e="video-author-nickname"]',
            'a[href*="/user/"]',
            'a[href*="/@"]',
          ];
          let authorName = '';
          for (const sel of authorSelectors) {
            const node = document.querySelector(sel);
            if (!node) continue;
            const txt = normalize(node.textContent || '');
            if (txt.length >= 1) {
              authorName = txt;
              break;
            }
          }

          const videoEl = document.querySelector('video');
          const videoSrc = videoEl ? (videoEl.currentSrc || videoEl.src || '') : '';

          return {
            aweme_id: awemeId,
            title: title,
            author_name: authorName,
            video_src: videoSrc,
            digg_text: pickCount(['digg', 'like', '点赞']),
            comment_text: pickCount(['comment', '评论']),
            share_text: pickCount(['share', '分享']),
            collect_text: pickCount(['collect', '收藏']),
          };
        }
        """
    )
    if not isinstance(data, dict):
        return None

    aweme_id = str(data.get("aweme_id") or "").strip() or target_aweme_id
    if not aweme_id:
        return None
    title = str(data.get("title") or "").strip() or None
    author_name = str(data.get("author_name") or "").strip() or None
    video_src = str(data.get("video_src") or "").strip() or None

    return DetailVideo(
        aweme_id=aweme_id,
        desc=title,
        create_time=None,
        author_id=None,
        author_name=author_name,
        author_sec_uid=None,
        author_unique_id=None,
        cover_url=None,
        video_url=video_src or page_url,
        duration=None,
        height=None,
        width=None,
        digg_count=parse_count_text(data.get("digg_text")),
        comment_count=parse_count_text(data.get("comment_text")),
        collect_count=parse_count_text(data.get("collect_text")),
        share_count=parse_count_text(data.get("share_text")),
        play_count=None,
        tags=extract_tags_from_title(title),
        source_kind="dom",
        source_api_url="dom://video-page",
        raw=data,
    )


def merge_details(
    candidates: list[DetailVideo],
    target_aweme_id: str,
    page_url: str,
) -> DetailVideo | None:
    candidates = [x for x in candidates if x is not None]
    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (source_priority(x.source_api_url), completeness_score(x)),
        reverse=True,
    )
    primary = candidates[0]

    def is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    merged = DetailVideo(
        aweme_id=target_aweme_id,
        desc=primary.desc,
        create_time=primary.create_time,
        author_id=primary.author_id,
        author_name=primary.author_name,
        author_sec_uid=primary.author_sec_uid,
        author_unique_id=primary.author_unique_id,
        cover_url=primary.cover_url,
        video_url=primary.video_url or page_url,
        duration=primary.duration,
        height=primary.height,
        width=primary.width,
        digg_count=primary.digg_count,
        comment_count=primary.comment_count,
        collect_count=primary.collect_count,
        share_count=primary.share_count,
        play_count=primary.play_count,
        tags=list(primary.tags),
        source_kind=primary.source_kind,
        source_api_url=primary.source_api_url,
        raw=primary.raw,
    )

    for cand in candidates[1:]:
        if is_missing(merged.desc) and not is_missing(cand.desc):
            merged.desc = cand.desc
        if merged.create_time is None and cand.create_time is not None:
            merged.create_time = cand.create_time
        if is_missing(merged.author_id) and not is_missing(cand.author_id):
            merged.author_id = cand.author_id
        if is_missing(merged.author_name) and not is_missing(cand.author_name):
            merged.author_name = cand.author_name
        if is_missing(merged.author_sec_uid) and not is_missing(cand.author_sec_uid):
            merged.author_sec_uid = cand.author_sec_uid
        if is_missing(merged.author_unique_id) and not is_missing(cand.author_unique_id):
            merged.author_unique_id = cand.author_unique_id
        if is_missing(merged.cover_url) and not is_missing(cand.cover_url):
            merged.cover_url = cand.cover_url
        if is_missing(merged.video_url) and not is_missing(cand.video_url):
            merged.video_url = cand.video_url
        if merged.duration is None and cand.duration is not None:
            merged.duration = cand.duration
        if merged.height is None and cand.height is not None:
            merged.height = cand.height
        if merged.width is None and cand.width is not None:
            merged.width = cand.width
        if merged.digg_count is None and cand.digg_count is not None:
            merged.digg_count = cand.digg_count
        if merged.comment_count is None and cand.comment_count is not None:
            merged.comment_count = cand.comment_count
        if merged.collect_count is None and cand.collect_count is not None:
            merged.collect_count = cand.collect_count
        if merged.share_count is None and cand.share_count is not None:
            merged.share_count = cand.share_count
        if merged.play_count is None and cand.play_count is not None:
            merged.play_count = cand.play_count
        for tag, tag_type in cand.tags:
            if (tag, tag_type) not in merged.tags:
                merged.tags.append((tag, tag_type))

    merged.raw = {
        "target_aweme_id": target_aweme_id,
        "merged_sources": [
            {
                "source_kind": c.source_kind,
                "source_api_url": c.source_api_url,
                "aweme_id": c.aweme_id,
                "score": completeness_score(c),
            }
            for c in candidates
        ],
        "primary_raw": primary.raw,
    }
    return merged


def upsert_video(conn: sqlite3.Connection, video: DetailVideo, seen_at: str) -> None:
    conn.execute(
        """
        INSERT INTO videos(
          aweme_id, "desc", create_time, author_id, author_name, author_sec_uid, author_unique_id,
          cover_url, video_url, duration, height, width, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(aweme_id) DO UPDATE SET
          "desc" = COALESCE(excluded."desc", videos."desc"),
          create_time = COALESCE(excluded.create_time, videos.create_time),
          author_id = COALESCE(excluded.author_id, videos.author_id),
          author_name = COALESCE(excluded.author_name, videos.author_name),
          author_sec_uid = COALESCE(excluded.author_sec_uid, videos.author_sec_uid),
          author_unique_id = COALESCE(excluded.author_unique_id, videos.author_unique_id),
          cover_url = COALESCE(excluded.cover_url, videos.cover_url),
          video_url = COALESCE(excluded.video_url, videos.video_url),
          duration = COALESCE(excluded.duration, videos.duration),
          height = COALESCE(excluded.height, videos.height),
          width = COALESCE(excluded.width, videos.width),
          last_seen_at = excluded.last_seen_at
        """,
        (
            video.aweme_id,
            video.desc,
            video.create_time,
            video.author_id,
            video.author_name,
            video.author_sec_uid,
            video.author_unique_id,
            video.cover_url,
            video.video_url,
            video.duration,
            video.height,
            video.width,
            seen_at,
            seen_at,
        ),
    )


def upsert_video_tags(conn: sqlite3.Connection, aweme_id: str, tags: list[tuple[str, str]], captured_at: str) -> int:
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


def insert_video_detail_snapshot(
    conn: sqlite3.Connection,
    run_id: str,
    video: DetailVideo,
    captured_at: str,
    page_url: str,
) -> None:
    conn.execute(
        """
        INSERT INTO video_detail_snapshots(
          run_id, aweme_id, source_kind, source_api_url, page_url,
          digg_count, comment_count, collect_count, share_count, play_count, captured_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            video.aweme_id,
            video.source_kind,
            video.source_api_url,
            page_url,
            video.digg_count,
            video.comment_count,
            video.collect_count,
            video.share_count,
            video.play_count,
            captured_at,
            json.dumps(video.raw, ensure_ascii=False),
        ),
    )


def update_run_status(
    conn: sqlite3.Connection, run_id: str, status: str, message: str | None = None
) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, message = ?, ended_at = ? WHERE run_id = ?",
        (status, message, utc_now_iso(), run_id),
    )
    conn.commit()


def get_latest_home_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT run_id
        FROM runs
        WHERE source = 'douyin_home_feed_crawler' AND status = 'success'
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError("no successful douyin_home_feed_crawler run found")
    return str(row["run_id"])


def load_targets(conn: sqlite3.Connection, args: argparse.Namespace) -> tuple[str, list[TargetVideo]]:
    origin = ""
    ids: list[str] = []

    if args.aweme_id:
        origin = "manual_aweme_id"
        seen: set[str] = set()
        for aweme in args.aweme_id:
            aw = str(aweme).strip()
            if not aw or aw in seen:
                continue
            seen.add(aw)
            ids.append(aw)
    else:
        run_id: str | None = None
        if args.from_home_run_id:
            run_id = args.from_home_run_id
        elif args.latest_home_run:
            run_id = get_latest_home_run_id(conn)

        if run_id:
            origin = f"home_run_id={run_id}"
            rows = conn.execute(
                """
                SELECT aweme_id, MIN(round_num) AS first_round, MIN(rank_in_round) AS first_rank
                FROM home_feed_snapshots
                WHERE run_id = ?
                GROUP BY aweme_id
                ORDER BY first_round ASC, first_rank ASC
                """,
                (run_id,),
            ).fetchall()
            ids = [str(row["aweme_id"]) for row in rows]
        else:
            origin = "videos_table"
            rows = conn.execute(
                """
                SELECT aweme_id
                FROM videos
                ORDER BY last_seen_at DESC
                """
            ).fetchall()
            ids = [str(row["aweme_id"]) for row in rows]

    if not ids:
        return origin, []

    enriched_ids: set[str] = set()
    if not args.force:
        rows = conn.execute("SELECT DISTINCT aweme_id FROM video_detail_snapshots").fetchall()
        enriched_ids = {str(row["aweme_id"]) for row in rows}

    targets: list[TargetVideo] = []
    for aweme_id in ids:
        if not aweme_id:
            continue
        if (not args.force) and (aweme_id in enriched_ids):
            continue

        if args.only_missing_meta:
            row = conn.execute(
                'SELECT "desc", author_name FROM videos WHERE aweme_id = ?',
                (aweme_id,),
            ).fetchone()
            if row:
                desc = row["desc"]
                author_name = row["author_name"]
                desc_ok = isinstance(desc, str) and desc.strip()
                author_ok = isinstance(author_name, str) and author_name.strip()
                if desc_ok and author_ok:
                    continue

        targets.append(TargetVideo(aweme_id=aweme_id, page_url=f"https://www.douyin.com/video/{aweme_id}"))
        if len(targets) >= args.limit:
            break

    return origin, targets


def dump_debug_payloads(
    debug_dump_dir: Path,
    run_id: str,
    seq_num: int,
    target: TargetVideo,
    page_state: dict[str, Any],
    payloads: list[tuple[str, Any]],
) -> None:
    debug_dump_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for url, payload in payloads[:150]:
        if isinstance(payload, dict):
            top_keys = list(payload.keys())[:20]
        elif isinstance(payload, list):
            top_keys = [f"list_len={len(payload)}"]
        else:
            top_keys = [type(payload).__name__]
        nodes: list[dict[str, Any]] = []
        collect_aweme_nodes(payload, nodes)
        records.append(
            {
                "url": url,
                "is_candidate_url": is_candidate_detail_response_url(url),
                "aweme_node_count": len(nodes),
                "top_keys": top_keys,
            }
        )

    path = debug_dump_dir / f"{run_id}_{seq_num:04d}_{target.aweme_id}.json"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "seq_num": seq_num,
                "target_aweme_id": target.aweme_id,
                "target_page_url": target.page_url,
                "page_state": page_state,
                "payload_count": len(payloads),
                "payloads": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def resolve_results_output_path(args: argparse.Namespace, run_id: str) -> Path | None:
    if args.no_dump_results:
        return None
    if args.dump_results_json:
        return Path(args.dump_results_json).expanduser()
    dump_dir = str(args.dump_results_dir or "").strip()
    if not dump_dir:
        return None
    return Path(dump_dir).expanduser() / f"{run_id}.json"


def build_result_record(
    seq_num: int,
    target: TargetVideo,
    merged: DetailVideo,
    captured_at: str,
    page_state: dict[str, Any],
    payload_count: int,
) -> dict[str, Any]:
    return {
        "seq_num": seq_num,
        "target_aweme_id": target.aweme_id,
        "target_page_url": target.page_url,
        "aweme_id": merged.aweme_id,
        "page_url": str(page_state.get("page_url") or target.page_url),
        "title": merged.desc,
        "author_name": merged.author_name,
        "author_id": merged.author_id,
        "author_sec_uid": merged.author_sec_uid,
        "author_unique_id": merged.author_unique_id,
        "video_url": merged.video_url,
        "cover_url": merged.cover_url,
        "create_time": merged.create_time,
        "duration": merged.duration,
        "width": merged.width,
        "height": merged.height,
        "digg_count": merged.digg_count,
        "comment_count": merged.comment_count,
        "collect_count": merged.collect_count,
        "share_count": merged.share_count,
        "play_count": merged.play_count,
        "source_kind": merged.source_kind,
        "source_api_url": merged.source_api_url,
        "payload_count": payload_count,
        "login_detected": bool(page_state.get("login_detected")),
        "captcha_detected": bool(page_state.get("captcha_detected")),
        "captured_at": captured_at,
        "tags": [{"tag": tag, "tag_type": tag_type} for tag, tag_type in merged.tags],
    }


def dump_result_json(
    output_path: Path,
    run_id: str,
    origin: str,
    total_targets: int,
    success_count: int,
    failed_count: int,
    stopped_by_user: bool,
    rows: list[dict[str, Any]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "source": "douyin_video_detail_enricher",
                "generated_at": utc_now_iso(),
                "target_origin": origin,
                "target_count": total_targets,
                "success_count": success_count,
                "failed_count": failed_count,
                "stopped_by_user": int(stopped_by_user),
                "records": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    db_path = Path(args.db).expanduser()
    conn = ensure_db(db_path)

    origin, targets = load_targets(conn, args)
    if not targets:
        raise RuntimeError("no target videos selected. Try --force or disable --only-missing-meta.")

    run_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO runs(run_id, source, started_at, status, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "douyin_video_detail_enricher",
            utc_now_iso(),
            "running",
            f"target_origin={origin}, target_count={len(targets)}",
        ),
    )
    conn.commit()

    success_count = 0
    failed_count = 0
    total_tags = 0
    source_network = 0
    source_render = 0
    source_dom = 0
    login_pages = 0
    captcha_pages = 0
    stopped_by_user = False
    result_rows: list[dict[str, Any]] = []
    result_output_path = resolve_results_output_path(args, run_id)

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
                    "headful mode requires an X server. "
                    "Use headless mode on servers: remove --headful. "
                    "If needed, run with virtual display: xvfb-run -a python ..."
                ) from exc
            raise

        if args.stealth:
            context.add_init_script(stealth_script())
            context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

        page = context.pages[0] if context.pages else context.new_page()

        for idx, target in enumerate(targets, start=1):
            payloads: list[tuple[str, Any]] = []

            def on_response(resp: Any) -> None:
                url = resp.url
                lower_url = url.lower()
                try:
                    content_type = resp.headers.get("content-type", "").lower()
                except Exception:
                    content_type = ""

                if not is_candidate_detail_response_url(url):
                    if "json" not in content_type:
                        return
                    if not any(host in lower_url for host in ("douyin.com", "zijieapi.com", "snssdk.com")):
                        return

                payload = extract_response_payload(resp)
                if payload is None:
                    return
                payloads.append((url, payload))

            page.on("response", on_response)
            try:
                page.goto(target.page_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                page.wait_for_timeout(int(args.wait_seconds * 1000))
                dismiss_common_popups(page)
                page.mouse.click(720, 420)
                if args.scroll_pixels != 0:
                    page.mouse.wheel(0, args.scroll_pixels)
                    page.wait_for_timeout(int(args.wait_seconds * 1000))

                page_state = inspect_page_state(page)
                if bool(page_state.get("login_detected")):
                    login_pages += 1
                if bool(page_state.get("captcha_detected")):
                    captcha_pages += 1

                network = extract_from_payloads(
                    payloads=payloads,
                    target_aweme_id=target.aweme_id,
                    max_payload_scan=args.max_payload_scan,
                )
                render = extract_from_render_data(page, target.aweme_id)
                dom = extract_from_dom(page, target.aweme_id, target.page_url)
                merged = merge_details([network, render, dom], target_aweme_id=target.aweme_id, page_url=target.page_url)

                if args.debug_dump_dir:
                    dump_debug_payloads(
                        debug_dump_dir=Path(args.debug_dump_dir).expanduser(),
                        run_id=run_id,
                        seq_num=idx,
                        target=target,
                        page_state=page_state,
                        payloads=payloads,
                    )

                if merged is None:
                    failed_count += 1
                    print(
                        f"[{idx}/{len(targets)}] aweme={target.aweme_id} status=failed "
                        f"reason=no_metadata payloads={len(payloads)}"
                    )
                    continue

                captured_at = utc_now_iso()
                upsert_video(conn, merged, seen_at=captured_at)
                insert_video_detail_snapshot(
                    conn=conn,
                    run_id=run_id,
                    video=merged,
                    captured_at=captured_at,
                    page_url=str(page_state.get("page_url") or page.url),
                )
                total_tags += upsert_video_tags(
                    conn=conn,
                    aweme_id=merged.aweme_id,
                    tags=merged.tags,
                    captured_at=captured_at,
                )
                conn.commit()
                result_rows.append(
                    build_result_record(
                        seq_num=idx,
                        target=target,
                        merged=merged,
                        captured_at=captured_at,
                        page_state=page_state,
                        payload_count=len(payloads),
                    )
                )

                success_count += 1
                if merged.source_kind == "network_aweme":
                    source_network += 1
                elif merged.source_kind == "render_data":
                    source_render += 1
                else:
                    source_dom += 1

                has_desc = int(bool(merged.desc))
                has_stats = int(
                    any(
                        x is not None
                        for x in (
                            merged.digg_count,
                            merged.comment_count,
                            merged.collect_count,
                            merged.share_count,
                            merged.play_count,
                        )
                    )
                )
                print(
                    f"[{idx}/{len(targets)}] aweme={target.aweme_id} status=ok "
                    f"source={merged.source_kind} payloads={len(payloads)} desc={has_desc} "
                    f"stats={has_stats} tags={len(merged.tags)} "
                    f"login={int(bool(page_state.get('login_detected')))} "
                    f"captcha={int(bool(page_state.get('captcha_detected')))}"
                )
            except Exception as exc:
                failed_count += 1
                conn.rollback()
                print(f"[{idx}/{len(targets)}] aweme={target.aweme_id} status=error reason={exc}")
            finally:
                page.remove_listener("response", on_response)

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

        message = (
            f"targets={len(targets)}, success={success_count}, failed={failed_count}, "
            f"tags={total_tags}, source_network={source_network}, source_render={source_render}, "
            f"source_dom={source_dom}, login_pages={login_pages}, captcha_pages={captcha_pages}, "
            f"stopped_by_user={int(stopped_by_user)}"
        )
        if result_output_path is not None:
            dump_result_json(
                output_path=result_output_path,
                run_id=run_id,
                origin=origin,
                total_targets=len(targets),
                success_count=success_count,
                failed_count=failed_count,
                stopped_by_user=stopped_by_user,
                rows=result_rows,
            )
        row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row and row["status"] == "running":
            update_run_status(conn, run_id, "success", message=message)
            print(f"video detail enricher success: run_id={run_id}, {message}, db={db_path}")
            if result_output_path is not None:
                print(f"video detail result json: {result_output_path}")
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich Douyin video metadata from video URLs.")
    parser.add_argument("--db", default="data/douyin_hot.db", help="SQLite database path.")
    parser.add_argument(
        "--user-data-dir",
        default="data/browser_profile",
        help="Persistent browser profile dir for session reuse.",
    )
    parser.add_argument("--aweme-id", action="append", help="Specific aweme_id to enrich (can repeat).")
    parser.add_argument(
        "--from-home-run-id",
        default=None,
        help="Read targets from a specific home_feed run_id.",
    )
    parser.add_argument(
        "--latest-home-run",
        action="store_true",
        help="Read targets from latest successful home_feed run (default unless --aweme-id is set).",
    )
    parser.add_argument(
        "--only-missing-meta",
        dest="only_missing_meta",
        action="store_true",
        help='Only select videos whose "desc" or author_name is empty (default).',
    )
    parser.add_argument(
        "--no-only-missing-meta",
        dest="only_missing_meta",
        action="store_false",
        help='Select videos regardless of current "desc"/author_name completeness.',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Include videos that were already enriched before.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Max number of target videos.")
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=3.5,
        help="Wait time after page load (seconds).",
    )
    parser.add_argument(
        "--scroll-pixels",
        type=int,
        default=1000,
        help="Optional single scroll distance per video page.",
    )
    parser.add_argument(
        "--max-payload-scan",
        type=int,
        default=120,
        help="Max response payloads to scan per page.",
    )
    parser.add_argument(
        "--debug-dump-dir",
        default=None,
        help="Optional directory to dump per-video payload diagnostics.",
    )
    parser.add_argument(
        "--dump-results-json",
        default=None,
        help="Optional file path to export parsed result JSON for this run.",
    )
    parser.add_argument(
        "--dump-results-dir",
        default="data/raw/video_detail_results",
        help="Directory for auto result JSON (default: data/raw/video_detail_results).",
    )
    parser.add_argument(
        "--no-dump-results",
        action="store_true",
        help="Disable result JSON export.",
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Enable basic anti-automation fingerprint masking (default).",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help="Browser user-agent for requests.",
    )
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Page timeout in milliseconds.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default).")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode.")
    parser.set_defaults(headless=True, stealth=True, latest_home_run=True, only_missing_meta=True)
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
    if args.limit <= 0:
        raise ValueError("--limit must be > 0")
    if args.max_payload_scan <= 0:
        raise ValueError("--max-payload-scan must be > 0")
    if args.aweme_id:
        # Explicit ids should not be constrained by latest_home_run.
        args.latest_home_run = False
        args.only_missing_meta = False
    run_collection(args)


if __name__ == "__main__":
    main()
