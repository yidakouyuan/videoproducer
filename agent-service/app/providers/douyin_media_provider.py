"""
真实抖音媒体 Provider。

resolve_video：
  解析分享链接 → ABogus 签名 → 抖音 Web API → 无水印 CDN URL

fetch_video：
  流式下载 CDN 视频 → 本地文件（VIDEO_DATA_DIR）
  → object_url 由 FastAPI StaticFiles 服务提供

环境变量：
  DOUYIN_COOKIE_FILE   Cookie 文件路径（默认 config/douyin_cookies.txt）
  VIDEO_DATA_DIR       本地视频存储目录（默认 /disk3/yuhang/openclaw_agent/data/videos）
  SERVER_BASE_URL      服务基础 URL，用于生成 object_url（默认 http://localhost:8000）
"""
from __future__ import annotations

import base64
import os
import re
import time
import uuid
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from mutagen.mp4 import MP4, MP4StreamInfoError

from app.domain.models import ContentRef, ResolvedMediaRef, StorageInfo, StoredMedia
from app.infra.exceptions import InvalidInputError, NotFoundError, ProviderError
from app.providers.abogus import ABogus

# ---------------------------------------------------------------------------
# 配置（均可通过环境变量覆盖）
# ---------------------------------------------------------------------------

_ENV_COOKIE_FILE = "DOUYIN_COOKIE_FILE"
_DEFAULT_COOKIE_FILE = "config/douyin_cookies.txt"

_ENV_DATA_DIR = "VIDEO_DATA_DIR"
_DEFAULT_DATA_DIR = "c:/openclaw_agent/data/videos"

_ENV_BASE_URL = "SERVER_BASE_URL"
_DEFAULT_BASE_URL = "http://localhost:8000"

_API_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_online": "true",
    "engine_name": "Blink",
    "os_name": "Windows",
    "os_version": "10",
    "platform": "PC",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_version": "90.0.4430.212",
    "engine_version": "90.0.4430.212",
    "cpu_core_num": "8",
    "device_memory": "8",
}

_AWEME_ID_RE = re.compile(r"\d{15,20}")

# 进程内 StoredMedia 索引（media_id → StoredMedia）
_store: dict[str, StoredMedia] = {}
_created_at: dict[str, float] = {}

# ---------------------------------------------------------------------------
# URL 解析工具
# ---------------------------------------------------------------------------


def _extract_aweme_id(url: str) -> Optional[str]:
    m = re.search(r"/video/(\d{15,20})", url)
    if m:
        return m.group(1)
    qs = parse_qs(urlparse(url).query)
    modal_id = qs.get("modal_id", [None])[0]
    if modal_id and _AWEME_ID_RE.fullmatch(modal_id):
        return modal_id
    return None


def _extract_url_from_text(text: str) -> Optional[str]:
    m = re.search(r"https?://(?:v\.douyin\.com|(?:www\.)?douyin\.com)/\S+", text)
    return m.group(0) if m else None


async def _follow_short_link(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "SamsungBrowser/14.0 Chrome/87.0.4280.141 Mobile Safari/537.36"
        )
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        r = await client.get(url, headers=headers)
        return str(r.url)


# ---------------------------------------------------------------------------
# Cookie 文件
# ---------------------------------------------------------------------------


def _load_cookies(cookie_file: str) -> dict[str, str]:
    if not os.path.exists(cookie_file):
        raise ProviderError(
            f"Cookie 文件不存在：{cookie_file}。\n"
            "请用 Chrome 插件 'Get cookies.txt LOCALLY' 在 douyin.com 导出，"
            f"上传到 {cookie_file}。"
        )
    cookies: dict[str, str] = {}
    with open(cookie_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5]:
                cookies[parts[5]] = parts[6]
    return cookies


# ---------------------------------------------------------------------------
# 抖音 Web API
# ---------------------------------------------------------------------------


def _gen_ms_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(96)).decode().rstrip("=")[:128]


