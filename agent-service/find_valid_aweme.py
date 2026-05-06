import httpx, asyncio, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8000"

# 从 DB 里取的最新 aweme_ids
CANDIDATES = [
    "7615189826035371298",
    "7614595196868651750",
    "7614505219082210612",
    "7614255876328770826",
    "7613803773022276458",
    "7613311390091602033",
    "7612235194426264832",
]

async def main():
    async with httpx.AsyncClient() as client:
        for aweme_id in CANDIDATES:
            r = await client.post(f"{BASE}/media/resolve_video", json={
                "source_ref": {
                    "platform": "douyin",
                    "aweme_id": aweme_id,
                    "share_url": f"https://www.douyin.com/video/{aweme_id}"
                }
            }, timeout=20)
            data = r.json()
            ok = data.get("ok", False)
            status = "OK" if ok else "NG"
            msg = ""
            if ok:
                msg = f"video_url={data['data'].get('video_url','')[:60]}..."
            else:
                msg = data.get("error", {}).get("message", "")
            print(f"[{status}] {aweme_id}  {msg}")
            if ok:
                print(f"\n>>> 找到有效 aweme_id: {aweme_id}")
                break

asyncio.run(main())
