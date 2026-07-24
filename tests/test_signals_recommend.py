"""engine/agent/signals.py + recommend.py 单元测试。

signals.py 覆盖：
- _REJECTION_KEYWORDS / _CONFESSION_KEYWORDS 等常量
- _detect_signals（拒绝/表白/邀约信号检测）
- detect_manipulation_signals（情感操控检测：金钱/甜言蜜语/受害者扮演/金额升级）
- _detect_moments_chat_signals（朋友圈-聊天联动分析）
- _query_signal_messages（信号消息查询）

recommend.py 覆盖：
- _FRAMEWORK_WIKI 常量
- _build_framework_recommendations（框架推荐构建）
- _recommend_wiki（Wiki 检索推荐）
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from engine.agent.signals import (
    _REJECTION_KEYWORDS,
    _CONFESSION_KEYWORDS,
    _INVITATION_KEYWORDS,
    _MONEY_KEYWORDS,
    _MANIPULATION_SWEET_KEYWORDS,
    _MANIPULATION_VICTIM_KEYWORDS,
    _ESCALATION_AMOUNT_KEYWORDS,
    SIGNAL_KEYWORDS,
    _detect_signals,
    detect_manipulation_signals,
    _detect_moments_chat_signals,
    _query_signal_messages,
)
from engine.agent.recommend import (
    _FRAMEWORK_WIKI,
    _build_framework_recommendations,
    _recommend_wiki,
)


# ═══════════════════════════════════════════════════════════════════
# signals.py 常量
# ═══════════════════════════════════════════════════════════════════

class TestSignalKeywords:
    """信号关键词常量。"""

    def test_rejection_keywords_includes_common_phrases(self):
        """拒绝关键词包含常见表达。"""
        assert "不喜欢" in _REJECTION_KEYWORDS
        assert "做朋友" in _REJECTION_KEYWORDS
        assert "没感觉" in _REJECTION_KEYWORDS
        assert "不是我的类型" in _REJECTION_KEYWORDS

    def test_confession_keywords_includes_common_phrases(self):
        """表白关键词包含常见表达。"""
        assert "做我女朋友" in _CONFESSION_KEYWORDS
        assert "我喜欢你" in _CONFESSION_KEYWORDS
        assert "在一起吧" in _CONFESSION_KEYWORDS

    def test_invitation_keywords_includes_common_phrases(self):
        """邀约关键词包含常见表达。"""
        assert "出来" in _INVITATION_KEYWORDS
        assert "见面" in _INVITATION_KEYWORDS
        assert "周末" in _INVITATION_KEYWORDS

    def test_money_keywords_includes_payment_terms(self):
        """金钱关键词包含支付术语。"""
        assert "红包" in _MONEY_KEYWORDS
        assert "转账" in _MONEY_KEYWORDS
        assert "支付宝" in _MONEY_KEYWORDS
        assert "微信支付" in _MONEY_KEYWORDS

    def test_manipulation_sweet_keywords_includes_pet_names(self):
        """甜言蜜语关键词包含昵称。"""
        assert "老公" in _MANIPULATION_SWEET_KEYWORDS
        assert "宝贝" in _MANIPULATION_SWEET_KEYWORDS
        assert "亲爱的" in _MANIPULATION_SWEET_KEYWORDS

    def test_manipulation_victim_keywords_includes_distress_phrases(self):
        """受害者扮演关键词包含求助表达。"""
        assert "我好害怕" in _MANIPULATION_VICTIM_KEYWORDS
        assert "别离开我" in _MANIPULATION_VICTIM_KEYWORDS

    def test_escalation_amount_keywords_includes_amounts(self):
        """金额升级关键词包含特殊数字。"""
        assert "1314" in _ESCALATION_AMOUNT_KEYWORDS
        assert "520" in _ESCALATION_AMOUNT_KEYWORDS
        assert "手机" in _ESCALATION_AMOUNT_KEYWORDS

    def test_signal_keywords_is_union(self):
        """SIGNAL_KEYWORDS 是拒绝+表白关键词的并集加额外词。"""
        # 应包含拒绝关键词
        for kw in _REJECTION_KEYWORDS:
            assert kw in SIGNAL_KEYWORDS
        # 应包含表白关键词
        for kw in _CONFESSION_KEYWORDS:
            assert kw in SIGNAL_KEYWORDS
        # 应包含额外词
        assert "女朋友" in SIGNAL_KEYWORDS
        assert "男朋友" in SIGNAL_KEYWORDS
        assert "开房" in SIGNAL_KEYWORDS
        assert "约" in SIGNAL_KEYWORDS

    def test_all_keyword_tuples_are_strings(self):
        """所有关键词元组都是字符串。"""
        for kw in _REJECTION_KEYWORDS + _CONFESSION_KEYWORDS + _INVITATION_KEYWORDS:
            assert isinstance(kw, str) and kw


# ═══════════════════════════════════════════════════════════════════
# signals._detect_signals
# ═══════════════════════════════════════════════════════════════════

class TestDetectSignals:
    """_detect_signals 检测 rejection / confession / invitation 三类信号。"""

    def test_empty_messages_returns_empty(self):
        """空消息列表 → 空信号。"""
        assert _detect_signals([]) == {}

    def test_no_signal_messages_returns_empty(self):
        """无信号关键词 → 空字典。"""
        msgs = [
            {"content": "你好", "sender": "她", "timestamp": 0},
            {"content": "今天天气不错", "sender": "我", "timestamp": 0},
        ]
        assert _detect_signals(msgs) == {}

    def test_rejection_signal_detected(self):
        """检测到拒绝信号。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我们还是做朋友吧", "sender": "她", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        assert "rejection" in result
        assert len(result["rejection"]) == 1
        assert "做朋友" in result["rejection"][0]
        assert "她" in result["rejection"][0]

    def test_confession_signal_detected(self):
        """检测到表白信号。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我喜欢你", "sender": "我", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        assert "confession" in result
        assert "我喜欢你" in result["confession"][0]

    def test_invitation_signal_only_for_her(self):
        """邀约信号只检测对方发来的（sender != 我）。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            # 我发的邀约词 → 不应被检测
            {"content": "周末出来玩吗", "sender": "我", "timestamp": ts},
            # 她发的邀约词 → 应被检测
            {"content": "周末出来玩吗", "sender": "她", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        assert "invitation" in result
        assert len(result["invitation"]) == 1
        assert "她" in result["invitation"][0]

    def test_rejection_only_one_signal_per_message(self):
        """单条消息即使含多个拒绝词也只记录一次（break）。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我不喜欢你，我们做朋友吧，没感觉", "sender": "她", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        assert len(result["rejection"]) == 1

    def test_multiple_messages_accumulate(self):
        """多条消息累积到同一信号列表。"""
        ts1 = int(datetime(2024, 7, 24, 10, 0).timestamp())
        ts2 = int(datetime(2024, 7, 24, 11, 0).timestamp())
        msgs = [
            {"content": "我们做朋友吧", "sender": "她", "timestamp": ts1},
            {"content": "我没感觉", "sender": "她", "timestamp": ts2},
        ]
        result = _detect_signals(msgs)
        assert len(result["rejection"]) == 2

    def test_invitation_keyword_in_my_message_skipped(self):
        """我发的消息含邀约词不触发 invitation 信号。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "周末一起吃饭吧", "sender": "我", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        assert "invitation" not in result

    def test_missing_content_field(self):
        """消息缺 content 字段 → 不崩溃（get 默认 ""）。"""
        msgs = [
            {"sender": "她", "timestamp": 0},
        ]
        # 不应崩溃
        result = _detect_signals(msgs)
        assert result == {}

    def test_missing_sender_field(self):
        """消息缺 sender 字段 → 不崩溃。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我喜欢你", "timestamp": ts},
        ]
        # 表白信号不依赖 sender
        result = _detect_signals(msgs)
        assert "confession" in result

    def test_zero_timestamp_no_timestamp_str(self):
        """timestamp=0 → ts_str 为空字符串。"""
        msgs = [
            {"content": "我喜欢你", "sender": "我", "timestamp": 0},
        ]
        result = _detect_signals(msgs)
        assert "confession" in result
        # ts_str 为空 → "[] 我: ..."
        assert "[]" in result["confession"][0]

    def test_content_truncated_to_60_chars(self):
        """content 长度 > 60 → 截断到 60 字符。"""
        long_content = "我喜欢你" + "a" * 100
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": long_content, "sender": "我", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        # 截取的 content 部分 ≤ 60 字符
        # 格式 "[ts_str] sender: content[:60]"
        content_part = result["confession"][0].split(": ", 1)[1]
        assert len(content_part) <= 60
        assert content_part.startswith("我喜欢你")

    def test_multiple_signal_types_in_one_message(self):
        """一条消息同时含拒绝+表白词 → 都被记录。"""
        # "不喜欢" + "我喜欢你" 同时存在
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我不喜欢你但我喜欢你这句话很俗", "sender": "她", "timestamp": ts},
        ]
        result = _detect_signals(msgs)
        # "不喜欢" 触发 rejection，"我喜欢你" 触发 confession
        assert "rejection" in result
        assert "confession" in result

    def test_missing_timestamp_field(self):
        """消息缺 timestamp 字段 → 默认 0，ts_str 为空。"""
        msgs = [
            {"content": "我喜欢你", "sender": "我"},
        ]
        result = _detect_signals(msgs)
        assert "confession" in result
        assert "[]" in result["confession"][0]


# ═══════════════════════════════════════════════════════════════════
# signals.detect_manipulation_signals
# ═══════════════════════════════════════════════════════════════════

class TestDetectManipulationSignals:
    """detect_manipulation_signals 检测情感操控信号（只看对方消息）。"""

    def test_empty_messages_returns_empty(self):
        """空消息列表 → 空。"""
        assert detect_manipulation_signals([], "wxid_me") == {}

    def test_only_my_messages_returns_empty(self):
        """只有我的消息 → 空。"""
        msgs = [
            {"content": "红包", "sender_id": "wxid_me"},
            {"content": "宝贝", "sender_id": "wxid_me"},
        ]
        assert detect_manipulation_signals(msgs, "wxid_me") == {}

    def test_money_requests_detected(self):
        """金钱请求被检测。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "给我发个红包吧", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "money_requests" in result
        assert "红包" in result["money_requests"][0]

    def test_sweet_escalation_detected(self):
        """甜言蜜语升级被检测。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "老公我想你了", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "sweet_escalation" in result

    def test_victim_play_detected(self):
        """受害者扮演被检测。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "我好害怕，别离开我", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "victim_play" in result

    def test_amount_escalation_detected(self):
        """金额升级被检测。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "给我转1314", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "amount_escalation" in result

    def test_multiple_signal_types_one_msg(self):
        """一条消息含多种操控信号 → 都被记录。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            # "宝贝" (sweet) + "红包" (money) + "1314" (amount)
            {"content": "宝贝发个红包1314", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "money_requests" in result
        assert "sweet_escalation" in result
        assert "amount_escalation" in result

    def test_signal_only_once_per_message(self):
        """单条消息即使含多个金钱词也只记录一次。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "红包转账支付宝", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert len(result["money_requests"]) == 1

    def test_content_truncated_to_60(self):
        """content 截断到 60 字符。"""
        long_content = "红包" + "a" * 100
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": long_content, "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        # 格式 "[ts_str] content[:60]"
        content_part = result["money_requests"][0].split("] ", 1)[1]
        assert len(content_part) <= 60

    def test_missing_content_field(self):
        """消息缺 content → 不崩溃。"""
        msgs = [{"sender_id": "wxid_her", "timestamp": 0}]
        # 不应崩溃
        assert detect_manipulation_signals(msgs, "wxid_me") == {}

    def test_missing_timestamp_field(self):
        """消息缺 timestamp → 默认 0，ts_str 为空。"""
        msgs = [
            {"content": "红包", "sender_id": "wxid_her"},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert "money_requests" in result
        assert "[]" in result["money_requests"][0]

    def test_my_messages_filtered_out(self):
        """我的消息被过滤掉，不参与检测。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "红包", "sender_id": "wxid_me", "timestamp": ts},
        ]
        assert detect_manipulation_signals(msgs, "wxid_me") == {}

    def test_combined_my_and_her_messages(self):
        """我和她的消息混合 → 只检测她的。"""
        ts = int(datetime(2024, 7, 24, 10, 0).timestamp())
        msgs = [
            {"content": "红包", "sender_id": "wxid_me", "timestamp": ts},
            {"content": "红包", "sender_id": "wxid_her", "timestamp": ts},
        ]
        result = detect_manipulation_signals(msgs, "wxid_me")
        assert len(result["money_requests"]) == 1


