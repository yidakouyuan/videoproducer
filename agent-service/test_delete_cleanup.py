"""
测试四个删除/清理接口：
  1. DELETE /transcribe/{job_id}       → GeminiTranscribeProvider.delete_transcribe
  2. DELETE /video/analyze/{job_id}    → GeminiVideoAnalysisProvider.delete_analysis
  3. DELETE /media/{media_id}          → DouyinMediaProvider.delete_media
  4. POST   /media/cleanup             → MediaService.cleanup (via provider)
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "c:/openclaw_agent")

from dotenv import load_dotenv
load_dotenv("c:/openclaw_agent/.env")

# ─── 颜色输出 ──────────────────────────────────────────────────────────────────
OK  = "\033[32m✓\033[0m"
ERR = "\033[31m✗\033[0m"
HDR = "\033[1;34m"
RST = "\033[0m"

def ok(msg):  print(f"  {OK}  {msg}")
def fail(msg): print(f"  {ERR}  {msg}"); sys.exit(1)
def hdr(msg):  print(f"\n{HDR}{'─'*60}{RST}\n{HDR}{msg}{RST}")

# ─── 1. DELETE /transcribe/{job_id} ───────────────────────────────────────────

hdr("1. DELETE /transcribe/{job_id}")

from app.providers.gemini_transcribe_provider import GeminiTranscribeProvider, _job_store as _tr_store
from app.domain.models import TranscribeJob

# 手动注入一个 job
job_id = "tr_test_delete_001"
_tr_store[job_id] = TranscribeJob(
    job_id=job_id, media_id="md_fake", provider_name="gemini",
    lang="zh", mode="highlights", status="done",
    transcript="测试内容", confidence=0.9,
)

async def test_transcribe_delete():
    p = GeminiTranscribeProvider()

    # 确认存在
    j = await p.get_transcribe_result(job_id)
    assert j is not None, "job 应存在"
    ok(f"job 存在: job_id={job_id}")

    # 删除
    deleted = await p.delete_transcribe(job_id)
    assert deleted is True, "delete 应返回 True"
    ok("delete 返回 True")

    # 确认不存在
    j2 = await p.get_transcribe_result(job_id)
    assert j2 is None, "删除后 job 应为 None"
    ok("删除后 job 不存在")

    # 重复删除 → 返回 False
    deleted2 = await p.delete_transcribe(job_id)
    assert deleted2 is False, "重复删除应返回 False"
    ok("重复删除返回 False（幂等）")

asyncio.run(test_transcribe_delete())

# ─── 2. DELETE /video/analyze/{job_id} ────────────────────────────────────────

hdr("2. DELETE /video/analyze/{job_id}")

from app.providers.gemini_video_analysis_provider import (
    GeminiVideoAnalysisProvider, _job_store as _va_store
)
from app.domain.models import VideoAnalysisJob

job_id2 = "va_test_delete_001"
_va_store[job_id2] = VideoAnalysisJob(
    job_id=job_id2, media_id="md_fake", input_url=None,
    analysis_profile="travel", lang="zh",
    output_schema_version="1.0", status="done",
)

async def test_va_delete():
    p = GeminiVideoAnalysisProvider()

    j = await p.get_analysis_result(job_id2)
    assert j is not None
    ok(f"job 存在: job_id={job_id2}")

    deleted = await p.delete_analysis(job_id2)
    assert deleted is True
    ok("delete 返回 True")

    j2 = await p.get_analysis_result(job_id2)
    assert j2 is None
    ok("删除后 job 不存在")

    deleted2 = await p.delete_analysis(job_id2)
    assert deleted2 is False
    ok("重复删除返回 False（幂等）")

asyncio.run(test_va_delete())

# ─── 3. DELETE /media/{media_id} ──────────────────────────────────────────────

hdr("3. DELETE /media/{media_id}")

import tempfile
from app.providers.douyin_media_provider import DouyinMediaProvider, _store as _media_store
from app.domain.models import StoredMedia, StorageInfo, ContentRef

# 创建一个临时 mp4 文件模拟已下载视频
tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
tmp.write(b"\x00" * 1024)  # 1KB 占位内容
tmp.close()
tmp_path = tmp.name

media_id = "md_test_delete_001"
_media_store[media_id] = StoredMedia(
    media_id=media_id,
    content_ref=ContentRef(platform="douyin", source_type="video",
                           source_id="test", source_url="https://example.com"),
    media_type="video",
    storage=StorageInfo(local_path=tmp_path, object_url="http://localhost/videos/test.mp4"),
    file_size_bytes=1024,
)

async def test_media_delete():
    p = DouyinMediaProvider()

    # 确认文件存在
    assert os.path.exists(tmp_path), "临时文件应存在"
    ok(f"本地文件存在: {tmp_path}")

    # 确认 store 有记录
    m = await p.get_media(media_id)
    assert m is not None
    ok(f"media store 有记录: media_id={media_id}")

    # 删除
    deleted, deleted_local, deleted_obj = await p.delete_media(media_id)
    assert deleted is True, "deleted 应为 True"
    assert deleted_local is True, "deleted_local 应为 True（文件存在应被删除）"
    ok(f"delete 返回 ({deleted}, {deleted_local}, {deleted_obj})")

    # 确认文件已删
    assert not os.path.exists(tmp_path), "文件应已删除"
    ok("本地文件已删除")

    # 确认 store 已清除
    m2 = await p.get_media(media_id)
    assert m2 is None
    ok("media store 记录已清除")

    # 重复删除
    d2, _, _ = await p.delete_media(media_id)
    assert d2 is False
    ok("重复删除返回 False（幂等）")

asyncio.run(test_media_delete())

# ─── 4. POST /media/cleanup ───────────────────────────────────────────────────

hdr("4. POST /media/cleanup")

from app.providers.douyin_media_provider import _created_at as _media_created_at

# 创建 3 个临时文件模拟旧视频（created_at 设为 8 天前）
tmp_files = []
old_media_ids = []
for i in range(3):
    t = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    t.write(b"\x00" * 512)
    t.close()
    mid = f"md_old_{i:03d}"
    _media_store[mid] = StoredMedia(
        media_id=mid,
        content_ref=ContentRef(platform="douyin", source_type="video",
                               source_id=f"fake_{i}", source_url="https://example.com"),
        media_type="video",
        storage=StorageInfo(local_path=t.name),
    )
    _media_created_at[mid] = time.time() - 8 * 86400  # 8 天前
    tmp_files.append(t.name)
    old_media_ids.append(mid)

# 再加一个新视频（不应被清理）
t_new = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
t_new.write(b"\x00" * 512)
t_new.close()
new_mid = "md_new_999"
_media_store[new_mid] = StoredMedia(
    media_id=new_mid,
    content_ref=ContentRef(platform="douyin", source_type="video",
                           source_id="new", source_url="https://example.com"),
    media_type="video",
    storage=StorageInfo(local_path=t_new.name),
)
_media_created_at[new_mid] = time.time()  # 刚创建

from app.services.media_service import MediaService
from app.schemas.media import CleanupRequest

async def test_cleanup():
    p = DouyinMediaProvider()
    svc = MediaService(provider=p)

    # dry_run=True：只预览，不实际删除（matched_count=3，deleted_count=0）
    req_dry = CleanupRequest(older_than_days=7, only_unreferenced=False, dry_run=True, limit=10)
    data_dry = await svc.cleanup(req_dry)
    assert data_dry.matched_count == 3, f"dry_run 应找到 3 个旧文件，实际: {data_dry.matched_count}"
    assert data_dry.deleted_count == 0, f"dry_run 不应删除，deleted_count 应为 0，实际: {data_dry.deleted_count}"
    assert all(os.path.exists(f) for f in tmp_files), "dry_run 不应删除文件"
    ok(f"dry_run 找到 {data_dry.matched_count} 个旧文件，deleted_count=0，文件未被删除")

    # dry_run=False：真实删除
    req_real = CleanupRequest(older_than_days=7, only_unreferenced=False, dry_run=False, limit=10)
    data_real = await svc.cleanup(req_real)
    assert data_real.deleted_count == 3, f"实际删除应为 3 个，实际: {data_real.deleted_count}"
    ok(f"实际删除 {data_real.deleted_count} 个旧文件")

    # 确认旧文件已删
    for f in tmp_files:
        assert not os.path.exists(f), f"旧文件应已删: {f}"
    ok("所有旧文件已从磁盘删除")

    # 确认新文件仍在
    assert os.path.exists(t_new.name), "新文件不应被删"
    m_new = await p.get_media(new_mid)
    assert m_new is not None, "新 media 记录不应被删"
    ok("新文件未被清理（符合预期）")

    # 清理新文件
    os.unlink(t_new.name)

asyncio.run(test_cleanup())

print(f"\n{HDR}{'─'*60}{RST}")
print(f"{OK} 全部 4 项测试通过\n")
