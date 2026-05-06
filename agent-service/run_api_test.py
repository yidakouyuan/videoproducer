"""
OpenClaw Agent - 全量 API 测试 (11 个接口 + /health)
使用 Mock 模式（无需真实抖音 Cookie / Gemini API Key）
"""
import asyncio
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"

results = []


async def test(client, name, method, path, body=None):
    url = BASE + path
    try:
        if body is not None:
            r = await client.request(method, url, json=body, timeout=15)
        else:
            r = await client.request(method, url, timeout=15)
        data = r.json()
        ok = data.get("ok", False) if isinstance(data, dict) else False
        status_mark = PASS if ok else FAIL
        print(f"{status_mark} {name}")
        print(f"       HTTP {r.status_code} | ok={ok}")
        d = data.get("data") if isinstance(data, dict) else data
        print(f"       data={json.dumps(d, ensure_ascii=False, indent=None)[:200]}")
        results.append((name, ok, r.status_code))
        return data
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"       ERROR: {e}")
        results.append((name, False, "ERR"))
        return None


async def main():
    print("\n" + "=" * 56)
    print("  OpenClaw Agent API Test (Mock Mode)")
    print("=" * 56 + "\n")

    async with httpx.AsyncClient() as client:

        # 0. Health
        await test(client, "0. GET  /health", "GET", "/health")

        # ── Media ──────────────────────────────────────────────
        # 1. POST /media/resolve_video
        r1 = await test(client, "1. POST /media/resolve_video", "POST",
                        "/media/resolve_video", {
                            "source_ref": {
                                "platform": "douyin",
                                "aweme_id": "7611851491078409481",
                                "share_url": "https://www.douyin.com/video/7611851491078409481"
                            }
                        })

        # 构造 resolved_video_ref（从 mock 返回，或手工构造兜底）
        resolved_ref = None
        if r1 and isinstance(r1.get("data"), dict):
            d = r1["data"]
            resolved_ref = {
                "platform": d.get("platform", "douyin"),
                "aweme_id": d.get("aweme_id", "7611851491078409481"),
                "share_url": d.get("share_url", "https://www.douyin.com/video/7611851491078409481"),
                "video_url": d.get("video_url", "https://example.com/video.mp4"),
                "downloadable": d.get("downloadable", True),
            }
        if not resolved_ref:
            resolved_ref = {
                "platform": "douyin",
                "aweme_id": "7611851491078409481",
                "share_url": "https://www.douyin.com/video/7611851491078409481",
                "video_url": "https://example.com/video.mp4",
                "downloadable": True,
            }

        # 2. POST /media/fetch_video
        r2 = await test(client, "2. POST /media/fetch_video", "POST",
                        "/media/fetch_video", {
                            "resolved_video_ref": resolved_ref
                        })

        media_id = None
        if r2 and isinstance(r2.get("data"), dict):
            media_id = r2["data"].get("media_id")
        if media_id:
            print(f"       >> media_id = {media_id}")

        # 3. POST /media/cleanup (dry_run)
        await test(client, "3. POST /media/cleanup (dry_run=true)", "POST",
                   "/media/cleanup", {"dry_run": True, "older_than_hours": 0})

        # ── Transcribe ─────────────────────────────────────────
        # 4. POST /transcribe/start
        r4 = await test(client, "4. POST /transcribe/start", "POST",
                        "/transcribe/start", {
                            "media_id": media_id or "md_mock_001",
                            "lang": "zh",
                            "mode": "highlights"
                        })

        job_id_tr = None
        if r4 and isinstance(r4.get("data"), dict):
            job_id_tr = r4["data"].get("job_id")
        if job_id_tr:
            print(f"       >> transcribe job_id = {job_id_tr}")

        # 5. GET /transcribe/result/{job_id}  (等 3 秒让 mock 完成)
        if job_id_tr:
            await asyncio.sleep(3)
            await test(client, f"5. GET  /transcribe/result/{job_id_tr}", "GET",
                       f"/transcribe/result/{job_id_tr}")

        # 6. DELETE /transcribe/{job_id}
        if job_id_tr:
            await test(client, f"6. DELETE /transcribe/{job_id_tr}", "DELETE",
                       f"/transcribe/{job_id_tr}")

        # ── Video Analyze ───────────────────────────────────────
        # 7. POST /video/analyze/start
        r7 = await test(client, "7. POST /video/analyze/start", "POST",
                        "/video/analyze/start", {
                            "media_id": media_id or "md_mock_001",
                            "analysis_types": ["content", "tags", "highlights"],
                            "lang": "zh"
                        })

        job_id_va = None
        if r7 and isinstance(r7.get("data"), dict):
            job_id_va = r7["data"].get("job_id")
        if job_id_va:
            print(f"       >> analyze job_id = {job_id_va}")

        # 8. GET /video/analyze/result/{job_id}
        if job_id_va:
            await asyncio.sleep(3)
            await test(client, f"8. GET  /video/analyze/result/{job_id_va}", "GET",
                       f"/video/analyze/result/{job_id_va}")

        # 9. DELETE /video/analyze/{job_id}
        if job_id_va:
            await test(client, f"9. DELETE /video/analyze/{job_id_va}", "DELETE",
                       f"/video/analyze/{job_id_va}")

        # ── Tag ────────────────────────────────────────────────
        # 10. POST /tag/script_pack  (真实 DB 中存在的 tag)
        await test(client, "10. POST /tag/script_pack", "POST",
                   "/tag/script_pack", {"tag": "影视解说"})

        # 11. DELETE /media/{media_id}
        if media_id:
            await test(client, f"11. DELETE /media/{media_id}", "DELETE",
                       f"/media/{media_id}")
        else:
            print(f"\033[33m[SKIP]\033[0m 11. DELETE /media/{{media_id}}  (no media_id)")

    # 汇总
    print("\n" + "=" * 56)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  结果：{passed}/{total} 通过")
    for name, ok, code in results:
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        mark2 = "OK" if ok else "NG"
        print(f"  {mark2} [{code}] {name}")
    print("=" * 56 + "\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
