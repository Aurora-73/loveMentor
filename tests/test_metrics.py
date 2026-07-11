"""指标计算单元测试。

覆盖 confidence/normalize_ratio/fback/rlatency/msg_count/active_days/
signal_level/base_score/neediness_penalty 等核心计算函数。
"""
import time
from datetime import datetime, timedelta

import pytest

from engine.config import Config, WeightsConfig
from engine.models.metrics import Metrics, MetricValue
from engine.analyzers.metrics import (
    _confidence,
    _normalize_ratio,
    _clamp,
    compute_fback,
    compute_rlatency,
    compute_msg_count,
    compute_active_days,
    compute_recent,
    compute_signal_level,
    compute_base_score,
    compute_neediness_penalty,
    compute_her_initiation_rate,
    compute_topic_continuation,
    compute_reply_quality,
    compute_session_balance,
    compute_emotional_temperature,
    compute_friendzone_risk,
)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_confidence_zero(self):
        assert _confidence(0) == 0.0

    def test_confidence_small(self):
        """样本量 10 → confidence 在 0.1-0.5 之间。"""
        c = _confidence(10)
        assert 0.1 < c < 0.5

    def test_confidence_medium(self):
        """样本量 50 → confidence 在 0.5-0.8 之间。"""
        c = _confidence(50)
        assert 0.5 <= c < 0.8

    def test_confidence_large(self):
        """样本量 100 → confidence >= 0.8。"""
        assert _confidence(100) >= 0.8

    def test_confidence_very_large(self):
        """样本量 5000 → confidence 接近 1.0。"""
        c = _confidence(5000)
        assert c > 0.95

    def test_normalize_ratio_zero(self):
        assert _normalize_ratio(0) == 0.0

    def test_normalize_ratio_one(self):
        """1.0 / (1.0 + 1.0) = 0.5。"""
        assert abs(_normalize_ratio(1.0) - 0.5) < 1e-6

    def test_normalize_ratio_large(self):
        """大数 → 接近 1.0。"""
        assert _normalize_ratio(100) > 0.95

    def test_normalize_ratio_negative(self):
        assert _normalize_ratio(-1) == 0.0

    def test_clamp_basic(self):
        assert _clamp(0.5) == 0.5
        assert _clamp(-0.1) == 0.0
        assert _clamp(1.5) == 1.0
        assert _clamp(0.3, lo=0.2, hi=0.8) == 0.3
        assert _clamp(0.1, lo=0.2, hi=0.8) == 0.2


# ── Fback ────────────────────────────────────────────────────────────────────

