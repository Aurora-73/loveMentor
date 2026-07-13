"""interaction_sequence.py 单元测试。

测试覆盖:
    - build_turns_from_messages: 连续同人消息合并、空消息、单条消息
    - group_turns_by_session: 会话分组、无时间戳处理、间隔判断
    - build_turn_pairs_from_session: TurnPair配对、同角色跳过、延迟计算
    - extract_turn_pairs: 高层API(使用tmp_db)
    - extract_turns: 高层API
    - 边界情况: 无时间戳、空消息、单方消息
"""
from __future__ import annotations

import pytest

from engine.analyzers.interaction_sequence import (
    Turn,
    TurnPair,
    build_turns_from_messages,
    group_turns_by_session,
    build_turn_pairs_from_session,
    extract_turn_pairs,
    extract_turns,
)


# ── build_turns_from_messages ──

class TestBuildTurnsFromMessages:
    """测试消息列表转 Turn 序列。"""

    def test_empty_messages(self):
        """空消息列表返回空列表。"""
        turns = build_turns_from_messages([], "wxid_me")
        assert turns == []

    def test_single_message(self):
        """单条消息生成单个 Turn。"""
        messages = [
            {"sender_id": "wxid_me", "content": "你好", "timestamp": 1000},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 1
        assert turns[0].role == "self"
        assert turns[0].content == "你好"
        assert turns[0].ts == 1000
        assert turns[0].raw_count == 1
        assert turns[0].timestamp_reliability == "reliable"
        assert turns[0].has_reliable_ts

    def test_consecutive_same_role_merged(self):
        """连续同人消息合并为一个 Turn。"""
        messages = [
            {"sender_id": "wxid_me", "content": "在吗", "timestamp": 1000},
            {"sender_id": "wxid_me", "content": "有空吗", "timestamp": 1001},
            {"sender_id": "wxid_me", "content": "想问你个事", "timestamp": 1002},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 1
        assert turns[0].role == "self"
        assert turns[0].contents == ["在吗", "有空吗", "想问你个事"]
        assert turns[0].content == "在吗\n有空吗\n想问你个事"
        assert turns[0].raw_count == 3
        assert turns[0].ts == 1000

    def test_role_alternation(self):
        """角色交替生成多个 Turn。"""
        messages = [
            {"sender_id": "wxid_me", "content": "你好", "timestamp": 1000},
            {"sender_id": "wxid_other", "content": "你也好", "timestamp": 1001},
            {"sender_id": "wxid_me", "content": "在吗", "timestamp": 1002},
            {"sender_id": "wxid_other", "content": "在", "timestamp": 1003},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 4
        assert turns[0].role == "self"
        assert turns[1].role == "other"
        assert turns[2].role == "self"
        assert turns[3].role == "other"

    def test_is_mine_field_takes_precedence(self):
        """is_mine 字段优先于 sender_id 判断。"""
        messages = [
            {"sender_id": "wxid_other", "is_mine": True, "content": "我的消息", "timestamp": 1000},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 1
        assert turns[0].role == "self"

    def test_zero_timestamp_preserved(self):
        """时间戳为0时标记为 missing 可靠性。"""
        messages = [
            {"sender_id": "wxid_me", "content": "无时间戳", "timestamp": 0},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 1
        assert turns[0].ts == 0
        assert turns[0].timestamp_reliability == "missing"
        assert not turns[0].has_reliable_ts

    def test_none_content_treated_as_empty(self):
        """content 为 None 时当作空字符串处理。"""
        messages = [
            {"sender_id": "wxid_me", "content": None, "timestamp": 1000},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 1
        assert turns[0].content == ""

    def test_mixed_consecutive_and_alternating(self):
        """混合连续和交替场景。"""
        messages = [
            {"sender_id": "wxid_me", "content": "你好", "timestamp": 1000},
            {"sender_id": "wxid_me", "content": "在吗", "timestamp": 1001},
            {"sender_id": "wxid_other", "content": "在", "timestamp": 1002},
            {"sender_id": "wxid_other", "content": "怎么了", "timestamp": 1003},
            {"sender_id": "wxid_me", "content": "没事", "timestamp": 1004},
        ]
        turns = build_turns_from_messages(messages, "wxid_me")
        assert len(turns) == 3
        assert turns[0].role == "self"
        assert turns[0].raw_count == 2
        assert turns[1].role == "other"
        assert turns[1].raw_count == 2
        assert turns[2].role == "self"
        assert turns[2].raw_count == 1


# ── group_turns_by_session ──

class TestGroupTurnsBySession:
    """测试会话分组。"""

    def test_empty_turns(self):
        """空 Turn 列表返回空列表。"""
        assert group_turns_by_session([]) == []

    def test_single_turn(self):
        """单个 Turn 形成单个会话。"""
        turns = [Turn(role="self", ts=1000, contents=["hi"], raw_count=1)]
        sessions = group_turns_by_session(turns)
        assert len(sessions) == 1
        assert len(sessions[0]) == 1

    def test_same_session(self):
        """间隔小的 Turn 归入同一会话。"""
        turns = [
            Turn(role="self", ts=1000, contents=["hi"], raw_count=1),
            Turn(role="other", ts=1100, contents=["hey"], raw_count=1),
            Turn(role="self", ts=1200, contents=["how"], raw_count=1),
        ]
        sessions = group_turns_by_session(turns, session_gap_hours=1)
        assert len(sessions) == 1
        assert len(sessions[0]) == 3

    def test_new_session_on_large_gap(self):
        """间隔超过阈值开新会话。"""
        # gap = 2小时 = 7200秒
        turns = [
            Turn(role="self", ts=1000, contents=["hi"], raw_count=1),
            Turn(role="other", ts=1000 + 7201, contents=["hey"], raw_count=1),
        ]
        sessions = group_turns_by_session(turns, session_gap_hours=2)
        assert len(sessions) == 2
        assert len(sessions[0]) == 1
        assert len(sessions[1]) == 1

    def test_zero_ts_conservative_same_session(self):
        """无时间戳的 Turn 保守归入同一会话。"""
        turns = [
            Turn(role="self", ts=0, contents=["hi"], raw_count=1),
            Turn(role="other", ts=0, contents=["hey"], raw_count=1),
        ]
        sessions = group_turns_by_session(turns, session_gap_hours=1)
        assert len(sessions) == 1
        assert len(sessions[0]) == 2

    def test_mixed_ts_and_zero_ts(self):
        """混合有效时间戳和零时间戳。"""
        turns = [
            Turn(role="self", ts=1000, contents=["hi"], raw_count=1),
            Turn(role="other", ts=0, contents=["hey"], raw_count=1),
            Turn(role="self", ts=2000, contents=["how"], raw_count=1),
        ]
        sessions = group_turns_by_session(turns, session_gap_hours=1)
        # 零时间戳保守归入同一会话
        assert len(sessions) == 1


# ── build_turn_pairs_from_session ──

class TestBuildTurnPairsFromSession:
    """测试 TurnPair 配对。"""

    def test_less_than_two_turns(self):
        """少于2个 Turn 不生成 TurnPair。"""
        turns = [Turn(role="self", ts=1000, contents=["hi"], raw_count=1)]
        pairs = build_turn_pairs_from_session(turns)
        assert pairs == []

    def test_normal_pairing(self):
        """正常配对:cue-response + 末尾未响应 cue。"""
        turns = [
            Turn(role="self", ts=1000, contents=["你好"], raw_count=1),
            Turn(role="other", ts=1100, contents=["你也好"], raw_count=1),
        ]
        pairs = build_turn_pairs_from_session(turns)
        # 1个正常配对(self→other) + 1个末尾未响应(other 无 response)
        assert len(pairs) == 2
        # 正常配对
        assert pairs[0].cue_role == "self"
        assert pairs[0].cue_content == "你好"
        assert pairs[0].response_role == "other"
        assert pairs[0].response_content == "你也好"
        assert pairs[0].response_latency_sec == 100
        assert pairs[0].has_response is True
        assert pairs[0].response_missing_reason == ""
        assert pairs[0].timestamp_reliability == "reliable"
        # 末尾未响应
        assert pairs[1].cue_role == "other"
        assert pairs[1].has_response is False
        assert pairs[1].response_missing_reason == "session_end"
        assert pairs[1].response_role == ""
        assert pairs[1].response_content == ""
        assert pairs[1].response_latency_sec == -1
        assert not pairs[1].has_reliable_latency

    def test_same_role_skipped(self):
        """同角色相邻 Turn 跳过不配对,末尾生成未响应 pair。"""
        turns = [
            Turn(role="self", ts=1000, contents=["hi"], raw_count=1),
            Turn(role="self", ts=1100, contents=["hello"], raw_count=1),
            Turn(role="other", ts=1200, contents=["hey"], raw_count=1),
        ]
        pairs = build_turn_pairs_from_session(turns)
        # self[1]→other 配对(self[0]→self[1] 同角色跳过) + 末尾 other 未响应
        assert len(pairs) == 2
        # 正常配对(self[1]→other)
        assert pairs[0].cue_role == "self"
        assert pairs[0].response_role == "other"
        # 末尾未响应
        assert pairs[1].cue_role == "other"
        assert pairs[1].has_response is False
        assert pairs[1].response_missing_reason == "session_end"

    def test_zero_ts_latency_negative_one(self):
        """无时间戳时 latency=-1,timestamp_reliability=missing。"""
        turns = [
            Turn(role="self", ts=0, contents=["hi"], raw_count=1, timestamp_reliability="missing"),
            Turn(role="other", ts=0, contents=["hey"], raw_count=1, timestamp_reliability="missing"),
        ]
        pairs = build_turn_pairs_from_session(turns)
        # 1正常(missing) + 1末尾未响应
        assert len(pairs) == 2
        assert pairs[0].response_latency_sec == -1
        assert pairs[0].timestamp_reliability == "missing"
        assert not pairs[0].has_reliable_latency
        # 末尾未响应
        assert pairs[1].has_response is False
        assert pairs[1].timestamp_reliability == "missing"

    def test_partial_ts_latency_negative_one(self):
        """只有一方有时间戳时 latency=-1,timestamp_reliability=missing。"""
        turns = [
            Turn(role="self", ts=1000, contents=["hi"], raw_count=1, timestamp_reliability="reliable"),
            Turn(role="other", ts=0, contents=["hey"], raw_count=1, timestamp_reliability="missing"),
        ]
        pairs = build_turn_pairs_from_session(turns)
        # 1正常(missing,因为 response 不可靠) + 1末尾未响应
        assert len(pairs) == 2
        assert pairs[0].response_latency_sec == -1
        assert pairs[0].timestamp_reliability == "missing"
        # 末尾未响应(other 的 cue,timestamp_reliability=missing)
        assert pairs[1].has_response is False
        assert pairs[1].timestamp_reliability == "missing"

    def test_multi_pair_session(self):
        """多轮对话生成多个 TurnPair + 末尾未响应。"""
        turns = [
            Turn(role="self", ts=1000, contents=["你好"], raw_count=1),
            Turn(role="other", ts=1100, contents=["你也好"], raw_count=1),
            Turn(role="self", ts=1200, contents=["在吗"], raw_count=1),
            Turn(role="other", ts=1300, contents=["在"], raw_count=1),
        ]
        pairs = build_turn_pairs_from_session(turns)
        # 3个正常配对 + 1个末尾未响应
        assert len(pairs) == 4
        # 第1对: self→other
        assert pairs[0].cue_role == "self"
        assert pairs[0].response_role == "other"
        assert pairs[0].has_response is True
        # 第2对: other→self
        assert pairs[1].cue_role == "other"
        assert pairs[1].response_role == "self"
        # 第3对: self→other
        assert pairs[2].cue_role == "self"
        assert pairs[2].response_role == "other"
        # 第4对: 末尾 other 未响应
        assert pairs[3].cue_role == "other"
        assert pairs[3].has_response is False
        assert pairs[3].response_missing_reason == "session_end"

    def test_trailing_cue_generates_unresponded_pair(self):
        """会话以 cue 结尾时生成未响应 TurnPair(pending_cues 输入)。"""
        turns = [
            Turn(role="self", ts=1000, contents=["你好"], raw_count=1),
            Turn(role="other", ts=1100, contents=["你也好"], raw_count=1),
            Turn(role="self", ts=1200, contents=["在吗"], raw_count=1),  # 无回应
        ]
        pairs = build_turn_pairs_from_session(turns)
        # 2个正常配对 + 1个末尾未响应(self 的 cue 无 response)
        assert len(pairs) == 3
        # 前两轮正常
        assert pairs[0].has_response is True
        assert pairs[1].has_response is True
        # 末尾 self 未响应
        assert pairs[2].cue_role == "self"
        assert pairs[2].cue_content == "在吗"
        assert pairs[2].has_response is False
        assert pairs[2].response_missing_reason == "session_end"
        assert pairs[2].response_role == ""
        assert pairs[2].response_content == ""


# ── extract_turn_pairs (高层API) ──

class TestExtractTurnPairs:
    """测试高层API extract_turn_pairs。"""

    def test_empty_conversation(self, tmp_db):
        """无消息的会话返回空列表。"""
        pairs = extract_turn_pairs(tmp_db, "wxid_me", "wxid_other")
        assert pairs == []

    def test_normal_conversation(self, tmp_db, insert_messages):
        """正常对话生成 TurnPair(含末尾未响应)。"""
        base_ts = 1700000000
        insert_messages("wxid_other", "wxid_me", "你好", base_ts)
        insert_messages("wxid_other", "wxid_other", "你也好", base_ts + 100)
        insert_messages("wxid_other", "wxid_me", "在吗", base_ts + 200)
        insert_messages("wxid_other", "wxid_other", "在", base_ts + 300)

        pairs = extract_turn_pairs(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 10000),
        )
        # 4条消息 → 4个 turn(self/other/self/other)→ 3正常 + 1末尾未响应 = 4个 pair
        assert len(pairs) == 4
        assert all(isinstance(p, TurnPair) for p in pairs)
        # 最后一个是末尾未响应
        assert pairs[-1].has_response is False
        assert pairs[-1].response_missing_reason == "session_end"

    def test_consecutive_same_sender_merged(self, tmp_db, insert_messages):
        """连续同人消息合并为一个 Turn,末尾生成未响应 pair。"""
        base_ts = 1700000000
        insert_messages("wxid_other", "wxid_me", "你好", base_ts)
        insert_messages("wxid_other", "wxid_me", "在吗", base_ts + 1)
        insert_messages("wxid_other", "wxid_me", "有空吗", base_ts + 2)
        insert_messages("wxid_other", "wxid_other", "在", base_ts + 100)

        pairs = extract_turn_pairs(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 10000),
        )
        # 前3条 me 合并为1个 turn,后1条 other → 2个 turn → 1正常 + 1末尾未响应 = 2个 pair
        assert len(pairs) == 2
        # 正常配对:cue 是合并后的 self turn
        assert "你好" in pairs[0].cue_content
        assert "在吗" in pairs[0].cue_content
        assert "有空吗" in pairs[0].cue_content
        assert pairs[0].has_response is True
        # 末尾未响应:other 的 cue
        assert pairs[1].cue_role == "other"
        assert pairs[1].has_response is False

    def test_multi_session(self, tmp_db, insert_messages):
        """多会话场景,每会话含末尾未响应 pair。"""
        base_ts = 1700000000
        # 会话1
        insert_messages("wxid_other", "wxid_me", "你好", base_ts)
        insert_messages("wxid_other", "wxid_other", "你也好", base_ts + 100)
        # 间隔超过6小时(21600秒)
        insert_messages("wxid_other", "wxid_me", "又在吗", base_ts + 22000)
        insert_messages("wxid_other", "wxid_other", "在", base_ts + 22100)

        pairs = extract_turn_pairs(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 50000),
            session_gap_hours=6,
        )
        # 2个会话,每会话 1正常 + 1末尾未响应 = 2个 pair,共4个 pair
        assert len(pairs) == 4
        # 会话1的末尾未响应
        assert pairs[1].has_response is False
        assert pairs[1].response_missing_reason == "session_end"
        # 会话2的末尾未响应
        assert pairs[3].has_response is False
        assert pairs[3].response_missing_reason == "session_end"

    def test_only_one_side_messages(self, tmp_db, insert_messages):
        """只有单方消息不生成 TurnPair。"""
        base_ts = 1700000000
        insert_messages("wxid_other", "wxid_me", "你好", base_ts)
        insert_messages("wxid_other", "wxid_me", "在吗", base_ts + 100)
        insert_messages("wxid_other", "wxid_me", "怎么不回", base_ts + 200)

        pairs = extract_turn_pairs(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 10000),
        )
        assert pairs == []


# ── extract_turns (高层API) ──

class TestExtractTurns:
    """测试高层API extract_turns。"""

    def test_empty_conversation(self, tmp_db):
        """无消息的会话返回空列表。"""
        turns = extract_turns(tmp_db, "wxid_me", "wxid_other")
        assert turns == []

    def test_normal_extraction(self, tmp_db, insert_messages):
        """正常提取 Turn 序列。"""
        base_ts = 1700000000
        insert_messages("wxid_other", "wxid_me", "你好", base_ts)
        insert_messages("wxid_other", "wxid_me", "在吗", base_ts + 1)
        insert_messages("wxid_other", "wxid_other", "在", base_ts + 100)

        turns = extract_turns(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 10000),
        )
        assert len(turns) == 2
        assert turns[0].role == "self"
        assert turns[0].raw_count == 2
        assert turns[1].role == "other"
        assert turns[1].raw_count == 1

    def test_role_assignment(self, tmp_db, insert_messages):
        """验证 role 正确赋值(self/other)。"""
        base_ts = 1700000000
        insert_messages("wxid_other", "wxid_me", "我的消息", base_ts)
        insert_messages("wxid_other", "wxid_other", "对方消息", base_ts + 100)

        turns = extract_turns(
            tmp_db, "wxid_me", "wxid_other",
            window_days=30, ref_date=__import__("datetime").datetime.fromtimestamp(base_ts + 10000),
        )
        assert turns[0].role == "self"
        assert turns[1].role == "other"
