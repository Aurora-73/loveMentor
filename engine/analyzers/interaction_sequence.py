"""互动序列分析 — 三视角架构 Phase 0 基础设施。

本模块提供可审计的双方行为与互动证据,不做任何推断性结论。
所有推断(如"未承接""过度推进")由后续 InteractionFinding 承载,带 confidence 和来源。

核心概念:
    Turn — 一个发言轮次(连续同人消息合并)
    TurnPair — 一个 cue-response 对(可审计证据)

设计原则(codex批注):
    - 代码只产出可审计的证据(原文、统计、候选finding)
    - 推断性结论由Agent基于Wiki做最终关系解释
    - 不与ML系统的Layer 1/2/3混淆,本模块属于"三视角"的INTERACTION视角
"""
from __future__ import annotations

# 角色命名: self/other，对应三视角框架的 SELF/OTHER。
# 在 ML 层和 semantic.py 中等价为 me/her。
# JSONL 训练数据、format_behavior_input、target_role 参数统一用 me/her。

import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_SESSION_GAP_HOURS = 4  # 与 metrics.py 和 MetricsConfig.session_gap_hours 保持一致


@dataclass
class Turn:
    """一个发言轮次(连续同人消息合并)。

    这是可审计的客观结构,不含任何推断。
    timestamp_reliability:
        "reliable"  — 生产 SQLite 的真实聊天时间戳(ts > 0)
        "missing"   — 时间戳缺失(ts == 0)
        "synthetic" — 合成时间戳(看起来存在但不能解释为真实等待,Phase 0 不产生)
        "unknown"   — 来源未知(Phase 0 不产生)
    Phase 0 只面向生产 SQLite 的真实聊天时间;若未来支持外部教学案例,
    必须由输入来源提供 timestamp_reliability,不能从正数时间戳自行推断。
    """
    role: str
    ts: int
    contents: list[str]
    raw_count: int
    timestamp_reliability: str = "reliable"

    @property
    def content(self) -> str:
        return "\n".join(self.contents)

    @property
    def has_reliable_ts(self) -> bool:
        return self.timestamp_reliability == "reliable"


@dataclass
class TurnPair:
    """一个 cue-response 对(可审计证据,不含推断结论)。

    response_type 不在此结构中,它属于推断结论,
    由后续 InteractionFinding 承载,带 confidence 和来源。

    未响应 cue:
        has_response=False 时,response_* 字段为空,这是 pending_cues 最重要的输入。
        例如"对方最后一个邀约后,我一直没回复"。
        response_missing_reason:
            "session_end" — 会话结束,无后续 turn
            "window_end"  — 查询窗口结束(Phase 0 不产生,预留给 Phase 1+)
            ""            — 有响应

    timestamp_reliability:
        基于 cue 和 response(如有)的时间戳可靠性。
        两者都 reliable → "reliable";任一 missing → "missing"。
        has_response=False 时,基于 cue 的可靠性。
        在 missing/synthetic/unknown 时,延迟字段不参与任何延迟指标或 finding。
    """
    cue_role: str
    cue_ts: int
    cue_content: str
    response_role: str = ""
    response_ts: int = 0
    response_content: str = ""
    response_latency_sec: int = -1
    has_response: bool = True
    response_missing_reason: str = ""
    timestamp_reliability: str = "reliable"

    @property
    def has_reliable_latency(self) -> bool:
        return (
            self.has_response
            and self.response_latency_sec >= 0
            and self.timestamp_reliability == "reliable"
        )


def build_turns_from_messages(
    messages: list[dict],
    my_wxid: str,
) -> list[Turn]:
    """将消息列表按发言轮次合并为 Turn 序列。

    连续同人消息合并为一个 Turn,交替计数。
    复用 semantic.py 的 _build_turns 逻辑,但输出 Turn 对象。

    Args:
        messages: 消息列表,每条有 sender_id/is_mine, content, timestamp
        my_wxid: 本人 wxid,用于判断 role

    Returns:
        Turn 列表,按时间顺序
    """
    if not messages:
        return []

    turns: list[Turn] = []
    current_role: Optional[str] = None
    current_contents: list[str] = []
    current_ts: int = 0
    current_count: int = 0

    for msg in messages:
        is_mine = msg.get("is_mine", msg.get("sender_id") == my_wxid)
        role = "self" if is_mine else "other"
        content = msg.get("content", "") or ""
        ts = msg.get("timestamp", 0) or 0

        if role != current_role:
            if current_role is not None and current_contents:
                turns.append(Turn(
                    role=current_role,
                    ts=current_ts,
                    contents=list(current_contents),
                    raw_count=current_count,
                    timestamp_reliability="reliable" if current_ts > 0 else "missing",
                ))
            current_role = role
            current_contents = [content]
            current_ts = ts
            current_count = 1
        else:
            current_contents.append(content)
            current_count += 1

    if current_role is not None and current_contents:
        turns.append(Turn(
            role=current_role,
            ts=current_ts,
            contents=list(current_contents),
            raw_count=current_count,
            timestamp_reliability="reliable" if current_ts > 0 else "missing",
        ))

    return turns


def group_turns_by_session(
    turns: list[Turn],
    session_gap_hours: int = DEFAULT_SESSION_GAP_HOURS,
) -> list[list[Turn]]:
    """将 Turn 序列按会话分组。

    相邻两个 Turn 的时间间隔超过 session_gap_hours 视为新会话。
    无时间戳(ts=0)的 Turn 保守归入前一个会话(避免误拆)。

    Args:
        turns: Turn 列表,按时间顺序
        session_gap_hours: 会话间隔阈值(小时)

    Returns:
        会话列表,每个会话是一个 Turn 列表
    """
    if not turns:
        return []

    sessions: list[list[Turn]] = [[turns[0]]]
    gap_sec = session_gap_hours * 3600

    for prev, curr in zip(turns, turns[1:]):
        if prev.ts == 0 or curr.ts == 0:
            sessions[-1].append(curr)
        elif curr.ts - prev.ts > gap_sec:
            sessions.append([curr])
        else:
            sessions[-1].append(curr)

    return sessions


