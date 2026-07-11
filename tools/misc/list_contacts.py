"""列出数据库中所有联系人及其消息统计。"""

from engine.config import load_config
from engine.importers.db_init import get_db
import datetime

config = load_config()
conn = get_db(config.db_path)
try:
    rows = conn.execute('''
        SELECT c.id AS wxid, 
               COALESCE(c.display_name, c.id) AS display_name,
               COUNT(m.id) AS message_count,
               MIN(m.timestamp) AS first_msg,
               MAX(m.timestamp) AS last_msg
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE c.type = 'private'
        GROUP BY c.id
        HAVING message_count >= 50
        ORDER BY message_count DESC
    ''').fetchall()

    print(f'{"显示名":20s} | {"wxid":25s} | {"消息数":6s} | 时间范围')
    print('-' * 80)
    for r in rows:
        first = datetime.datetime.fromtimestamp(r['first_msg']).strftime('%Y-%m-%d') if r['first_msg'] else 'N/A'
        last = datetime.datetime.fromtimestamp(r['last_msg']).strftime('%Y-%m-%d') if r['last_msg'] else 'N/A'
        print(f'{r["display_name"]:20s} | {r["wxid"][:25]:25s} | {r["message_count"]:6d} | {first} ~ {last}')
finally:
    conn.close()
