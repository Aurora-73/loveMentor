"""ml/pre_check/mvp_validate.py 单元测试。

覆盖：
- detect_question_asking（提问检测：正则模式匹配）
- detect_flirt（暧昧检测：关键词匹配）
- detect_perfunctory（敷衍检测：短文本+敷衍词/全标点）
- detect_window（窗口级聚合：target_role 过滤+binary 结果）
- build_windows（滑动窗口：轮次合并+步长滑动+最小消息数过滤）
- _clean_content（内容清洗：XML 标签去除+长度截断）
"""
from __future__ import annotations

import pytest

from ml.pre_check.mvp_validate import (
    detect_question_asking,
    detect_flirt,
    detect_perfunctory,
    detect_window,
    build_windows,
    _clean_content,
    _QUESTION_PATTERNS,
    _FLIRT_KEYWORDS,
    _PERFUNCTORY_WORDS,
)


# ═══════════════════════════════════════════════════════════════════
# detect_question_asking
# ═══════════════════════════════════════════════════════════════════

class TestDetectQuestionAsking:
    """detect_question_asking 检测文本是否包含提问。"""

    def test_chinese_question_mark(self):
        assert detect_question_asking("你在吗？") is True

    def test_english_question_mark(self):
        assert detect_question_asking("are you there?") is True

    def test_ma_particle(self):
        assert detect_question_asking("你好吗") is True

    def test_ne_particle(self):
        assert detect_question_asking("你在干嘛呢") is True

    def test_shenme_pattern(self):
        assert detect_question_asking("你在做什么工作") is True

    def test_zenme_pattern(self):
        assert detect_question_asking("怎么去那里") is True

    def test_weishenme_pattern(self):
        assert detect_question_asking("为什么不去") is True

    def test_shenme_shihou(self):
        assert detect_question_asking("什么时候出发") is True

    def test_is_not_pattern(self):
        assert detect_question_asking("是不是真的") is True

    def test_ni_ne_pattern(self):
        assert detect_question_asking("你呢") is True

    def test_plain_statement_false(self):
        assert detect_question_asking("今天天气很好") is False

    def test_empty_string_false(self):
        assert detect_question_asking("") is False

    def test_none_false(self):
        assert detect_question_asking(None) is False

    def test_short_text_false(self):
        """strip 后 < 2 字符 → False（长度检查在正则之前）。"""
        # "？" 虽匹配正则 [？?]，但 len("？".strip())==1 < 2 → 直接返回 False
        assert detect_question_asking("？") is False
        assert detect_question_asking("啊") is False

    def test_whitespace_only_false(self):
        assert detect_question_asking("   ") is False

    def test_long_text_with_question_true(self):
        text = "今天我想和你聊一件事，不知道你有没有时间？"
        assert detect_question_asking(text) is True


# ═══════════════════════════════════════════════════════════════════
# detect_flirt
# ═══════════════════════════════════════════════════════════════════

class TestDetectFlirt:
    """detect_flirt 检测文本是否包含暧昧/调侃表达。"""

    def test_xiang_ni(self):
        assert detect_flirt("想你啦") is True

    def test_xihuan_ni(self):
        assert detect_flirt("我喜欢你") is True

    def test_ai_ni(self):
        assert detect_flirt("爱你宝贝") is True

    def test_baobei(self):
        assert detect_flirt("早安宝贝") is True

    def test_momoda(self):
        assert detect_flirt("么么哒") is True

    def test_emoji_heart_eyes(self):
        assert detect_flirt("今天好开心😍") is True

    def test_xin_dong(self):
        assert detect_flirt("看到你我就心动了") is True

    def test_case_insensitive(self):
        """检测是大小写不敏感的（text.lower()）。"""
        # 关键词列表中没有英文，但 lower() 不会影响中文匹配
        assert detect_flirt("想你") is True

    def test_plain_text_false(self):
        assert detect_flirt("今天去开会了") is False

    def test_empty_string_false(self):
        assert detect_flirt("") is False

    def test_none_false(self):
        assert detect_flirt(None) is False

    def test_short_text_false(self):
        """strip 后 < 2 字符 → False。"""
        assert detect_flirt("哈") is False  # 单字不匹配（_FLIRT_KEYWORDS 中"哈哈"是两字）

    def test_whitespace_only_false(self):
        assert detect_flirt("   ") is False

    def test_business_text_false(self):
        assert detect_flirt("请把文件发给我") is False


# ═══════════════════════════════════════════════════════════════════
# detect_perfunctory
# ═══════════════════════════════════════════════════════════════════

