"""语义分析模块单元测试。

覆盖 Layer 2 融合纯函数（_build_turns / _extract_windows / _compute_*），
不依赖模型或数据库。
"""
import pytest

from engine.analyzers.semantic import (
    _build_turns,
    _extract_windows,
    _compute_emotion_balance,
    _compute_interest_signal,
    _compute_friendship_signal,
    _compute_conversation_depth,
    _compute_trend,
    WindowBehavior,
    LABELS,
    WINDOW_SIZE,
    SLIDE_SIZE,
    MIN_TURNS,
)


# ── _build_turns ────────────────────────────────────────────────────────────

class TestBuildTurns:
    def test_empty_messages(self):
        """空消息列表 → 空轮次。"""
        turns = _build_turns([], "wxid_me")
        assert turns == []

    def test_single_message(self):
        """单条消息 → 单轮。"""
        msgs = [
            {"sender_id": "wxid_her", "is_mine": False, "content": "你好", "timestamp": 100},
        ]
        turns = _build_turns(msgs, "wxid_me")
        assert len(turns) == 1
        assert turns[0]["role"] == "her"
        assert turns[0]["content"] == "你好"

    def test_alternating_turns(self):
        """交替消息 → 每方各算一轮。"""
        msgs = [
            {"sender_id": "wxid_me", "is_mine": True, "content": "在吗", "timestamp": 100},
            {"sender_id": "wxid_her", "is_mine": False, "content": "在的", "timestamp": 200},
            {"sender_id": "wxid_me", "is_mine": True, "content": "干嘛呢", "timestamp": 300},
            {"sender_id": "wxid_her", "is_mine": False, "content": "看书", "timestamp": 400},
        ]
        turns = _build_turns(msgs, "wxid_me")
        assert len(turns) == 4
        assert [t["role"] for t in turns] == ["me", "her", "me", "her"]

    def test_consecutive_same_sender(self):
        """连续同发件人 → 合并为一轮。"""
        msgs = [
            {"sender_id": "wxid_her", "is_mine": False, "content": "在吗", "timestamp": 100},
            {"sender_id": "wxid_her", "is_mine": False, "content": "人呢", "timestamp": 110},
            {"sender_id": "wxid_her", "is_mine": False, "content": "??", "timestamp": 120},
            {"sender_id": "wxid_me", "is_mine": True, "content": "在的", "timestamp": 200},
        ]
        turns = _build_turns(msgs, "wxid_me")
        assert len(turns) == 2
        assert turns[0]["role"] == "her"
        assert "在吗\n人呢\n??" in turns[0]["content"]
        assert turns[1]["role"] == "me"

    def test_preserves_first_timestamp(self):
        """合并轮次的时间戳取第一条消息的时间。"""
        msgs = [
            {"sender_id": "wxid_her", "is_mine": False, "content": "a", "timestamp": 100},
            {"sender_id": "wxid_her", "is_mine": False, "content": "b", "timestamp": 200},
        ]
        turns = _build_turns(msgs, "wxid_me")
        assert turns[0]["ts"] == 100

    def test_is_mine_fallback(self):
        """没有 is_mine 字段时回退到 sender_id 判断。"""
        msgs = [
            {"sender_id": "wxid_me", "content": "hi", "timestamp": 100},
            {"sender_id": "wxid_her", "content": "hello", "timestamp": 200},
        ]
        turns = _build_turns(msgs, "wxid_me")
        assert len(turns) == 2
        assert turns[0]["role"] == "me"
        assert turns[1]["role"] == "her"


# ── _extract_windows ────────────────────────────────────────────────────────

class TestExtractWindows:
    def test_fewer_than_min_turns(self):
        """轮次数 < MIN_TURNS → 空列表。"""
        turns = [{"role": "her", "content": "hi", "ts": 100}] * 5
        windows = _extract_windows(turns)
        assert windows == []

    def test_exact_min_turns(self):
        """刚好 MIN_TURNS 轮 → 一个窗口。"""
        turns = [{"role": "her", "content": f"msg_{i}", "ts": 100 + i}
                 for i in range(MIN_TURNS)]
        windows = _extract_windows(turns)
        assert len(windows) == 1
        assert len(windows[0]) == MIN_TURNS

    def test_sliding_window(self):
        """滑动窗口：window_size=20, slide_size=10。"""
        turns = [{"role": "her" if i % 2 == 0 else "me",
                  "content": f"msg_{i}", "ts": 100 + i}
                 for i in range(35)]  # 35轮
        windows = _extract_windows(turns, window_size=20, slide_size=10, min_turns=10)
        # 35 轮：[0:20], [10:30] → 2 个窗口（[20:40]越界）
        assert len(windows) == 2
        assert len(windows[0]) == 20
        assert len(windows[1]) == 20
        assert windows[1][0]["content"] == "msg_10"

    def test_exact_window_count(self):
        """刚好多个完整窗口。"""
        turns = [{"role": "her", "content": f"m_{i}", "ts": i}
                 for i in range(40)]
        windows = _extract_windows(turns, window_size=20, slide_size=10, min_turns=10)
        # [0:20], [10:30], [20:40] → 3 个窗口
        assert len(windows) == 3

    def test_custom_params(self):
        """自定义窗口参数。"""
        turns = [{"role": "her", "content": f"m_{i}", "ts": i}
                 for i in range(15)]
        windows = _extract_windows(turns, window_size=10, slide_size=5, min_turns=5)
        # [0:10], [5:15] → 2 个窗口
        assert len(windows) == 2


