"""ml/scripts/clean_batch.py 单元测试。

覆盖：
- prune_message（短语清洗：整行删除+行内删除）
- clean_sample（样本清洗：调用 clean_message + 轮数过滤）

注意：clean_message 要求每行 >= 2 字符且总结果 >= 3 字符，
所以测试消息长度需 >= 3 字符才会被保留。
"""
from __future__ import annotations

import pytest

from ml.scripts.clean_batch import (
    prune_message,
    clean_sample,
)


# ═══════════════════════════════════════════════════════════════════
# prune_message
# ═══════════════════════════════════════════════════════════════════

class TestPruneMessage:
    """prune_message 删除包含指定短语的行，或行内删除短语。"""

    def test_empty_phrases_returns_original(self):
        """phrases 为空 → 返回原文。"""
        content = "你好呀\n世界真美好"
        assert prune_message(content, []) == content

    def test_no_matching_phrase_returns_original(self):
        content = "你好呀\n世界真美好"
        result = prune_message(content, ["不存在的短语"])
        assert result == content

    def test_line_with_phrase_removed_when_becomes_empty(self):
        """整行只剩短语 → 整行删除。"""
        content = "你好呀\nneyhow\n世界真美好"
        result = prune_message(content, ["neyhow"])
        assert "neyhow" not in result
        assert "你好呀" in result
        assert "世界真美好" in result

    def test_phrase_removed_inline_preserves_rest(self):
        """行内删除短语，保留剩余内容。"""
        content = "你好neyhow世界"
        result = prune_message(content, ["neyhow"])
        assert "neyhow" not in result
        assert "你好世界" in result

    def test_multiple_phrases(self):
        """多个短语同时清洗。"""
        content = "关注neyhow\n广告puaxingnan\n正常对话呀"
        result = prune_message(content, ["neyhow", "puaxingnan"])
        assert "neyhow" not in result
        assert "puaxingnan" not in result
        assert "正常对话呀" in result

    def test_phrase_in_multiple_lines(self):
        """短语出现在多行 → 全部清洗。"""
        content = "neyhow第一行\n中间内容呀\nneyhow第三行"
        result = prune_message(content, ["neyhow"])
        assert "neyhow" not in result
        assert "中间内容呀" in result

    def test_empty_content(self):
        assert prune_message("", ["neyhow"]) == ""

    def test_empty_lines_preserved(self):
        """空行不受影响（不含短语则保留）。"""
        content = "你好呀\n\n世界真美好"
        result = prune_message(content, ["neyhow"])
        assert result == content

    def test_phrase_partial_match(self):
        """短语是子串匹配（不是全行匹配）。"""
        content = "加微信neyhow获取更多内容"
        result = prune_message(content, ["neyhow"])
        # 行内删除 neyhow，保留"加微信获取更多内容"
        assert "neyhow" not in result
        assert "加微信" in result
        assert "获取更多内容" in result

    def test_line_becomes_whitespace_only_after_prune(self):
        """行内删除后只剩空白 → 整行删除。"""
        content = "你好呀\n  neyhow  \n世界真美好"
        result = prune_message(content, ["neyhow"])
        assert "neyhow" not in result
        assert "你好呀" in result
        assert "世界真美好" in result

    def test_multiline_content_with_mixed_phrases(self):
        """多行混合场景。"""
        content = "正常对话一\n广告neyhow\n正常对话二neyhow尾巴\n  neyhow  \n正常对话三"
        result = prune_message(content, ["neyhow"])
        assert "neyhow" not in result
        assert "正常对话一" in result
        assert "正常对话二尾巴" in result
        assert "正常对话三" in result

    def test_phrase_with_special_regex_chars(self):
        """含正则特殊字符的短语按字面匹配（replace 不是 regex）。"""
        content = "价格: 100.00 元整"
        result = prune_message(content, ["100.00"])
        assert "100.00" not in result
        assert "价格" in result


