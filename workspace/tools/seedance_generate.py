#!/home/administrator/.venvs/openclaw/bin/python
# -*- coding: utf-8 -*-

import os
import time
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from byteplussdkarkruntime import Ark


DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_MODEL = "seedance-1-5-pro-251215"


def pretty(obj: Any) -> str:
    try:
        return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2)
    except Exception:
        try:
            return json.dumps(obj.__dict__, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(obj)


def find_first_url(obj: Any) -> Optional[str]:
    """启发式从返回对象里找到视频 URL（字段名可能随版本变化）"""
    def walk(x: Any) -> Optional[str]:
        if isinstance(x, dict):
            for k, v in x.items():
                lk = str(k).lower()
                if lk in ("url", "video_url", "download_url", "file_url", "play_url"):
                    if isinstance(v, str) and v.startswith("http"):
                        return v
                got = walk(v)
                if got:
                    return got
        elif isinstance(x, list):
            for it in x:
                got = walk(it)
                if got:
                    return got
        else:
            try:
                return walk(x.model_dump())
            except Exception:
                try:
                    return walk(x.__dict__)
                except Exception:
                    return None
        return None

    return walk(obj)


def download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="Text prompt, can include --duration/--ratio/--resolution etc.")
    ap.add_argument("--first-frame-url", default="", help="Optional first frame image URL for i2v")
    ap.add_argument("--base-url", default=os.getenv("ARK_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--model", default=os.getenv("SEEDANCE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--poll", type=float, default=float(os.getenv("POLL_INTERVAL_SEC", "1")))
    ap.add_argument("--timeout", type=float, default=float(os.getenv("MAX_WAIT_SEC", "240")))
    ap.add_argument("--out-dir", default=os.getenv("SEEDANCE_OUT_DIR", "/mnt/c/OpenClawDrop/to_upload"))
    ap.add_argument("--manifest-dir", default=os.getenv("SEEDANCE_MANIFEST_DIR", "/mnt/c/OpenClawDrop/manifests"))
    args = ap.parse_args()

    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ARK_API_KEY not set")

    client = Ark(base_url=args.base_url, api_key=api_key)

    content = [{"type": "text", "text": args.prompt}]
    if args.first_frame_url.strip():
        content.append({"type": "image_url", "image_url": {"url": args.first_frame_url.strip()}})

    print("[seedance] creating task...")
    create_result = client.content_generation.tasks.create(model=args.model, content=content)
    task_id = getattr(create_result, "id", None) or getattr(create_result, "task_id", None)
    if not task_id:
        print(pretty(create_result))
        raise SystemExit("ERROR: cannot find task_id in create_result")

    print(f"[seedance] task_id={task_id}")

    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        last = client.content_generation.tasks.get(task_id=task_id)
        status = getattr(last, "status", None) or getattr(last, "state", None)
        status_s = str(status).lower() if status is not None else ""
        print(f"[seedance] status={status}")

        if status_s == "succeeded":
            url = find_first_url(last)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_dir = Path(args.out_dir)
            mp4_path = out_dir / f"seedance_{task_id}_{ts}.mp4"

            manifest_dir = Path(args.manifest_dir)
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / f"seedance_{task_id}_{ts}.json"

            result_obj = {
                "task_id": task_id,
                "model": args.model,
                "prompt": args.prompt,
                "first_frame_url": args.first_frame_url,
                "base_url": args.base_url,
                "status": "succeeded",
                "video_url_guess": url,
                "mp4_path": str(mp4_path),
                "raw_result": None,
            }

            # 保存 raw_result（尽量可序列化）
            try:
                result_obj["raw_result"] = last.model_dump()
            except Exception:
                try:
                    result_obj["raw_result"] = last.__dict__
                except Exception:
                    result_obj["raw_result"] = str(last)

            if url:
                print(f"[seedance] downloading video: {url}")
                download(url, mp4_path)
                print(f"[seedance] saved: {mp4_path}")
            else:
                print("[seedance] WARNING: succeeded but cannot find video url in response (inspect manifest raw_result).")

            manifest_path.write_text(json.dumps(result_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[seedance] manifest: {manifest_path}")

            # 最后输出一行“机器可读”的路径，给 OpenClaw 解析用
            print(f"OUTPUT_MP4={mp4_path}")
            print(f"OUTPUT_MANIFEST={manifest_path}")
            return

        if status_s == "failed":
            print("[seedance] FAILED")
            print(pretty(last))
            raise SystemExit(1)

        time.sleep(args.poll)

    print("[seedance] TIMEOUT")
    if last is not None:
        print(pretty(last))
    raise SystemExit(1)


if __name__ == "__main__":
    main()
