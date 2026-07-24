"""events.py 单元测试。

覆盖 EventType / TimelineCategory / Event / detect_events / detect_milestones /
compute_timeline / timeline_to_dict / format_events / format_timeline。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from engine.analyzers.events import (
    EVENT_CATEGORY_MAP,
    Event,
    EventType,
    TimelineCategory,
    compute_timeline,
    detect_events,
    detect_milestones,
    format_events,
    format_timeline,
    timeline_to_dict,
)
from engine.identity.directory import IdentityAccount, IdentityPerson


# ── 工具 fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def make_person():
    """构造 IdentityPerson 的工厂 fixture。"""
    def _make(wxid: str = "wxid_alice", display_name: str = "Alice",
              person_id: str = "person_alice"):
        account = IdentityAccount(
            id=f"acct_{wxid}",
            person_id=person_id,
            wxid=wxid,
            conversation_id=wxid,
            display_name=display_name,
        )
        return IdentityPerson(
            id=person_id,
            display_name=display_name,
            accounts=[account],
        )
    return _make


@pytest.fixture
def insert_messages(tmp_db):
    """插入测试消息的 helper。"""
    _counter = 0

    def _insert(conversation_id: str, sender_id: str, content: str,
                timestamp: int, msg_type: int = 1):
        nonlocal _counter
        _counter += 1
        msg_id = f"evt_msg_{_counter}"
        tmp_db.execute(
            """INSERT OR IGNORE INTO messages
               (id, conversation_id, sender_id, timestamp, type, content, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, conversation_id, sender_id, timestamp, msg_type, content, timestamp),
        )
        tmp_db.commit()
        return msg_id

    return _insert


# ── Event / Enum ─────────────────────────────────────────────────────────────

class TestEventModel:
    def test_event_to_dict_basic(self):
        e = Event(
            event_type=EventType.FIRST_CHAT,
            date="2026-07-24",
            detail="首次聊天",
        )
        d = e.to_dict()
        assert d["event_type"] == "首次聊天"
        assert d["date"] == "2026-07-24"
        assert d["detail"] == "首次聊天"
        assert d["confidence"] == 1.0
        assert d["category"] == "沟通动态"  # 默认值
        assert d["metadata"] == {}

    def test_event_to_dict_with_metadata(self):
        e = Event(
            event_type=EventType.MILESTONE,
            date="2026-07-24",
            detail="认识 100 天",
            confidence=0.8,
            category=TimelineCategory.MILESTONE,
            metadata={"milestone_type": "days", "days": 100},
        )
        d = e.to_dict()
        assert d["confidence"] == 0.8
        assert d["category"] == "里程碑"
        assert d["metadata"]["days"] == 100

    def test_event_default_category_is_communication(self):
        e = Event(event_type=EventType.DISCONNECT, date="2026-07-24", detail="x")
        assert e.category == TimelineCategory.COMMUNICATION

    def test_event_default_confidence_is_1(self):
        e = Event(event_type=EventType.FIRST_CHAT, date="2026-07-24", detail="x")
        assert e.confidence == 1.0

    def test_event_default_metadata_empty(self):
        e = Event(event_type=EventType.FIRST_CHAT, date="2026-07-24", detail="x")
        assert e.metadata == {}