class TestDetectPerfunctory:
    """detect_perfunctory 检测文本是否为敷衍回应。"""

    def test_empty_string_true(self):
        """空字符串 → True（视为敷衍）。"""
        assert detect_perfunctory("") is True

    def test_none_true(self):
        assert detect_perfunctory(None) is True

    def test_whitespace_only_true(self):
        assert detect_perfunctory("   ") is True

    def test_short_en_true(self):
        """短文本"嗯" → True。"""
        assert detect_perfunctory("嗯") is True

    def test_short_o_true(self):
        assert detect_perfunctory("哦") is True

    def test_short_hao_true(self):
        assert detect_perfunctory("好") is True

    def test_ok_true(self):
        assert detect_perfunctory("ok") is True

    def test_haha_true(self):
        """超短句"哈哈" → True。"""
        assert detect_perfunctory("哈哈") is True

    def test_emoji_true(self):
        """超短句含敷衍 emoji → True。"""
        assert detect_perfunctory("😊") is True

    def test_punctuation_only_true(self):
        """全是标点 → True。"""
        assert detect_perfunctory("。。。") is True

    def test_normal_long_text_false(self):
        """正常长文本 → False。"""
        assert detect_perfunctory("今天我想和你聊一件很重要的事情") is False

    def test_long_text_with_en_false(self):
        """长文本含"嗯"但整体不是敷衍 → False。"""
        assert detect_perfunctory("嗯嗯，我想了一下，还是觉得这个方案不错") is False

    def test_combination_of_perfunctory_words_true(self):
        """全是敷衍词的组合（如"嗯好的"）→ True。"""
        # "嗯好的"：去掉"嗯""好""的"... 等等，"的"不在 _PERFUNCTORY_WORDS
        # 用"嗯好"：去掉"嗯""好"后为空 → True
        assert detect_perfunctory("嗯好") is True

    def test_oh_xing_true(self):
        """全是敷衍词的组合"哦行" → True。"""
        assert detect_perfunctory("哦行") is True

    def test_custom_min_chars(self):
        """自定义 min_chars 阈值。"""
        # min_chars=10 时，5 字的"嗯嗯嗯嗯嗯"仍 <= 10，含"嗯" → True
        assert detect_perfunctory("嗯嗯嗯嗯嗯", min_chars=10) is True

    def test_min_chars_exceeds_text_length(self):
        """min_chars 很大时，短文本仍可能因全敷衍词组合被判为 True。"""
        # "嗯好"全是敷衍词，即使 min_chars=100 也 True
        assert detect_perfunctory("嗯好", min_chars=100) is True


# ═══════════════════════════════════════════════════════════════════
# detect_window
# ═══════════════════════════════════════════════════════════════════

class TestDetectWindow:
    """detect_window 聚合窗口内 target_role 的检测结果。"""

    def test_basic_window_with_all_labels(self):
        """窗口内同时包含提问/暧昧/敷衍 → 全 True。"""
        messages = [
            {"role": "her", "text": "在吗？"},
            {"role": "her", "text": "想你啦"},
            {"role": "her", "text": "嗯"},
            {"role": "me", "text": "我在"},
        ]
        result = detect_window(messages)
        assert result["question_asking"] is True
        assert result["flirt"] is True
        assert result["perfunctory"] is True
        assert result["_her_msg_count"] == 3

    def test_no_labels_window(self):
        """窗口内无任何标签触发 → 全 False。"""
        messages = [
            {"role": "her", "text": "今天天气真好啊，我想出去走走"},
            {"role": "her", "text": "公园的樱花开得很漂亮"},
        ]
        result = detect_window(messages)
        assert result["question_asking"] is False
        assert result["flirt"] is False
        assert result["perfunctory"] is False
        assert result["_her_msg_count"] == 2

    def test_only_me_messages_filtered(self):
        """只有 me 消息 → her 相关字段全 False，count=0。"""
        messages = [
            {"role": "me", "text": "在吗？"},
            {"role": "me", "text": "想你"},
        ]
        result = detect_window(messages)
        assert result["question_asking"] is False
        assert result["flirt"] is False
        assert result["perfunctory"] is False
        assert result["_her_msg_count"] == 0
        assert result["_her_total_chars"] == 0

    def test_custom_target_role(self):
        """target_role="me" → 只检测 me 的消息。"""
        messages = [
            {"role": "me", "text": "在吗？"},
            {"role": "her", "text": "嗯"},
        ]
        result = detect_window(messages, target_role="me")
        assert result["question_asking"] is True
        assert result["_her_msg_count"] == 1  # 字段名仍是 _her_msg_count

    def test_empty_messages(self):
        result = detect_window([])
        assert result["question_asking"] is False
        assert result["flirt"] is False
        assert result["perfunctory"] is False
        assert result["_her_msg_count"] == 0

    def test_her_total_chars(self):
        messages = [
            {"role": "her", "text": "你好"},  # 2 chars
            {"role": "her", "text": "在吗"},  # 2 chars
        ]
        result = detect_window(messages)
        assert result["_her_total_chars"] == 4

    def test_missing_text_field_treated_as_empty(self):
        """消息缺少 text 字段 → 视为空字符串。"""
        messages = [
            {"role": "her"},  # 无 text
            {"role": "her", "text": "嗯"},
        ]
        result = detect_window(messages)
        assert result["_her_msg_count"] == 2
        # 一条空文本（detect_perfunctory("") → True）+ 一条"嗯" → perfunctory=True
        assert result["perfunctory"] is True

    def test_one_true_message_triggers_label(self):
        """窗口内 ≥1 条消息触发 → 标签为 True。"""
        messages = [
            {"role": "her", "text": "今天天气真好"},
            {"role": "her", "text": "你在干嘛"},  # 无问号，但"干嘛"不在模式中... 
            {"role": "her", "text": "你呢"},  # 触发 question_asking
        ]
        result = detect_window(messages)
        assert result["question_asking"] is True