class TestComputeFback:
    def test_balanced(self, tmp_db, insert_messages, now_ts):
        """双方字数相近 → raw ≈ 1.0，normalized ≈ 0.5。"""
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "你好啊今天怎么样", now_ts - 100)
        insert_messages(wxid, wxid, "挺好的你呢", now_ts - 50)
        insert_messages(wxid, my, "我也挺好的", now_ts - 10)
        result = compute_fback(tmp_db, my, wxid, window_days=30)
        assert result.raw > 0
        assert result.normalized > 0
        assert result.sample_size == 3

    def test_my_zero_chars(self, tmp_db, insert_messages, now_ts):
        """我方 0 字符 → raw=0, normalized=0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        # 只有她的消息
        insert_messages(wxid, wxid, "你好", now_ts - 100)
        insert_messages(wxid, wxid, "在吗", now_ts - 50)
        result = compute_fback(tmp_db, my, wxid, window_days=30)
        assert result.raw == 0.0
        assert result.normalized == 0.0

    def test_no_messages(self, tmp_db):
        """无消息 → raw=0, confidence=0。"""
        result = compute_fback(tmp_db, "wxid_me", "wxid_empty", window_days=30)
        assert result.raw == 0.0
        assert result.confidence == 0.0


# ── Rlatency ─────────────────────────────────────────────────────────────────

class TestComputeRlatency:
    def test_basic(self, tmp_db, insert_messages, now_ts):
        """交替消息 → 计算出回复速度比。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        # 交替消息，间隔 60 秒
        insert_messages(wxid, my, "你好", base)
        insert_messages(wxid, wxid, "嗯嗯", base + 60)
        insert_messages(wxid, my, "在干嘛", base + 120)
        insert_messages(wxid, wxid, "看书", base + 180)
        result = compute_rlatency(tmp_db, my, wxid, session_gap_hours=4)
        assert result.raw > 0
        assert result.sample_size > 0

    def test_too_few_messages(self, tmp_db, insert_messages, now_ts):
        """少于 2 条消息 → raw=0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "你好", now_ts - 100)
        result = compute_rlatency(tmp_db, my, wxid, session_gap_hours=4)
        assert result.raw == 0.0


# ── Msg Count ────────────────────────────────────────────────────────────────

class TestComputeMsgCount:
    def test_basic(self, tmp_db, insert_messages, now_ts):
        """插入 100 条消息 → 对数归一化。"""
        wxid = "wxid_her"
        my = "wxid_me"
        for i in range(100):
            insert_messages(wxid, my if i % 2 == 0 else wxid, f"msg_{i}", now_ts - i * 60)
        result = compute_msg_count(tmp_db, wxid)
        assert result.raw == 100
        assert 0.7 < result.normalized < 0.8  # log(101)/log(501) ≈ 0.74

    def test_zero_messages(self, tmp_db):
        """无消息 → raw=0, normalized=0。"""
        result = compute_msg_count(tmp_db, "wxid_empty")
        assert result.raw == 0
        assert result.normalized == 0.0

    def test_500_messages(self, tmp_db, insert_messages, now_ts):
        """500 条消息 → normalized 接近 1.0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        for i in range(500):
            insert_messages(wxid, my, f"msg_{i}", now_ts - i * 60)
        result = compute_msg_count(tmp_db, wxid)
        assert result.raw == 500
        assert result.normalized >= 0.95


# ── Active Days ──────────────────────────────────────────────────────────────

class TestComputeActiveDays:
    def test_multiple_days(self, tmp_db, insert_messages, now_ts):
        """3 个不同日期 → active_days=3。"""
        wxid = "wxid_her"
        my = "wxid_me"
        today = now_ts
        yesterday = now_ts - 86400
        two_days_ago = now_ts - 172800
        insert_messages(wxid, my, "a", today)
        insert_messages(wxid, my, "b", yesterday)
        insert_messages(wxid, my, "c", two_days_ago)
        result = compute_active_days(tmp_db, wxid, window_days=30)
        assert result.raw >= 3

    def test_same_day(self, tmp_db, insert_messages, now_ts):
        """同一天多条消息 → active_days=1。"""
        wxid = "wxid_her"
        my = "wxid_me"
        for i in range(5):
            insert_messages(wxid, my, f"msg_{i}", now_ts - i * 60)
        result = compute_active_days(tmp_db, wxid, window_days=30)
        assert result.raw == 1


# ── Recent ───────────────────────────────────────────────────────────────────

class TestComputeRecent:
    def test_just_now(self, tmp_db, insert_messages, now_ts):
        """刚发的消息 → recent 约 0 天。"""
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "hi", now_ts)
        result = compute_recent(tmp_db, wxid, recency_decay=90)
        assert result.raw < 1.0
        assert result.normalized > 0.9

    def test_no_messages(self, tmp_db):
        """无消息 → raw=999, normalized=0。"""
        result = compute_recent(tmp_db, "wxid_empty", recency_decay=90)
        assert result.raw == 999
        assert result.normalized == 0.0


# ── Signal Level ─────────────────────────────────────────────────────────────

class TestSignalLevel:
    def test_strong(self):
        assert compute_signal_level(0.75) == "强窗口"

    def test_medium(self):
        assert compute_signal_level(0.40) == "中窗口"

    def test_weak(self):
        assert compute_signal_level(0.30) == "弱窗口"

    def test_cold(self):
        assert compute_signal_level(0.20) == "冷淡"

    def test_none(self):
        assert compute_signal_level(0.05) == "无信号"

    def test_boundary_strong(self):
        assert compute_signal_level(0.70) == "强窗口"

    def test_boundary_medium(self):
        assert compute_signal_level(0.40) == "中窗口"

    def test_boundary_weak(self):
        assert compute_signal_level(0.30) == "弱窗口"

    def test_boundary_cold(self):
        assert compute_signal_level(0.15) == "冷淡"


