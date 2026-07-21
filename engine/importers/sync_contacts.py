"""联系人同步

从 WeFlow API 拉取联系人列表，幂等写入 SQLite。
"""
import json
import logging
import sqlite3

from engine.importers.weflow_client import WeFlowClient

logger = logging.getLogger(__name__)


def sync_contacts(client: WeFlowClient, db: sqlite3.Connection, source: str | None = None) -> int:
    """同步联系人到 SQLite，返回联系人总数。

    Args:
        client: WeFlowClient 或 WCDClient 实例
        db: SQLite 连接
        source: 数据源（仅 WCD 有效，None=auto/realtime，decrypted=读解密快照）
                当 WeChat 运行时（WCD 后端），传 source=decrypted 绕过 session.db 锁
    """
    contacts = client.list_contacts(limit=10000, source=source) if source else client.list_contacts(limit=10000)
    logger.info(f"拉取到 {len(contacts)} 个联系人")

    for c in contacts:
        labels = c.get("labels") or []
        db.execute(
            """
            INSERT INTO contacts (
                id, nickname, remark, alias, display_name,
                avatar_url, type, labels, raw_json, first_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))
            ON CONFLICT(id) DO UPDATE SET
                nickname = excluded.nickname,
                remark = excluded.remark,
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url,
                type = excluded.type,
                labels = excluded.labels,
                raw_json = excluded.raw_json,
                updated_at = strftime('%s','now')
            """,
            (
                c.get("username", ""),
                c.get("nickname"),
                c.get("remark"),
                c.get("alias"),
                c.get("displayName"),
                c.get("avatarUrl"),
                c.get("type"),
                json.dumps(labels, ensure_ascii=False),
                json.dumps(c, ensure_ascii=False),
            ),
        )

    db.commit()
    logger.info(f"联系人同步完成: {len(contacts)} 条")
    return len(contacts)
