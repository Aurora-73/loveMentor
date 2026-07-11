"""关系阶段自动识别器单元测试。

覆盖 9 个阶段的识别逻辑、停滞判定、推进信号和阻碍识别。
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from engine.analyzers.stage_recognizer import (
    recognize_stage,
    is_stagnant,
    _stage_index,
    _next_stage,
    _days_since,
    _has_event_type,
)
from engine.analyzers.events import Event, EventType, TimelineCategory
from engine.identity import IdentityPerson, IdentityAccount
from engine.models.stage import STAGES, StageState


# ── 工具函数测试 ─────────────────────────────────────────────────────────────


class TestHelpers:
    def test_stage_index_known(self):
        assert _stage_index("未识别") == 0
        assert _stage_index("关系确认") == 7
        assert _stage_index("退出/失败") == 8

    def test_stage_index_unknown(self):
        assert _stage_index("不存在") == -1

    def test_next_stage_normal(self):
        assert _next_stage("初识") == "有基本互动"
        assert _next_stage("高频聊天") == "已约见"

    def test_next_stage_terminal(self):
        """退出/失败 和 关系确认 是终态。"""
        assert _next_stage("退出/失败") == ""
        assert _next_stage("关系确认") == ""

    def test_next_stage_unknown(self):
        assert _next_stage("不存在") == ""

    def test_days_since_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        assert _days_since(today) == 0

    def test_days_since_past(self):
        past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        assert _days_since(past) == 10

    def test_days_since_empty(self):
        assert _days_since("") == 9999

    def test_days_since_invalid(self):
        assert _days_since("invalid") == 9999

    def test_has_event_type_true(self):
        events = [Event(event_type=EventType.FIRST_CHAT, date="2026-01-01", detail="test")]
        assert _has_event_type(events, EventType.FIRST_CHAT) is True

    def test_has_event_type_false(self):
        events = [Event(event_type=EventType.FIRST_CHAT, date="2026-01-01", detail="test")]
        assert _has_event_type(events, EventType.TOGETHER) is False

    def test_has_event_type_empty(self):
        assert _has_event_type([], EventType.FIRST_CHAT) is False


# ── is_stagnant 测试 ──────────────────────────────────────────────────────────


class TestIsStagnant:
    def test_terminal_not_stagnant(self):
        """关系确认 和 退出/失败 不判定停滞。"""
        s1 = StageState(current_stage="关系确认", days_in_current_stage=999)
        s2 = StageState(current_stage="退出/失败", days_in_current_stage=999)
        assert is_stagnant(s1) is False
        assert is_stagnant(s2) is False

    def test_未识别_not_stagnant(self):
        s = StageState(current_stage="未识别", days_in_current_stage=999)
        assert is_stagnant(s) is False

    def test_初识_stagnant_after_7_days(self):
        s = StageState(current_stage="初识", days_in_current_stage=8)
        assert is_stagnant(s) is True

    def test_初识_not_stagnant_within_7_days(self):
        s = StageState(current_stage="初识", days_in_current_stage=5)
        assert is_stagnant(s) is False

    def test_高频聊天_stagnant_after_14_days(self):
        s = StageState(current_stage="高频聊天", days_in_current_stage=15)
        assert is_stagnant(s) is True

    def test_暧昧推进_stagnant_after_30_days(self):
        s = StageState(current_stage="暧昧推进", days_in_current_stage=31)
        assert is_stagnant(s) is True

    def test_暧昧推进_not_stagnant_within_30_days(self):
        s = StageState(current_stage="暧昧推进", days_in_current_stage=25)
        assert is_stagnant(s) is False


# ── recognize_stage 集成测试 ──────────────────────────────────────────────────


def _make_person(person_id="p1", display_name="测试", wxid="wxid_test"):
    """创建测试用 IdentityPerson。"""
    account = IdentityAccount(
        id=f"acct_{wxid}",
        person_id=person_id,
        wxid=wxid,
        conversation_id=wxid,
        display_name=display_name,
    )
    return IdentityPerson(id=person_id, display_name=display_name, accounts=[account])


class TestRecognizeStage:
    def test_no_accounts(self, tmp_db, test_config):
        """无账号 → 未识别。"""
        person = IdentityPerson(id="p1", display_name="空", accounts=[])
        result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "未识别"
        assert "无任何账号信息" in result.blockers

    def test_no_messages(self, tmp_db, test_config):
        """有账号但无消息 → 未识别。"""
        person = _make_person()
        result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "未识别"
        assert "无任何消息记录" in result.blockers

    def test_initial_初识(self, tmp_db, test_config, insert_messages, now_ts):
        """少量消息 → 初识。"""
        wxid = "wxid_test"
        person = _make_person(wxid=wxid)
        insert_messages(wxid, "wxid_testuser", "你好", now_ts - 100)
        insert_messages(wxid, wxid, "嗨", now_ts - 50)
        result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "初识"
        assert result.next_stage == "有基本互动"

    def test_退出失败_long_disconnect(self, tmp_db, test_config, insert_messages):
        """30 天以上无消息 → 退出/失败。"""
        wxid = "wxid_test"
        person = _make_person(wxid=wxid)
        # 40 天前的消息
        old_ts = int((datetime.now() - timedelta(days=40)).timestamp())
        insert_messages(wxid, "wxid_testuser", "old msg", old_ts)
        result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "退出/失败"
        assert result.is_stagnant is True
        assert "断联" in result.blockers[0]

    def test_退出失败_in_failure_archive(self, tmp_db, test_config, insert_messages, now_ts):
        """在失败档案中 → 退出/失败。"""
        wxid = "wxid_test"
        person = _make_person(display_name="失败案例", wxid=wxid)
        insert_messages(wxid, "wxid_testuser", "hi", now_ts - 100)

        # mock failure archive
        from engine.models.failure import FailureCase
        fake_case = FailureCase(person="失败案例", date="2026-06-01", stage="暧昧推进")
        with patch("engine.analyzers.stage_recognizer.load_all_failures", return_value=[fake_case]):
            result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "退出/失败"
        assert "失败档案" in result.blockers[0]


class TestRecognizeStageStages:
    """测试各阶段的识别（使用 mock 避免复杂指标计算）。"""

    def test_关系确认_with_together_event(self, tmp_db, test_config, insert_messages, now_ts):
        """有 TOGETHER 事件 → 关系确认。"""
        wxid = "wxid_test"
        person = _make_person(wxid=wxid)
        insert_messages(wxid, "wxid_testuser", "在一起吧", now_ts - 100)

        # mock detect_events 返回 TOGETHER 事件
        together_event = Event(
            event_type=EventType.TOGETHER,
            date="2026-06-15",
            detail="确定关系",
            category=TimelineCategory.RELATIONSHIP,
        )
        with patch("engine.analyzers.stage_recognizer.detect_events", return_value=[together_event]):
            result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "关系确认"
        assert result.next_stage == ""

    def test_暧昧推进_with_flirt_event(self, tmp_db, test_config, insert_messages, now_ts):
        """有 FIRST_FLIRT 事件 → 暧昧推进。"""
        wxid = "wxid_test"
        person = _make_person(wxid=wxid)
        for i in range(5):
            insert_messages(wxid, "wxid_testuser", f"msg_{i}", now_ts - i * 100)

        flirt_event = Event(
            event_type=EventType.FIRST_FLIRT,
            date="2026-06-20",
            detail="初次暧昧",
            category=TimelineCategory.RELATIONSHIP,
        )
        with patch("engine.analyzers.stage_recognizer.detect_events", return_value=[flirt_event]):
            result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "暧昧推进"
        assert result.next_stage == "关系确认"
        assert any("暧昧" in s for s in result.advancement_signals)

    def test_已约见_with_first_date_event(self, tmp_db, test_config, insert_messages, now_ts):
        """有 FIRST_DATE 事件 → 已约见。"""
        wxid = "wxid_test"
        person = _make_person(wxid=wxid)
        for i in range(5):
            insert_messages(wxid, "wxid_testuser", f"msg_{i}", now_ts - i * 100)

        date_event = Event(
            event_type=EventType.FIRST_DATE,
            date="2026-06-10",
            detail="首次约见",
            category=TimelineCategory.MILESTONE,
        )
        with patch("engine.analyzers.stage_recognizer.detect_events", return_value=[date_event]):
            result = recognize_stage(tmp_db, test_config, person)
        assert result.current_stage == "已约见"
        assert result.next_stage == "持续接触"


class TestStageStateModel:
    def test_stage_state_to_dict(self):
        s = StageState(
            current_stage="高频聊天",
            next_stage="已约见",
            entered_at="2026-06-01",
            days_in_current_stage=10,
            is_stagnant=False,
            advancement_signals=["信号1"],
            blockers=["阻碍1"],
        )
        d = s.to_dict()
        assert d["current_stage"] == "高频聊天"
        assert d["next_stage"] == "已约见"
        assert d["advancement_signals"] == ["信号1"]
        assert d["blockers"] == ["阻碍1"]

    def test_stage_state_from_dict(self):
        d = {
            "current_stage": "暧昧推进",
            "next_stage": "关系确认",
            "entered_at": "2026-06-01",
            "days_in_current_stage": 15,
            "is_stagnant": False,
            "advancement_signals": ["a"],
            "blockers": ["b"],
        }
        s = StageState.from_dict(d)
        assert s.current_stage == "暧昧推进"
        assert s.days_in_current_stage == 15

    def test_stages_list_complete(self):
        """STAGES 列表包含 9 个阶段。"""
        assert len(STAGES) == 9
        assert STAGES[0] == "未识别"
        assert STAGES[-1] == "退出/失败"
