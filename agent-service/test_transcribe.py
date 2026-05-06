"""
直接测试 GeminiTranscribeProvider，无需通过 HTTP。
使用磁盘上已有的视频文件。
"""
import asyncio
import sys
import time
from dotenv import load_dotenv

load_dotenv("c:/openclaw_agent/.env")

# 把 app 目录加入 Python 路径
sys.path.insert(0, "c:/openclaw_agent")

from app.domain.models import StorageInfo, StoredMedia, ContentRef
from app.providers import douyin_media_provider
from app.providers.gemini_transcribe_provider import GeminiTranscribeProvider

# 用较小的 33MB 视频
MEDIA_ID = "md_837c213d35be"
LOCAL_PATH = f"c:/openclaw_agent/data/videos/{MEDIA_ID}.mp4"

# 把文件注入到 media store，模拟已下载状态
douyin_media_provider._store[MEDIA_ID] = StoredMedia(
    media_id=MEDIA_ID,
    content_ref=ContentRef(
        platform="douyin",
        source_type="video",
        source_id="test",
        source_url="https://www.douyin.com/",
    ),
    media_type="video",
    storage=StorageInfo(local_path=LOCAL_PATH),
)


async def main():
    provider = GeminiTranscribeProvider()
    job_id = f"tr_test_{int(time.time())}"

    print(f"[1] 启动转写任务: job_id={job_id}, media_id={MEDIA_ID}, mode=highlights")
    job = await provider.start_transcribe(
        job_id=job_id,
        media_id=MEDIA_ID,
        provider_name="gemini",
        lang="zh",
        mode="highlights",
    )
    print(f"    status={job.status}")

    print("[2] 轮询结果（最多等 5 分钟）...")
    for i in range(60):
        await asyncio.sleep(5)
        job = await provider.get_transcribe_result(job_id)
        print(f"    [{i*5+5}s] status={job.status}", end="")
        if job.error_message:
            print(f"  error={job.error_message}", end="")
        print()
        if job.status in ("done", "failed"):
            break

    print(f"\n[3] 最终状态: {job.status}")
    if job.status == "done":
        print(f"    confidence: {job.confidence}")
        print(f"    transcript ({len(job.transcript)} chars):")
        print(f"    {job.transcript[:300]}...")
        print(f"    highlights ({len(job.highlights)} items):")
        for h in job.highlights:
            print(f"      [{h.start_sec:.1f}s ~ {h.end_sec:.1f}s] {h.text}")
    else:
        print(f"    error: {job.error_message}")


asyncio.run(main())
