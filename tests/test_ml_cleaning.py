"""ml/cleaning_patterns.py + ml/scripts/clean_watermarks.py 单元测试。

覆盖：
- is_narrative（旁白判定：NARRATIVE_MARKERS + 长文本无对话标记）
- clean_message（消息清洗：案例标签/水印/时间戳/OCR碎片/旁白/行内替换）
- clean_text（水印清洗：WATERMARK_PATTERNS + 空白清理）
- diff_text（文本差异摘要）
- load_jsonl / save_jsonl（JSONL I/O）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.cleaning_patterns import (
    is_narrative,
    clean_message,
    NARRATIVE_MARKERS,
)
from ml.scripts.clean_watermarks import (
    clean_text,
    diff_text,
    load_jsonl,
    save_jsonl,
)


# ═══════════════════════════════════════════════════════════════════
# is_narrative
# ═══════════════════════════════════════════════════════════════════

class TestIsNarrative:
    """is_narrative 判断文本是否为旁白。"""

    def test_narrative_marker_present(self):
        """含 NARRATIVE_MARKERS → True。"""
        # NARRATIVE_MARKERS 包含 "顺势把车开去"
        assert is_narrative("顺势把车开去了她家") is True

    def test_short_dialogue_not_narrative(self):
        """短对话文本 → False。"""
        # 含对话标记（？你我他她！）
        assert is_narrative("你好呀？") is False

    def test_long_text_with_dialogue(self):
        """长文本但有对话标记 → False。"""
        text = "今天天气真好啊？我们去散步吧" + "x" * 50
        assert is_narrative(text) is False

    def test_long_text_without_dialogue(self):
        """长文本无对话标记 → True（旁白）。"""
        # 超过 40 字符，不含 ？?！!你我他她
        text = "a" * 50
        assert is_narrative(text) is True

    def test_short_text_without_dialogue(self):
        """短文本无对话标记 → False（不是旁白，太短）。"""
        # ≤40 字符，不含对话标记
        assert is_narrative("abcd") is False

    def test_empty_string(self):
        """空字符串 → False。"""
        assert is_narrative("") is False

    def test_has_exclamation_mark(self):
        """含感叹号 → 有对话标记 → 需结合长度判断。"""
        # 短文本 + 感叹号 → False
        assert is_narrative("好棒！") is False

    def test_has_question_mark(self):
        """含问号 → 有对话标记。"""
        assert is_narrative("在吗？") is False

    def test_has_you(self):
        """含"你" → 有对话标记。"""
        assert is_narrative("你在干嘛") is False

    def test_long_text_with_narrative_marker(self):
        """长文本 + 旁白标记 → True（标记优先）。"""
        text = "顺势把车开去" + "x" * 50
        assert is_narrative(text) is True

    def test_boundary_40_chars(self):
        """40 字符边界（≤40 不算长文本）。"""
        # 正好 40 字符，无对话标记 → len(text) > 40 为 False
        text = "a" * 40
        assert is_narrative(text) is False
        # 41 字符 → True
        text = "a" * 41
        assert is_narrative(text) is True


# ═══════════════════════════════════════════════════════════════════
# clean_message
# ═══════════════════════════════════════════════════════════════════

class TestCleanMessage:
    """clean_message 清洗单条消息。"""

    def test_normal_message_kept(self):
        """正常消息 → 保留。"""
        result = clean_message("你好呀，在吗？")
        assert result is not None
        assert "你好呀" in result
        assert "在吗" in result

    def test_empty_content_returns_none(self):
        """空内容 → None。"""
        assert clean_message("") is None

    def test_whitespace_only_returns_none(self):
        """纯空白 → None。"""
        assert clean_message("   \n  \n  ") is None

    def test_case_tag_removed(self):
        """案例标签行被移除。"""
        # CASE_TAG_REGEX 匹配 <3621台湾超模案例 等
        content = "<3621台湾超模案例\n你好呀"
        result = clean_message(content)
        assert result is not None
        assert "3621" not in result
        assert "台湾超模" not in result
        assert "你好呀" in result

    def test_too_short_returns_none(self):
        """清洗后剩余内容 < 3 字符 → None。"""
        # 单行 "ab" 长度 < 2 → 不保留
        assert clean_message("ab") is None

    def test_multiple_lines_kept(self):
        """多行正常消息 → 全部保留。"""
        content = "你好呀\n在吗？\n今天天气真好"
        result = clean_message(content)
        assert result is not None
        assert "你好呀" in result
        assert "在吗" in result
        assert "今天天气真好" in result

    def test_verbose_mode(self, capsys):
        """verbose=True → 输出移除信息到 stderr。"""
        # 用案例标签触发 skip
        content = "<3621台湾超模案例\n你好呀"
        clean_message(content, verbose=True)
        captured = capsys.readouterr()
        assert "移除了" in captured.err or "案例标签" in captured.err

    def test_single_line_kept(self):
        """单行正常消息 → 保留。"""
        result = clean_message("你好呀，今天怎么样？")
        assert result is not None
        assert "你好呀" in result

    def test_line_too_short_filtered(self):
        """行长度 < 2 → 被过滤。"""
        # "a" 长度 < 2 → 不保留
        content = "a\n你好呀"
        result = clean_message(content)
        assert result is not None
        assert "你好呀" in result
        # "a" 单独一行应被过滤
        assert result.strip() == "你好呀"


# ═══════════════════════════════════════════════════════════════════
# clean_text
# ═══════════════════════════════════════════════════════════════════

class TestCleanText:
    """clean_text 去除水印。"""

    def test_plain_text_unchanged(self):
        """无水印文本 → 不变。"""
        text = "你好呀，在吗？"
        assert clean_text(text) == text

    def test_empty_string(self):
        """空字符串 → 空字符串。"""
        assert clean_text("") == ""

    def test_whitespace_cleaned(self):
        """行首行尾空格被清理。"""
        text = "  你好  \n  在吗  "
        result = clean_text(text)
        assert "你好" in result
        assert "在吗" in result
        # 不应有行首行尾空格
        for line in result.split("\n"):
            assert line == line.strip()

    def test_multiple_blank_lines_compressed(self):
        """多个连续空行压缩为最多 2 个。"""
        text = "你好\n\n\n\n\n在吗"
        result = clean_text(text)
        # 不应有超过 2 个连续换行
        assert "\n\n\n" not in result

    def test_trailing_whitespace_removed(self):
        """行尾空格被移除。"""
        text = "你好   \n在吗"
        result = clean_text(text)
        assert "你好   " not in result

    def test_leading_whitespace_removed(self):
        """行首空格被移除。"""
        text = "你好\n   在吗"
        result = clean_text(text)
        assert "   在吗" not in result

    def test_strip_called(self):
        """最终结果被 strip。"""
        text = "\n\n你好\n\n"
        result = clean_text(text)
        assert not result.startswith("\n")
        assert not result.endswith("\n")

    def test_normal_dialogue_preserved(self):
        """正常对话内容保留。"""
        text = "在吗？\n嗯嗯怎么了\n没事就问问"
        result = clean_text(text)
        assert "在吗" in result
        assert "嗯嗯怎么了" in result
        assert "没事就问问" in result


# ═══════════════════════════════════════════════════════════════════
# diff_text
# ═══════════════════════════════════════════════════════════════════

class TestDiffText:
    """diff_text 生成文本差异摘要。"""

    def test_identical_text_returns_empty(self):
        """相同文本 → 空字符串。"""
        assert diff_text("你好", "你好") == ""

    def test_single_line_change(self):
        """单行变更。"""
        before = "你好呀"
        after = "你好啊"
        result = diff_text(before, after)
        assert "- 你好呀" in result
        assert "+ 你好啊" in result

    def test_line_removed(self):
        """行被移除。"""
        before = "你好\n在吗"
        after = "你好"
        result = diff_text(before, after)
        assert "- 在吗" in result
        assert "+ (removed)" in result

    def test_line_added(self):
        """行被添加。"""
        before = "你好"
        after = "你好\n在吗"
        result = diff_text(before, after)
        assert "+ 在吗" in result

    def test_empty_before(self):
        """before 为空 → 全部是新增。"""
        result = diff_text("", "你好")
        assert "+ 你好" in result

    def test_empty_after(self):
        """after 为空 → 全部是移除。"""
        result = diff_text("你好", "")
        assert "- 你好" in result
        assert "+ (removed)" in result

    def test_both_empty(self):
        """两者都空 → 空字符串。"""
        assert diff_text("", "") == ""

    def test_max_20_lines(self):
        """最多显示 20 行差异。"""
        before = "\n".join([f"line_{i}" for i in range(30)])
        after = "\n".join([f"changed_{i}" for i in range(30)])
        result = diff_text(before, after)
        # parts[:20] 限制，但每行变更产生 2 行（- 和 +）
        # 所以最多 20 行输出
        lines = result.split("\n")
        assert len(lines) <= 20

    def test_line_truncated_to_80_chars(self):
        """行内容截取前 80 字符。"""
        long_line = "a" * 200
        result = diff_text(long_line, "b")
        # - 行应只含前 80 个字符
        for line in result.split("\n"):
            if line.startswith("- "):
                # "- " (2 chars) + 80 chars = 82
                assert len(line) <= 82

    def test_multiline_diff(self):
        """多行差异。"""
        before = "你好\n在吗\n今天怎么样"
        after = "你好\n在吗\n明天见"
        result = diff_text(before, after)
        assert "- 今天怎么样" in result
        assert "+ 明天见" in result


# ═══════════════════════════════════════════════════════════════════
# load_jsonl / save_jsonl
# ═══════════════════════════════════════════════════════════════════

class TestLoadSaveJsonl:
    """load_jsonl / save_jsonl JSONL I/O。"""

    def test_save_and_load_roundtrip(self, tmp_path):
        """保存后加载 → 数据一致。"""
        records = [
            {"sample_id": "s_001", "content": "你好"},
            {"sample_id": "s_002", "content": "在吗"},
        ]
        path = tmp_path / "test.jsonl"
        save_jsonl(path, records)
        loaded = load_jsonl(path)
        assert len(loaded) == 2
        assert loaded[0]["sample_id"] == "s_001"
        assert loaded[1]["content"] == "在吗"

    def test_load_empty_file(self, tmp_path):
        """空文件 → 空列表。"""
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        assert load_jsonl(path) == []

    def test_load_skips_empty_lines(self, tmp_path):
        """空行被跳过。"""
        path = tmp_path / "test.jsonl"
        path.write_text(
            json.dumps({"a": 1}) + "\n\n\n" + json.dumps({"b": 2}) + "\n",
            encoding="utf-8")
        result = load_jsonl(path)
        assert len(result) == 2

    def test_save_empty_list(self, tmp_path):
        """保存空列表 → 空文件。"""
        path = tmp_path / "empty.jsonl"
        save_jsonl(path, [])
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""

    def test_save_unicode(self, tmp_path):
        """保存中文 → ensure_ascii=False。"""
        records = [{"content": "你好世界"}]
        path = tmp_path / "unicode.jsonl"
        save_jsonl(path, records)
        content = path.read_text(encoding="utf-8")
        assert "你好世界" in content

    def test_save_creates_file(self, tmp_path):
        """保存创建新文件。"""
        path = tmp_path / "new.jsonl"
        save_jsonl(path, [{"test": True}])
        assert path.exists()

    def test_load_single_record(self, tmp_path):
        """单条记录。"""
        path = tmp_path / "single.jsonl"
        path.write_text(json.dumps({"sample_id": "s_001"}) + "\n", encoding="utf-8")
        result = load_jsonl(path)
        assert len(result) == 1
        assert result[0]["sample_id"] == "s_001"
