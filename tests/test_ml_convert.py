"""ml/dataset/convert_chat_data.py 单元测试。

覆盖：
- fix_reordered_text（乱序文本修复：开头"们"+结尾"我"模式）
- clean_message（消息清洗：低置信度/低质量/水印过滤/乱序修复）
- CleanMessage.is_valid（消息有效性：空内容/非法 sender）
- merge_consecutive_same_sender（合并连续同发件人消息）
- build_windows（滑动窗口：MIN_TURNS 边界/STEP_SIZE 步长）
- window_to_dict（窗口转字典：字段完整性）
- load_and_clean_file（文件加载：JSON 解析/批量清洗）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.dataset.convert_chat_data import (
    CleanMessage,
    WINDOW_SIZE,
    STEP_SIZE,
    MIN_TURNS,
    CONFIDENCE_THRESHOLD,
    fix_reordered_text,
    clean_message,
    merge_consecutive_same_sender,
    build_windows,
    window_to_dict,
    load_and_clean_file,
)


# ═══════════════════════════════════════════════════════════════════
# 常量验证
# ═══════════════════════════════════════════════════════════════════

class TestConstants:
    """模块常量符合预期设计值。"""

    def test_window_size_is_20(self):
        assert WINDOW_SIZE == 20

    def test_step_size_is_10(self):
        assert STEP_SIZE == 10

    def test_min_turns_is_10(self):
        assert MIN_TURNS == 10

    def test_confidence_threshold_is_07(self):
        assert CONFIDENCE_THRESHOLD == 0.7


# ═══════════════════════════════════════════════════════════════════
# fix_reordered_text
# ═══════════════════════════════════════════════════════════════════

class TestFixReorderedText:
    """fix_reordered_text 修复特定的乱序模式。"""

    def test_normal_text_unchanged(self):
        """普通文本不修改。"""
        text = "我通过了你的朋友验证请求"
        assert fix_reordered_text(text) == text

    def test_empty_string(self):
        assert fix_reordered_text("") == ""

    def test_reordered_pattern_men_at_start(self):
        """开头"们"+单个"我"且 parts[0]=="们" → 重建为"我...们"。
        
        函数实现限制：长度守恒检查 len(reconstructed)==len(text) 仅在
        parts[0]=="们"（单字符）时成立。此时：
        - text = "们" + "我" + rest
        - parts = ["们", rest]
        - reconstructed = "我" + rest + "们"（把"们"从开头移到结尾）
        """
        # 构造满足长度守恒的输入：text = "们我XXX" → "我XXX们"
        text = "们我通过了你的验证"
        result = fix_reordered_text(text)
        assert result == "我通过了你的验证们"
        assert len(result) == len(text)
        assert result.startswith("我")
        assert result.endswith("们")

    def test_men_at_start_no_wo_returns_original(self):
        """开头"们"但无"我" → 不修改。"""
        text = "们是一个测试"
        assert fix_reordered_text(text) == text

    def test_men_at_start_multiple_wo(self):
        """开头"们"且有多个"我" → 长度守恒通常失败，返回原文。
        
        多个"我"时 split 产生 >2 个 parts，reconstructed 丢失 parts[0] 内容
        导致长度不匹配，函数返回原始文本。这是函数实现的已知限制。
        """
        text = "们可以我通过我验证"
        result = fix_reordered_text(text)
        # 长度守恒失败（8 != 7），返回原文
        assert result == text

    def test_documented_example_not_fixed_due_to_length_check(self):
        """文档示例"们可以开始聊天了我...现在我"因长度守恒失败不被修复。
        
        已知限制：函数文档声明的示例输入实际上无法被修复，因为
        parts[0]="们可以开始聊天了"（8字符）被丢弃导致长度不匹配。
        此测试记录该限制，防止误以为函数能处理该案例。
        """
        text = "们可以开始聊天了我通过了你的朋友验证请求，现在我"
        result = fix_reordered_text(text)
        # 长度守恒失败，返回原文
        assert result == text

    def test_text_without_men_at_start(self):
        """非"们"开头 → 不修改。"""
        text = "我们可以开始聊天了"
        assert fix_reordered_text(text) == text


# ═══════════════════════════════════════════════════════════════════
# CleanMessage.is_valid
# ═══════════════════════════════════════════════════════════════════

class TestCleanMessageIsValid:
    """CleanMessage.is_valid 验证消息有效性。"""

    def test_valid_me_message(self):
        msg = CleanMessage(sender="me", content="你好", timestamp=1000)
        assert msg.is_valid() is True

    def test_valid_her_message(self):
        msg = CleanMessage(sender="her", content="嗨", timestamp=1000)
        assert msg.is_valid() is True

    def test_empty_content_invalid(self):
        msg = CleanMessage(sender="me", content="", timestamp=1000)
        assert msg.is_valid() is False

    def test_whitespace_only_content_invalid(self):
        msg = CleanMessage(sender="me", content="   ", timestamp=1000)
        assert msg.is_valid() is False

    def test_invalid_sender(self):
        msg = CleanMessage(sender="other", content="你好", timestamp=1000)
        assert msg.is_valid() is False

    def test_none_content_invalid(self):
        msg = CleanMessage(sender="me", content=None, timestamp=1000)
        assert msg.is_valid() is False

    def test_non_string_content_invalid(self):
        msg = CleanMessage(sender="me", content=12345, timestamp=1000)
        assert msg.is_valid() is False

    def test_confidence_default_is_1(self):
        msg = CleanMessage(sender="me", content="你好", timestamp=1000)
        assert msg.confidence == 1.0


# ═══════════════════════════════════════════════════════════════════
# clean_message
# ═══════════════════════════════════════════════════════════════════

class TestCleanMessageFunction:
    """clean_message 函数清洗单条消息字典。"""

    def test_basic_valid_message(self):
        raw = {"sender": "me", "content": "你好呀", "timestamp": 1000}
        result = clean_message(raw)
        assert result is not None
        assert result.sender == "me"
        assert result.content == "你好呀"
        assert result.timestamp == 1000

    def test_low_confidence_filtered(self):
        """confidence < 0.7 → None。"""
        raw = {"sender": "me", "content": "你好", "timestamp": 1000, "confidence": 0.5}
        assert clean_message(raw) is None

    def test_confidence_at_threshold_kept(self):
        """confidence == 0.7 → 保留。"""
        raw = {"sender": "me", "content": "你好", "timestamp": 1000, "confidence": 0.7}
        result = clean_message(raw)
        assert result is not None

    def test_high_confidence_kept(self):
        raw = {"sender": "me", "content": "你好", "timestamp": 1000, "confidence": 0.95}
        result = clean_message(raw)
        assert result is not None

    def test_low_quality_digit_only_filtered(self):
        """纯数字 → None。"""
        raw = {"sender": "me", "content": "12345", "timestamp": 1000}
        assert clean_message(raw) is None

    def test_low_quality_dots_only_filtered(self):
        """纯点号 → None。"""
        raw = {"sender": "me", "content": "···", "timestamp": 1000}
        assert clean_message(raw) is None

    def test_watermark_removed(self):
        """水印内容被去除。"""
        raw = {"sender": "me", "content": "你好 2020-09-18 10:00", "timestamp": 1000}
        result = clean_message(raw)
        assert result is not None
        assert "2020-09-18" not in result.content
        assert "你好" in result.content

    def test_content_stripped(self):
        """前后空白被去除。"""
        raw = {"sender": "me", "content": "  你好  ", "timestamp": 1000}
        result = clean_message(raw)
        assert result is not None
        assert result.content == "你好"

    def test_whitespace_collapsed(self):
        """内部多余空白被压缩为单空格。"""
        raw = {"sender": "me", "content": "你    好    呀", "timestamp": 1000}
        result = clean_message(raw)
        assert result is not None
        assert result.content == "你 好 呀"

    def test_non_dict_input_returns_none(self):
        assert clean_message("not a dict") is None
        assert clean_message(None) is None
        assert clean_message([]) is None

    def test_non_string_content_converted(self):
        """非字符串 content 被转为字符串。"""
        raw = {"sender": "me", "content": 12345, "timestamp": 1000}
        result = clean_message(raw)
        # "12345" 是纯数字 → LOW_QUALITY_PATTERNS 匹配 → None
        assert result is None

    def test_empty_content_after_cleaning_returns_none(self):
        """清洗后内容为空 → None。"""
        raw = {"sender": "me", "content": "2020-09-18", "timestamp": 1000}
        # 全是水印，清洗后为空
        assert clean_message(raw) is None

    def test_default_confidence_is_1(self):
        raw = {"sender": "me", "content": "你好", "timestamp": 1000}
        result = clean_message(raw)
        assert result is not None
        assert result.confidence == 1.0

    def test_default_timestamp_is_0(self):
        raw = {"sender": "me", "content": "你好"}
        result = clean_message(raw)
        assert result is not None
        assert result.timestamp == 0


# ═══════════════════════════════════════════════════════════════════
# merge_consecutive_same_sender
# ═══════════════════════════════════════════════════════════════════

class TestMergeConsecutiveSameSender:
    """merge_consecutive_same_sender 合并连续同发件人。"""

    def test_empty_list(self):
        assert merge_consecutive_same_sender([]) == []

    def test_single_message(self):
        msgs = [CleanMessage(sender="me", content="你好", timestamp=1000)]
        result = merge_consecutive_same_sender(msgs)
        assert len(result) == 1
        assert result[0].content == "你好"

    def test_already_alternating(self):
        """交替发送 → 每条都是一轮。"""
        msgs = [
            CleanMessage(sender="me", content="你好", timestamp=1000),
            CleanMessage(sender="her", content="嗨", timestamp=2000),
            CleanMessage(sender="me", content="在吗", timestamp=3000),
        ]
        result = merge_consecutive_same_sender(msgs)
        assert len(result) == 3
        assert result[0].content == "你好"
        assert result[1].content == "嗨"
        assert result[2].content == "在吗"

    def test_consecutive_same_sender_merged(self):
        """连续同人 → 合并为一轮。"""
        msgs = [
            CleanMessage(sender="me", content="你好", timestamp=1000),
            CleanMessage(sender="me", content="在吗", timestamp=2000),
            CleanMessage(sender="her", content="嗯", timestamp=3000),
        ]
        result = merge_consecutive_same_sender(msgs)
        assert len(result) == 2
        assert result[0].content == "你好\n在吗"
        assert result[1].content == "嗯"

    def test_three_consecutive_merged(self):
        """三条连续同人 → 合并为一轮。"""
        msgs = [
            CleanMessage(sender="her", content="嗨", timestamp=1000),
            CleanMessage(sender="her", content="你好", timestamp=2000),
            CleanMessage(sender="her", content="在吗", timestamp=3000),
        ]
        result = merge_consecutive_same_sender(msgs)
        assert len(result) == 1
        assert result[0].content == "嗨\n你好\n在吗"

    def test_merged_uses_first_timestamp(self):
        """合并后的时间戳使用第一条消息的时间戳。"""
        msgs = [
            CleanMessage(sender="me", content="你好", timestamp=1000),
            CleanMessage(sender="me", content="在吗", timestamp=2000),
        ]
        result = merge_consecutive_same_sender(msgs)
        assert result[0].timestamp == 1000

    def test_merged_preserves_confidence(self):
        """合并后的 confidence 使用第一条消息的 confidence。"""
        msgs = [
            CleanMessage(sender="me", content="你好", timestamp=1000, confidence=0.9),
            CleanMessage(sender="me", content="在吗", timestamp=2000, confidence=0.5),
        ]
        result = merge_consecutive_same_sender(msgs)
        assert result[0].confidence == 0.9


# ═══════════════════════════════════════════════════════════════════
# build_windows
# ═══════════════════════════════════════════════════════════════════

class TestBuildWindows:
    """build_windows 从轮次列表构建滑动窗口。"""

    def _make_turns(self, n: int) -> list[CleanMessage]:
        """生成 n 个交替发送的轮次。"""
        return [
            CleanMessage(sender="me" if i % 2 == 0 else "her", content=f"msg{i}", timestamp=i)
            for i in range(n)
        ]

    def test_empty_turns(self):
        assert build_windows([]) == []

    def test_fewer_than_min_turns(self):
        """轮次数 < MIN_TURNS(10) → 空列表。"""
        turns = self._make_turns(9)
        assert build_windows(turns) == []

    def test_exactly_min_turns(self):
        """轮次数 == MIN_TURNS → 1 个窗口。"""
        turns = self._make_turns(MIN_TURNS)
        windows = build_windows(turns)
        assert len(windows) == 1
        assert len(windows[0]) == MIN_TURNS

    def test_window_size_capped(self):
        """窗口大小不超过 WINDOW_SIZE(20)。"""
        turns = self._make_turns(25)
        windows = build_windows(turns)
        for w in windows:
            assert len(w) <= WINDOW_SIZE

    def test_step_size_slide(self):
        """滑动步长为 STEP_SIZE(10)。
        
        30 轮 → 窗口起始位置 0, 10 → 2 个窗口（start=20 时 end=30, 30-20=10 >= MIN_TURNS）
        """
        turns = self._make_turns(30)
        windows = build_windows(turns)
        # start=0 (end=20), start=10 (end=30), start=20 (end=min(40,30)=30, 30-20=10>=10)
        assert len(windows) == 3

    def test_last_window_shorter_but_valid(self):
        """最后一个窗口可能小于 WINDOW_SIZE 但 >= MIN_TURNS。"""
        turns = self._make_turns(15)
        windows = build_windows(turns)
        # start=0, end=min(20,15)=15, 15-0=15>=10 → 1 个窗口
        assert len(windows) == 1
        assert len(windows[0]) == 15

    def test_last_window_too_short_skipped(self):
        """最后一个窗口 < MIN_TURNS → 跳过。"""
        turns = self._make_turns(19)
        windows = build_windows(turns)
        # start=0, end=min(20,19)=19, 19-0=19>=10 → 1 个窗口
        # start=10, end=min(30,19)=19, 19-10=9<10 → 跳过
        assert len(windows) == 1

    def test_window_content_preserved(self):
        """窗口内消息顺序和内容保持一致。"""
        turns = self._make_turns(10)
        windows = build_windows(turns)
        assert windows[0][0].content == "msg0"
        assert windows[0][9].content == "msg9"


# ═══════════════════════════════════════════════════════════════════
# window_to_dict
# ═══════════════════════════════════════════════════════════════════

class TestWindowToDict:
    """window_to_dict 将窗口转换为标准字典。"""

    def test_basic_conversion(self):
        window = [
            CleanMessage(sender="me", content="你好", timestamp=1000),
            CleanMessage(sender="her", content="嗨", timestamp=2000),
        ]
        result = window_to_dict(window, "s_001", "chat_001", "测试对话")

        assert result["sample_id"] == "s_001"
        assert result["contact_wxid"] == "chat_001"
        assert result["contact_remark"] == "测试对话"
        assert result["turn_count"] == 2
        assert result["start_ts"] == 1000
        assert result["end_ts"] == 2000

    def test_messages_structure(self):
        window = [
            CleanMessage(sender="me", content="你好", timestamp=1000),
            CleanMessage(sender="her", content="嗨", timestamp=2000),
        ]
        result = window_to_dict(window, "s_001", "chat_001", "测试")
        msgs = result["messages"]
        assert len(msgs) == 2
        assert msgs[0] == {"turn": 1, "role": "me", "content": "你好", "timestamp": 1000}
        assert msgs[1] == {"turn": 2, "role": "her", "content": "嗨", "timestamp": 2000}

    def test_turn_index_starts_at_1(self):
        """turn 从 1 开始计数。"""
        window = [CleanMessage(sender="me", content=f"m{i}", timestamp=i) for i in range(5)]
        result = window_to_dict(window, "s_001", "chat_001", "测试")
        turns = [m["turn"] for m in result["messages"]]
        assert turns == [1, 2, 3, 4, 5]

    def test_single_message_window(self):
        window = [CleanMessage(sender="me", content="你好", timestamp=1000)]
        result = window_to_dict(window, "s_001", "chat_001", "测试")
        assert result["turn_count"] == 1
        assert result["start_ts"] == 1000
        assert result["end_ts"] == 1000

    def test_start_end_ts_correct(self):
        """start_ts 是第一条，end_ts 是最后一条。"""
        window = [
            CleanMessage(sender="me", content="A", timestamp=5000),
            CleanMessage(sender="her", content="B", timestamp=1000),
            CleanMessage(sender="me", content="C", timestamp=9000),
        ]
        result = window_to_dict(window, "s_001", "chat_001", "测试")
        assert result["start_ts"] == 5000
        assert result["end_ts"] == 9000


# ═══════════════════════════════════════════════════════════════════
# load_and_clean_file
# ═══════════════════════════════════════════════════════════════════

class TestLoadAndCleanFile:
    """load_and_clean_file 加载并清洗 JSON 文件。"""

    def test_valid_file(self, tmp_path):
        """正常 JSON 文件 → 返回清洗后的 CleanMessage 列表。"""
        data = [
            {"sender": "me", "content": "你好", "timestamp": 1000},
            {"sender": "her", "content": "嗨", "timestamp": 2000},
        ]
        fpath = tmp_path / "test.json"
        fpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = load_and_clean_file(fpath)
        assert len(result) == 2
        assert all(isinstance(m, CleanMessage) for m in result)
        assert result[0].content == "你好"
        assert result[1].content == "嗨"

    def test_empty_file(self, tmp_path):
        """空文件 → 空列表。"""
        fpath = tmp_path / "empty.json"
        fpath.write_text("", encoding="utf-8")
        result = load_and_clean_file(fpath)
        assert result == []

    def test_nonexistent_file(self, tmp_path):
        """不存在的文件 → 空列表（异常被捕获）。"""
        fpath = tmp_path / "nonexistent.json"
        result = load_and_clean_file(fpath)
        assert result == []

    def test_non_list_json(self, tmp_path):
        """JSON 不是列表 → 空列表。"""
        fpath = tmp_path / "dict.json"
        fpath.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        result = load_and_clean_file(fpath)
        assert result == []

    def test_invalid_json(self, tmp_path):
        """JSON 格式错误 → 空列表。"""
        fpath = tmp_path / "bad.json"
        fpath.write_text("not a json{{{", encoding="utf-8")
        result = load_and_clean_file(fpath)
        assert result == []

    def test_filters_invalid_messages(self):
        """无效消息被过滤（低置信度/低质量）。"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([
                {"sender": "me", "content": "你好", "timestamp": 1000},
                {"sender": "me", "content": "12345", "timestamp": 2000},  # 纯数字被过滤
                {"sender": "her", "content": "嗨", "timestamp": 3000},
            ], f, ensure_ascii=False)
            fpath = Path(f.name)

        try:
            result = load_and_clean_file(fpath)
            assert len(result) == 2
            assert result[0].content == "你好"
            assert result[1].content == "嗨"
        finally:
            fpath.unlink(missing_ok=True)

    def test_empty_list_json(self, tmp_path):
        """JSON 是空列表 → 空列表。"""
        fpath = tmp_path / "empty_list.json"
        fpath.write_text("[]", encoding="utf-8")
        result = load_and_clean_file(fpath)
        assert result == []

    def test_all_messages_filtered(self, tmp_path):
        """所有消息都无效 → 空列表。"""
        data = [
            {"sender": "me", "content": "12345", "timestamp": 1000},
            {"sender": "me", "content": "···", "timestamp": 2000},
        ]
        fpath = tmp_path / "all_bad.json"
        fpath.write_text(json.dumps(data), encoding="utf-8")
        result = load_and_clean_file(fpath)
        assert result == []