def build_turn_pairs_from_session(
    session_turns: list[Turn],
) -> list[TurnPair]:
    """从单个会话的 Turn 序列构建 TurnPair 列表。

    在会话内,相邻的不同角色 Turn 配对为 cue-response。
    会话末尾的 Turn 作为 cue 时没有 response,生成未响应 TurnPair
    (has_response=False, response_missing_reason="session_end"),
    这是 pending_cues 最重要的输入。

    单个 Turn 的会话不生成任何 TurnPair(无互动上下文)。

    Args:
        session_turns: 单个会话的 Turn 列表

    Returns:
        TurnPair 列表,末尾包含未响应 cue(如有)
    """
    if len(session_turns) < 2:
        return []

    pairs: list[TurnPair] = []

    for i in range(len(session_turns) - 1):
        cue = session_turns[i]
        response = session_turns[i + 1]

        if cue.role == response.role:
            continue

        if cue.ts > 0 and response.ts > 0:
            latency = max(0, response.ts - cue.ts)
        else:
            latency = -1

        ts_reliability = (
            "reliable"
            if cue.timestamp_reliability == "reliable"
            and response.timestamp_reliability == "reliable"
            else "missing"
        )

        pairs.append(TurnPair(
            cue_role=cue.role,
            cue_ts=cue.ts,
            cue_content=cue.content,
            response_role=response.role,
            response_ts=response.ts,
            response_content=response.content,
            response_latency_sec=latency,
            has_response=True,
            response_missing_reason="",
            timestamp_reliability=ts_reliability,
        ))

    # 末尾 cue:最后一个 Turn 作为 cue 时没有 response
    last_turn = session_turns[-1]
    pairs.append(TurnPair(
        cue_role=last_turn.role,
        cue_ts=last_turn.ts,
        cue_content=last_turn.content,
        response_role="",
        response_ts=0,
        response_content="",
        response_latency_sec=-1,
        has_response=False,
        response_missing_reason="session_end",
        timestamp_reliability=last_turn.timestamp_reliability,
    ))

    return pairs


def _query_messages(
    conn: sqlite3.Connection,
    contact_wxid: str,
    cutoff_ts: int,
) -> list[dict]:
    """查询指定时间后的文本消息。

    复用 semantic.py 的查询逻辑,字段格式保持一致。
    """
    rows = conn.execute(
        "SELECT id, sender_id, content, timestamp, type "
        "FROM messages WHERE conversation_id = ? AND type = 1 AND timestamp >= ? "
        "ORDER BY timestamp ASC",
        (contact_wxid, cutoff_ts),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "sender_id": row["sender_id"] or "",
            "content": row["content"] or "",
            "timestamp": row["timestamp"] or 0,
        }
        for row in rows
    ]


def extract_turn_pairs(
    conn: sqlite3.Connection,
    my_wxid: str,
    contact_wxid: str,
    window_days: int = 30,
    ref_date: Optional[datetime] = None,
    session_gap_hours: int = DEFAULT_SESSION_GAP_HOURS,
) -> list[TurnPair]:
    """提取 cue-response 对序列(纯证据,无推断)。

    按 session 分组,在每个 session 内按轮次配对。
    连续同人消息合并为一个 turn(复用 _build_turns 逻辑)。
    无时间戳/合成时间戳的消息:ts=0, latency=-1,标记为不可靠。

    Args:
        conn: SQLite 连接
        my_wxid: 本人 wxid
        contact_wxid: 联系人 wxid(或 conversation_id)
        window_days: 查询窗口(天)
        ref_date: 基准日期(默认 now)
        session_gap_hours: 会话间隔阈值(小时)

    Returns:
        TurnPair 列表,按时间顺序
    """
    if ref_date is None:
        ref_date = datetime.now()
    cutoff = int((ref_date - timedelta(days=window_days)).timestamp())

    messages = _query_messages(conn, contact_wxid, cutoff)
    if not messages:
        return []

    for msg in messages:
        msg["is_mine"] = msg["sender_id"] == my_wxid

    turns = build_turns_from_messages(messages, my_wxid)
    sessions = group_turns_by_session(turns, session_gap_hours)

    pairs: list[TurnPair] = []
    for session_turns in sessions:
        pairs.extend(build_turn_pairs_from_session(session_turns))

    return pairs


def extract_turns(
    conn: sqlite3.Connection,
    my_wxid: str,
    contact_wxid: str,
    window_days: int = 30,
    ref_date: Optional[datetime] = None,
) -> list[Turn]:
    """提取 Turn 序列(不配对,仅合并连续同人消息)。

    用于描述性统计,如发起频率、消息量分布等。

    Args:
        conn: SQLite 连接
        my_wxid: 本人 wxid
        contact_wxid: 联系人 wxid
        window_days: 查询窗口(天)
        ref_date: 基准日期

    Returns:
        Turn 列表,按时间顺序
    """
    if ref_date is None:
        ref_date = datetime.now()
    cutoff = int((ref_date - timedelta(days=window_days)).timestamp())

    messages = _query_messages(conn, contact_wxid, cutoff)
    if not messages:
        return []

    for msg in messages:
        msg["is_mine"] = msg["sender_id"] == my_wxid

    return build_turns_from_messages(messages, my_wxid)