async def _fetch_aweme_detail(aweme_id: str, cookies: dict[str, str]) -> dict:
    ms_token = _gen_ms_token()
    cookies = {**cookies, "msToken": ms_token}
    params = {**_BASE_PARAMS, "aweme_id": aweme_id, "msToken": ms_token}
    params["a_bogus"] = ABogus().get_value(params)

    headers = {
        "User-Agent": ABogus.UA,
        "Referer": f"https://www.douyin.com/video/{aweme_id}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    async with httpx.AsyncClient(headers=headers, cookies=cookies, timeout=15) as client:
        r = await client.get(_API_URL, params=params)

    if not r.content:
        raise ProviderError("抖音 API 返回空响应，Cookie 可能已过期，请重新导出 cookies.txt。")
    try:
        data = r.json()
    except Exception as e:
        raise ProviderError(f"抖音 API 返回非 JSON 响应：{e}")

    detail = data.get("aweme_detail")
    if not detail:
        raise NotFoundError(f"视频不存在或已被删除：aweme_id={aweme_id}")

    returned_id = str(detail.get("aweme_id", ""))
    if returned_id and returned_id != aweme_id:
        raise NotFoundError(
            f"视频不存在：请求 {aweme_id}，API 返回不同视频 {returned_id}"
        )
    return detail


def _pick_video_url(detail: dict) -> str:
    video = detail.get("video", {})
    for field in ("download_addr", "play_addr"):
        urls = video.get(field, {}).get("url_list", [])
        if urls:
            return urls[0]
    raise ProviderError("API 未返回可用的播放 URL。")


# ---------------------------------------------------------------------------
# 视频时长提取
# ---------------------------------------------------------------------------


def _get_duration(local_path: str) -> Optional[float]:
    """用 mutagen 从 MP4 文件读取时长（秒）。文件损坏时返回 None。"""
    try:
        audio = MP4(local_path)
        return round(audio.info.length, 2)
    except (MP4StreamInfoError, Exception):
        return None


# ---------------------------------------------------------------------------
# DouyinMediaProvider
# ---------------------------------------------------------------------------


class DouyinMediaProvider:
    """
    真实抖音媒体 Provider。

    resolve_video — 抖音 Web API + A-Bogus 签名，返回无水印 CDN URL。
    fetch_video   — 流式下载到本地，由 FastAPI StaticFiles 提供 object_url。
    CRUD 操作     — 基于进程内 _store 字典（重启后清空，生产环境替换为 DB）。
    """

    def __init__(self, cookie_file: Optional[str] = None) -> None:
        self._cookie_file = (
            cookie_file
            or os.environ.get(_ENV_COOKIE_FILE)
            or _DEFAULT_COOKIE_FILE
        )
        self._data_dir = os.environ.get(_ENV_DATA_DIR) or _DEFAULT_DATA_DIR
        self._base_url = (os.environ.get(_ENV_BASE_URL) or _DEFAULT_BASE_URL).rstrip("/")
        os.makedirs(self._data_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # resolve_video
    # ------------------------------------------------------------------

    async def resolve_video(
        self,
        platform: str,
        aweme_id: str,
        share_url: str,
    ) -> ResolvedMediaRef:
        working_url = share_url
        if not working_url.startswith("http"):
            extracted = _extract_url_from_text(working_url)
            working_url = extracted or f"https://www.douyin.com/video/{aweme_id}"

        if "v.douyin.com" in working_url:
            working_url = await _follow_short_link(working_url)

        final_aweme_id = _extract_aweme_id(working_url) or aweme_id
        cookies = _load_cookies(self._cookie_file)
        detail = await _fetch_aweme_detail(final_aweme_id, cookies)
        video_url = _pick_video_url(detail)

        content_ref = ContentRef(
            platform=platform,  # type: ignore[arg-type]
            source_type="video",
            source_id=final_aweme_id,
            source_url=share_url,
        )
        return ResolvedMediaRef(
            content_ref=content_ref,
            media_type="video",
            media_url=video_url,
            downloadable=True,
            mime_type="video/mp4",
        )

    # ------------------------------------------------------------------
    # fetch_video（真实下载）
    # ------------------------------------------------------------------

    async def fetch_video(self, resolved: ResolvedMediaRef) -> StoredMedia:
        """
        流式下载 CDN 视频到本地，生成 media_id 和 object_url。

        下载时使用 Referer + User-Agent，确保抖音 CDN 不拒绝请求。
        """
        if not resolved.downloadable:
            raise InvalidInputError("video is not downloadable; cannot fetch")
        if not resolved.media_url:
            raise InvalidInputError("resolved.media_url is empty")

        media_id = f"md_{uuid.uuid4().hex[:12]}"
        local_path = os.path.join(self._data_dir, f"{media_id}.mp4")
        object_url = f"{self._base_url}/videos/{media_id}.mp4"

        headers = {
            "User-Agent": ABogus.UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "*/*",
        }

        # 流式下载，避免将整个视频载入内存
        try:
            async with httpx.AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(connect=10, read=300, write=60, pool=10),
            ) as client:
                async with client.stream("GET", resolved.media_url) as r:
                    if r.status_code != 200:
                        raise ProviderError(
                            f"CDN 下载失败，HTTP {r.status_code}：{resolved.media_url[:80]}"
                        )
                    with open(local_path, "wb") as f:
                        async for chunk in r.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
        except ProviderError:
            raise
        except Exception as e:
            # 下载失败时清理残留文件
            if os.path.exists(local_path):
                os.remove(local_path)
            raise ProviderError(f"视频下载失败：{e}")

        file_size = os.path.getsize(local_path)
        duration = _get_duration(local_path)

        stored = StoredMedia(
            media_id=media_id,
            content_ref=resolved.content_ref,
            media_type="video",
            storage=StorageInfo(
                local_path=local_path,
                object_url=object_url,
            ),
            duration_sec=duration,
            mime_type="video/mp4",
            file_size_bytes=file_size,
        )
        _store[media_id] = stored
        _created_at[media_id] = time.time()
        return stored

    # ------------------------------------------------------------------
    # CRUD（基于进程内 _store）
    # ------------------------------------------------------------------

    async def get_media(self, media_id: str) -> Optional[StoredMedia]:
        return _store.get(media_id)

    async def delete_media(self, media_id: str) -> tuple[bool, bool, bool]:
        stored = _store.pop(media_id, None)
        _created_at.pop(media_id, None)
        if stored is None:
            return (False, False, False)

        deleted_local = False
        if stored.storage.local_path and os.path.exists(stored.storage.local_path):
            try:
                os.remove(stored.storage.local_path)
                deleted_local = True
            except OSError:
                pass

        # object_url 由 StaticFiles 提供，无单独文件需删除
        return (True, deleted_local, False)

    async def list_for_cleanup(
        self,
        older_than_days: Optional[int],
        only_unreferenced: bool,
        limit: int,
    ) -> list[StoredMedia]:
        now = time.time()
        results: list[StoredMedia] = []
        for media_id, stored in _store.items():
            if older_than_days is not None:
                age = (now - _created_at.get(media_id, now)) / 86400
                if age < older_than_days:
                    continue
            results.append(stored)
            if len(results) >= limit:
                break
        return results

    async def delete_bulk(
        self, media_ids: list[str]
    ) -> dict[str, tuple[bool, bool, bool]]:
        return {mid: await self.delete_media(mid) for mid in media_ids}