# ── Base Score ───────────────────────────────────────────────────────────────

class TestBaseScore:
    def test_all_zero(self):
        """全零指标 → base_score=0。"""
        m = Metrics()
        w = WeightsConfig({})
        assert compute_base_score(m, w) == 0.0

    def test_all_half(self):
        """全 0.5 指标 → base_score = 0.5 × base_weight_sum。"""
        m = Metrics()
        half = MetricValue(raw=0.5, normalized=0.5, confidence=1.0, sample_size=100)
        for field_name in m.all_metrics():
            setattr(m, field_name, half)
        w = WeightsConfig({})
        score = compute_base_score(m, w)
        # base 权重（不含 trend, friendzone_risk）总和 = 1.43
        # fback=0.10 + rlatency=0.10 + qscore=0.00 + escore=0.05 + moments=0.06
        # + msg_count=0.02 + active_days=0.04 + recent=0.05
        # + fback_quality=0.10 + escore_volatility=0.08 + qscore_personal=0.10
        # + qscore_functional=0.05 + rlatency_context=0.05 + msg_volume_trend=0.05
        # + latency_trend=0.05 + her_initiation_rate=0.08 + topic_continuation=0.06
        # + reply_quality=0.06 + session_balance=0.04 + emotional_temperature=0.06
        # + semantic_flirt=0.10 + semantic_invitation=0.08 + semantic_emotion_balance=0.05
        # sum = 1.43, base_score = 0.5 * 1.43 = 0.715
        assert abs(score - 0.715) < 0.01

    def test_top_target_bonus(self):
        """top_target=True → +0.10。"""
        m = Metrics()
        half = MetricValue(raw=0.5, normalized=0.5, confidence=1.0, sample_size=100)
        for field_name in m.all_metrics():
            setattr(m, field_name, half)
        w = WeightsConfig({})
        normal = compute_base_score(m, w)
        boosted = compute_base_score(m, w, top_target=True)
        assert abs(boosted - normal - 0.10) < 0.01

    def test_trend_excluded(self):
        """trend 不参与 base_score 计算。"""
        m = Metrics()
        zero = MetricValue(raw=0.0, normalized=0.0, confidence=1.0, sample_size=100)
        high_trend = MetricValue(raw=1.0, normalized=1.0, confidence=1.0, sample_size=100)
        for field_name in m.all_metrics():
            setattr(m, field_name, zero)
        m.trend = high_trend
        w = WeightsConfig({})
        assert compute_base_score(m, w) == 0.0


# ── Neediness Penalty ────────────────────────────────────────────────────────

