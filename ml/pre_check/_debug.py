"""调试：检查消息数据和窗口构建。"""
import sqlite3
from pathlib import Path

DB_PATH = Path(r"<project_root>\data\raw\core.db")

conn = sqlite3.connect(DB_PATH)

# 1. 检查发送者分布
print("=== 发送者TOP 10 ===")
rows = conn.execute("""
    SELECT sender_id, COUNT(*) as cnt
    FROM messages
    WHERE type = 1 AND content IS NOT NULL AND length(content) > 0
    GROUP BY sender_id
    ORDER BY cnt DESC
    LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]} 条")

# 2. 检查 sync_state
print("\n=== sync_state ===")
rows = conn.execute("SELECT * FROM sync_state").fetchall()
for r in rows:
    print(f"  {r}")

# 3. 抽一个会话看看消息
print("\n=== 某个会话的前10条消息 ===")
conv = conn.execute("""
    SELECT c.id, c.display_name, COUNT(m.id) as cnt
    FROM conversations c
    JOIN messages m ON m.conversation_id = c.id
    WHERE c.type = 'private' AND m.type = 1
    GROUP BY c.id
    ORDER BY cnt DESC
    LIMIT 1
""").fetchone()
print(f"  会话: {conv[0]} ({conv[1]}), {conv[2]} 条消息")

msgs = conn.execute("""
    SELECT sender_id, timestamp, substr(content, 1, 80)
    FROM messages
    WHERE conversation_id = ? AND type = 1
    ORDER BY timestamp ASC
    LIMIT 10
""", (conv[0],)).fetchall()
for m in msgs:
    print(f"  {m[0]} | {m[1]} | {m[2]}")

conn.close()
