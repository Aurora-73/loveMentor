"""聊天证据视图 — agent_chat + agent_chat_data。"""
from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine.config import Config
from engine.identity import IdentityPerson
from engine.agent.core import _build_cross_refs
from engine.agent.response import ok, err

_BEIJING_TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 非文本消息内容提取
# ---------------------------------------------------------------------------
# 用户需求：很多无法转为文字的消息（卡片/链接/文件等）被直接忽略，Agent 不知道发了什么。
# 这里把非文本消息转成可读的占位文本，让 Agent 至少知道"对方发了一个 QQ 音乐链接"。
#
# 微信消息 type 值（标准）：
#   1=文本  3=图片  34=语音  42=名片  43=视频  47=表情贴纸
#   48=位置  49=卡片/链接/文件  50=位置分享  10000=系统消息
# 注意：WCD 返回的 type 可能带高位状态标志（如 25769803825 = 0x600000031），
#       用 type & 0xFF 取低字节作为基础类型。


def _base_type(msg_type: int) -> int:
    """取消息类型低字节（WCD 返回的 type 可能带高位状态标志）。"""
    try:
        return int(msg_type) & 0xFF
    except (TypeError, ValueError):
        return 0


def _strip_xml_to_text(content: str) -> str:
    """粗略去除 XML 标签，保留纯文本（用于系统消息等）。"""
    if not content:
        return ""
    # 去掉 CDATA 段，保留内容
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", content, flags=re.DOTALL)
    # 去掉所有标签
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _parse_appmsg_xml(content: str) -> str:
    """解析 type 49 卡片/链接消息的 appmsg XML，提取标题/描述/URL。

    微信 appmsg XML 格式：
        <msg><appmsg><title>...</title><des>...</des><url>...</url>
        <type>...</type><appname>...</appname></appmsg></msg>

    常见场景：QQ 音乐卡片、微信公众号文章、小程序分享、文件分享等。
    """
    if not content or not content.lstrip().startswith("<"):
        return content or ""

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        # XML 解析失败，返回原始内容的前 100 字符
        return content[:100]

    # 查找 appmsg 节点（可能在 <msg> 下，也可能直接是根）
    # 注意：不能用 `.find() or ...`，因为 Element 的 __len__ 返回子元素数量，
    # 自闭合标签没有子元素时 bool(element) == False，会导致 or 逻辑失效。
    appmsg = root.find(".//appmsg")
    if appmsg is None and root.tag == "appmsg":
        appmsg = root
    if appmsg is None:
        # 不是 appmsg XML，可能是其他类型，返回纯文本
        return _strip_xml_to_text(content)[:200]

    title = (appmsg.findtext("title") or "").strip()
    des = (appmsg.findtext("des") or "").strip()
    url = (appmsg.findtext("url") or "").strip()
    appname = (appmsg.findtext("appname") or "").strip()
    appmsg_type = (appmsg.findtext("type") or "").strip()

    # appmsg type: 5=链接 33=小程序 36=小程序 57=引用 51=视频号 19=合并转发 6=文件
    type_label = ""
    if appmsg_type == "33" or appmsg_type == "36":
        type_label = "小程序"
    elif appmsg_type == "51":
        type_label = "视频号"
    elif appmsg_type == "19":
        type_label = "合并转发"
    elif appmsg_type == "6":
        type_label = "文件"
    elif appmsg_type == "5":
        type_label = "链接"
    else:
        type_label = "卡片"

    parts = [f"[{type_label}]"]
    if title:
        parts.append(title)
    if des:
        parts.append(des)
    if appname:
        parts.append(f"(来源: {appname})")
    if url:
        # URL 太长时截断
        short_url = url if len(url) <= 80 else url[:77] + "..."
        parts.append(short_url)

    result = " ".join(parts)
    return result if result != f"[{type_label}]" else f"[{type_label}] {title or des or '未知内容'}"