class TestEventCategoryMap:
    def test_milestone_events_mapped_to_milestone(self):
        assert EVENT_CATEGORY_MAP[EventType.FIRST_CHAT] == TimelineCategory.MILESTONE
        assert EVENT_CATEGORY_MAP[EventType.FIRST_DATE] == TimelineCategory.MILESTONE
        assert EVENT_CATEGORY_MAP[EventType.MILESTONE] == TimelineCategory.MILESTONE
        assert EVENT_CATEGORY_MAP[EventType.ANNIVERSARY] == TimelineCategory.MILESTONE

    def test_relationship_events_mapped(self):
        assert EVENT_CATEGORY_MAP[EventType.FIRST_FLIRT] == TimelineCategory.RELATIONSHIP
        assert EVENT_CATEGORY_MAP[EventType.CONFESSION] == TimelineCategory.RELATIONSHIP
        assert EVENT_CATEGORY_MAP[EventType.TOGETHER] == TimelineCategory.RELATIONSHIP

    def test_communication_events_mapped(self):
        assert EVENT_CATEGORY_MAP[EventType.FREQUENCY_UP] == TimelineCategory.COMMUNICATION
        assert EVENT_CATEGORY_MAP[EventType.FREQUENCY_DOWN] == TimelineCategory.COMMUNICATION
        assert EVENT_CATEGORY_MAP[EventType.DISCONNECT] == TimelineCategory.COMMUNICATION
        assert EVENT_CATEGORY_MAP[EventType.RECONNECT] == TimelineCategory.COMMUNICATION

    def test_signal_events_mapped(self):
        assert EVENT_CATEGORY_MAP[EventType.SIGNAL_LEVEL_UP] == TimelineCategory.SIGNAL
        assert EVENT_CATEGORY_MAP[EventType.SIGNAL_LEVEL_DOWN] == TimelineCategory.SIGNAL

    def test_info_events_mapped(self):
        assert EVENT_CATEGORY_MAP[EventType.INFO_UPDATE] == TimelineCategory.INFO


# ── detect_events ────────────────────────────────────────────────────────────

