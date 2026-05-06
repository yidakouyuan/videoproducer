"""
测试 /video/generate 三个接口（Mock 模式）
"""
import asyncio, httpx, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8000"
PASS = "[PASS]"
FAIL = "[FAIL]"


async def test(client, name, method, path, body=None):
    url = BASE + path
    r = await client.request(method, url, json=body, timeout=15)
    data = r.json()
    ok = data.get("ok", False)
    mark = PASS if ok else FAIL
    print(f"{mark} {name}")
    print(f"       HTTP {r.status_code} | ok={ok}")
    d = data.get("data") or data.get("error")
    print(f"       {json.dumps(d, ensure_ascii=False)[:200]}")
    return data


async def main():
    print("\n=== video/generate 接口测试（Mock）===\n")
    async with httpx.AsyncClient() as client:

        # 1. start（纯文生视频）
        r1 = await test(client, "1. POST /video/generate/start (t2v)", "POST",
                        "/video/generate/start", {
                            "prompt": "一只猫在草地上奔跑，阳光明媚"
                        })
        job_id = r1.get("data", {}).get("job_id")
        print(f"       >> job_id={job_id}")

        # 2. start（图生视频）
        r2 = await test(client, "2. POST /video/generate/start (i2v)", "POST",
                        "/video/generate/start", {
                            "prompt": "镜头缓慢推近，背景虚化",
                            "first_frame_path": "https://example.com/frame.jpg"
                        })
        job_id_i2v = r2.get("data", {}).get("job_id")

        # 3. result（queued → running）
        await test(client, "3. GET /video/generate/result (running)", "GET",
                   f"/video/generate/result/{job_id}")

        # 4. result（等 3 秒 → done）
        await asyncio.sleep(3)
        await test(client, "4. GET /video/generate/result (done)", "GET",
                   f"/video/generate/result/{job_id}")

        # 5. delete
        await test(client, "5. DELETE /video/generate/{job_id}", "DELETE",
                   f"/video/generate/{job_id}")

        # 6. delete 已删除的 → 404
        r6 = await test(client, "6. DELETE /video/generate/{job_id} (404)", "DELETE",
                        f"/video/generate/{job_id}")

        # 7. i2v result
        await asyncio.sleep(3)
        await test(client, "7. GET /video/generate/result (i2v done)", "GET",
                   f"/video/generate/result/{job_id_i2v}")

    print("\n=== 完成 ===\n")

asyncio.run(main())
