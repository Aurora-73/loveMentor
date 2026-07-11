"""关系阶段自动识别器。

基于 metrics + events + failure_archive 推断当前关系阶段。

阶段定义（STAGES）：
    未识别 → 初识 → 有基本互动 → 高频聊天 → 已约见 → 持续接触 → 暧昧推进 → 关系确认 → 退出/失败

识别优先级（从最终状态向前回溯）：
    1. 退出/失败：在失败档案中，或长期断联（>30 天）无恢复
    2. 关系确认：有 TOGETHER 事件
    3. 暧昧推进：有 FIRST_FLIRT/CONFESSION 事件，或强窗口+lover 模式+消息量充足
    4. 已约见：有 FIRST_DATE 事件
    5. 持续接触：长期稳定互动（消息>500，活跃天>20，最近互动<14 天）
    6. 高频聊天：近期高频互动（活跃天>10，最近<3 天，消息>50）
    7. 有基本互动：有持续但低频互动（消息>20，活跃天>3）
    8. 初识：有少量消息
    9. 未识别：无消息
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from engine.analyzers.events import detect_events, EventType
from engine.analyzers.metrics import compute_metrics_for_contact, SIGNAL_ORDER
from engine.config import Config
from engine.facts.failure_archive import load_all_failures
from engine.identity import IdentityPerson
from engine.models.stage import STAGES, StageState


def _stage_index(stage: str) -> int:
    """返回阶段在 STAGES 中的索引，未找到返回 -1。"""
    try:
        return STAGES.index(stage)
    except ValueError:
        return -1


def _next_stage(stage: str) -> str:
    """返回下一个阶段（退出/失败 和 关系确认 无下一阶段）。"""
    # 关系确认 和 退出/失败 都是终态，无下一阶段
    if stage in ("关系确认", "退出/失败"):
        return ""
    idx = _stage_index(stage)
    if idx < 0 or idx >= len(STAGES) - 1:
        return ""
    return STAGES[idx + 1]


def _is_in_failure_archive(person: IdentityPerson) -> bool:
    """检查联系人是否在失败档案中。"""
    try:
        cases = load_all_failures()
        if not cases:
            return False
        person_name = person.display_name
        person_aliases = {a.display_name for a in person.accounts if a.display_name}
        person_aliases.add(person_name)
        for case in cases:
            if case.person in person_aliases:
                return True
        return False
    except Exception:
        return False


def _has_event_type(events: list, event_type: EventType) -> bool:
    """检查事件列表中是否包含指定类型的事件。"""
    return any(e.event_type == event_type for e in events)


def _latest_event_date(events: list, event_type: EventType) -> str:
    """返回指定类型事件的最新日期。"""
    dates = [e.date for e in events if e.event_type == event_type]
    return max(dates) if dates else ""


def _days_since(date_str: str) -> int:
    """计算从 date_str（YYYY-MM-DD）到今天的天数。"""
    if not date_str:
        return 9999
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.now() - d).days
    except ValueError:
        return 9999


def _estimate_entered_at(events: list, stage: str) -> str:
    """估算进入当前阶段的日期。"""
    today = datetime.now().strftime("%Y-%m-%d")
    if stage == "关系确认":
        return _latest_event_date(events, EventType.TOGETHER) or today
    if stage == "暧昧推进":
        flirt_date = _latest_event_date(events, EventType.FIRST_FLIRT)
        confession_date = _latest_event_date(events, EventType.CONFESSION)
        candidates = [d for d in [flirt_date, confession_date] if d]
        return max(candidates) if candidates else today
    if stage == "已约见":
        return _latest_event_date(events, EventType.FIRST_DATE) or today
    if stage == "初识":
        first_chat_dates = [e.date for e in events if e.event_type == EventType.FIRST_CHAT]
        return min(first_chat_dates) if first_chat_dates else today
    return today


def recognize_stage(
    conn: sqlite3.Connection,
    config: Config,
    person: IdentityPerson,
) -> StageState:
    """识别联系人当前的关系阶段。

    Args:
        conn: SQLite 连接
        config: 项目配置
        person: 联系人身份

    Returns:
        StageState 对象，含 current_stage, next_stage, advancement_signals,
        blockers, is_stagnant, entered_at, days_in_current_stage
    """
    wxids = [a.wxid for a in person.accounts if a.wxid]
    if not wxids:
        return StageState(
            current_stage="未识别",
            entered_at=datetime.now().strftime("%Y-%m-%d"),
            days_in_current_stage=0,
            blockers=["无任何账号信息"],
        )

    # 检测事件
    events = detect_events(conn, person, disconnect_days=7)

    # 检查失败档案
    in_failure = _is_in_failure_archive(person)

    # 检查长期断联（>30 天无任何消息）
    placeholders = ",".join("?" for _ in wxids)
    row = conn.execute(
        f"""
        SELECT MAX(timestamp) as last_ts, COUNT(*) as total_count
        FROM messages
        WHERE conversation_id IN ({placeholders})
          AND type = 1
        """,
        tuple(wxids),
    ).fetchone()
    total_count = row["total_count"] if row else 0
    last_ts = row["last_ts"] if row else 0

    if total_count == 0:
        return StageState(
            current_stage="未识别",
            entered_at=datetime.now().strftime("%Y-%m-%d"),
            days_in_current_stage=0,
            blockers=["无任何消息记录"],
        )

    days_since_last_msg = 9999
    if last_ts:
        last_date = datetime.fromtimestamp(last_ts)
        days_since_last_msg = (datetime.now() - last_date).days

    # 1. 退出/失败
    if in_failure:
        return StageState(
            current_stage="退出/失败",
            entered_at=datetime.now().strftime("%Y-%m-%d"),
            days_in_current_stage=days_since_last_msg,
            is_stagnant=True,
            blockers=["已在失败档案中"],
        )
    if days_since_last_msg > 30:
        return StageState(
            current_stage="退出/失败",
            entered_at=last_date.strftime("%Y-%m-%d") if last_ts else "",
            days_in_current_stage=days_since_last_msg,
            is_stagnant=True,
            blockers=[f"已断联 {days_since_last_msg} 天"],
        )

    # 计算指标
    primary_wxid = wxids[0]
    primary_name = person.accounts[0].display_name if person.accounts else person.display_name
    metrics = compute_metrics_for_contact(conn, config, primary_wxid, primary_name)

    msg_count = int(metrics.msg_count.raw)
    active_days = int(metrics.active_days.raw)
    recent_days = metrics.recent.raw
    signal_level = metrics.signal_level
    interaction_pattern = metrics.interaction_pattern
    signal_strength = SIGNAL_ORDER.get(signal_level, 0)

    # 2. 关系确认
    if _has_event_type(events, EventType.TOGETHER):
        stage = "关系确认"
        entered_at = _estimate_entered_at(events, stage)
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="",
            advancement_signals=[],
            blockers=[],
        )

    # 3. 暧昧推进
    has_flirt = _has_event_type(events, EventType.FIRST_FLIRT)
    has_confession = _has_event_type(events, EventType.CONFESSION)
    is_strong_lover = (signal_level == "强窗口" and interaction_pattern == "lover" and msg_count > 100)
    if has_flirt or has_confession or is_strong_lover:
        stage = "暧昧推进"
        entered_at = _estimate_entered_at(events, stage)
        signals = []
        blockers = []
        if has_flirt:
            signals.append("已检测到初次暧昧事件")
        if has_confession:
            signals.append("已检测到表白事件")
        if is_strong_lover:
            signals.append(f"强窗口信号 + lover 互动模式（消息 {msg_count} 条）")
        if not _has_event_type(events, EventType.TOGETHER):
            blockers.append("尚未确定关系")
        if signal_strength < 3:
            blockers.append(f"当前信号等级 {signal_level}，建议提升互动质量")
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="关系确认",
            advancement_signals=signals,
            blockers=blockers,
        )

    # 4. 已约见
    if _has_event_type(events, EventType.FIRST_DATE):
        stage = "已约见"
        entered_at = _estimate_entered_at(events, stage)
        signals = []
        blockers = []
        if recent_days < 7:
            signals.append(f"约见后 {recent_days:.1f} 天内仍有互动")
        if signal_strength >= 3:
            signals.append(f"信号等级 {signal_level}，互动积极")
        if recent_days > 14:
            blockers.append(f"约见后已 {recent_days:.0f} 天无互动，可能冷却")
        if interaction_pattern == "lover":
            signals.append("互动模式为 lover，有升温潜力")
        else:
            blockers.append(f"互动模式 {interaction_pattern}，缺乏情感投入")
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="持续接触",
            advancement_signals=signals,
            blockers=blockers,
        )

    # 5. 持续接触（长期稳定）
    if msg_count > 500 and active_days > 20 and recent_days < 14:
        stage = "持续接触"
        entered_at = _estimate_entered_at(events, stage)
        signals = []
        blockers = []
        if signal_strength >= 3:
            signals.append(f"信号等级 {signal_level}，可考虑推进关系")
        if interaction_pattern == "lover":
            signals.append("互动模式为 lover，可尝试暧昧升级")
        if recent_days > 7:
            blockers.append(f"最近 {recent_days:.1f} 天互动减少，需重新激活")
        if not _has_event_type(events, EventType.FIRST_DATE):
            blockers.append("尚未约见，建议发起邀约")
        if signal_strength < 2:
            blockers.append(f"信号等级 {signal_level} 偏低，需提升互动质量")
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="暧昧推进",
            advancement_signals=signals,
            blockers=blockers,
        )

    # 6. 高频聊天
    if active_days > 10 and recent_days < 3 and msg_count > 50:
        stage = "高频聊天"
        entered_at = _estimate_entered_at(events, stage)
        signals = []
        blockers = []
        if signal_strength >= 3:
            signals.append(f"信号等级 {signal_level}，互动积极")
        if interaction_pattern == "lover":
            signals.append("互动模式为 lover，情感投入高")
        if msg_count > 200:
            signals.append(f"消息量 {msg_count} 条，可考虑邀约")
        if recent_days >= 3:
            blockers.append("互动频率可能下降")
        if signal_strength < 2:
            blockers.append(f"信号等级 {signal_level}，需提升互动质量")
        if not _has_event_type(events, EventType.FIRST_DATE):
            blockers.append("尚未约见，建议抓住窗口期发起邀约")
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="已约见",
            advancement_signals=signals,
            blockers=blockers,
        )

    # 7. 有基本互动
    if msg_count > 20 and active_days > 3:
        stage = "有基本互动"
        entered_at = _estimate_entered_at(events, stage)
        signals = []
        blockers = []
        if recent_days < 7:
            signals.append("近期有互动，可提升频率")
        if signal_strength >= 2:
            signals.append(f"信号等级 {signal_level}，有升温潜力")
        if recent_days > 14:
            blockers.append(f"已 {recent_days:.0f} 天无互动，关系冷却")
        if msg_count < 50:
            blockers.append(f"消息量 {msg_count} 条偏少，需增加互动")
        if active_days < 7:
            blockers.append(f"活跃天数 {active_days} 天偏少，需持续互动")
        return StageState(
            current_stage=stage,
            entered_at=entered_at,
            days_in_current_stage=_days_since(entered_at),
            next_stage="高频聊天",
            advancement_signals=signals,
            blockers=blockers,
        )

    # 8. 初识
    stage = "初识"
    entered_at = _estimate_entered_at(events, stage)
    signals = []
    blockers = []
    if msg_count > 0:
        signals.append("已建立首次联系")
    if recent_days > 14:
        blockers.append(f"首次联系后已 {recent_days:.0f} 天无后续")
    if msg_count < 5:
        blockers.append("消息量极少，需主动发起话题")
    return StageState(
        current_stage=stage,
        entered_at=entered_at,
        days_in_current_stage=_days_since(entered_at),
        next_stage="有基本互动",
        advancement_signals=signals,
        blockers=blockers,
    )


def is_stagnant(stage_state: StageState) -> bool:
    """判断是否停滞。

    停滞判定规则：
    - 已约见/持续接触/暧昧推进：超过 30 天无进展
    - 高频聊天/有基本互动：超过 14 天无进展
    - 初识：超过 7 天无进展
    - 关系确认/退出/失败：不判定停滞
    """
    stage = stage_state.current_stage
    days = stage_state.days_in_current_stage

    if stage in ("关系确认", "退出/失败", "未识别"):
        return False

    thresholds = {
        "初识": 7,
        "有基本互动": 14,
        "高频聊天": 14,
        "已约见": 30,
        "持续接触": 30,
        "暧昧推进": 30,
    }
    threshold = thresholds.get(stage, 30)
    return days > threshold
