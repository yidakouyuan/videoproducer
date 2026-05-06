import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('c:/openclaw_agent/video-agent-system/data/douyin_hot.db')

# 看表结构
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)

cursor = conn.execute("PRAGMA table_info(videos)")
cols = [r[1] for r in cursor.fetchall()]
print("videos columns:", cols)

# 取最新视频
order_col = 'create_time' if 'create_time' in cols else ('updated_at' if 'updated_at' in cols else cols[0])
title_col = next((c for c in cols if 'title' in c.lower()), cols[1] if len(cols) > 1 else cols[0])
aweme_col = next((c for c in cols if 'aweme' in c.lower()), cols[0])

print(f"\n用 aweme_col={aweme_col}, title_col={title_col}, order_col={order_col}")
cursor = conn.execute(f"""
    SELECT {aweme_col}, {title_col}, {order_col}
    FROM videos
    WHERE {title_col} IS NOT NULL AND {title_col} != ''
    ORDER BY {order_col} DESC
    LIMIT 10
""")
print("\n最近 10 条视频:")
for row in cursor.fetchall():
    print(f"  aweme_id={row[0]}  title={str(row[1])[:40]}  time={row[2]}")

conn.close()