# ═══════════════════════════════════════════════════════════════════
# build_windows
# ═══════════════════════════════════════════════════════════════════

class TestBuildWindowsMvp:
    """build_windows 从消息列表构建滑动窗口（mvp_validate 版本）。

    注意：此版本与 convert_chat_data.py 的 build_windows 实现不同：
    - 输入是 list[dict]（消息字典），不是 CleanMessage
    - 按轮次（turn）滑动，轮次 = 连续同人消息合并
    - 过滤掉消息数 < 10 的窗口
    """

    def _make_messages(self, n: int) -> list[dict]:
        """生成 n 条交替发送的消息。"""
        return [
            {"role": "me" if i % 2 == 0 else "her", "text": f"msg{i}", "timestamp": i}
            for i in range(n)
        ]

    def test_empty_messages(self):
        assert build_windows([]) == []

    def test_single_message(self):
        """单条消息 → 1 轮，但消息数 < 10 → 被过滤，返回空列表。"""
        msgs = self._make_messages(1)
        windows = build_windows(msgs)
        assert windows == []

    def test_alternating_messages_one_turn_per_role(self):
        """交替发送 → 每条消息 1 轮。"""
        msgs = self._make_messages(5)
        windows = build_windows(msgs)
        # 5 轮 < window_turns(20)，但 max(1, len(turns)-window_turns+1)=1
        # end=min(0+20, 5)=5, 5-0=5, 但 len(window_msgs)=5 < 10 → 过滤
        # 实际：range(0, max(1, 5-20+1), 10) = range(0, 1, 10) = [0]
        # window_msgs = turns[0:5] = 5 条消息，len < 10 → 过滤
        assert windows == []

    def test_consecutive_same_sender_merged_to_one_turn(self):
        """连续同人消息合并为一轮。"""
        msgs = [
            {"role": "me", "text": "a", "timestamp": 1},
            {"role": "me", "text": "b", "timestamp": 2},
            {"role": "me", "text": "c", "timestamp": 3},
            {"role": "her", "text": "x", "timestamp": 4},
            {"role": "her", "text": "y", "timestamp": 5},
            {"role": "me", "text": "d", "timestamp": 6},
            {"role": "her", "text": "z", "timestamp": 7},
            {"role": "me", "text": "e", "timestamp": 8},
            {"role": "her", "text": "w", "timestamp": 9},
            {"role": "me", "text": "f", "timestamp": 10},
        ]
        # 5 轮（me, her, me, her, me, her, me, her, me, her 实际是 5 轮 me+her）
        # 重新数：me(me,me,me), her(her,her), me(d), her(z), me(e), her(w), me(f) = 7 轮
        # 但只有 10 条消息，window_turns=20 > 7，所以只有 1 个窗口 start=0
        # end=min(20,7)=7, window_msgs = 7 轮的所有消息 = 10 条 >= 10 → 保留
        windows = build_windows(msgs)
        assert len(windows) == 1
        assert len(windows[0]) == 10

    def test_window_size_default_20_turns(self):
        """默认 window_turns=20。"""
        # 生成 40 条交替消息 = 40 轮
        msgs = self._make_messages(40)
        windows = build_windows(msgs)
        # start=0: turns[0:20] = 20 条消息 >= 10 ✓
        # start=10: turns[10:30] = 20 条消息 >= 10 ✓
        # start=20: turns[20:40] = 20 条消息 >= 10 ✓
        # start=30: 30 >= max(1, 40-20+1)=21? No, range(0, 21, 10) = [0, 10, 20]
        assert len(windows) == 3
        for w in windows:
            assert len(w) == 20  # 每个窗口 20 条消息

    def test_slide_turns_default_10(self):
        """默认 slide_turns=10。"""
        msgs = self._make_messages(50)
        windows = build_windows(msgs)
        # range(0, max(1, 50-20+1), 10) = range(0, 31, 10) = [0, 10, 20, 30]
        assert len(windows) == 4

    def test_custom_window_and_slide(self):
        """自定义 window_turns 和 slide_turns。"""
        msgs = self._make_messages(20)
        windows = build_windows(msgs, window_turns=5, slide_turns=2)
        # range(0, max(1, 20-5+1), 2) = range(0, 16, 2) = [0,2,4,6,8,10,12,14]
        # 每个窗口 5 条消息 >= 10? No, 5 < 10 → 全被过滤
        assert windows == []

    def test_window_with_fewer_than_10_messages_filtered(self):
        """窗口内消息数 < 10 → 过滤。"""
        # 构造 5 轮，每轮 1 条消息 = 5 条消息 < 10
        msgs = [
            {"role": "me" if i % 2 == 0 else "her", "text": f"m{i}", "timestamp": i}
            for i in range(5)
        ]
        windows = build_windows(msgs)
        assert windows == []

    def test_custom_params_with_enough_messages(self):
        """自定义参数 + 足够消息 → 生成窗口。"""
        msgs = self._make_messages(30)
        windows = build_windows(msgs, window_turns=10, slide_turns=5)
        # range(0, max(1, 30-10+1), 5) = range(0, 21, 5) = [0, 5, 10, 15, 20]
        # 每个窗口 10 条消息 >= 10 ✓
        assert len(windows) == 5