# ═══════════════════════════════════════════════════════════════════
# signals._detect_moments_chat_signals
# ═══════════════════════════════════════════════════════════════════

class TestDetectMomentsChatSignals:
    """_detect_moments_chat_signals 朋友圈-聊天联动分析。"""

    def test_no_messages_returns_empty(self, tmp_db):
        """无消息 → 空。"""
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert result == {}

    def test_no_chat_days_returns_empty(self, tmp_db):
        """无聊天记录的日子 → 空（提前 return）。"""
        # wxid_her 没有任何消息
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert result == {}

    def test_one_sided_interaction_detected(self, tmp_db, now_ts):
        """我有互动但她没有 → moments_one_sided 信号。"""
        # 1. 插入聊天记录（wxid_her 与 wxid_me）
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "hi", now_ts),
        )
        tmp_db.commit()
        # 2. 我在她的朋友圈有评论（m.author_id = wxid_her, mi.user_name = my_name）
        # 需要先创建 contacts 记录 wxid_me 的 display_name
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            ("wxid_me", "我的名字", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她发的朋友圈", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_me", "我的名字", "我的评论", now_ts, now_ts),
        )
        tmp_db.commit()
        # 3. 调用：display_name=Alice（她的名字），my_wxid=wxid_me
        # 注：函数会从 contacts 表查 wxid_me 的 display_name 作为 my_name
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 应检测到 moments_one_sided（我有互动她没有）
        assert "moments_one_sided" in result
        assert any("单向投入" in s for s in result["moments_one_sided"])

    def test_her_comment_detected(self, tmp_db, now_ts):
        """她在我的朋友圈评论 → moments_comment 信号。"""
        # 1. 聊天记录
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "hi", now_ts),
        )
        # 2. 我发的朋友圈（m.author_id = wxid_me）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的朋友圈内容", now_ts, now_ts),
        )
        # 3. 她的评论（mi.user_name = Alice）
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "她的评论内容", now_ts, now_ts),
        )
        tmp_db.commit()
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 应有 moments_comment（非断联期）
        assert "moments_comment" in result
        assert any("她评论你的朋友圈" in s for s in result["moments_comment"])

    def test_her_like_in_silence_period_detected(self, tmp_db):
        """断联期她点赞 → moments_weak_ioi 信号。"""
        # 1. 聊天记录：3 天前和今天，gap >= 3 触发断联
        ts_old = int(datetime(2024, 7, 20).timestamp())
        ts_new = int(datetime(2024, 7, 24).timestamp())
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", ts_old, 1, "hi", ts_old),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_her", ts_new, 1, "hello", ts_new),
        )
        # 2. 我发的朋友圈 + 她在断联期点赞
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的朋友圈内容", ts_old, ts_old),
        )
        # 点赞时间在断联期（7-21 ~ 7-23）
        ts_like = int(datetime(2024, 7, 22).timestamp())
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "like", "wxid_her", "Alice", "", ts_like, ts_like),
        )
        tmp_db.commit()
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 应有 moments_weak_ioi（断联期点赞）
        assert "moments_weak_ioi" in result
        assert any("断联期她点赞" in s for s in result["moments_weak_ioi"])

    def test_her_comment_in_silence_period_detected(self, tmp_db):
        """断联期她评论 → moments_strong_ioi 信号。"""
        ts_old = int(datetime(2024, 7, 20).timestamp())
        ts_new = int(datetime(2024, 7, 24).timestamp())
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", ts_old, 1, "hi", ts_old),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_her", ts_new, 1, "hello", ts_new),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的朋友圈内容", ts_old, ts_old),
        )
        ts_comment = int(datetime(2024, 7, 22).timestamp())
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "她在断联期的评论", ts_comment, ts_comment),
        )
        tmp_db.commit()
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 应有 moments_strong_ioi（断联期评论）
        assert "moments_strong_ioi" in result
        assert any("断联期她评论" in s for s in result["moments_strong_ioi"])

    def test_consecutive_comments_detected(self, tmp_db, now_ts):
        """24 小时内连续评论 → moments_conversation 信号。"""
        # 聊天记录
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "hi", now_ts),
        )
        # 朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的朋友圈内容", now_ts, now_ts),
        )
        # 两条评论间隔 < 24 小时
        ts_c1 = now_ts
        ts_c2 = now_ts + 3600  # 1 小时后
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "评论1", ts_c1, ts_c1),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi2", "mo1", "comment", "wxid_her", "Alice", "评论2", ts_c2, ts_c2),
        )
        tmp_db.commit()
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert "moments_conversation" in result
        assert any("连续评论" in s for s in result["moments_conversation"])

    def test_no_my_name_no_my_interactions(self, tmp_db, now_ts):
        """contacts 表无 wxid_me 记录 → my_interactions 为空列表。"""
        # 聊天记录
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "hi", now_ts),
        )
        # 不创建 contacts 记录 wxid_me
        # 她评论我朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "", "我的朋友圈内容", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "评论", now_ts, now_ts),
        )
        tmp_db.commit()
        # 不应崩溃
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 仍应检测到她的评论
        assert "moments_comment" in result

    def test_silence_period_not_triggered(self, tmp_db, now_ts):
        """聊天间隔 < 3 天 → 无断联期。"""
        # 两天聊天
        ts1 = int(datetime(2024, 7, 23).timestamp())
        ts2 = int(datetime(2024, 7, 24).timestamp())
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", ts1, 1, "hi", ts1),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_her", ts2, 1, "hello", ts2),
        )
        # 朋友圈评论（不在断联期）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的朋友圈", ts1, ts1),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "评论", ts2, ts2),
        )
        tmp_db.commit()
        result = _detect_moments_chat_signals(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 应是 moments_comment（非断联期），不是 moments_strong_ioi
        assert "moments_comment" in result
        assert "moments_strong_ioi" not in result


# ═══════════════════════════════════════════════════════════════════
# signals._query_signal_messages
# ═══════════════════════════════════════════════════════════════════

class TestQuerySignalMessages:
    """_query_signal_messages 从 DB 查询近 N 月消息。"""

    def test_empty_wxids_returns_empty(self, tmp_db):
        """wxids 为空 → 空列表。"""
        assert _query_signal_messages(tmp_db, [], "wxid_me") == []

    def test_query_returns_messages_with_sender_label(self, tmp_db, now_ts):
        """查询返回消息，sender 字段为 我/她。"""
        # 插入两条消息：我 + 她
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, raw_content, voice_text, image_text, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "你好", None, None, None, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, raw_content, voice_text, image_text, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_her", now_ts + 60, 1, "hello", None, None, None, now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert len(result) == 2
        # 按 timestamp ASC 排序
        assert result[0]["sender"] == "我"
        assert result[1]["sender"] == "她"
        assert result[0]["content"] == "你好"
        assert result[1]["content"] == "hello"

    def test_multiple_wxids(self, tmp_db, now_ts):
        """多个 wxid 查询合并结果。"""
        for i, wxid in enumerate(["wxid_a", "wxid_b"]):
            tmp_db.execute(
                "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"m{i}", wxid, "wxid_me", now_ts + i, 1, f"msg{i}", now_ts),
            )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_a", "wxid_b"], "wxid_me", months=3)
        assert len(result) == 2
        contents = [m["content"] for m in result]
        assert "msg0" in contents
        assert "msg1" in contents

    def test_old_messages_filtered_by_months(self, tmp_db):
        """months=3 → 3 个月前的消息被过滤。"""
        # 4 个月前的消息
        old_ts = int(datetime(2024, 3, 1).timestamp())
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", old_ts, 1, "old", old_ts),
        )
        tmp_db.commit()
        # months=3：4 个月前应被过滤（now 比 old_ts 大 4 个月以上）
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert len(result) == 0

    def test_sender_label_she_for_unknown(self, tmp_db, now_ts):
        """sender_id 不等于 my_wxid → 标记为 她。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_other", now_ts, 1, "hi", now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert len(result) == 1
        assert result[0]["sender"] == "她"

    def test_sender_label_wo_for_me(self, tmp_db, now_ts):
        """sender_id 等于 my_wxid → 标记为 我。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 1, "hi", now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert result[0]["sender"] == "我"

    def test_empty_sender_id_treated_as_she(self, tmp_db, now_ts):
        """sender_id 为空字符串 → 不等于 my_wxid → 她。
        注：DB schema 有 NOT NULL 约束，无法插入 NULL；
        代码中 `r["sender_id"] or ""` 是防御性编程处理空字符串/NULL。"""
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "", now_ts, 1, "hi", now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert len(result) == 1
        assert result[0]["sender"] == "她"

    def test_results_ordered_by_timestamp_asc(self, tmp_db, now_ts):
        """结果按 timestamp 升序。"""
        # 插入顺序与时间顺序相反
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts + 100, 1, "late", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m2", "wxid_her", "wxid_me", now_ts, 1, "early", now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert [m["content"] for m in result] == ["early", "late"]

    def test_extract_display_content_called(self, tmp_db, now_ts):
        """非文本消息通过 extract_display_content 转换。"""
        # 语音消息 type=34，有 voice_text
        tmp_db.execute(
            "INSERT INTO messages (id, conversation_id, sender_id, timestamp, type, content, raw_content, voice_text, image_text, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("m1", "wxid_her", "wxid_me", now_ts, 34, "", "<msg><voicelength>5000</voicelength></msg>", "语音转写内容", None, now_ts),
        )
        tmp_db.commit()
        result = _query_signal_messages(tmp_db, ["wxid_her"], "wxid_me", months=3)
        assert len(result) == 1
        # 应包含 voice_text 内容
        assert "语音转写内容" in result[0]["content"]


