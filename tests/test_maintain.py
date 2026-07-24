"""engine/agent/maintain.py 单元测试。

覆盖：
- Candidate（dataclass）
- _classify_reason（原因分类纯函数）
- _get_last_message_summary（最后消息摘要）
- format_candidates（格式化输出）
- maintain_candidates（候选人筛选主流程）
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from engine.agent.maintain import (
    Candidate,
    _classify_reason,
    _get_last_message_summary,
    format_candidates,
    maintain_candidates,
)


# ═══════════════════════════════════════════════════════════════════
# Candidate dataclass
# ═══════════════════════════════════════════════════════════════════

class TestCandidate:
    """Candidate 数据类。"""

    def test_construction_with_all_fields(self):
        """构造 Candidate 含所有字段。"""
        c = Candidate(
            name="Alice", person_id="p1", wxid="wxid_a", rank=1,
            composite=0.85, signal_level="中窗口", recent_days=2.5,
            trend=-0.01, neediness_penalty=0.95, interaction_pattern="均衡",
            last_msg_summary="[07-24] 她: hello", reason="窗口未推进",
        )
        assert c.name == "Alice"
        assert c.rank == 1
        assert c.composite == 0.85
        assert c.reason == "窗口未推进"

    def test_default_rank_can_be_zero(self):
        """rank 默认为 0（maintain_candidates 中后续赋值）。"""
        c = Candidate(
            name="Bob", person_id="p2", wxid="wxid_b", rank=0,
            composite=0.5, signal_level="弱窗口", recent_days=1.5,
            trend=0.0, neediness_penalty=0.5, interaction_pattern="主动",
            last_msg_summary="", reason="需关注",
        )
        assert c.rank == 0
        assert c.last_msg_summary == ""


# ═══════════════════════════════════════════════════════════════════
# _classify_reason
# ═══════════════════════════════════════════════════════════════════

class TestClassifyReason:
    """_classify_reason 根据指标分类原因。"""

    def test_hot_decline(self):
        """recent_days > 3 且 trend < -0.005 → 热度下降。"""
        assert _classify_reason(4.0, "中窗口", -0.01, 0.5) == "热度下降"

    def test_hot_decline_boundary_recent_days(self):
        """recent_days = 3.01（> 3）→ 热度下降。"""
        assert _classify_reason(3.01, "中窗口", -0.01, 0.5) == "热度下降"

    def test_hot_decline_not_triggered_when_trend_zero(self):
        """recent_days > 3 但 trend = 0 → 不是热度下降。"""
        assert _classify_reason(4.0, "中窗口", 0.0, 0.5) != "热度下降"

    def test_hot_decline_not_triggered_when_trend_positive(self):
        """recent_days > 3 但 trend > 0 → 不是热度下降。"""
        assert _classify_reason(4.0, "中窗口", 0.01, 0.5) != "热度下降"

    def test_window_not_advanced(self):
        """信号 ≥ 弱窗口 且 1 < recent_days <= 3 → 窗口未推进。"""
        # 弱窗口 signal_strength = 2
        assert _classify_reason(2.0, "弱窗口", 0.0, 0.5) == "窗口未推进"

    def test_window_not_advanced_with_strong_signal(self):
        """强窗口 + 1 < recent_days <= 3 → 窗口未推进。"""
        # 强窗口 signal_strength = 4
        assert _classify_reason(2.0, "强窗口", 0.0, 0.5) == "窗口未推进"

    def test_window_not_advanced_boundary_recent_1(self):
        """recent_days = 1.01 → 窗口未推进。"""
        assert _classify_reason(1.01, "弱窗口", 0.0, 0.5) == "窗口未推进"

    def test_window_not_advanced_boundary_recent_3(self):
        """recent_days = 3 → 窗口未推进（<= 3）。"""
        assert _classify_reason(3.0, "弱窗口", 0.0, 0.5) == "窗口未推进"

    def test_window_not_advanced_not_triggered_with_cold_signal(self):
        """冷淡信号（signal_strength=1）+ 1 < recent <= 3 → 不是窗口未推进。"""
        # 冷淡 signal_strength = 1 < 2
        result = _classify_reason(2.0, "冷淡", 0.0, 0.5)
        assert result != "窗口未推进"

    def test_high_potential(self):
        """neediness_penalty > 0.9 且 recent_days > 2 → 高潜力未投入。"""
        assert _classify_reason(2.5, "冷淡", 0.0, 0.95) == "高潜力未投入"

    def test_high_potential_boundary_neediness(self):
        """neediness_penalty = 0.91 → 高潜力未投入。"""
        assert _classify_reason(2.5, "冷淡", 0.0, 0.91) == "高潜力未投入"

    def test_high_potential_not_triggered_when_neediness_low(self):
        """neediness_penalty = 0.9 → 不满足 > 0.9，不是高潜力。"""
        result = _classify_reason(2.5, "冷淡", 0.0, 0.9)
        assert result != "高潜力未投入"

    def test_high_potential_not_triggered_when_recent_le_2(self):
        """recent_days = 2 → 不满足 > 2，不是高潜力。"""
        result = _classify_reason(2.0, "冷淡", 0.0, 0.95)
        assert result != "高潜力未投入"

    def test_default_need_attention(self):
        """不满足任何条件 → 需关注。"""
        assert _classify_reason(1.5, "冷淡", 0.0, 0.5) == "需关注"

    def test_priority_hot_decline_over_window(self):
        """热度下降优先于窗口未推进（即使信号足够）。"""
        # recent > 3 + trend < 0 + 信号强 → 热度下降（不是窗口未推进）
        assert _classify_reason(4.0, "强窗口", -0.01, 0.5) == "热度下降"

    def test_priority_window_over_high_potential(self):
        """窗口未推进优先于高潜力未投入。"""
        # 1 < recent <= 3 + 信号强 + neediness高 → 窗口未推进（不是高潜力）
        assert _classify_reason(2.5, "弱窗口", 0.0, 0.95) == "窗口未推进"

    def test_no_signal_falls_to_default_or_high_potential(self):
        """无信号（signal_strength=0）→ 跳过窗口未推进，可能落到高潜力或需关注。"""
        # 无信号 + recent > 2 + neediness > 0.9 → 高潜力未投入
        assert _classify_reason(2.5, "无信号", 0.0, 0.95) == "高潜力未投入"
        # 无信号 + recent <= 2 → 需关注
        assert _classify_reason(1.5, "无信号", 0.0, 0.95) == "需关注"


# ═══════════════════════════════════════════════════════════════════
# _get_last_message_summary
# ═══════════════════════════════════════════════════════════════════

class TestGetLastMessageSummary:
    """_get_last_message_summary 获取最后一条消息摘要。"""

    def test_no_messages_returns_empty(self, tmp_db):
        """无消息 → 空字符串。"""
        assert _get_last_message_summary(tmp_db, "wxid_her", "wxid_me") == ""

    def test_my_message(self, tmp_db, now_ts):
        """我发的最后消息 → 标记 '我'。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "你好呀", now_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        assert "我" in result
        assert "你好呀" in result

    def test_her_message(self, tmp_db, now_ts):
        """她发的最后消息 → 标记 '她'。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_her", now_ts, 1, "hi there", now_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        assert "她" in result
        assert "hi there" in result

    def test_content_truncated_to_50(self, tmp_db, now_ts):
        """content 截取前 50 字符。"""
        long_content = "a" * 100
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, long_content, now_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        # content 部分（不含 [日期] 前缀）≤ 50 字符
        # 格式 "[MM-DD] sender: content"
        content_part = result.split(": ", 1)[1] if ": " in result else result
        assert len(content_part) <= 50

    def test_includes_date_prefix(self, tmp_db, now_ts):
        """有 timestamp → 含 [MM-DD] 日期前缀。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", ts, 1, "hello", ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        assert "[07-24]" in result

    def test_returns_latest_message(self, tmp_db, now_ts):
        """多条消息 → 返回最新（timestamp DESC LIMIT 1）。"""
        old_ts = now_ts - 86400
        new_ts = now_ts
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", old_ts, 1, "old msg", old_ts),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_her", new_ts, 1, "new msg", new_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        assert "new msg" in result
        assert "old msg" not in result

    def test_empty_sender_id_treated_as_her(self, tmp_db, now_ts):
        """sender_id 为空字符串 → 不等于 my_wxid → 她。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "", now_ts, 1, "hello", now_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        assert "她" in result

    def test_non_text_message_uses_extract_display_content(self, tmp_db, now_ts):
        """非文本消息通过 extract_display_content 转换。"""
        # 语音消息 type=34，有 voice_text
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, raw_content, voice_text, image_text, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_her", now_ts, 34, "",
             "<msg><voicelength>5000</voicelength></msg>", "语音转写内容", None, now_ts),
        )
        tmp_db.commit()
        result = _get_last_message_summary(tmp_db, "wxid_her", "wxid_me")
        # 应包含 voice_text 内容
        assert "语音转写内容" in result


# ═══════════════════════════════════════════════════════════════════
# format_candidates
# ═══════════════════════════════════════════════════════════════════

class TestFormatCandidates:
    """format_candidates 格式化候选人为 Markdown。"""

    def test_empty_list(self):
        """空列表 → 默认提示。"""
        result = format_candidates([])
        assert "当前无需维持关系的联系人" in result

    def test_single_candidate(self):
        """单个候选人 → 含排名和详情。"""
        c = Candidate(
            name="Alice", person_id="p1", wxid="wxid_a", rank=1,
            composite=0.85, signal_level="中窗口", recent_days=2.5,
            trend=-0.01, neediness_penalty=0.95, interaction_pattern="均衡",
            last_msg_summary="[07-24] 她: hello", reason="窗口未推进",
        )
        result = format_candidates([c])
        assert "## 维持关系提醒" in result
        assert "共 1 人需要关注" in result
        assert "### 1. Alice" in result
        assert "- 原因: 窗口未推进" in result
        assert "- 信号: 中窗口" in result
        assert "composite: 0.850" in result
        assert "- 最后联系: 2.5 天前" in result
        assert "- 趋势: -0.010" in result
        assert "- 上次消息: [07-24] 她: hello" in result

    def test_multiple_candidates(self):
        """多个候选人 → 都显示。"""
        candidates = [
            Candidate(
                name="Alice", person_id="p1", wxid="wxid_a", rank=i + 1,
                composite=0.8 - i * 0.1, signal_level="中窗口", recent_days=2.5,
                trend=-0.01, neediness_penalty=0.95, interaction_pattern="均衡",
                last_msg_summary="", reason="窗口未推进",
            )
            for i in range(3)
        ]
        result = format_candidates(candidates)
        assert "共 3 人需要关注" in result
        assert "### 1. Alice" in result
        assert "### 2. Alice" in result
        assert "### 3. Alice" in result

    def test_empty_last_msg_summary_omitted(self):
        """last_msg_summary 为空 → 不显示"上次消息"行。"""
        c = Candidate(
            name="Bob", person_id="p2", wxid="wxid_b", rank=1,
            composite=0.5, signal_level="弱窗口", recent_days=1.5,
            trend=0.0, neediness_penalty=0.5, interaction_pattern="主动",
            last_msg_summary="", reason="需关注",
        )
        result = format_candidates([c])
        assert "上次消息" not in result

    def test_trend_format_with_sign(self):
        """trend 格式化带正负号。"""
        c_pos = Candidate(
            name="A", person_id="p1", wxid="w1", rank=1,
            composite=0.5, signal_level="弱窗口", recent_days=1.5,
            trend=0.005, neediness_penalty=0.5, interaction_pattern="",
            last_msg_summary="", reason="需关注",
        )
        c_neg = Candidate(
            name="B", person_id="p2", wxid="w2", rank=2,
            composite=0.5, signal_level="弱窗口", recent_days=1.5,
            trend=-0.005, neediness_penalty=0.5, interaction_pattern="",
            last_msg_summary="", reason="需关注",
        )
        result_pos = format_candidates([c_pos])
        result_neg = format_candidates([c_neg])
        assert "- 趋势: +0.005" in result_pos
        assert "- 趋势: -0.005" in result_neg

    def test_footer_contains_recommendations(self):
        """结尾含建议说明。"""
        c = Candidate(
            name="A", person_id="p1", wxid="w1", rank=1,
            composite=0.5, signal_level="弱窗口", recent_days=1.5,
            trend=0.0, neediness_penalty=0.5, interaction_pattern="",
            last_msg_summary="", reason="需关注",
        )
        result = format_candidates([c])
        assert "---" in result
        assert "每人建议给出 3 条可发送的消息选项" in result
        assert "基于实际聊天内容" in result
        assert "不超过 2 句话" in result


# ═══════════════════════════════════════════════════════════════════
# maintain_candidates
# ═══════════════════════════════════════════════════════════════════

class TestMaintainCandidates:
    """maintain_candidates 候选人筛选主流程。"""

    def _make_contact(self, wxid, display_name, message_count=50):
        """构造 get_all_contacts_with_messages 返回的 contact dict。"""
        return {
            "wxid": wxid,
            "display_name": display_name,
            "message_count": message_count,
        }

    def _make_metrics(self, recent_raw=2.5, signal_level="弱窗口",
                      trend_normalized=0.5, neediness_penalty=0.5,
                      composite=0.7, interaction_pattern="均衡"):
        """构造 compute_metrics_for_contact 返回的 metrics mock。"""
        m = MagicMock()
        m.recent.raw = recent_raw
        m.signal_level = signal_level
        m.trend.normalized = trend_normalized
        m.neediness_penalty = neediness_penalty
        m.composite = composite
        m.interaction_pattern = interaction_pattern
        return m

    def test_no_contacts_returns_empty(self, monkeypatch):
        """无联系人 → 空列表。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: [])
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        result = maintain_candidates()
        assert result == []

    def test_recent_days_le_1_filtered(self, monkeypatch):
        """recent_days <= 1 → 过滤掉。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "Alice")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        # recent_days = 1 → 过滤
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(recent_raw=1.0))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert result == []

    def test_no_signal_filtered(self, monkeypatch):
        """signal_level = 无信号 → 过滤掉。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "Alice")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="无信号"))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert result == []

    def test_my_wxid_filtered(self, monkeypatch):
        """wxid 等于 my_wxid → 过滤掉。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_me", "Me")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p_me")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Me")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="弱窗口"))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert result == []

    def test_valid_candidate_returned(self, monkeypatch):
        """满足条件的联系人 → 返回 Candidate。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "Alice")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="弱窗口", composite=0.75))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "[07-24] 她: hi")
        result = maintain_candidates()
        assert len(result) == 1
        assert isinstance(result[0], Candidate)
        assert result[0].name == "Alice"
        assert result[0].rank == 1
        assert result[0].composite == 0.75
        assert result[0].last_msg_summary == "[07-24] 她: hi"

    def test_max_people_limit(self, monkeypatch):
        """max_people 限制返回数量。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        # 5 个联系人
        contacts = [self._make_contact(f"wxid_{i}", f"Person{i}") for i in range(5)]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: f"p_{wxid}")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: f"Name_{wxid}")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="弱窗口", composite=0.7))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates(max_people=3)
        assert len(result) == 3
        # 应有 rank 1, 2, 3
        assert [c.rank for c in result] == [1, 2, 3]

    def test_priority_sorting(self, monkeypatch):
        """热度下降 > 窗口未推进 > 高潜力未投入 > 需关注。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        # 4 个联系人，对应 4 种 reason
        contacts = [
            self._make_contact("wxid_need", "NeedAttn"),     # 需关注
            self._make_contact("wxid_high", "HighPotential"),# 高潜力未投入
            self._make_contact("wxid_win", "WindowNotAdv"),  # 窗口未推进
            self._make_contact("wxid_hot", "HotDecline"),    # 热度下降
        ]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        pid_map = {"wxid_need": "p1", "wxid_high": "p2", "wxid_win": "p3", "wxid_hot": "p4"}
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: pid_map[wxid])
        name_map = {"wxid_need": "NeedAttn", "wxid_high": "HighPotential",
                    "wxid_win": "WindowNotAdv", "wxid_hot": "HotDecline"}
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: name_map[wxid])

        metrics_map = {
            "wxid_need": self._make_metrics(recent_raw=1.5, signal_level="冷淡", trend_normalized=0.5, composite=0.3),
            "wxid_high": self._make_metrics(recent_raw=2.5, signal_level="冷淡", trend_normalized=0.5,
                                            neediness_penalty=0.95, composite=0.4),
            "wxid_win": self._make_metrics(recent_raw=2.0, signal_level="弱窗口", trend_normalized=0.5, composite=0.5),
            "wxid_hot": self._make_metrics(recent_raw=4.0, signal_level="中窗口",
                                           trend_normalized=0.49, composite=0.6),
        }
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: metrics_map[wxid])
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        # 顺序应为：HotDecline, WindowNotAdv, HighPotential, NeedAttn
        assert [c.name for c in result] == ["HotDecline", "WindowNotAdv", "HighPotential", "NeedAttn"]
        assert [c.reason for c in result] == ["热度下降", "窗口未推进", "高潜力未投入", "需关注"]

    def test_multi_account_grouped(self, monkeypatch):
        """同一 person_id 的多账号合并为一组。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        # 2 个 wxid 属于同一 person_id
        contacts = [
            {"wxid": "wxid_a1", "display_name": "Alice", "message_count": 30},
            {"wxid": "wxid_a2", "display_name": "Alice2", "message_count": 50},  # primary（更多消息）
        ]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p_alice")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        # 应使用 primary（message_count 更多的 wxid_a2）
        captured_wxid = []
        def fake_metrics(conn, config, wxid, name, **kw):
            captured_wxid.append(wxid)
            return self._make_metrics(recent_raw=2.0, signal_level="弱窗口")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact", fake_metrics)
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert len(result) == 1  # 合并为 1 个
        # 应使用消息更多的 wxid_a2
        assert captured_wxid == ["wxid_a2"]

    def test_resolve_person_name_fallback_to_display_name(self, monkeypatch):
        """_resolve_person_name 返回 None → 使用 display_name。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "FallbackName")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        # _resolve_person_name 返回 None
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: None)
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="弱窗口"))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert len(result) == 1
        assert result[0].name == "FallbackName"  # 使用 display_name

    def test_trend_converted_to_change_value(self, monkeypatch):
        """trend.normalized - 0.5 转为变化值。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "Alice")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        # trend.normalized = 0.45 → trend change = -0.05
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.0, signal_level="弱窗口", trend_normalized=0.45))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert len(result) == 1
        # trend = 0.45 - 0.5 = -0.05，round 4 位
        assert result[0].trend == -0.05

    def test_recent_days_rounded_to_1_decimal(self, monkeypatch):
        """recent_days round 到 1 位小数。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.maintain._get_conn", lambda: (mock_conn, mock_config))
        contacts = [self._make_contact("wxid_a", "Alice")]
        monkeypatch.setattr("engine.agent.maintain.get_all_contacts_with_messages", lambda c, min_messages: contacts)
        monkeypatch.setattr("engine.agent.maintain.filter_contacts", lambda contacts, conn, **kw: (contacts, []))
        monkeypatch.setattr("engine.agent.maintain._person_id_for_wxid", lambda wxid: "p1")
        monkeypatch.setattr("engine.agent.maintain._resolve_person_name", lambda conn, wxid: "Alice")
        monkeypatch.setattr("engine.agent.maintain.compute_metrics_for_contact",
                            lambda conn, config, wxid, name, **kw: self._make_metrics(
                                recent_raw=2.567))
        monkeypatch.setattr("engine.agent.maintain._get_last_message_summary", lambda conn, wxid, my: "")
        result = maintain_candidates()
        assert result[0].recent_days == 2.6
