#!/usr/bin/env python3
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

INBOX = Path('/home/administrator/.openclaw/workspace/bridge-inbox/douyin-publish-request.json')
RESULT = Path('/home/administrator/.openclaw/workspace/bridge-inbox/douyin-publish-result.json')
BASE = 'http://127.0.0.1:8787'

if not INBOX.exists():
    print(json.dumps({"ok": False, "error": "no_handoff_file"}, ensure_ascii=False))
    raise SystemExit(2)

obj = json.loads(INBOX.read_text(encoding='utf-8'))
if obj.get('action') != 'douyin_publish':
    print(json.dumps({"ok": False, "error": "unsupported_action"}, ensure_ascii=False))
    raise SystemExit(2)

payload = obj.get('payload', {})
req = urllib.request.Request(
    BASE + '/publish/douyin',
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    headers={'Content-Type': 'application/json; charset=utf-8'},
    method='POST'
)
with urllib.request.urlopen(req, timeout=30) as resp:
    created = json.loads(resp.read().decode('utf-8'))

job_id = created.get('job_id')
if not job_id:
    RESULT.write_text(json.dumps({"ok": False, "stage": "create", "response": created}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(RESULT.read_text(encoding='utf-8'))
    raise SystemExit(1)

last = None
for _ in range(60):
    with urllib.request.urlopen(BASE + '/jobs/' + job_id, timeout=30) as resp:
        last = json.loads(resp.read().decode('utf-8'))
    status = ((last.get('job') or {}).get('status'))
    if status in ('done', 'failed'):
        break
    time.sleep(5)

RESULT.write_text(json.dumps({"ok": True, "create": created, "job": last}, ensure_ascii=False, indent=2), encoding='utf-8')
print(RESULT.read_text(encoding='utf-8'))