def _parse_emoji_xml(content: str) -> str:
    """解析 type 47 表情贴纸 XML。"""
    if not content or not content.lstrip().startswith("<"):
        return "[表情]"
    try:
        root = ET.fromstring(content)
        # <msg><emoji md5="..." cdnurl="..." type="..."/>
        emoji = root.find(".//emoji")
        if emoji is None and root.tag == "emoji":
            emoji = root
        if emoji is not None:
            # 表情贴纸没有文字内容，返回占位
            return "[表情]"
    except ET.ParseError:
        pass
    return "[表情]"


def _parse_contact_card_xml(content: str) -> str:
    """解析 type 42 名片消息 XML。"""
    if not content or not content.lstrip().startswith("<"):
        return "[名片]"
    try:
        root = ET.fromstring(content)
        # <msg><msg><product nickname="..." /></msg></msg>
        # 或 <msg source="...">
        #   <contact nickname="..." alias="..." /></msg>
        for tag in (".//contact", ".//product"):
            node = root.find(tag)
            if node is not None:
                nickname = node.get("nickname") or node.get("nick") or ""
                if nickname:
                    return f"[名片] {nickname}"
    except ET.ParseError:
        pass
    return "[名片]"


def _parse_location_xml(content: str) -> str:
    """解析 type 48/50 位置消息 XML。"""
    if not content or not content.lstrip().startswith("<"):
        return "[位置]"
    try:
        root = ET.fromstring(content)
        # <msg><location x="..." y="..." scale="..." label="..." poiname="..." maptype="..."/></msg>
        loc = root.find(".//location")
        if loc is None and root.tag == "location":
            loc = root
        if loc is not None:
            # 优先用 label（详细地址），为空时 fallback 到 poiname（地名）
            label = (loc.get("label") or "").strip()
            if not label:
                label = (loc.get("poiname") or "").strip()
            if not label:
                label = (loc.get("name") or "").strip()
            if label:
                return f"[位置] {label}"
    except ET.ParseError:
        pass
    return "[位置]"


def _parse_system_message(content: str) -> str:
    """解析 type 10000 系统消息（撤回提示、添加好友等）。"""
    if not content:
        return ""
    # 系统消息可能是纯文本，也可能是 XML（如撤回消息）
    if content.lstrip().startswith("<"):
        try:
            root = ET.fromstring(content)
            # <sysmsg type="revokemsg"><revokemsg><content>...</content></revokemsg></sysmsg>
            revoke_content = root.findtext(".//content") or ""
            if revoke_content:
                return f"[系统] {revoke_content}"
            # 其他系统消息类型，提取纯文本
            text = _strip_xml_to_text(content)
            return f"[系统] {text}" if text else "[系统消息]"
        except ET.ParseError:
            text = _strip_xml_to_text(content)
            return f"[系统] {text}" if text else "[系统消息]"
    return f"[系统] {content}"  # 纯文本系统消息，加前缀保持一致性