# ── _compute_emotion_balance ────────────────────────────────────────────────

class TestComputeEmotionBalance:
    def test_zero_emotions(self):
        """无情绪数据 → 返回 0.5（中性）。"""
        scores = {"emotion_positive": 0, "emotion_negative": 0}
        assert _compute_emotion_balance(scores) == 0.5

    def test_all_positive(self):
        """全正面情绪 → 1.0。"""
        scores = {"emotion_positive": 9.0, "emotion_negative": 0.0}
        assert _compute_emotion_balance(scores) == 1.0

    def test_all_negative(self):
        """全负面情绪 → 0.0。"""
        scores = {"emotion_positive": 0.0, "emotion_negative": 9.0}
        assert _compute_emotion_balance(scores) == 0.0

    def test_balanced(self):
        """正负相等 → 0.5。"""
        scores = {"emotion_positive": 5.0, "emotion_negative": 5.0}
        assert _compute_emotion_balance(scores) == 0.5

    def test_missing_keys(self):
        """缺少键 → 视为 0，返回 0.5。"""
        assert _compute_emotion_balance({}) == 0.5
        assert _compute_emotion_balance({"other": 3.0}) == 0.5

    def test_mostly_positive(self):
        """正面居多 → > 0.5。"""
        scores = {"emotion_positive": 6.0, "emotion_negative": 2.0}
        bal = _compute_emotion_balance(scores)
        assert 0.7 < bal < 0.8  # 6/8 = 0.75


# ── _compute_interest_signal ────────────────────────────────────────────────

class TestComputeInterestSignal:
    def test_zero_interest(self):
        """所有兴趣指标为 0 → 0。"""
        scores = {"question_asking": 0, "self_disclosure": 0,
                  "invitation": 0, "flirt": 0}
        assert _compute_interest_signal(scores) == 0.0

    def test_max_interest(self):
        """所有兴趣指标满分为 9 → 1.0。"""
        scores = {"question_asking": 9.0, "self_disclosure": 9.0,
                  "invitation": 9.0, "flirt": 9.0}
        assert _compute_interest_signal(scores) == 1.0

    def test_half_interest(self):
        """所有兴趣指标 4.5 → 0.5。"""
        scores = {"question_asking": 4.5, "self_disclosure": 4.5,
                  "invitation": 4.5, "flirt": 4.5}
        assert _compute_interest_signal(scores) == 0.5

    def test_missing_keys_treated_as_zero(self):
        """缺少键视为 0 分。"""
        scores = {"question_asking": 9.0}  # 只有一个指标满分
        sig = _compute_interest_signal(scores)
        # avg = 9/4 = 2.25, normalized = 2.25/9 = 0.25
        assert abs(sig - 0.25) < 0.01


# ── _compute_friendship_signal ──────────────────────────────────────────────

class TestComputeFriendshipSignal:
    def test_zero_friendship(self):
        """边界和敷衍都为 0 → 0。"""
        scores = {"framing_boundary": 0, "perfunctory": 0}
        assert _compute_friendship_signal(scores) == 0.0

    def test_max_friendship(self):
        """都满分 → 1.0。"""
        scores = {"framing_boundary": 9.0, "perfunctory": 9.0}
        assert _compute_friendship_signal(scores) == 1.0

    def test_half_friendship(self):
        """都 4.5 → 0.5。"""
        scores = {"framing_boundary": 4.5, "perfunctory": 4.5}
        assert _compute_friendship_signal(scores) == 0.5

    def test_only_perfunctory(self):
        """只有敷衍。"""
        scores = {"perfunctory": 9.0}
        sig = _compute_friendship_signal(scores)
        # avg = 9/2 = 4.5, /9 = 0.5
        assert abs(sig - 0.5) < 0.01


