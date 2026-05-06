import httpx, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

tag = '影视解说'
r = httpx.post('http://127.0.0.1:8000/tag/script_pack', json={'tag': tag})
print(f'HTTP {r.status_code}')
data = r.json()
print(json.dumps(data, ensure_ascii=False, indent=2)[:800])