def extract_display_content(
    msg_type: int,
    content: str | None,
    raw_content: str | None = None,
    voice_text: str | None = None,
    image_text: str | None = None,
) -> str:
    """把非文本消息转成 Agent 可读的展示文本。

    策略：
    - 文本消息(type 1)：原样返回
    - 图片(type 3)：有 image_text 用 image_text，否则 "[图片]"
    - 语音(type 34)：有 voice_text 用 voice_text，否则 "[语音]"
    - 表情贴纸(type 47)："[表情]"
    - 名片(type 42)：解析 XML 提取昵称 → "[名片] 昵称"
    - 视频(type 43)："[视频]"
    - 位置(type 48/50)：解析 XML 提取地名 → "[位置] 地名"
    - 卡片/链接/文件(type 49)：解析 appmsg XML → "[链接] 标题 - 描述 URL"
    - 系统消息(type 10000)：解析 XML 或纯文本 → "[系统] 内容"
    - 未知类型：如果内容是纯文本就用，否则 "[未知消息类型 X]"

    Args:
        msg_type: 消息类型（可能带高位标志，内部用 & 0xFF 取基础类型）
        content: messages.content 字段
        raw_content: messages.raw_content 字段（可能含完整 XML）
        voice_text: messages.voice_text 字段（语音转文字结果，带 [语音转文字] 前缀）
        image_text: messages.image_text 字段（图片描述结果，带 [图片描述] 前缀）

    Returns:
        Agent 可读的展示文本
    """
    content = content or ""
    raw_content = raw_content or ""
    base = _base_type(msg_type)

    # type 1: 文本消息，原样返回
    if base == 1:
        return content

    # type 3: 图片消息
    if base == 3:
        if image_text:
            return image_text  # 已带 [图片描述] 前缀
        return "[图片]"

    # type 34: 语音消息
    if base == 34:
        if voice_text:
            return voice_text  # 已带 [语音转文字] 前缀
        return "[语音]"

    # type 47: 表情贴纸
    if base == 47:
        return _parse_emoji_xml(raw_content or content)

    # type 42: 名片
    if base == 42:
        return _parse_contact_card_xml(raw_content or content)

    # type 43: 视频
    if base == 43:
        return "[视频]"

    # type 48 / 50: 位置
    if base in (48, 50):
        return _parse_location_xml(raw_content or content)

    # type 49: 卡片/链接/文件/小程序
    if base == 49:
        return _parse_appmsg_xml(raw_content or content)

    # type 10000: 系统消息
    if base == 10000 or msg_type == 10000:
        return _parse_system_message(content)

    # 未知类型：如果内容是纯文本就用，否则返回占位符
    # （WCD 可能返回非标准 type，但内容是可读文本）
    if content and not content.lstrip().startswith("<") and len(content) < 500:
        return content
    return f"[未知消息类型 {msg_type}]"


