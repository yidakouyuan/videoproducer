"""
Mock Media Provider。

内存存储（进程重启后清空），供开发 / 测试使用。

Mock 行为说明：
  resolve_video  : 任意合法 aweme_id 均返回 mock video_url，downloadable=True
  fetch_video    : 生成 media_id（md_<hex>），写入内存 store，伪造 local_path / object_url
  get_media      : 从内存 store 查询
  delete_media   : 从内存 store 删除，返回 (True, has_local, has_object)
  list_for_cleanup: 按 older_than_days / limit 过滤内存 store（忽略 only_unreferenced，视全部为未引用）
  delete_bulk    : 逐条调用 delete_media

替换成真实实现时：
  - 新建 app/providers/douyin_media_provider.py（resolve + fetch）
  - 新建 app/providers/db_media_repository.py（CRUD）
  - 在 routes/media.py 的 get_media_provider() 里换实例
  - 本文件保留，供测试环境使用
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from app.domain.models import (
    ContentRef,
    ResolvedMediaRef,
    StorageInfo,
    StoredMedia,
)
from app.infra.exceptions import InvalidInputError, NotFoundError

# ---------------------------------------------------------------------------
# 进程内内存存储
# ---------------------------------------------------------------------------

_store: dict[str, StoredMedia] = {}
_created_at: dict[str, float] = {}   # media_id → unix timestamp（秒）

# ---------------------------------------------------------------------------
# Mock Provider 实现
# ---------------------------------------------------------------------------


class MockMediaProvider:
    """结构严格对齐 MediaProvider Protocol。"""

    # ------------------------------------------------------------------
    # resolve_video
    # ------------------------------------------------------------------

    async def resolve_video(
        self,
        platform: str,
        aweme_id: str,
        share_url: str,
    ) -> ResolvedMediaRef:
        content_ref = ContentRef(
            platform=platform,          # type: ignore[arg-type]
            source_type="video",
            source_id=aweme_id,
            source_url=share_url,
        )
        # Mock：构造假的 CDN 地址
        mock_video_url = (
            f"https://mock-cdn.example.com/douyin/{aweme_id}/v720p.mp4"
        )
        return ResolvedMediaRef(
            content_ref=content_ref,
            media_type="video",
            media_url=mock_video_url,
            downloadable=True,
            mime_type="video/mp4",
        )

    # ------------------------------------------------------------------
    # fetch_video
    # ------------------------------------------------------------------

    async def fetch_video(self, resolved: ResolvedMediaRef) -> StoredMedia:
        if not resolved.downloadable:
            raise InvalidInputError(
                "video is not downloadable; cannot fetch"
            )

        media_id = f"md_{uuid.uuid4().hex[:12]}"
        aweme_id = resolved.content_ref.source_id
        local_path = f"/data/videos/{media_id}.mp4"
        object_url = f"https://storage.example.com/videos/{media_id}.mp4"
        mock_duration = round(15.0 + (hash(aweme_id) % 100) * 0.5, 1)  # 15~65 秒
        mock_size = int(mock_duration * 1_500_000)                        # ~1.5 MB/s

        stored = StoredMedia(
            media_id=media_id,
            content_ref=resolved.content_ref,
            media_type="video",
            storage=StorageInfo(
                local_path=local_path,
                object_url=object_url,
            ),
            duration_sec=mock_duration,
            mime_type="video/mp4",
            file_size_bytes=mock_size,
        )

        _store[media_id] = stored
        _created_at[media_id] = time.time()
        return stored

    # ------------------------------------------------------------------
    # get_media
    # ------------------------------------------------------------------

    async def get_media(self, media_id: str) -> Optional[StoredMedia]:
        return _store.get(media_id)

    # ------------------------------------------------------------------
    # delete_media
    # ------------------------------------------------------------------

    async def delete_media(
        self, media_id: str
    ) -> tuple[bool, bool, bool]:
        stored = _store.pop(media_id, None)
        _created_at.pop(media_id, None)
        if stored is None:
            return (False, False, False)
        has_local = bool(stored.storage.local_path)
        has_object = bool(stored.storage.object_url)
        return (True, has_local, has_object)

    # ------------------------------------------------------------------
    # list_for_cleanup
    # ------------------------------------------------------------------

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
                created = _created_at.get(media_id, now)
                age_days = (now - created) / 86400
                if age_days < older_than_days:
                    continue
            # Mock：只要 only_unreferenced=True 就全部视为未引用
            # 真实实现应查 job 表确认是否被引用
            results.append(stored)
            if len(results) >= limit:
                break

        return results

    # ------------------------------------------------------------------
    # delete_bulk
    # ------------------------------------------------------------------

    async def delete_bulk(
        self, media_ids: list[str]
    ) -> dict[str, tuple[bool, bool, bool]]:
        result = {}
        for media_id in media_ids:
            result[media_id] = await self.delete_media(media_id)
        return result