class TestNeedinessPenalty:
    def test_balanced_no_penalty(self, tmp_db, insert_messages, now_ts):
        """消息量比 <= 2 → 无惩罚。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        # 她 10 条，我 10 条，交替发送
        for i in range(10):
            insert_messages(wxid, my if i % 2 == 0 else wxid, f"msg_{i}", base + i * 60)
        penalty, ratio, init = compute_neediness_penalty(tmp_db, my, wxid, session_gap_hours=4)
        assert penalty >= 0.9  # 基本无惩罚

    def test_excessive_messaging_penalty(self, tmp_db, insert_messages, now_ts):
        """我发远多于她 → 触发惩罚。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 7200
        # 我发 30 条，她发 5 条
        for i in range(30):
            insert_messages(wxid, my, f"msg_{i}", base + i * 60)
        for i in range(5):
            insert_messages(wxid, wxid, f"reply_{i}", base + 3600 + i * 60)
        penalty, ratio, init = compute_neediness_penalty(tmp_db, my, wxid, session_gap_hours=4)
        assert penalty < 1.0  # 有惩罚

    def test_too_few_messages(self, tmp_db, insert_messages, now_ts):
        """少于 2 条消息 → 返回 (1.0, 1.0, 0.5)。"""
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "hi", now_ts)
        penalty, ratio, init = compute_neediness_penalty(tmp_db, my, wxid, session_gap_hours=4)
        assert penalty == 1.0

    def test_no_her_messages(self, tmp_db, insert_messages, now_ts):
        """她没发消息 → 返回 (0.5, 1.0, 0.5)。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(5):
            insert_messages(wxid, my, f"msg_{i}", base + i * 60)
        penalty, ratio, init = compute_neediness_penalty(tmp_db, my, wxid, session_gap_hours=4)
        assert penalty == 0.5


# ── Her Initiation Rate ──────────────────────────────────────────────────────

class TestComputeHerInitiationRate:
    def test_too_few_messages(self, tmp_db, insert_messages, now_ts):
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "hi", now_ts)
        result = compute_her_initiation_rate(tmp_db, my, wxid, window_days=30, session_gap_hours=4)
        assert result.raw == 0.0
        assert result.confidence == 0.0

    def test_all_her_initiation(self, tmp_db, insert_messages, now_ts):
        """5个会话，全是她主动开启。"""
        wxid = "wxid_her"
        my = "wxid_me"
        gap = 5 * 3600  # 5小时 > 4h gap
        for i in range(5):
            base = now_ts - (5 - i) * gap
            insert_messages(wxid, wxid, f"她主动{i}", base)
            insert_messages(wxid, my, f"我的回复{i}", base + 60)
        result = compute_her_initiation_rate(tmp_db, my, wxid, window_days=30, session_gap_hours=4)
        assert result.raw == 1.0
        assert result.sample_size == 5

    def test_all_my_initiation(self, tmp_db, insert_messages, now_ts):
        """5个会话，全是我主动开启。"""
        wxid = "wxid_her"
        my = "wxid_me"
        gap = 5 * 3600
        for i in range(5):
            base = now_ts - (5 - i) * gap
            insert_messages(wxid, my, f"我主动{i}", base)
            insert_messages(wxid, wxid, f"她的回复{i}", base + 60)
        result = compute_her_initiation_rate(tmp_db, my, wxid, window_days=30, session_gap_hours=4)
        assert result.raw == 0.0

    def test_mixed_initiation(self, tmp_db, insert_messages, now_ts):
        """4个会话，2个她主动2个我主动 → 0.5。"""
        wxid = "wxid_her"
        my = "wxid_me"
        gap = 5 * 3600
        for i in range(4):
            base = now_ts - (4 - i) * gap
            starter = wxid if i % 2 == 0 else my
            replier = my if i % 2 == 0 else wxid
            insert_messages(wxid, starter, f"发起{i}", base)
            insert_messages(wxid, replier, f"回复{i}", base + 60)
        result = compute_her_initiation_rate(tmp_db, my, wxid, window_days=30, session_gap_hours=4)
        assert result.raw == 0.5
        assert result.sample_size == 4

    def test_single_session(self, tmp_db, insert_messages, now_ts):
        """只有1个会话 → confidence=0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(10):
            insert_messages(wxid, my if i % 2 == 0 else wxid, f"msg_{i}", base + i * 60)
        result = compute_her_initiation_rate(tmp_db, my, wxid, window_days=30, session_gap_hours=4)
        assert result.confidence == 0.0


# ── Topic Continuation ───────────────────────────────────────────────────────

class TestComputeTopicContinuation:
    def test_no_messages(self, tmp_db):
        result = compute_topic_continuation(tmp_db, "wxid_me", "wxid_her")
        assert result.raw == 0.0
        assert result.confidence == 0.0

    def test_all_long_messages(self, tmp_db, insert_messages, now_ts):
        """全部是长消息有问句 → 全部延续。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(10):
            insert_messages(wxid, wxid, f"这是一段比较长的回复内容{i}，你觉得呢？", base + i * 60)
        result = compute_topic_continuation(tmp_db, my, wxid)
        assert result.raw == 1.0

    def test_all_terminators(self, tmp_db, insert_messages, now_ts):
        """全部是敷衍词 → 全部终结。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for w in ["嗯", "哦", "好的", "嗯嗯", "好吧"]:
            insert_messages(wxid, wxid, w, base)
            base += 60
        result = compute_topic_continuation(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_short_with_question(self, tmp_db, insert_messages, now_ts):
        """短消息但有问号 → 视为延续。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "真的？", base)
        insert_messages(wxid, wxid, "然后呢？", base + 60)
        result = compute_topic_continuation(tmp_db, my, wxid)
        assert result.raw == 1.0

    def test_emotional_content(self, tmp_db, insert_messages, now_ts):
        """包含情感词 → 视为延续。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "好开心呀", base)
        insert_messages(wxid, wxid, "挺想你的", base + 60)
        result = compute_topic_continuation(tmp_db, my, wxid)
        assert result.raw == 1.0