def _ts_to_beijing(ts):
    """Unix 秒级时间戳转北京时间字符串（内部存储仍为整数，接口处转为可读格式）。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _query_chat_messages(
    conn: sqlite3.Connection, config: Config, person: IdentityPerson, *,
    recent: int = 50, from_date: str | None = None, to_date: str | None = None,
    keyword: str | None = None, context_lines: int = 0,
) -> dict:
    """共享查询层：返回 {messages, total, returned, total_before_filter}。

    包含所有消息类型（文本/图片/语音/卡片/链接/表情/视频/系统消息等）。
    非文本消息通过 extract_display_content() 转成可读的展示文本。
    """
    from engine.analyzers.chat_history import parse_date_bound

    start_ts = parse_date_bound(from_date, is_end=False)
    end_ts = parse_date_bound(to_date, is_end=True)
    messages: list[dict] = []
    for account in person.accounts:
        cid = account.conversation_id or account.wxid
        if not cid:
            continue
        params: list = [cid]
        conditions = ["m.conversation_id = ?"]
        if start_ts is not None:
            conditions.append("m.timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("m.timestamp <= ?")
            params.append(end_ts)
        # 查询所有消息类型，包含 raw_content/voice_text/image_text 用于内容提取
        sql = (
            f"SELECT m.id, m.conversation_id, m.sender_id, m.content, "
            f"m.raw_content, m.voice_text, m.image_text, "
            f"m.timestamp, m.type, m.platform, m.source "
            f"FROM messages m WHERE {' AND '.join(conditions)} ORDER BY m.timestamp ASC"
        )
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            sender_id = row["sender_id"] or ""
            raw_content = row["raw_content"] or ""
            voice_text = row["voice_text"] or ""
            image_text = row["image_text"] or ""
            msg_type = row["type"]
            content = row["content"] or ""
            # 非文本消息提取可读内容（卡片解析标题/链接、图片/语音用转写文字等）
            display_content = extract_display_content(
                msg_type, content, raw_content, voice_text, image_text
            )
            messages.append({
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "sender_id": sender_id,
                "is_mine": sender_id == config.my_wxid,
                "timestamp": row["timestamp"],
                "time_str": _ts_to_beijing(row["timestamp"]),
                "content": display_content,
                "raw_content": raw_content,
                "type": msg_type,
                "platform": row["platform"] or "wechat",
                "source": row["source"] or "sync",
            })
    messages.sort(key=lambda m: m["timestamp"])

    total_before_filter = len(messages)

    if keyword:
        matched_indices: set[int] = set()
        for i, msg in enumerate(messages):
            if keyword in msg["content"]:
                for j in range(max(0, i - context_lines), min(len(messages), i + context_lines + 1)):
                    matched_indices.add(j)
        messages = [messages[i] for i in sorted(matched_indices)]

    total = len(messages)
    if len(messages) > recent:
        messages = messages[-recent:]

    return {
        "messages": messages,
        "total": total,
        "returned": len(messages),
        "total_before_filter": total_before_filter,
    }


def agent_chat_data(
    conn: sqlite3.Connection, config: Config, person: IdentityPerson, *,
    recent: int = 50, from_date: str | None = None, to_date: str | None = None,
    keyword: str | None = None, context_lines: int = 0,
) -> dict:
    """结构化聊天查询 — 返回 ToolEnvelope dict。"""
    result = _query_chat_messages(
        conn, config, person,
        recent=recent, from_date=from_date, to_date=to_date,
        keyword=keyword, context_lines=context_lines,
    )
    return ok(
        {
            "messages": result["messages"],
            "filter": {
                "keyword": keyword,
                "from_date": from_date,
                "to_date": to_date,
                "context_lines": context_lines,
            },
            "total": result["total"],
            "returned": result["returned"],
        },
        person_id=person.id,
        display_name=person.display_name,
    )


def agent_chat(
    conn: sqlite3.Connection, config: Config, person: IdentityPerson, *,
    recent: int = 50, from_date: str | None = None, to_date: str | None = None,
    keyword: str | None = None, context_lines: int = 0, output_file: str | None = None,
) -> str:
    """聊天记录（按日期分组 Markdown，已标注"我"/对方名字）。"""
    result = _query_chat_messages(
        conn, config, person,
        recent=recent, from_date=from_date, to_date=to_date,
        keyword=keyword, context_lines=context_lines,
    )
    messages = result["messages"]
    total = result["total"]
    total_before_filter = result["total_before_filter"]

    grouped: OrderedDict[str, list] = OrderedDict()
    for msg in messages:
        day = datetime.fromtimestamp(msg["timestamp"]).strftime("%Y-%m-%d")
        grouped.setdefault(day, []).append(msg)

    parts = [f"# Chat Evidence: {person.display_name}\n"]
    first_day = next(iter(grouped)) if grouped else "N/A"
    last_day = next(reversed(grouped)) if grouped else "N/A"
    filter_desc = []
    if keyword:
        filter_desc.append(f'keyword="{keyword}"')
    if from_date:
        filter_desc.append(f"from={from_date}")
    if to_date:
        filter_desc.append(f"to={to_date}")
    parts.append(f"- 时间范围: {first_day} ~ {last_day}")
    parts.append(f"- 显示消息: {len(messages)} / {total_before_filter}")
    if filter_desc:
        parts.append(f"- 过滤: {', '.join(filter_desc)}")
    parts.append("")

    for day, day_msgs in grouped.items():
        parts.append(f"## {day} ({len(day_msgs)} 条)\n")
        for msg in day_msgs:
            ts = datetime.fromtimestamp(msg["timestamp"]).strftime("%H:%M")
            sender_label = "我" if msg.get("is_mine") else person.display_name
            parts.append(f"- **{ts}** {sender_label}: {msg['content']}")
        parts.append("")

    parts.append(_build_cross_refs(person, has_fact=True, has_event=True))
    result_md = "\n".join(parts)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(result_md, encoding="utf-8")
        return f"已写入: {output_file} ({len(messages)} 条消息)"
    return result_md
