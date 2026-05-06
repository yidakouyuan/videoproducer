import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('c:/openclaw_agent/video-agent-system/tag_knowledge_db/data/tag_knowledge.db')

# 取有 tag_card 的 canonical_tag 前10个
cursor = conn.execute("""
    SELECT ct.canonical_name, cts.video_count
    FROM canonical_tags ct
    JOIN canonical_tag_stats cts ON ct.canonical_tag_id = cts.canonical_tag_id
    WHERE ct.merged_into IS NULL
    ORDER BY cts.video_count DESC
    LIMIT 10
""")
print("Top 10 tags by video_count:")
for row in cursor.fetchall():
    print(f"  tag={row[0]!r}  videos={row[1]}")

conn.close()