# ── Reply Quality ────────────────────────────────────────────────────────────

class TestComputeReplyQuality:
    def test_no_messages(self, tmp_db):
        result = compute_reply_quality(tmp_db, "wxid_me", "wxid_her")
        assert result.raw == 0.0
        assert result.confidence == 0.0

    def test_long_with_question_emotion(self, tmp_db, insert_messages, now_ts):
        """长消息+问句+情感词 → 高质量。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "真的很开心你能来找我，你最近怎么样呀？", base)
        result = compute_reply_quality(tmp_db, my, wxid)
        assert result.raw > 0.8  # 长度0.4 + 问句0.3 + 情感0.2 = 0.9

    def test_terminator_zero(self, tmp_db, insert_messages, now_ts):
        """敷衍词 → 0分。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "嗯", base)
        result = compute_reply_quality(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_medium_length(self, tmp_db, insert_messages, now_ts):
        """中等长度5-15字 → 0.2分。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "还可以吧嗯", base)  # 5字
        result = compute_reply_quality(tmp_db, my, wxid)
        assert result.raw == 0.2

    def test_score_capped_at_one(self, tmp_db, insert_messages, now_ts):
        """分数不超过1.0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "这是一段非常非常长的消息内容，有很多很多字，我很开心你觉得呢？", base)
        result = compute_reply_quality(tmp_db, my, wxid)
        assert result.raw <= 1.0


# ── Session Balance ──────────────────────────────────────────────────────────