# ═══════════════════════════════════════════════════════════════════
# recommend._FRAMEWORK_WIKI 常量
# ═══════════════════════════════════════════════════════════════════

class TestFrameworkWikiConstants:
    """_FRAMEWORK_WIKI 静态映射常量。"""

    def test_always_key_exists(self):
        """always 键存在（基础推荐）。"""
        assert "always" in _FRAMEWORK_WIKI
        assert len(_FRAMEWORK_WIKI["always"]) >= 3

    def test_signal_keys_exist(self):
        """5 个信号类型键都存在。"""
        for key in ("rejection", "confession", "invitation",
                    "moments_strong_ioi", "moments_weak_ioi"):
            assert key in _FRAMEWORK_WIKI

    def test_cold_key_exists(self):
        """cold 键存在（无信号时的默认推荐）。"""
        assert "cold" in _FRAMEWORK_WIKI

    def test_entries_are_path_desc_tuples(self):
        """每个条目是 (path, desc) 元组。"""
        for key, entries in _FRAMEWORK_WIKI.items():
            for entry in entries:
                assert isinstance(entry, tuple)
                assert len(entry) == 2
                path, desc = entry
                assert isinstance(path, str) and path
                assert isinstance(desc, str) and desc
                assert path.endswith(".md")

    def test_always_contains_core_frameworks(self):
        """always 包含 IOI、关系三要素、需求感控制 3 个核心框架。"""
        paths = [p for p, _ in _FRAMEWORK_WIKI["always"]]
        assert any("IOI" in p for p in paths)
        assert any("关系三要素" in p for p in paths)
        assert any("需求感控制" in p for p in paths)