# ── _compute_conversation_depth ─────────────────────────────────────────────

class TestComputeConversationDepth:
    def test_zero_depth(self):
        """全部为 0 → 0。"""
        scores = {k: 0 for k in
                  ["information_exchange", "opinion_expression",
                   "emotion_positive", "emotion_negative", "flirt"]}
        assert _compute_conversation_depth(scores) == 0.0

    def test_max_depth(self):
        """全部满分 → 1.0。"""
        scores = {k: 9.0 for k in
                  ["information_exchange", "opinion_expression",
                   "emotion_positive", "emotion_negative", "flirt"]}
        assert _compute_conversation_depth(scores) == 1.0

    def test_half_depth(self):
        """全部 4.5 → 0.5。"""
        scores = {k: 4.5 for k in
                  ["information_exchange", "opinion_expression",
                   "emotion_positive", "emotion_negative", "flirt"]}
        assert _compute_conversation_depth(scores) == 0.5

    def test_information_only(self):
        """只有信息交换。"""
        scores = {"information_exchange": 9.0}
        depth = _compute_conversation_depth(scores)
        # avg = 9/5 = 1.8, /9 = 0.2
        assert abs(depth - 0.2) < 0.01


# ── _compute_trend ──────────────────────────────────────────────────────────

class TestComputeTrend:
    def test_single_window(self):
        """单个窗口 → 无趋势 = 0。"""
        windows = [WindowBehavior(
            window_index=0, start_ts=100, end_ts=200, turn_count=10,
            scores={"flirt": 5.0}, labels={"flirt": True},
        )]
        assert _compute_trend(windows, "flirt") == 0.0

    def test_rising_trend(self):
        """后半场比前半场高 → 正趋势。"""
        windows = []
        for i in range(4):
            score = float(i)  # 0, 1, 2, 3 → 上升
            windows.append(WindowBehavior(
                window_index=i, start_ts=100 * i, end_ts=200 * i,
                turn_count=10, scores={"flirt": score}, labels={},
            ))
        trend = _compute_trend(windows, "flirt")
        # first_half: avg(0, 1) = 0.5, second_half: avg(2, 3) = 2.5
        # diff = 2.0, /9 ≈ 0.222
        assert trend > 0

    def test_falling_trend(self):
        """后半场比前半场低 → 负趋势。"""
        windows = []
        for i in range(4):
            score = float(3 - i)  # 3, 2, 1, 0 → 下降
            windows.append(WindowBehavior(
                window_index=i, start_ts=100 * i, end_ts=200 * i,
                turn_count=10, scores={"flirt": score}, labels={},
            ))
        trend = _compute_trend(windows, "flirt")
        assert trend < 0

    def test_stable_trend(self):
        """前后一致 → 趋势接近 0。"""
        windows = []
        for i in range(4):
            windows.append(WindowBehavior(
                window_index=i, start_ts=100 * i, end_ts=200 * i,
                turn_count=10, scores={"flirt": 5.0}, labels={},
            ))
        trend = _compute_trend(windows, "flirt")
        assert abs(trend) < 0.01

    def test_empty_windows(self):
        """空列表 → 0。"""
        assert _compute_trend([], "flirt") == 0.0

    def test_odd_number_of_windows(self):
        """奇数个窗口时前后半场划分。"""
        windows = []
        for i in range(3):
            score = float(i * 2)  # 0, 2, 4
            windows.append(WindowBehavior(
                window_index=i, start_ts=100 * i, end_ts=200 * i,
                turn_count=10, scores={"flirt": score}, labels={},
            ))
        trend = _compute_trend(windows, "flirt")
        # n=3, first_half = [0], avg=0; second_half = [2,4], avg=3
        # diff = 3, /9 ≈ 0.333
        assert trend > 0.3


# ── LABELS 常量验证 ──────────────────────────────────────────────────────────

class TestLabels:
    def test_labels_count(self):
        """10 个可观测行为标签。"""
        assert len(LABELS) == 10

    def test_labels_contains_expected(self):
        """包含所有预期标签。"""
        expected = [
            "information_exchange", "opinion_expression",
            "emotion_positive", "emotion_negative",
            "flirt", "question_asking", "self_disclosure",
            "invitation", "framing_boundary", "perfunctory",
        ]
        for label in expected:
            assert label in LABELS

    def test_window_constants_positive(self):
        """窗口常量均为正整数。"""
        assert WINDOW_SIZE > 0
        assert SLIDE_SIZE > 0
        assert MIN_TURNS > 0
        assert SLIDE_SIZE < WINDOW_SIZE