class TestComputeSessionBalance:
    def test_too_few_messages(self, tmp_db, insert_messages, now_ts):
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "hi", now_ts)
        result = compute_session_balance(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_perfect_balance(self, tmp_db, insert_messages, now_ts):
        """每个会话双方各发5条 → balance=1.0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(10):
            sender = my if i % 2 == 0 else wxid
            insert_messages(wxid, sender, f"msg_{i}", base + i * 60)
        result = compute_session_balance(tmp_db, my, wxid)
        assert result.raw == 1.0

    def test_all_mine(self, tmp_db, insert_messages, now_ts):
        """全是我发的 → balance=0.0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(10):
            insert_messages(wxid, my, f"msg_{i}", base + i * 60)
        result = compute_session_balance(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_three_to_one(self, tmp_db, insert_messages, now_ts):
        """她发1条我发3条 → balance=1 - 2/3 ≈ 0.333。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, my, "msg1", base)
        insert_messages(wxid, my, "msg2", base + 60)
        insert_messages(wxid, my, "msg3", base + 120)
        insert_messages(wxid, wxid, "reply", base + 180)
        result = compute_session_balance(tmp_db, my, wxid)
        # 1 - |3-1| / max(3,1) = 1 - 2/3 ≈ 0.333
        assert abs(result.raw - 0.333) < 0.01

    def test_multiple_sessions(self, tmp_db, insert_messages, now_ts):
        """多个会话取平均。"""
        wxid = "wxid_her"
        my = "wxid_me"
        gap = 5 * 3600
        # session 1: 完美平衡 (5-5 → 1.0)
        base1 = now_ts - 2 * gap
        for i in range(10):
            sender = my if i % 2 == 0 else wxid
            insert_messages(wxid, sender, f"s1_{i}", base1 + i * 60)
        # session 2: 全是我的，只有1条 → <2条被跳过
        base2 = now_ts - gap
        insert_messages(wxid, my, "s2_0", base2)
        result = compute_session_balance(tmp_db, my, wxid, session_gap_hours=4)
        # 只有 session 1 有效（>=2条且有双方）→ 1.0
        assert result.raw == 1.0
        assert result.sample_size == 1


# ── Emotional Temperature ────────────────────────────────────────────────────

class TestComputeEmotionalTemperature:
    def test_too_few_messages(self, tmp_db, insert_messages, now_ts):
        wxid = "wxid_her"
        my = "wxid_me"
        insert_messages(wxid, my, "hi", now_ts)
        result = compute_emotional_temperature(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_fast_reply_long_emotional(self, tmp_db, insert_messages, now_ts):
        """快回+长消息+情感词 → 温度高。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, my, "在吗？", base)
        insert_messages(wxid, wxid, "在呀在呀，我好开心你找我！", base + 120)  # 2分钟回复
        result = compute_emotional_temperature(tmp_db, my, wxid)
        assert result.raw > 0.7  # 速度0.4 + 长度0.3 + 情感0.3 = 1.0

    def test_slow_short_terminator(self, tmp_db, insert_messages, now_ts):
        """慢回+敷衍词 → 温度低。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600 * 5
        insert_messages(wxid, my, "在吗？", base)
        insert_messages(wxid, wxid, "嗯", base + 3 * 3600)  # 3小时回复
        result = compute_emotional_temperature(tmp_db, my, wxid)
        assert result.raw < 0.2

    def test_no_her_replies(self, tmp_db, insert_messages, now_ts):
        """她没回复我 → 0。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        for i in range(5):
            insert_messages(wxid, my, f"msg_{i}", base + i * 60)
        result = compute_emotional_temperature(tmp_db, my, wxid)
        assert result.raw == 0.0

    def test_speed_tiers(self, tmp_db, insert_messages, now_ts):
        """不同回复速度对应不同分数。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 7200
        # 5分钟回复（<10min → 0.4速度分）+ 长度>=15字 → 0.3长度分
        insert_messages(wxid, my, "a", base)
        insert_messages(wxid, wxid, "a回复内容比较长有很多很多字哦哦", base + 300)
        # 30分钟回复（<1h → 0.25速度分）+ 长度>=15字 → 0.3长度分
        insert_messages(wxid, my, "b", base + 2000)
        insert_messages(wxid, wxid, "b回复内容比较长有很多很多字哦哦", base + 2000 + 1800)
        result = compute_emotional_temperature(tmp_db, my, wxid, session_gap_hours=4)
        # 两条消息的平均：(0.4+0.3)和(0.25+0.3)的平均 = (0.7 + 0.55)/2 = 0.625
        assert abs(result.raw - 0.625) < 0.01


# ── Friendzone Risk ──────────────────────────────────────────────────────────

class TestComputeFriendzoneRisk:
    def test_no_messages(self, tmp_db):
        result = compute_friendzone_risk(tmp_db, "wxid_me", "wxid_her")
        assert result.raw == 0.0
        assert result.confidence == 0.0

    def test_all_daily_topics(self, tmp_db, insert_messages, now_ts):
        """全是日常话题 → 风险高。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "今天上班好累", base)
        insert_messages(wxid, wxid, "下班了地铁好挤", base + 60)
        insert_messages(wxid, wxid, "明天天气怎么样", base + 120)
        result = compute_friendzone_risk(tmp_db, my, wxid)
        assert result.normalized > 0.7  # 日常比例高

    def test_all_emotional(self, tmp_db, insert_messages, now_ts):
        """全是情感话题 → 风险低。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "我好开心呀", base)
        insert_messages(wxid, wxid, "挺想你的", base + 60)
        insert_messages(wxid, wxid, "你喜欢我吗", base + 120)
        result = compute_friendzone_risk(tmp_db, my, wxid)
        assert result.normalized < 0.7

    def test_extra_fields(self, tmp_db, insert_messages, now_ts):
        """extra 中包含 daily_ratio 和 emotional_ratio。"""
        wxid = "wxid_her"
        my = "wxid_me"
        base = now_ts - 3600
        insert_messages(wxid, wxid, "今天上班", base)  # 日常
        insert_messages(wxid, wxid, "好开心", base + 60)  # 情感
        result = compute_friendzone_risk(tmp_db, my, wxid)
        assert "daily_ratio" in result.extra
        assert "emotional_ratio" in result.extra
        assert result.extra["daily_ratio"] == 0.5
        assert result.extra["emotional_ratio"] == 0.5