# ═══════════════════════════════════════════════════════════════════
# recommend._build_framework_recommendations
# ═══════════════════════════════════════════════════════════════════

class TestBuildFrameworkRecommendations:
    """_build_framework_recommendations 根据信号构建推荐列表。"""

    def test_empty_signals_returns_always_plus_cold(self):
        """无信号 → 返回 always + cold 推荐。"""
        result = _build_framework_recommendations({}, has_archive=True)
        paths = [p for p, _ in result]
        # 应包含 always 部分
        for p, _ in _FRAMEWORK_WIKI["always"]:
            assert p in paths
        # 应包含 cold 部分
        for p, _ in _FRAMEWORK_WIKI["cold"]:
            assert p in paths

    def test_rejection_signal_includes_rejection_wiki(self):
        """rejection 信号 → 包含 rejection 推荐。"""
        result = _build_framework_recommendations({"rejection": ["msg"]}, has_archive=True)
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["rejection"]:
            assert p in paths

    def test_confession_signal_includes_confession_wiki(self):
        """confession 信号 → 包含 confession 推荐。"""
        result = _build_framework_recommendations({"confession": ["msg"]}, has_archive=True)
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["confession"]:
            assert p in paths

    def test_invitation_signal_includes_invitation_wiki(self):
        """invitation 信号 → 包含 invitation 推荐。"""
        result = _build_framework_recommendations({"invitation": ["msg"]}, has_archive=True)
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["invitation"]:
            assert p in paths

    def test_moments_strong_ioi_includes_wiki(self):
        """moments_strong_ioi 信号 → 包含对应推荐。"""
        result = _build_framework_recommendations(
            {"moments_strong_ioi": ["msg"]}, has_archive=True
        )
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["moments_strong_ioi"]:
            assert p in paths

    def test_moments_weak_ioi_includes_wiki(self):
        """moments_weak_ioi 信号 → 包含对应推荐。"""
        result = _build_framework_recommendations(
            {"moments_weak_ioi": ["msg"]}, has_archive=True
        )
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["moments_weak_ioi"]:
            assert p in paths

    def test_cold_excluded_when_rejection_signal_present(self):
        """有 rejection 信号 → 不包含 cold 推荐。"""
        result = _build_framework_recommendations({"rejection": ["msg"]}, has_archive=True)
        paths = [p for p, _ in result]
        for p, _ in _FRAMEWORK_WIKI["cold"]:
            # cold 中的某些条目可能与其他信号重复（去重后只剩一份），
            # 但 cold 独有的条目不应出现
            # 这里只验证 cold 的第一个条目不重复添加（去重机制）
            pass
        # 更准确的验证：cold 中的 "她一直聊但不见面.md" 不应出现
        assert not any("她一直聊但不见面" in p for p in paths)

    def test_cold_excluded_when_confession_present(self):
        """有 confession 信号 → 不包含 cold 推荐。"""
        result = _build_framework_recommendations({"confession": ["msg"]}, has_archive=True)
        paths = [p for p, _ in result]
        assert not any("她一直聊但不见面" in p for p in paths)

    def test_cold_excluded_when_moments_strong_ioi_present(self):
        """有 moments_strong_ioi 信号 → 不包含 cold 推荐。"""
        result = _build_framework_recommendations(
            {"moments_strong_ioi": ["msg"]}, has_archive=True
        )
        paths = [p for p, _ in result]
        assert not any("她一直聊但不见面" in p for p in paths)

    def test_cold_included_when_only_moments_weak_ioi(self):
        """只有 moments_weak_ioi 信号 → 仍包含 cold（条件不满足排除）。"""
        result = _build_framework_recommendations(
            {"moments_weak_ioi": ["msg"]}, has_archive=True
        )
        paths = [p for p, _ in result]
        # 条件：rejection/confession/moments_strong_ioi 都不在 signals 时才加 cold
        # 只有 moments_weak_ioi 仍应加 cold
        assert any("她一直聊但不见面" in p for p in paths)

    def test_duplicates_deduplicated(self):
        """重复的 wiki 路径去重（only first occurrence kept）。"""
        # always 和 cold 都可能包含同一页面（如 什么时候该止损.md）
        result = _build_framework_recommendations({}, has_archive=True)
        paths = [p for p, _ in result]
        # 不应有重复
        assert len(paths) == len(set(paths))

    def test_multiple_signals_merge(self):
        """多个信号合并推荐（去重）。"""
        result = _build_framework_recommendations(
            {"rejection": ["msg"], "confession": ["msg"], "invitation": ["msg"]},
            has_archive=True,
        )
        paths = [p for p, _ in result]
        # 应包含所有 3 个信号的推荐
        for p, _ in _FRAMEWORK_WIKI["rejection"]:
            assert p in paths
        for p, _ in _FRAMEWORK_WIKI["confession"]:
            assert p in paths
        for p, _ in _FRAMEWORK_WIKI["invitation"]:
            assert p in paths
        # 应不包含 cold（rejection 存在）
        assert not any("她一直聊但不见面" in p for p in paths)
        # 应不重复
        assert len(paths) == len(set(paths))

    def test_order_is_always_then_signals_then_cold(self):
        """推荐顺序：always → 信号 → cold。"""
        result = _build_framework_recommendations(
            {"rejection": ["msg"]}, has_archive=True
        )
        paths = [p for p, _ in result]
        # always 的第一个应在结果开头
        assert paths[0] == _FRAMEWORK_WIKI["always"][0][0]
        # rejection 的条目应在 always 之后
        first_rejection_path = _FRAMEWORK_WIKI["rejection"][0][0]
        first_always_path = _FRAMEWORK_WIKI["always"][0][0]
        assert paths.index(first_rejection_path) > paths.index(first_always_path)

    def test_has_archive_param_does_not_affect_result(self):
        """has_archive 参数当前实现中不影响结果（保留参数兼容）。"""
        r1 = _build_framework_recommendations({}, has_archive=True)
        r2 = _build_framework_recommendations({}, has_archive=False)
        assert r1 == r2


