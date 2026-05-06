"""
Media Service — 业务编排层。

职责：
  - 接收 route 传来的请求 schema
  - 调用 MediaProvider（解析 / 下载 / CRUD）
  - 将 domain 对象转换为 HTTP 响应 schema
  - 处理业务规则（如 downloadable 校验、media_id 存在性校验）
  - 不感知 HTTP、不感知 request_id
"""
from __future__ import annotations

from app.domain.models import ResolvedMediaRef, StoredMedia
from app.infra.exceptions import NotFoundError
from app.providers.base import MediaProvider
from app.schemas.media import (
    CleanupCandidate,
    CleanupData,
    CleanupRequest,
    DeleteMediaData,
    FetchedVideoData,
    FetchVideoRequest,
    ResolvedVideoData,
    ResolveVideoRequest,
)


class MediaService:
    def __init__(self, provider: MediaProvider) -> None:
        self._p = provider

    # ------------------------------------------------------------------
    # POST /media/resolve_video
    # ------------------------------------------------------------------

    async def resolve_video(self, req: ResolveVideoRequest) -> ResolvedVideoData:
        ref = req.source_ref
        resolved: ResolvedMediaRef = await self._p.resolve_video(
            platform=ref.platform,
            aweme_id=ref.aweme_id,
            share_url=ref.share_url,
        )
        return ResolvedVideoData(
            platform=resolved.content_ref.platform,
            aweme_id=resolved.content_ref.source_id,
            share_url=resolved.content_ref.source_url,
            video_url=resolved.media_url or "",
            downloadable=resolved.downloadable,
        )

    # ------------------------------------------------------------------
    # POST /media/fetch_video
    # ------------------------------------------------------------------

    async def fetch_video(self, req: FetchVideoRequest) -> FetchedVideoData:
        ref = req.resolved_video_ref

        # 重建 domain ResolvedMediaRef，供 provider 使用
        from app.domain.models import ContentRef, ResolvedMediaRef as RMR

        content_ref = ContentRef(
            platform=ref.platform,   # type: ignore[arg-type]
            source_type="video",
            source_id=ref.aweme_id,
            source_url=ref.share_url,
        )
        resolved = RMR(
            content_ref=content_ref,
            media_type="video",
            media_url=ref.video_url,
            downloadable=ref.downloadable,
            mime_type="video/mp4",
        )

        stored: StoredMedia = await self._p.fetch_video(resolved)
        return _stored_to_fetched(stored)

    # ------------------------------------------------------------------
    # DELETE /media/{media_id}
    # ------------------------------------------------------------------

    async def delete_media(self, media_id: str) -> DeleteMediaData:
        existing = await self._p.get_media(media_id)
        if existing is None:
            raise NotFoundError(f"media_id '{media_id}' not found")

        deleted_record, deleted_local, deleted_object = await self._p.delete_media(media_id)
        return DeleteMediaData(
            media_id=media_id,
            deleted=deleted_record,
            deleted_local_file=deleted_local,
            deleted_object_file=deleted_object,
        )

    # ------------------------------------------------------------------
    # POST /media/cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, req: CleanupRequest) -> CleanupData:
        candidates: list[StoredMedia] = await self._p.list_for_cleanup(
            older_than_days=req.older_than_days,
            only_unreferenced=req.only_unreferenced,
            limit=req.limit,
        )

        deleted_count = 0

        if not req.dry_run:
            results = await self._p.delete_bulk([m.media_id for m in candidates])
            deleted_count = sum(1 for v in results.values() if v[0])

        return CleanupData(
            dry_run=req.dry_run,
            matched_count=len(candidates),
            deleted_count=deleted_count,
            candidates=[
                CleanupCandidate(
                    media_id=m.media_id,
                    local_video_path=m.storage.local_path,
                    size_bytes=m.file_size_bytes,
                )
                for m in candidates
            ],
        )


# ---------------------------------------------------------------------------
# 私有转换函数
# ---------------------------------------------------------------------------


def _stored_to_fetched(stored: StoredMedia) -> FetchedVideoData:
    return FetchedVideoData(
        media_id=stored.media_id,
        platform=stored.content_ref.platform,
        aweme_id=stored.content_ref.source_id,
        share_url=stored.content_ref.source_url,
        local_video_path=stored.storage.local_path,
        object_url=stored.storage.object_url,
        duration_sec=stored.duration_sec,
    )