class TestDetectEvents:
    def test_empty_accounts_returns_empty(self, tmp_db, make_person):
        """person.accounts 为空时返回空列表。"""
        person = IdentityPerson(id="p", display_name="X", accounts=[])
        assert detect_events(tmp_db, person) == []

    def test_no_messages_returns_empty(self, tmp_db, make_person):
        person = make_person()
        assert detect_events(tmp_db, person) == []

    def test_first_chat_event(self, tmp_db, make_person, insert_messages):
        """单条消息触发 FIRST_CHAT 事件。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "你好", 1700000000)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.FIRST_CHAT in types
        first_chat = next(e for e in events if e.event_type == EventType.FIRST_CHAT)
        assert first_chat.date == datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d")
        assert first_chat.confidence == 1.0
        assert first_chat.category == TimelineCategory.MILESTONE

    def test_single_day_no_disconnect(self, tmp_db, make_person, insert_messages):
        """只有一天的消息不产生断联事件。"""
        person = make_person()
        # 同一天多条消息
        for i in range(5):
            insert_messages("wxid_alice", "wxid_alice", f"msg{i}", 1700000000 + i * 60)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.DISCONNECT not in types
        assert EventType.RECONNECT not in types

    def test_disconnect_7_days(self, tmp_db, make_person, insert_messages):
        """7 天以上无消息触发断联事件，断联后再次有消息触发 RECONNECT。

        代码逻辑：gap >= 7 标记 DISCONNECT + in_disconnect=True；
        后续有消息（gap < 7）且 in_disconnect=True 时触发 RECONNECT。
        所以需要 3 个时间点：day1 → day8（断联）→ day9（恢复）。
        """
        person = make_person()
        # 第一天
        insert_messages("wxid_alice", "wxid_alice", "hi", 1700000000)
        # 8 天后（gap=8 >= 7，触发 DISCONNECT）
        insert_messages("wxid_alice", "wxid_alice", "回来啦",
                        1700000000 + 8 * 86400)
        # 第 9 天（gap=1 < 7，且 in_disconnect=True → 触发 RECONNECT）
        insert_messages("wxid_alice", "wxid_alice", "继续聊",
                        1700000000 + 9 * 86400)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.DISCONNECT in types
        assert EventType.RECONNECT in types

    def test_disconnect_custom_threshold(self, tmp_db, make_person, insert_messages):
        """disconnect_days=3 触发更短间隔的断联。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "hi", 1700000000)
        # 4 天后（默认 7 天不会触发，但 disconnect_days=3 会）
        insert_messages("wxid_alice", "wxid_alice", "回来",
                        1700000000 + 4 * 86400)
        events = detect_events(tmp_db, person, disconnect_days=3)
        types = [e.event_type for e in events]
        assert EventType.DISCONNECT in types

    def test_disconnect_below_threshold_no_event(self, tmp_db, make_person, insert_messages):
        """gap < disconnect_days 不触发断联。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "hi", 1700000000)
        # 5 天后（默认 7 天不会触发）
        insert_messages("wxid_alice", "wxid_alice", "回来",
                        1700000000 + 5 * 86400)
        events = detect_events(tmp_db, person, disconnect_days=7)
        types = [e.event_type for e in events]
        assert EventType.DISCONNECT not in types

    def test_flirt_keyword_detection(self, tmp_db, make_person, insert_messages):
        """暧昧关键词触发 FIRST_FLIRT。

        注意：detect_events 在 `len(sorted_days) < 2` 时提前 return，
        跳过关键词检测，所以需要至少跨 2 天的消息。
        """
        person = make_person()
        # day1 普通消息
        insert_messages("wxid_alice", "wxid_alice", "你好", 1700000000)
        # day2 暧昧消息
        insert_messages("wxid_alice", "wxid_alice", "想你啦",
                        1700000000 + 86400)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.FIRST_FLIRT in types
        flirt = next(e for e in events if e.event_type == EventType.FIRST_FLIRT)
        assert flirt.confidence == 0.6
        assert flirt.category == TimelineCategory.RELATIONSHIP

    def test_confession_keyword_detection(self, tmp_db, make_person, insert_messages):
        """表白关键词触发 CONFESSION。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "你好", 1700000000)
        insert_messages("wxid_alice", "wxid_alice", "我喜欢你",
                        1700000000 + 86400)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.CONFESSION in types
        confession = next(e for e in events if e.event_type == EventType.CONFESSION)
        assert confession.confidence == 0.5

    def test_together_keyword_detection(self, tmp_db, make_person, insert_messages):
        """确定关系关键词触发 TOGETHER。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "你好", 1700000000)
        insert_messages("wxid_alice", "wxid_alice", "我们在一起吧",
                        1700000000 + 86400)
        events = detect_events(tmp_db, person)
        types = [e.event_type for e in events]
        assert EventType.TOGETHER in types

    def test_flirt_only_first_occurrence(self, tmp_db, make_person, insert_messages):
        """多条暧昧消息只产生一次 FIRST_FLIRT。"""
        person = make_person()
        # day1 第一条暧昧
        insert_messages("wxid_alice", "wxid_alice", "想你", 1700000000)
        # day2 后续暧昧（不应再触发）
        insert_messages("wxid_alice", "wxid_alice", "宝贝",
                        1700000000 + 86400)
        insert_messages("wxid_alice", "wxid_alice", "亲爱的",
                        1700000000 + 86400 + 60)
        events = detect_events(tmp_db, person)
        flirt_count = sum(1 for e in events if e.event_type == EventType.FIRST_FLIRT)
        assert flirt_count == 1

    def test_events_sorted_by_date(self, tmp_db, make_person, insert_messages):
        """事件按日期正序排列。"""
        person = make_person()
        # 跨 3 天
        insert_messages("wxid_alice", "wxid_alice", "day1", 1700000000)
        insert_messages("wxid_alice", "wxid_alice", "day2", 1700086400)
        insert_messages("wxid_alice", "wxid_alice", "day3", 1700172800)
        events = detect_events(tmp_db, person)
        dates = [e.date for e in events]
        assert dates == sorted(dates)

    def test_events_category_auto_filled(self, tmp_db, make_person, insert_messages):
        """所有事件的 category 应被 EVENT_CATEGORY_MAP 自动填充。"""
        person = make_person()
        insert_messages("wxid_alice", "wxid_alice", "hi", 1700000000)
        events = detect_events(tmp_db, person)
        for e in events:
            expected = EVENT_CATEGORY_MAP.get(e.event_type, TimelineCategory.COMMUNICATION)
            assert e.category == expected

    def test_multi_account_person(self, tmp_db, make_person, insert_messages):
        """多账号 person：查询所有账号的消息。"""
        account1 = IdentityAccount(
            id="acct1", person_id="p1", wxid="wxid_a1",
            conversation_id="wxid_a1", display_name="A1",
        )
        account2 = IdentityAccount(
            id="acct2", person_id="p1", wxid="wxid_a2",
            conversation_id="wxid_a2", display_name="A2",
        )
        person = IdentityPerson(id="p1", display_name="A1", accounts=[account1, account2])
        insert_messages("wxid_a1", "wxid_a1", "from_a1", 1700000000)
        insert_messages("wxid_a2", "wxid_a2", "from_a2", 1700000060)
        events = detect_events(tmp_db, person)
        # 至少有 FIRST_CHAT
        assert any(e.event_type == EventType.FIRST_CHAT for e in events)

    def test_only_type_1_messages_queried(self, tmp_db, make_person, insert_messages):
        """detect_events 只查询 type=1 文本消息。

        type=3 图片消息不会被查询，所以 "想你" 关键词只可能来自 type=1 消息。
        跨 2 天以满足 detect_events 的 `len(sorted_days) >= 2` 前置条件。
        """
        person = make_person()
        # day1 type=3 图片消息（不应被检测）
        insert_messages("wxid_alice", "wxid_alice", "[图片]", 1700000000, msg_type=3)
        # day1 type=1 普通文本（让 sorted_days 长度足够）
        insert_messages("wxid_alice", "wxid_alice", "你好", 1700000000, msg_type=1)
        # day2 type=1 含暧昧关键词
        insert_messages("wxid_alice", "wxid_alice", "想你",
                        1700000000 + 86400, msg_type=1)
        events = detect_events(tmp_db, person)
        flirt_events = [e for e in events if e.event_type == EventType.FIRST_FLIRT]
        assert len(flirt_events) == 1


# ── detect_milestones ────────────────────────────────────────────────────────

class TestDetectMilestones:
    def test_empty_accounts(self, tmp_db):
        person = IdentityPerson(id="p", display_name="X", accounts=[])
        assert detect_milestones(tmp_db, person) == []

    def test_no_messages(self, tmp_db, make_person):
        person = make_person()
        assert detect_milestones(tmp_db, person) == []

    def test_30_days_milestone(self, tmp_db, make_person, insert_messages):
        """认识 30 天里程碑（消息起始日 +30 天已过去）。"""
        person = make_person()
        # 60 天前的消息
        old_ts = int((datetime.now() - timedelta(days=60)).timestamp())
        insert_messages("wxid_alice", "wxid_alice", "hi", old_ts)
        events = detect_milestones(tmp_db, person)
        milestone_days = [
            e.metadata.get("days")
            for e in events
            if e.metadata.get("milestone_type") == "days"
        ]
        assert 30 in milestone_days

    def test_100_days_milestone(self, tmp_db, make_person, insert_messages):
        """认识 100 天里程碑。"""
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=150)).timestamp())
        insert_messages("wxid_alice", "wxid_alice", "hi", old_ts)
        events = detect_milestones(tmp_db, person)
        milestone_days = [
            e.metadata.get("days")
            for e in events
            if e.metadata.get("milestone_type") == "days"
        ]
        assert 30 in milestone_days
        assert 100 in milestone_days
        assert 365 not in milestone_days

    def test_365_days_milestone(self, tmp_db, make_person, insert_messages):
        """认识 365 天里程碑。"""
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=400)).timestamp())
        insert_messages("wxid_alice", "wxid_alice", "hi", old_ts)
        events = detect_milestones(tmp_db, person)
        milestone_days = [
            e.metadata.get("days")
            for e in events
            if e.metadata.get("milestone_type") == "days"
        ]
        assert 365 in milestone_days

    def test_message_count_milestone_100(self, tmp_db, make_person, insert_messages):
        """消息数破 100 里程碑。"""
        person = make_person()
        for i in range(150):
            insert_messages("wxid_alice", "wxid_alice", f"msg{i}", 1700000000 + i)
        events = detect_milestones(tmp_db, person)
        counts = [
            e.metadata.get("count")
            for e in events
            if e.metadata.get("milestone_type") == "message_count"
        ]
        assert 100 in counts

    def test_message_count_milestone_500(self, tmp_db, make_person, insert_messages):
        person = make_person()
        for i in range(600):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", 1700000000 + i)
        events = detect_milestones(tmp_db, person)
        counts = [
            e.metadata.get("count")
            for e in events
            if e.metadata.get("milestone_type") == "message_count"
        ]
        assert 100 in counts
        assert 500 in counts
        assert 1000 not in counts

    def test_milestones_sorted_by_date(self, tmp_db, make_person, insert_messages):
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=100)).timestamp())
        for i in range(150):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", old_ts + i)
        events = detect_milestones(tmp_db, person)
        dates = [e.date for e in events]
        assert dates == sorted(dates)

    def test_milestone_category(self, tmp_db, make_person, insert_messages):
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=60)).timestamp())
        insert_messages("wxid_alice", "wxid_alice", "hi", old_ts)
        events = detect_milestones(tmp_db, person)
        for e in events:
            assert e.category == TimelineCategory.MILESTONE


# ── compute_timeline ─────────────────────────────────────────────────────────

class TestComputeTimeline:
    def test_empty_returns_empty(self, tmp_db, make_person):
        person = make_person()
        assert compute_timeline(tmp_db, person) == []

    def test_includes_detect_events_and_milestones(self, tmp_db, make_person, insert_messages):
        """默认包含 detect_events 和 detect_milestones 的结果。"""
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=60)).timestamp())
        for i in range(150):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", old_ts + i * 60)
        timeline = compute_timeline(tmp_db, person)
        types = {e.event_type for e in timeline}
        # 应同时有 FIRST_CHAT 和 MILESTONE
        assert EventType.FIRST_CHAT in types
        assert EventType.MILESTONE in types

    def test_exclude_milestones(self, tmp_db, make_person, insert_messages):
        """include_milestones=False 不包含里程碑。"""
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=60)).timestamp())
        for i in range(150):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", old_ts + i * 60)
        timeline = compute_timeline(tmp_db, person, include_milestones=False)
        types = {e.event_type for e in timeline}
        assert EventType.MILESTONE not in types
        # FIRST_CHAT 来自 detect_events，仍应存在
        assert EventType.FIRST_CHAT in types

    def test_category_filter(self, tmp_db, make_person, insert_messages):
        """categories 过滤只返回指定分类的事件。"""
        person = make_person()
        old_ts = int((datetime.now() - timedelta(days=60)).timestamp())
        for i in range(150):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", old_ts + i * 60)
        # 只要 MILESTONE 分类
        timeline = compute_timeline(
            tmp_db, person, categories=[TimelineCategory.MILESTONE]
        )
        for e in timeline:
            assert e.category == TimelineCategory.MILESTONE

    def test_max_events_limit(self, tmp_db, make_person, insert_messages):
        """max_events 限制返回事件数。"""
        person = make_person()
        # 制造大量事件：多天 + 多个里程碑
        old_ts = int((datetime.now() - timedelta(days=400)).timestamp())
        for i in range(2000):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", old_ts + i * 60)
        timeline = compute_timeline(tmp_db, person, max_events=5)
        assert len(timeline) <= 5

    def test_sorted_ascending_by_date(self, tmp_db, make_person, insert_messages):
        """compute_timeline 返回的事件按日期正序排列。"""
        person = make_person()
        for i in range(10):
            insert_messages("wxid_alice", "wxid_alice", f"m{i}", 1700000000 + i * 86400)
        timeline = compute_timeline(tmp_db, person)
        dates = [e.date for e in timeline]
        assert dates == sorted(dates)


# ── timeline_to_dict ─────────────────────────────────────────────────────────

class TestTimelineToDict:
    def test_empty_list(self):
        assert timeline_to_dict([]) == []

    def test_converts_events(self):
        events = [
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="首聊"),
            Event(event_type=EventType.MILESTONE, date="2026-07-02", detail="破百",
                  category=TimelineCategory.MILESTONE,
                  metadata={"milestone_type": "message_count", "count": 100}),
        ]
        result = timeline_to_dict(events)
        assert len(result) == 2
        assert result[0]["event_type"] == "首次聊天"
        assert result[1]["metadata"]["count"] == 100


# ── format_events ────────────────────────────────────────────────────────────

class TestFormatEvents:
    def test_empty_returns_placeholder(self):
        assert format_events([]) == "(未检测到事件)"

    def test_basic_format(self):
        events = [
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="首聊"),
        ]
        out = format_events(events)
        assert "[2026-07-01]" in out
        assert "首次聊天" in out
        assert "首聊" in out

    def test_confidence_shown_when_below_1(self):
        e = Event(
            event_type=EventType.FIRST_FLIRT, date="2026-07-01",
            detail="x", confidence=0.6,
            category=TimelineCategory.RELATIONSHIP,
        )
        out = format_events([e])
        assert "60%" in out

    def test_confidence_hidden_when_1(self):
        e = Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="x")
        out = format_events([e])
        assert "100%" not in out

    def test_category_shown_when_not_communication(self):
        e = Event(
            event_type=EventType.MILESTONE, date="2026-07-01", detail="x",
            category=TimelineCategory.MILESTONE,
        )
        out = format_events([e])
        assert "[里程碑]" in out

    def test_category_hidden_when_communication(self):
        e = Event(
            event_type=EventType.DISCONNECT, date="2026-07-01", detail="x",
            category=TimelineCategory.COMMUNICATION,
        )
        out = format_events([e])
        assert "[沟通动态]" not in out


# ── format_timeline ──────────────────────────────────────────────────────────

class TestFormatTimeline:
    def test_empty_returns_placeholder(self):
        assert format_timeline([]) == "(暂无时间线事件)"

    def test_group_by_month(self):
        events = [
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="A"),
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-15", detail="B"),
            Event(event_type=EventType.FIRST_CHAT, date="2026-06-01", detail="C"),
        ]
        out = format_timeline(events, group_by_month=True)
        # 两个月份标题
        assert "## 2026-07" in out
        assert "## 2026-06" in out
        # 按月倒序
        assert out.index("## 2026-07") < out.index("## 2026-06")

    def test_no_group_by_month_falls_back_to_format_events(self):
        events = [
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="A"),
        ]
        out = format_timeline(events, group_by_month=False)
        assert "[2026-07-01]" in out
        assert "## " not in out

    def test_date_truncated_in_grouped_view(self):
        """group_by_month=True 时日期只显示 MM-DD。"""
        e = Event(event_type=EventType.FIRST_CHAT, date="2026-07-15", detail="hello")
        out = format_timeline([e], group_by_month=True)
        # 日期显示为 07-15（去掉年份前缀）
        assert "07-15" in out
        assert "2026-07-15" not in out

    def test_month_count_in_header(self):
        events = [
            Event(event_type=EventType.FIRST_CHAT, date="2026-07-01", detail="A"),
            Event(event_type=EventType.DISCONNECT, date="2026-07-15", detail="B"),
        ]
        out = format_timeline(events, group_by_month=True)
        assert "## 2026-07（2 件）" in out
