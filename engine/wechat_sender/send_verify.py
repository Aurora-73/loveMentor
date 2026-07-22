"""发送验证模块（v4 数据同步管道验证）。

通过数据同步管道的增量同步机制验证消息发送结果：
1. 发送前记录时间戳 before_ts
2. 发送后轮询同步 + 查询数据库
3. 对比 sender_id = my_wxid 的我方消息是否出现

注意：WeChat→WCD 同步有延迟，采用轮询策略（默认 10s×3 次）。
验证结果"未验证"不等于"发送失败"，只是同步管道未拉取到。

关键设计：
- 只对比我方消息（sender_id == my_wxid），不对比对方消息
  （对方可能很快回复，干扰验证）
- 图片/表情包消息在数据库中 type 不同（3=图片, 47=表情），
  content 字段可能为空，用 extract_display_content 生成可读标签
- sync_person 返回 Markdown 摘要不返回消息列表，需直接查询数据库
"""
import os
import sys
import time
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 数据库路径
_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "raw", "core.db")


def _get_my_wxid() -> str:
    """获取登录用户的 wxid。"""
    from engine.config import load_config
    config = load_config()
    return config.my_wxid or ""


def _resolve_contact_wxid(name: str) -> str:
    """解析联系人标识符，返回其 wxid（作为 conversation_id）。

    复用 engine.wechat_sender.contact_profile.resolve_contact 的解析逻辑。
    """
    from engine.wechat_sender.contact_profile import resolve_contact
    resolution = resolve_contact(name)
    if not resolution.get("success"):
        return ""
    return resolution.get("id", "") or ""


