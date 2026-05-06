"""
真实 Provider 全链路测试：
  resolve_video (真实抖音API) → fetch_video (真实下载) → transcribe (Gemini) → video/analyze (Gemini)
"""
import asyncio, httpx, json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8000"

# 从 douyin_hot.db 里取的真实 aweme_id
AWEME_ID = "7615189826035371298"
SHARE_URL = f"https://www.douyin.com/video/{AWEME_ID}"



passed = []
failed = []


async def test(client, name, method, path, body=None, timeout=60):
    url = BASE + path
    print(f"\n{'─'*54}")
    print(f">>> {name}")
    try:
        r = await client.request(method, url, json=body, timeout=timeout)
        data = r.json()
        ok = data.get("ok", False) if isinstance(data, dict) else False
        status = "PASS" if ok else "FAIL"
        print(f"    HTTP {r.status_code} | ok={ok}")
        d = data.get("data") if isinstance(data, dict) else data
        e = data.get("error") if isinstance(data, dict) else None
        if d:
            print(f"    data={json.dumps(d, ensure_ascii=False)[:300]}")
        if e:
            print(f"    error={json.dumps(e, ensure_ascii=False)}")
        if ok:
            passed.append(name)
        else:
            failed.append(name)
        return data
    except Exception as ex:
        print(f"    EXCEPTION: {ex}")
        failed.append(name)
        return None


async def main():
    print("=" * 54)
    print("  OpenClaw Agent — 真实 Provider 测试")
    print("  USE_REAL_DOUYIN=1 / USE_REAL_GEMINI=1")
    print("=" * 54)

    async with httpx.AsyncClient() as client:

        # 0. Health
        await test(client, "0. GET /health", "GET", "/health")

        # ── Tag（真实 GraphRAG DB，不依赖其他）──────────────────
        await test(client, "10. POST /tag/script_pack (影视解说)", "POST",
                   "/tag/script_pack", {"tag": "影视解说"})

        # ── Media: resolve ──────────────────────────────────────
        print(f"\n[INFO] 使用 aweme_id={AWEME_ID}")
        r1 = await test(client, "1. POST /media/resolve_video (真实抖音)", "POST",
                        "/media/resolve_video", {
                            "source_ref": {
                                "platform": "douyin",
                                "aweme_id": AWEME_ID,
                                "share_url": SHARE_URL
                            }
                        }, timeout=30)

        # ── Media: fetch ────────────────────────────────────────
        resolved_ref = None
        if r1 and r1.get("ok") and isinstance(r1.get("data"), dict):
            d = r1["data"]
            resolved_ref = {
                "platform": d.get("platform", "douyin"),
                "aweme_id": d.get("aweme_id", AWEME_ID),
                "share_url": d.get("share_url", SHARE_URL),
                "video_url": d.get("video_url", ""),
                "downloadable": d.get("downloadable", False),
            }
        else:
            print("\n[SKIP] resolve_video 失败，跳过 fetch_video 及后续依赖接口")

        media_id = None
        if resolved_ref and resolved_ref.get("downloadable"):
            r2 = await test(client, "2. POST /media/fetch_video (真实下载)", "POST",
                            "/media/fetch_video", {"resolved_video_ref": resolved_ref},
                            timeout=120)
            if r2 and r2.get("ok") and isinstance(r2.get("data"), dict):
                media_id = r2["data"].get("media_id")
                print(f"\n[INFO] media_id={media_id}")
        elif resolved_ref:
            print("\n[WARN] video downloadable=False，跳过 fetch_video")

        # ── Cleanup（不依赖真实视频）───────────────────────────
        await test(client, "3. POST /media/cleanup (dry_run)", "POST",
                   "/media/cleanup", {"dry_run": True}, timeout=10)

        # ── Transcribe ─────────────────────────────────────────
        job_id_tr = None
        if media_id:
            r4 = await test(client, "4. POST /transcribe/start (Gemini)", "POST",
                            "/transcribe/start", {
                                "media_id": media_id, "lang": "zh", "mode": "highlights"
                            }, timeout=30)
            if r4 and r4.get("ok"):
                job_id_tr = r4["data"].get("job_id")

            if job_id_tr:
                print(f"\n[INFO] 等待转写完成（最多 5 分钟轮询）...")
                for i in range(30):
                    await asyncio.sleep(10)
                    r5 = await test(client,
                                    f"5. GET /transcribe/result/{job_id_tr} (poll {i+1})",
                                    "GET", f"/transcribe/result/{job_id_tr}", timeout=15)
                    if r5 and r5.get("data", {}).get("status") in ("done", "failed"):
                        break

                await test(client, f"6. DELETE /transcribe/{job_id_tr}", "DELETE",
                           f"/transcribe/{job_id_tr}", timeout=10)
        else:
            print("\n[SKIP] 无 media_id，跳过 transcribe 测试")

        # ── Video Analyze ───────────────────────────────────────
        job_id_va = None
        if media_id:
            r7 = await test(client, "7. POST /video/analyze/start (Gemini)", "POST",
                            "/video/analyze/start", {
                                "media_id": media_id,
                                "analysis_types": ["content", "tags", "highlights"],
                                "lang": "zh"
                            }, timeout=30)
            if r7 and r7.get("ok"):
                job_id_va = r7["data"].get("job_id")

            if job_id_va:
                print(f"\n[INFO] 等待视频分析完成（最多 5 分钟轮询）...")
                for i in range(30):
                    await asyncio.sleep(10)
                    r8 = await test(client,
                                    f"8. GET /video/analyze/result/{job_id_va} (poll {i+1})",
                                    "GET", f"/video/analyze/result/{job_id_va}", timeout=15)
                    if r8 and r8.get("data", {}).get("status") in ("done", "failed"):
                        break

                await test(client, f"9. DELETE /video/analyze/{job_id_va}", "DELETE",
                           f"/video/analyze/{job_id_va}", timeout=10)
        else:
            print("\n[SKIP] 无 media_id，跳过 video/analyze 测试")

        # ── Media Delete ────────────────────────────────────────
        if media_id:
            await test(client, f"11. DELETE /media/{media_id}", "DELETE",
                       f"/media/{media_id}", timeout=10)

    # 汇总
    print("\n" + "=" * 54)
    total = len(passed) + len(failed)
    print(f"  结果：{len(passed)}/{total} 通过")
    for n in passed:
        print(f"  OK  {n}")
    for n in failed:
        print(f"  NG  {n}")
    print("=" * 54)


if __name__ == "__main__":
    asyncio.run(main())