# ═══════════════════════════════════════════════════════════════════
# clean_sample
# ═══════════════════════════════════════════════════════════════════

class TestCleanSample:
    """clean_sample 清洗整个样本（调用 clean_message + 轮数过滤）。

    注意：clean_message 要求每行 >= 2 字符且总结果 >= 3 字符，
    所以测试消息长度需 >= 3 字符才会被保留。
    """

    def test_basic_clean_sample(self):
        """正常样本 → 返回清洗后的字典。"""
        sample = {
            "sample_id": "s_001",
            "contact_wxid": "chat_001",
            "contact_remark": "测试",
            "turn_count": 3,
            "messages": [
                {"role": "her", "content": "你好呀，在吗", "timestamp": 1000},
                {"role": "me", "content": "我在这里呀", "timestamp": 2000},
                {"role": "her", "content": "嗯嗯好的呀", "timestamp": 3000},
                {"role": "me", "content": "今天天气真好", "timestamp": 4000},
                {"role": "her", "content": "是呀很不错", "timestamp": 5000},
                {"role": "me", "content": "出去走走吧？", "timestamp": 6000},
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        assert result["sample_id"] == "s_001"
        assert result["contact_wxid"] == "chat_001"
        assert result["contact_remark"] == "测试"
        assert result["turn_count"] == 6
        assert len(result["messages"]) == 6

    def test_sample_with_fewer_than_6_messages_returns_none(self):
        """清洗后消息数 < 6 → None。"""
        sample = {
            "sample_id": "s_002",
            "messages": [
                {"role": "her", "content": "你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "我在这里呀", "timestamp": 2000},
            ],
        }
        result = clean_sample(sample)
        assert result is None

    def test_sample_with_watermark_messages(self):
        """含水印的消息被清洗后保留有效内容。"""
        sample = {
            "sample_id": "s_003",
            "messages": [
                {"role": "her", "content": "你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "加PUA倪微信平台：neyhow", "timestamp": 2000},  # 水印行
                {"role": "her", "content": "在吗在吗呀", "timestamp": 3000},
                {"role": "me", "content": "今天天气真好", "timestamp": 4000},
                {"role": "her", "content": "是呀很不错", "timestamp": 5000},
                {"role": "me", "content": "出去走走吧", "timestamp": 6000},
                {"role": "her", "content": "好的没问题", "timestamp": 7000},
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        # 水印行被整行删除后，该消息变为空 → 被过滤
        assert len(result["messages"]) < 7
        # 剩余消息中不应包含水印
        for m in result["messages"]:
            assert "neyhow" not in m["content"]
            assert "PUA" not in m["content"]

    def test_sample_with_prune_phrases(self):
        """prune_phrases 在 clean_message 之前应用。"""
        sample = {
            "sample_id": "s_004",
            "messages": [
                {"role": "her", "content": "你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "正常消息呀", "timestamp": 2000},
                {"role": "her", "content": "custom_ad_text在这里", "timestamp": 3000},
                {"role": "me", "content": "另一条消息", "timestamp": 4000},
                {"role": "her", "content": "再一条消息", "timestamp": 5000},
                {"role": "me", "content": "最后一条呀", "timestamp": 6000},
            ],
        }
        result = clean_sample(sample, prune_phrases=["custom_ad"])
        assert result is not None
        for m in result["messages"]:
            assert "custom_ad" not in m["content"]

    def test_sample_missing_messages_field(self):
        """缺少 messages 字段 → 视为空，返回 None。"""
        sample = {"sample_id": "s_005"}
        result = clean_sample(sample)
        assert result is None

    def test_sample_missing_sample_id(self):
        """缺少 sample_id → 字段为 None。"""
        sample = {
            "messages": [
                {"role": "her", "content": "你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "我在这里呀", "timestamp": 2000},
                {"role": "her", "content": "嗯嗯好的呀", "timestamp": 3000},
                {"role": "me", "content": "今天天气好", "timestamp": 4000},
                {"role": "her", "content": "是呀不错", "timestamp": 5000},
                {"role": "me", "content": "走吧走走", "timestamp": 6000},
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        assert result["sample_id"] is None

    def test_sample_missing_timestamp_defaults_to_0(self):
        """消息缺少 timestamp → 默认为 0。"""
        sample = {
            "sample_id": "s_006",
            "messages": [
                {"role": "her", "content": "你好呀在吗"},
                {"role": "me", "content": "我在这里呀"},
                {"role": "her", "content": "嗯嗯好的呀"},
                {"role": "me", "content": "今天天气好"},
                {"role": "her", "content": "是呀不错"},
                {"role": "me", "content": "走吧走走"},
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        for m in result["messages"]:
            assert m["timestamp"] == 0

    def test_sample_with_case_tag_lines(self):
        """案例标签行被清洗。"""
        sample = {
            "sample_id": "s_007",
            "messages": [
                {"role": "her", "content": "<3621台湾超模案例\n你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "我在这里呀", "timestamp": 2000},
                {"role": "her", "content": "嗯嗯好的呀", "timestamp": 3000},
                {"role": "me", "content": "今天天气真好", "timestamp": 4000},
                {"role": "her", "content": "是呀很不错", "timestamp": 5000},
                {"role": "me", "content": "出去走走吧", "timestamp": 6000},
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        for m in result["messages"]:
            assert "3621" not in m["content"]
            assert "台湾超模" not in m["content"]

    def test_all_messages_filtered_returns_none(self):
        """所有消息清洗后都无效 → None。"""
        sample = {
            "sample_id": "s_008",
            "messages": [
                {"role": "her", "content": "加PUA倪微信平台：neyhow", "timestamp": 1000},
                {"role": "me", "content": "瑞恩情感RYAN PUA", "timestamp": 2000},
            ],
        }
        result = clean_sample(sample)
        assert result is None

    def test_turn_count_reflects_valid_messages(self):
        """turn_count 等于清洗后的有效消息数。"""
        sample = {
            "sample_id": "s_009",
            "turn_count": 10,  # 原始值
            "messages": [
                {"role": "her", "content": "你好呀在吗", "timestamp": 1000},
                {"role": "me", "content": "我在这里呀", "timestamp": 2000},
                {"role": "her", "content": "嗯嗯好的呀", "timestamp": 3000},
                {"role": "me", "content": "今天天气好", "timestamp": 4000},
                {"role": "her", "content": "是呀不错呀", "timestamp": 5000},
                {"role": "me", "content": "走吧走走吧", "timestamp": 6000},
                {"role": "her", "content": "瑞恩情感RYAN PUA", "timestamp": 7000},  # 水印，过滤
            ],
        }
        result = clean_sample(sample)
        assert result is not None
        assert result["turn_count"] == 6  # 过滤掉 1 条水印
        assert len(result["messages"]) == 6

    def test_empty_messages_list(self):
        sample = {
            "sample_id": "s_010",
            "messages": [],
        }
        result = clean_sample(sample)
        assert result is None

    def test_sample_with_all_short_messages_filtered(self):
        """所有消息都太短（< 3 字符）→ 全部被过滤 → None。"""
        sample = {
            "sample_id": "s_011",
            "messages": [
                {"role": "her", "content": "嗯", "timestamp": 1000},
                {"role": "me", "content": "哦", "timestamp": 2000},
                {"role": "her", "content": "好", "timestamp": 3000},
                {"role": "me", "content": "行", "timestamp": 4000},
                {"role": "her", "content": "对", "timestamp": 5000},
                {"role": "me", "content": "是", "timestamp": 6000},
            ],
        }
        result = clean_sample(sample)
        # 所有消息都是 1 字符，clean_message 返回 None → 全部过滤 → < 6 条 → None
        assert result is None
