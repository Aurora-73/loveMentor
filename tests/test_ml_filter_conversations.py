"""ml/dataset/filter_conversations.py 单元测试。

覆盖：
- load_business_filter（加载 YAML 过滤配置）
- is_business_conversation（商务对话判定：keyword 模式 + sender_ratio 模式）

注意：is_business_conversation 使用 getattr(msg, "content"/"sender_id", "")
访问消息对象的属性，因此测试使用 types.SimpleNamespace 模拟消息对象。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.dataset.filter_conversations import (
    load_business_filter,
    is_business_conversation,
    BUSINESS_FILTER_PATH,
)


def make_msg(content: str = "", sender_id: str = "her") -> SimpleNamespace:
    """构造测试用消息对象。"""
    return SimpleNamespace(content=content, sender_id=sender_id)


# ═══════════════════════════════════════════════════════════════════
# load_business_filter
# ═══════════════════════════════════════════════════════════════════

class TestLoadBusinessFilter:
    """load_business_filter 加载商务过滤配置。"""

    def test_returns_dict(self):
        """返回字典。"""
        config = load_business_filter()
        assert isinstance(config, dict)

    def test_has_patterns_key(self):
        """配置包含 patterns 键。"""
        config = load_business_filter()
        assert "patterns" in config
        assert isinstance(config["patterns"], list)

    def test_has_keyword_pattern(self):
        """配置包含 keyword 类型的模式。"""
        config = load_business_filter()
        keyword_patterns = [p for p in config["patterns"] if p.get("type") == "keyword"]
        assert len(keyword_patterns) >= 1

    def test_has_sender_ratio_pattern(self):
        """配置包含 sender_ratio 类型的模式。"""
        config = load_business_filter()
        ratio_patterns = [p for p in config["patterns"] if p.get("type") == "sender_ratio"]
        assert len(ratio_patterns) >= 1

    def test_keyword_pattern_has_value_and_threshold(self):
        """keyword 模式包含 value（关键词列表）和 threshold。"""
        config = load_business_filter()
        keyword_pattern = next(p for p in config["patterns"] if p.get("type") == "keyword")
        assert "value" in keyword_pattern
        assert isinstance(keyword_pattern["value"], list)
        assert len(keyword_pattern["value"]) > 0
        assert "threshold" in keyword_pattern

    def test_business_filter_path_exists(self):
        """过滤配置文件存在。"""
        assert BUSINESS_FILTER_PATH.exists()


# ═══════════════════════════════════════════════════════════════════
# is_business_conversation - 边界情况
# ═══════════════════════════════════════════════════════════════════

class TestIsBusinessConversationBoundary:
    """is_business_conversation 边界情况。"""

    def test_empty_messages_returns_false(self):
        """空消息列表 → False。"""
        assert is_business_conversation([]) is False


# ═══════════════════════════════════════════════════════════════════
# is_business_conversation - keyword 模式
# ═══════════════════════════════════════════════════════════════════

class TestIsBusinessConversationKeyword:
    """is_business_conversation keyword 模式判定。

    配置中 keyword 模式 threshold=5，意味着至少 5 条消息命中商务关键词
    才判定为商务对话。
    """

    def test_normal_conversation_not_business(self):
        """正常聊天 → False。"""
        messages = [
            make_msg("你好呀，在吗"),
            make_msg("今天天气真好"),
            make_msg("我们去散步吧"),
            make_msg("好的呀"),
        ]
        assert is_business_conversation(messages) is False

    def test_below_threshold_not_business(self):
        """命中次数 < threshold(5) → False。"""
        messages = [
            make_msg("这个价格多少"),
            make_msg("你好呀"),
            make_msg("今天天气好"),
            make_msg("去散步吧"),
        ]
        # 只有 1 条消息命中"价格"，< 5 → False
        assert is_business_conversation(messages) is False

    def test_at_threshold_is_business(self):
        """命中次数 == threshold(5) → True。"""
        messages = [
            make_msg("这个价格多少"),
            make_msg("付款方式是什么"),
            make_msg("订单什么时候发货"),
            make_msg("发票能开吗"),
            make_msg("快递多久到"),
        ]
        # 5 条消息各命中一个不同的关键词 → hit_count=5 >= threshold=5 → True
        assert is_business_conversation(messages) is True

    def test_above_threshold_is_business(self):
        """命中次数 > threshold(5) → True。"""
        messages = [
            make_msg("价格多少"),
            make_msg("付款方式"),
            make_msg("订单发货"),
            make_msg("发票开具"),
            make_msg("快递时间"),
            make_msg("合同签订"),
            make_msg("预算多少"),
        ]
        assert is_business_conversation(messages) is True

    def test_same_message_multiple_keywords_counts_once(self):
        """单条消息含多个关键词只算 1 次 hit（break 逻辑）。"""
        messages = [
            make_msg("价格付款订单发票快递"),  # 含 5 个关键词，但 break 后只 +1
            make_msg("价格付款订单发票快递"),
            make_msg("价格付款订单发票快递"),
            make_msg("价格付款订单发票快递"),
            make_msg("价格付款订单发票快递"),
        ]
        # 5 条消息，每条 +1 → hit_count=5 >= 5 → True
        assert is_business_conversation(messages) is True

    def test_keyword_hit_breaks_early(self):
        """命中 threshold 后立即返回 True（短路）。"""
        messages = [
            make_msg("价格多少"),
            make_msg("付款方式"),
            make_msg("订单发货"),
            make_msg("发票开具"),
            make_msg("快递时间"),
            make_msg("正常消息一"),
            make_msg("正常消息二"),
        ]
        # 第 5 条消息后 hit_count=5 >= 5 → 立即返回 True
        assert is_business_conversation(messages) is True

    def test_empty_content_no_hit(self):
        """空 content 不命中关键词。"""
        messages = [make_msg("", "her") for _ in range(10)]
        assert is_business_conversation(messages) is False

    def test_missing_content_attribute_treated_as_empty(self):
        """消息对象缺少 content 属性 → 视为空字符串。"""
        messages = [
            SimpleNamespace(sender_id="her"),
            SimpleNamespace(sender_id="her"),
            SimpleNamespace(sender_id="her"),
            SimpleNamespace(sender_id="her"),
            SimpleNamespace(sender_id="her"),
        ]
        # 全是空 content → 不命中 → False
        assert is_business_conversation(messages) is False


# ═══════════════════════════════════════════════════════════════════
# is_business_conversation - sender_ratio 模式
# ═══════════════════════════════════════════════════════════════════

class TestIsBusinessConversationSenderRatio:
    """is_business_conversation sender_ratio 模式判定。

    配置中 sender_ratio 模式：
    - me_ratio_threshold: 0.8（我发送占比 > 80%）
    - her_reply_avg_len: 5（她回复平均长度 < 5 字符）
    两个条件同时满足才判定为商务对话。
    """

    def test_me_dominant_short_her_replies_is_business(self):
        """我发送占 > 80% + 她回复平均 < 5 字符 → True。"""
        # 10 条消息，9 条 me + 1 条 her → me_ratio = 0.9 > 0.8
        # her 回复 "嗯" (1 字符) → avg_len = 1 < 5
        messages = [
            make_msg("我发了很多内容", "me"),
            make_msg("我继续发内容", "me"),
            make_msg("我还在发内容", "me"),
            make_msg("我发更多内容", "me"),
            make_msg("我发很多内容", "me"),
            make_msg("我继续发内容", "me"),
            make_msg("我还在发内容", "me"),
            make_msg("我发更多内容", "me"),
            make_msg("我发很多内容", "me"),
            make_msg("嗯", "her"),  # 唯一一条 her，1 字符 < 5
        ]
        assert is_business_conversation(messages) is True

    def test_me_dominant_long_her_replies_not_business(self):
        """我发送占 > 80% 但她回复较长 → False。"""
        messages = [
            make_msg("我发了很多内容", "me"),
            make_msg("我继续发内容", "me"),
            make_msg("我还在发内容", "me"),
            make_msg("我发更多内容", "me"),
            make_msg("我发很多内容", "me"),
            make_msg("我继续发内容", "me"),
            make_msg("我还在发内容", "me"),
            make_msg("我发更多内容", "me"),
            make_msg("我发很多内容", "me"),
            make_msg("嗯嗯我收到了谢谢", "her"),  # 8 字符 >= 5
        ]
        assert is_business_conversation(messages) is False

    def test_balanced_conversation_not_business(self):
        """双方消息均衡 → False（me_ratio < 0.8）。"""
        messages = [
            make_msg("你好呀", "me"),
            make_msg("嗨你好", "her"),
            make_msg("在吗", "me"),
            make_msg("在的", "her"),
            make_msg("今天天气好", "me"),
            make_msg("是呀", "her"),
            make_msg("去散步吗", "me"),
            make_msg("好的", "her"),
            make_msg("走吧", "me"),
            make_msg("嗯嗯", "her"),
        ]
        # me_ratio = 5/10 = 0.5 < 0.8 → False
        assert is_business_conversation(messages) is False

    def test_me_dominant_at_threshold_not_business(self):
        """我发送占比正好 == 0.8 → 不 > 0.8 → False。"""
        # 10 条消息，8 条 me + 2 条 her → me_ratio = 0.8，不 > 0.8
        messages = [
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("我发内容", "me"),
            make_msg("嗯", "her"),
            make_msg("哦", "her"),
        ]
        # me_ratio = 8/10 = 0.8，不 > 0.8 → False
        assert is_business_conversation(messages) is False

    def test_self_wxid_treated_as_me(self):
        """sender_id 为 "self"/"wxid_me" 也视为 me。"""
        messages = [
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("我发内容", "self"),
            make_msg("嗯", "her"),
        ]
        # me_ratio = 9/10 = 0.9 > 0.8, her avg_len = 1 < 5 → True
        assert is_business_conversation(messages) is True

    def test_no_her_messages_skipped(self):
        """无 her 消息 → her_count=0 → 跳过 sender_ratio 检查。"""
        messages = [make_msg("我发内容", "me") for _ in range(10)]
        # 没有 her 消息 → her_count=0 → 跳过，继续检查下一个 pattern
        # 但只有这一个 sender_ratio pattern，检查完后返回 False
        assert is_business_conversation(messages) is False

    def test_missing_sender_id_treated_as_her(self):
        """消息缺少 sender_id → None 不在 me 列表 → 视为 her。"""
        messages = [
            SimpleNamespace(content="我发内容"),  # 无 sender_id → None → her
        ] * 10
        # 全部 her，me_count=0 → me_ratio=0 < 0.8 → False
        assert is_business_conversation(messages) is False


# ═══════════════════════════════════════════════════════════════════
# is_business_conversation - 混合模式
# ═══════════════════════════════════════════════════════════════════

class TestIsBusinessConversationMixed:
    """is_business_conversation 混合模式（keyword + sender_ratio）。"""

    def test_keyword_pattern_takes_priority(self):
        """keyword 模式先检查，命中即返回 True。"""
        messages = [
            make_msg("价格多少", "her"),
            make_msg("付款方式", "her"),
            make_msg("订单发货", "her"),
            make_msg("发票开具", "her"),
            make_msg("快递时间", "her"),
        ]
        # 全部 her 消息，me_ratio=0 < 0.8 → sender_ratio 不触发
        # 但 keyword 命中 5 次 >= threshold=5 → True
        assert is_business_conversation(messages) is True

    def test_neither_pattern_triggered(self):
        """两个模式都不触发 → False。"""
        messages = [
            make_msg("你好呀在吗", "me"),
            make_msg("我在这里呀", "her"),
            make_msg("今天天气好", "me"),
            make_msg("是呀不错", "her"),
            make_msg("去散步吧", "me"),
            make_msg("好的呀", "her"),
        ]
        # 无商务关键词，me_ratio=3/6=0.5 < 0.8 → False
        assert is_business_conversation(messages) is False