# ═══════════════════════════════════════════════════════════════════
# _clean_content
# ═══════════════════════════════════════════════════════════════════

class TestCleanContent:
    """_clean_content 清洗消息内容。"""

    def test_plain_text_unchanged(self):
        text = "你好呀"
        assert _clean_content(text) == "你好呀"

    def test_xml_tags_removed(self):
        text = "<emoji>你好</emoji>"
        result = _clean_content(text)
        assert "<" not in result
        assert ">" not in result
        assert "你好" in result

    def test_empty_string(self):
        assert _clean_content("") == ""

    def test_none_input(self):
        """None 输入 → 返回空字符串。"""
        assert _clean_content(None) == ""

    def test_whitespace_stripped(self):
        assert _clean_content("  你好  ") == "你好"

    def test_long_text_truncated(self):
        """超过 500 字符 → 截断到 500。"""
        text = "a" * 600
        result = _clean_content(text)
        assert len(result) == 500

    def test_text_at_500_chars_not_truncated(self):
        """正好 500 字符 → 不截断。"""
        text = "a" * 500
        result = _clean_content(text)
        assert len(result) == 500

    def test_mixed_xml_and_text(self):
        text = "你好<image>图片</image>世界"
        result = _clean_content(text)
        assert "你好" in result
        assert "世界" in result
        assert "<image>" not in result

    def test_only_xml_tags(self):
        """全是 XML 标签 → 清洗后为空字符串。"""
        text = "<tag></tag>"
        result = _clean_content(text)
        assert result == ""


# ═══════════════════════════════════════════════════════════════════
# 常量验证
# ═══════════════════════════════════════════════════════════════════

class TestConstants:
    """模块常量非空且符合预期。"""

    def test_question_patterns_non_empty(self):
        assert len(_QUESTION_PATTERNS) > 0
        assert all(isinstance(p, str) for p in _QUESTION_PATTERNS)

    def test_flirt_keywords_non_empty(self):
        assert len(_FLIRT_KEYWORDS) > 0
        assert all(isinstance(k, str) for k in _FLIRT_KEYWORDS)

    def test_perfunctory_words_non_empty(self):
        assert len(_PERFUNCTORY_WORDS) > 0
        assert all(isinstance(w, str) for w in _PERFUNCTORY_WORDS)

    def test_perfunctory_words_contains_common_responses(self):
        """敷衍词列表包含常见敷衍回应。"""
        for word in ["嗯", "哦", "好", "ok"]:
            assert word in _PERFUNCTORY_WORDS

    def test_flirt_keywords_contains_common_flirt(self):
        """暧昧词列表包含常见暧昧表达。"""
        for word in ["想你", "喜欢你", "爱你", "宝贝"]:
            assert word in _FLIRT_KEYWORDS