def _query_my_new_messages(
    conn: sqlite3.Connection,
    conversation_id: str,
    my_wxid: str,
    since_ts: int,
) -> list[dict]:
    """查询指定时间之后的我方新消息。

    Args:
        conn: 数据库连接
        conversation_id: 会话 ID（联系人 wxid）
        my_wxid: 登录用户 wxid
        since_ts: Unix 时间戳（秒），查询 timestamp >= since_ts 的消息

    Returns:
        list[dict]: 我方新消息列表，每条含 id/timestamp/type/content/display_content
    """
    # since_ts 可能是秒级，数据库 timestamp 也是秒级（INTEGER）
    # 但发送后消息的 timestamp 可能略早于 before_ts（时钟差异），给 5 秒容差
    query_ts = since_ts - 5

    rows = conn.execute(
        """
        SELECT id, timestamp, type, content, raw_content, voice_text, image_text
        FROM messages
        WHERE conversation_id = ?
          AND sender_id = ?
          AND timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (conversation_id, my_wxid, query_ts),
    ).fetchall()

    # 用 extract_display_content 生成可读标签（图片/表情包/语音等）
    try:
        from engine.agent.chat import extract_display_content
        messages = []
        for row in rows:
            display = extract_display_content(
                row["type"],
                row["content"],
                row["raw_content"],
                row["voice_text"],
                row["image_text"],
            )
            messages.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "type": row["type"],
                "content": display,
            })
        return messages
    except ImportError:
        # extract_display_content 不可用时，返回原始 content
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "type": row["type"],
                "content": row["content"] or "",
            }
            for row in rows
        ]


def verify_send_via_sync(
    name: str,
    before_ts: int,
    max_retries: int = 3,
    interval: int = 10,
) -> dict:
    """通过数据同步管道验证消息发送结果（轮询策略）。

    流程：
    1. 解析联系人 → 获取 wxid（conversation_id）
    2. 获取 my_wxid（登录用户 wxid）
    3. 第一次轮询时强制刷新 WCD 解密快照（force=True，跳过 30 分钟节流）
    4. 轮询（最多 max_retries 次，每次间隔 interval 秒）：
       a. 调用 sync_person(name) 同步最新消息
       b. 查询数据库：messages WHERE conversation_id=wxid AND sender_id=my_wxid AND timestamp >= before_ts
       c. 如果查到我方消息 → 验证成功，返回
    5. max_retries 次都未查到 → 返回"未验证"（不一定是失败）

    关键设计：
    - WCD 解密快照有 30 分钟节流（_DECRYPT_INTERVAL=1800s），普通 sync_person 不会重新解密
    - 验证场景下必须强制解密（force=True），否则 30 分钟内发送的消息无法同步
    - 强制解密耗时约 30-90 秒（取决于数据库大小），第一次轮询会较慢

    Args:
        name: 联系人标识符（微信号/wxid/昵称/备注名 均可）
        before_ts: 发送前的 Unix 时间戳（秒）
        max_retries: 最大重试次数（默认 3）
        interval: 每次重试间隔秒数（默认 10）

    Returns:
        dict: {
            "verified": bool,       # 是否验证成功（查到我方新消息）
            "new_messages": list,   # 新增的我方消息列表
            "new_count": int,       # 新增消息数
            "attempts": int,        # 尝试次数
            "elapsed": float,       # 总耗时秒数
            "conversation_id": str, # 联系人 wxid
            "my_wxid": str,         # 登录用户 wxid
            "error": str|None,
        }
    """
    start_time = time.time()

    logger.info("=" * 60)
    logger.info(f"  数据同步管道验证: {name!r}")
    logger.info(f"  before_ts={before_ts} max_retries={max_retries} interval={interval}s")
    logger.info("=" * 60)

    # ── 1. 解析联系人 wxid ──
    contact_wxid = _resolve_contact_wxid(name)
    if not contact_wxid:
        return {
            "verified": False,
            "new_messages": [],
            "new_count": 0,
            "attempts": 0,
            "elapsed": time.time() - start_time,
            "conversation_id": "",
            "my_wxid": "",
            "error": f"无法解析联系人: {name}",
        }
    logger.info(f"[1] 联系人 wxid: {contact_wxid}")

    # ── 2. 获取 my_wxid ──
    my_wxid = _get_my_wxid()
    if not my_wxid:
        return {
            "verified": False,
            "new_messages": [],
            "new_count": 0,
            "attempts": 0,
            "elapsed": time.time() - start_time,
            "conversation_id": contact_wxid,
            "my_wxid": "",
            "error": "无法获取 my_wxid（config.my_wxid 为空）",
        }
    logger.info(f"[2] my_wxid: {my_wxid}")

    # ── 3. 轮询同步 + 查询 ──
    # 关键：sync_person 内部的 decrypt_databases() 有 30 分钟节流，不会重新解密。
    # 发送验证场景下必须强制刷新解密快照，否则 30 分钟内发送的消息无法同步。
    from engine.agent.sync_agent import sync_person, _build_sync_client
    from engine.agent.core import _get_conn

    # 构建 WCD client 用于强制解密
    try:
        conn_tmp, config_tmp = _get_conn()
        conn_tmp.close()
        wcd_client = _build_sync_client(config_tmp)
        can_force_decrypt = config_tmp.weflow.backend == "wcd"
    except Exception as e:
        logger.warning(f"⚠️ 无法构建 WCD client（强制解密不可用）: {e}")
        wcd_client = None
        can_force_decrypt = False

    all_new_messages = []
    attempts = 0

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        logger.info(f"\n[3.{attempt}/{max_retries}] 等待 {interval}s 后同步...")

        # 等待（第一次也需要等，给 WeChat→WCD 同步时间）
        time.sleep(interval)

        # 强制刷新 WCD 解密快照（跳过 30 分钟节流）
        # 只有第一次需要强制解密，后续 sync_person 的节流会自动放行（因为刚解密过）
        if can_force_decrypt and wcd_client and attempt == 1:
            logger.info(f"   强制刷新 WCD 解密快照 (force=True)...")
            try:
                decrypt_result = wcd_client.decrypt_databases(force=True)
                status = decrypt_result.get("status", "unknown")
                success = decrypt_result.get("success_count", 0)
                failed = decrypt_result.get("failure_count", 0)
                logger.info(f"   解密结果: status={status} success={success} failed={failed}")
            except Exception as e:
                logger.warning(f"   ⚠️ 强制解密异常: {e}")

        # 调用 sync_person 同步
        logger.info(f"   调用 sync_person('{name}')...")
        try:
            sync_result = sync_person(name, mode="incremental", transcribe_mode="off")
            logger.info(f"   同步结果: {sync_result.split(chr(10))[0] if sync_result else '空'}")
        except Exception as e:
            logger.warning(f"   ⚠️ sync_person 异常: {e}")
            sync_result = ""

        # 查询数据库
        try:
            conn = sqlite3.connect(_DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                new_msgs = _query_my_new_messages(conn, contact_wxid, my_wxid, before_ts)
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"   ❌ 数据库查询异常: {e}")
            continue

        if new_msgs:
            all_new_messages = new_msgs
            logger.info(f"   ✅ 查到我方新消息 {len(new_msgs)} 条:")
            for msg in new_msgs:
                logger.info(f"      - ts={msg['timestamp']} type={msg['type']} content={msg['content']!r}")
            break
        else:
            logger.info(f"   ⚠️ 未查到我方新消息（第 {attempt} 次）")

    elapsed = time.time() - start_time
    verified = len(all_new_messages) > 0

    logger.info("\n" + "=" * 60)
    if verified:
        logger.info(f"  ✅ 验证成功: 查到 {len(all_new_messages)} 条我方新消息（{attempts} 次尝试，{elapsed:.1f}s）")
    else:
        logger.info(f"  ⚠️ 未验证: {max_retries} 次尝试后未查到我方新消息（{elapsed:.1f}s）")
        logger.info(f"     注意：未验证 ≠ 发送失败")
        logger.info(f"     可能原因：微信本地数据库未写入 / WCD 强制解密失败 / sync_one_session 未拉取到")
        logger.info(f"     建议：检查 WCD 服务状态，或手动调用 sync_person 确认")
    logger.info("=" * 60)

    return {
        "verified": verified,
        "new_messages": all_new_messages,
        "new_count": len(all_new_messages),
        "attempts": attempts,
        "elapsed": round(elapsed, 1),
        "conversation_id": contact_wxid,
        "my_wxid": my_wxid,
        "error": None if verified else (
            f"同步管道未拉取到我方新消息（{max_retries}次×{interval}s={max_retries*interval}s）"
            "，可能原因：WCD 强制解密失败或微信本地数据库未写入"
        ),
    }


if __name__ == "__main__":
    # 命令行测试：python send_verify.py <联系人名> <before_ts>
    if len(sys.argv) < 3:
        print("用法: python send_verify.py <联系人名> <before_ts>")
        print("示例: python send_verify.py [REDACTED] 1784721800")
        sys.exit(1)
    contact_name = sys.argv[1]
    before_timestamp = int(sys.argv[2])
    result = verify_send_via_sync(contact_name, before_timestamp)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