# ═══════════════════════════════════════════════════════════════════
# recommend._recommend_wiki
# ═══════════════════════════════════════════════════════════════════

class TestRecommendWiki:
    """_recommend_wiki 基于 ctx 和 events 检索 wiki 页面。"""

    def _make_ctx(self, recent_messages=None, fact_archive="", historical_analysis=None):
        """构造测试用 ctx mock。"""
        ctx = MagicMock()
        ctx.recent_messages = recent_messages or []
        ctx.fact_archive = fact_archive
        ctx.historical_analysis = historical_analysis
        return ctx

    def _make_event(self, event_type_value="confession"):
        """构造测试用 event mock。"""
        e = MagicMock()
        e.event_type.value = event_type_value
        return e

    def _make_snippet(self, title, path, page_type="entity", summary="摘要", score=10.0):
        """构造测试用 WikiSnippet mock。"""
        s = MagicMock()
        s.title = title
        s.path = path
        s.page_type = page_type
        s.summary = summary
        s.score = score
        return s

    def test_empty_ctx_returns_empty(self, monkeypatch):
        """ctx 无任何内容 → 返回空列表。"""
        ctx = self._make_ctx()
        # 不需要 mock WikiIndex，因为 query_text 为空会提前返回
        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert result == []

    def test_no_recent_messages_no_archive_no_events_returns_empty(self, monkeypatch):
        """无 recent_messages + 无 fact_archive + 无 events → 返回空。"""
        ctx = self._make_ctx()
        # query_text 为空，会提前返回 []
        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert result == []

    def test_recent_messages_only(self, monkeypatch):
        """只有 recent_messages → 拼接成 query_text 检索。"""
        msgs = [{"content": "我喜欢你"}, {"content": "做我女朋友"}]
        ctx = self._make_ctx(recent_messages=msgs)
        # mock WikiIndex 和 WikiRetriever
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippet = self._make_snippet("表白应对", "wiki/scenarios/表白.md", score=15.0)
        mock_retriever.retrieve.return_value = [snippet]
        # patch import
        import sys
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert len(result) == 1
        assert result[0]["title"] == "表白应对"
        assert result[0]["type"] == "wiki"
        assert result[0]["score"] == 15.0

    def test_recent_messages_truncated_to_last_15(self, monkeypatch):
        """recent_messages 只取最后 15 条。"""
        # 20 条消息
        msgs = [{"content": f"msg{i}"} for i in range(20)]
        ctx = self._make_ctx(recent_messages=msgs)
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # query_text 应只包含最后 15 条（msg5~msg19）
        # 每条 content 截取 80 字符
        assert "msg5" in captured_query["text"]
        assert "msg19" in captured_query["text"]
        assert "msg4" not in captured_query["text"]

    def test_fact_archive_section_extracted(self, monkeypatch):
        """fact_archive 中关键 section 被提取到 query_text。"""
        archive = (
            "## 关键信息\n这是关键信息内容\n"
            "## 当前状态\n这是当前状态\n"
            "## 关系时间线\n这是时间线\n"
            "## 其他\n这是其他\n"
        )
        ctx = self._make_ctx(fact_archive=archive)
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # 应包含 3 个 section 的内容
        assert "关键信息内容" in captured_query["text"]
        assert "这是当前状态" in captured_query["text"]
        assert "这是时间线" in captured_query["text"]
        # "其他" section 不在提取列表中
        assert "这是其他" not in captured_query["text"]

    def test_events_appended_to_query(self, monkeypatch):
        """events 前 2 条 event_type 拼接到 query_text。"""
        ctx = self._make_ctx()
        events = [
            self._make_event("confession"),
            self._make_event("invitation"),
            self._make_event("rejection"),
        ]
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, events)
        # 前 2 个 event_type 应在 query_text 中
        assert "confession" in captured_query["text"]
        assert "invitation" in captured_query["text"]
        # 第 3 个不应出现
        assert "rejection" not in captured_query["text"]

    def test_index_load_failure_returns_empty(self, monkeypatch):
        """WikiIndex.load() 返回 False → 返回空列表。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        mock_index = MagicMock()
        mock_index.load.return_value = False
        mock_index.is_empty = False
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)

        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert result == []

    def test_index_empty_returns_empty(self, monkeypatch):
        """WikiIndex.is_empty 为 True → 返回空列表。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = True
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)

        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert result == []

    def test_stage_passed_to_retriever(self, monkeypatch):
        """historical_analysis 中的 stage 传递给 retriever。"""
        ctx = self._make_ctx(
            recent_messages=[{"content": "hi"}],
            historical_analysis={"stage": {"stage": "stage_2"}},
        )
        captured_kwargs = {}

        def fake_retrieve(query_text, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert captured_kwargs.get("stage") == "stage_2"
        assert captured_kwargs.get("task_type") == "analyze"

    def test_no_historical_analysis_empty_stage(self, monkeypatch):
        """无 historical_analysis → stage 为空字符串。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        captured_kwargs = {}

        def fake_retrieve(query_text, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert captured_kwargs.get("stage") == ""

    def test_max_pages_passed_to_retriever(self, monkeypatch):
        """max_pages 参数传递给 retriever。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        captured_kwargs = {}

        def fake_retrieve(query_text, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [], max_pages=10)
        assert captured_kwargs.get("max_pages") == 10

    def test_snippets_converted_to_dict(self, monkeypatch):
        """WikiSnippet 转换为 dict 格式。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        snippets = [
            self._make_snippet("标题1", "wiki/path1.md", page_type="scenario",
                               summary="摘要1", score=12.5),
            self._make_snippet("标题2", "wiki/path2.md", page_type="entity",
                               summary="摘要2", score=8.0),
        ]
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert len(result) == 2
        assert result[0] == {
            "type": "wiki", "title": "标题1", "path": "wiki/path1.md",
            "page_type": "scenario", "summary": "摘要1", "score": 12.5,
        }
        assert result[1] == {
            "type": "wiki", "title": "标题2", "path": "wiki/path2.md",
            "page_type": "entity", "summary": "摘要2", "score": 8.0,
        }

    def test_fact_archive_section_without_end_marker(self, monkeypatch):
        """fact_archive 中 section 是最后一个（无 \n## 结束标记）→ 截取到字符串末尾。"""
        archive = "## 关键信息\n这是最后一个 section 的内容"
        ctx = self._make_ctx(fact_archive=archive)
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # 应截取到末尾
        assert "这是最后一个 section 的内容" in captured_query["text"]

    def test_fact_archive_section_truncated_to_300_chars(self, monkeypatch):
        """fact_archive section（含 ## header）截取前 300 字符。"""
        long_content = "a" * 500
        archive = f"## 关键信息\n{long_content}"
        ctx = self._make_ctx(fact_archive=archive)
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # section 含 "## 关键信息\n" header（10 字符）+ content，截取前 300 字符
        # 因此 content 部分最多 290 个 a
        query = captured_query["text"]
        # 应包含 header
        assert "## 关键信息" in query
        # 不应包含全部 500 个 a（被截断）
        assert "a" * 500 not in query
        # 应包含至少 200 个 a（前 300 字符中扣除 header 后剩 290 个 a）
        assert "a" * 200 in query

    def test_recent_message_content_truncated_to_80_chars(self, monkeypatch):
        """单条 recent_message 的 content 截取前 80 字符。"""
        long_msg = "b" * 100
        ctx = self._make_ctx(recent_messages=[{"content": long_msg}])
        captured_query = {}

        def fake_retrieve(query_text, **kwargs):
            captured_query["text"] = query_text
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # 应截取到 80 字符
        assert "b" * 80 in captured_query["text"]
        assert "b" * 100 not in captured_query["text"]

    def test_empty_events_list(self, monkeypatch):
        """events 为空列表 → 不影响 query_text。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        # 不应崩溃
        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert result == []

    def test_query_text_strips_whitespace(self, monkeypatch):
        """query_text 前后空白被 strip。"""
        # recent_messages 的 content 为空 → query_text 为空 → 返回 []
        ctx = self._make_ctx(recent_messages=[{"content": ""}])
        # fact_archive 和 events 都为空
        result = _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        # query_text.strip() 后为空 → 提前返回 []
        assert result == []

    def test_max_chars_passed_to_retriever(self, monkeypatch):
        """max_chars=5000 默认值传递给 retriever。"""
        ctx = self._make_ctx(recent_messages=[{"content": "hi"}])
        captured_kwargs = {}

        def fake_retrieve(query_text, **kwargs):
            captured_kwargs.update(kwargs)
            return []

        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.side_effect = fake_retrieve
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)

        _recommend_wiki(MagicMock(), MagicMock(), MagicMock(), ctx, [])
        assert captured_kwargs.get("max_chars") == 5000
