"""chat_history.py 单元测试。

覆盖 parse_date_bound / resolve_chat_target / query_chat_messages /
format_chat_messages / 内部辅助函数（_display_content / _fold_xml_message /
_speaker / _summarize_messages / _group_by_day）等。
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, time as dtime
from pathlib import Path

import pytest

from engine.analyzers.chat_history import (
    ChatMessage,
    ChatTarget,
    _display_content,
    _fold_xml_message,
    _format_summary_md,
    _format_summary_text,
    _group_by_day,
    _is_xml_message,
    _speaker,
    _summarize_messages,
    format_chat_messages,
    parse_date_bound,
    query_chat_messages,
    resolve_chat_target,
    write_chat_output,
)


# ── parse_date_bound ─────────────────────────────────────────────────────────

class TestParseDateBound:
    def test_none_returns_none(self):
        assert parse_date_bound(None) is None

    def test_empty_string_returns_none(self):
        assert parse_date_bound("") is None

    def test_whitespace_only_raises(self):
        """strip 后为空字符串走 isoformat 解析路径会抛 ValueError。"""
        with pytest.raises(ValueError, match="无法解析日期"):
            parse_date_bound("   ")

    def test_date_only_start(self):
        """YYYY-MM-DD 起始边界 = 当天 00:00:00。"""
        ts = parse_date_bound("2026-07-24")
        dt = datetime.fromtimestamp(ts)
        assert dt.date() == datetime(2026, 7, 24).date()
        assert dt.time() == dtime.min

    def test_date_only_end(self):
        """YYYY-MM-DD 结束边界 = 当天 23:59:59（timestamp 取整后微秒丢失）。"""
        ts = parse_date_bound("2026-07-24", is_end=True)
        dt = datetime.fromtimestamp(ts)
        assert dt.date() == datetime(2026, 7, 24).date()
        # int(timestamp) 截断微秒，得到 23:59:59
        assert dt.time() == dtime(23, 59, 59)

    def test_datetime_with_space(self):
        """YYYY-MM-DD HH:MM 通过空格分隔。"""
        ts = parse_date_bound("2026-07-24 15:30")
        dt = datetime.fromtimestamp(ts)
        assert dt == datetime(2026, 7, 24, 15, 30)

    def test_datetime_iso_with_t(self):
        """YYYY-MM-DDTHH:MM:SS ISO 格式。"""
        ts = parse_date_bound("2026-07-24T15:30:45")
        dt = datetime.fromtimestamp(ts)
        assert dt == datetime(2026, 7, 24, 15, 30, 45)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="无法解析日期"):
            parse_date_bound("not-a-date")

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError, match="无法解析日期"):
            parse_date_bound("2026-13-01")

    def test_strips_whitespace(self):
        ts = parse_date_bound("  2026-07-24  ")
        assert ts is not None


# ── resolve_chat_target ──────────────────────────────────────────────────────

class TestResolveChatTarget:
    def test_exact_wxid_match(self, tmp_db, setup_contacts):
        """按 wxid 精确匹配。"""
        setup_contacts("wxid_alice", "Alice", display_name="Alice")
        target, candidates = resolve_chat_target(tmp_db, "wxid_alice")
        assert target is not None
        assert target.wxid == "wxid_alice"
        assert target.display_name == "Alice"
        assert candidates == []

    def test_no_match_returns_empty(self, tmp_db):
        target, candidates = resolve_chat_target(tmp_db, "不存在的关键词")
        assert target is None
        assert candidates == []

    def test_fuzzy_single_match(self, tmp_db, setup_contacts):
        """模糊匹配到唯一候选 → target 返回该候选。"""
        setup_contacts("wxid_bob", "Bob叔叔", display_name="Bob叔叔")
        target, candidates = resolve_chat_target(tmp_db, "Bob")
        assert target is not None
        assert target.wxid == "wxid_bob"
        assert len(candidates) == 1

    def test_fuzzy_multiple_no_exact_returns_none_target(self, tmp_db, setup_contacts):
        """模糊匹配多个候选且无精确匹配 → target=None，返回候选列表。

        注意：display_name/remark/nickname 中任一等于 keyword 视为精确匹配，
        所以两个候选的 display_name 都不能等于 keyword。
        """
        setup_contacts("wxid_a1", "AliceA", display_name="AliceA")
        setup_contacts("wxid_a2", "AliceB", display_name="AliceB")
        target, candidates = resolve_chat_target(tmp_db, "Alice")
        assert target is None
        assert len(candidates) == 2

    def test_fuzzy_multiple_with_single_exact_match(self, tmp_db, setup_contacts):
        """多个模糊候选中只有一个精确匹配 display_name → 返回该精确匹配。"""
        setup_contacts("wxid_alice", "Alice", display_name="Alice")
        setup_contacts("wxid_alice2", "Alice姐姐", display_name="Alice姐姐")
        target, candidates = resolve_chat_target(tmp_db, "Alice")
        # 只有一个精确匹配，应该返回
        assert target is not None
        assert target.wxid == "wxid_alice"
        assert len(candidates) == 2


# ── query_chat_messages ──────────────────────────────────────────────────────

class TestQueryChatMessages:
    def test_empty_conversation(self, tmp_db):
        """无消息时返回空列表。"""
        result = query_chat_messages(tmp_db, "wxid_noone")
        assert result == []

    def test_basic_query(self, tmp_db, insert_messages):
        """基础查询返回 ChatMessage 列表。"""
        insert_messages("conv1", "wxid_me", "你好", 1700000000)
        insert_messages("conv1", "wxid_alice", "在吗", 1700000060)
        result = query_chat_messages(tmp_db, "conv1")
        assert len(result) == 2
        assert all(isinstance(m, ChatMessage) for m in result)
        # 默认按时间正序
        assert result[0].content == "你好"
        assert result[1].content == "在吗"

    def test_text_only_filter_excludes_non_text(self, tmp_db, insert_messages):
        """text_only=True 默认只返回 type=1 文本消息。"""
        insert_messages("conv1", "wxid_me", "文本", 1700000000, msg_type=1)
        insert_messages("conv1", "wxid_me", "[图片]", 1700000060, msg_type=3)
        result = query_chat_messages(tmp_db, "conv1", text_only=True)
        assert len(result) == 1
        assert result[0].type == 1

    def test_text_only_false_includes_all(self, tmp_db, insert_messages):
        """text_only=False 返回所有类型（系统消息除外）。"""
        insert_messages("conv1", "wxid_me", "文本", 1700000000, msg_type=1)
        insert_messages("conv1", "wxid_me", "[图片]", 1700000060, msg_type=3)
        result = query_chat_messages(tmp_db, "conv1", text_only=False)
        assert len(result) == 2

    def test_include_system(self, tmp_db, insert_messages):
        """include_system=True 包含 type=10000 系统消息。"""
        insert_messages("conv1", "wxid_me", "文本", 1700000000, msg_type=1)
        insert_messages("conv1", "", "撤回了一条消息", 1700000060, msg_type=10000)
        # 默认不包含系统
        r1 = query_chat_messages(tmp_db, "conv1", text_only=False)
        assert all(m.type != 10000 for m in r1)
        # 包含系统（text_only=True + include_system=True 应同时返回 type=1 和 10000）
        r2 = query_chat_messages(tmp_db, "conv1", text_only=True, include_system=True)
        types = {m.type for m in r2}
        assert 1 in types
        assert 10000 in types

    def test_time_range_filter(self, tmp_db, insert_messages):
        """按 start_ts/end_ts 过滤。"""
        insert_messages("conv1", "wxid_me", "旧", 1700000000)
        insert_messages("conv1", "wxid_me", "中", 1700000060)
        insert_messages("conv1", "wxid_me", "新", 1700000120)
        result = query_chat_messages(
            tmp_db, "conv1", start_ts=1700000030, end_ts=1700000090
        )
        assert len(result) == 1
        assert result[0].content == "中"

    def test_limit_without_time_range_returns_latest(self, tmp_db, insert_messages):
        """无时间边界时，limit 取最近 N 条（DESC + 外层 ASC）。"""
        for i in range(10):
            insert_messages("conv1", "wxid_me", f"msg_{i}", 1700000000 + i * 60)
        result = query_chat_messages(tmp_db, "conv1", limit=3)
        # 默认正序返回，应该是最后 3 条按时间升序
        assert len(result) == 3
        assert result[0].content == "msg_7"
        assert result[2].content == "msg_9"

    def test_limit_with_time_range(self, tmp_db, insert_messages):
        """带时间边界时，limit 从开头取。"""
        for i in range(10):
            insert_messages("conv1", "wxid_me", f"msg_{i}", 1700000000 + i * 60)
        result = query_chat_messages(
            tmp_db, "conv1", start_ts=1700000000, limit=3
        )
        assert len(result) == 3
        assert result[0].content == "msg_0"
        assert result[2].content == "msg_2"

    def test_limit_none_returns_all(self, tmp_db, insert_messages):
        """limit=None 不限制条数。"""
        for i in range(5):
            insert_messages("conv1", "wxid_me", f"msg_{i}", 1700000000 + i)
        result = query_chat_messages(tmp_db, "conv1", limit=None)
        assert len(result) == 5

    def test_limit_zero_returns_all(self, tmp_db, insert_messages):
        """limit=0 时不加 LIMIT 子句（代码条件 `limit > 0`），返回全部。

        这是一个已知行为（可能不是用户期望，但当前代码如此），测试固化。
        """
        insert_messages("conv1", "wxid_me", "hi", 1700000000)
        result = query_chat_messages(tmp_db, "conv1", limit=0)
        assert len(result) == 1

    def test_reverse_order(self, tmp_db, insert_messages):
        """reverse=True 按时间倒序。"""
        for i in range(3):
            insert_messages("conv1", "wxid_me", f"msg_{i}", 1700000000 + i * 60)
        result = query_chat_messages(tmp_db, "conv1", reverse=True)
        assert result[0].content == "msg_2"
        assert result[2].content == "msg_0"

    def test_chat_message_local_time(self, tmp_db, insert_messages):
        """ChatMessage.local_time 返回 datetime。"""
        insert_messages("conv1", "wxid_me", "hi", 1700000000)
        result = query_chat_messages(tmp_db, "conv1")
        assert isinstance(result[0].local_time, datetime)
        assert result[0].local_time == datetime.fromtimestamp(1700000000)


# ── format_chat_messages ─────────────────────────────────────────────────────

class TestFormatChatMessages:
    @pytest.fixture
    def sample_messages(self, tmp_db, insert_messages):
        """构造 3 条消息（跨两天）。"""
        # 2023-11-14 22:00:00 UTC ≈ 2023-11-15 06:00 CST
        insert_messages("conv1", "wxid_me", "你好", 1700000000)
        insert_messages("conv1", "wxid_alice", "在吗", 1700000060)
        insert_messages("conv1", "wxid_me", "晚安", 1700086400)  # +24h
        return query_chat_messages(tmp_db, "conv1", limit=None)

    @pytest.fixture
    def sample_target(self):
        return ChatTarget(
            wxid="wxid_alice",
            display_name="Alice",
            remark="",
            nickname="Alice",
        )

    def test_text_format(self, sample_messages, sample_target):
        out = format_chat_messages(
            sample_target, sample_messages, my_wxid="wxid_me", fmt="text"
        )
        assert "=== 联系人: Alice ===" in out
        assert "=== wxid: wxid_alice ===" in out
        assert "=== 消息数:" in out
        assert "[06:13]" in out  # 1700000000 在 CST 是 06:13:20
        assert "我: 你好" in out
        assert "Alice: 在吗" in out

    def test_md_format(self, sample_messages, sample_target):
        out = format_chat_messages(
            sample_target, sample_messages, my_wxid="wxid_me", fmt="md"
        )
        assert "# Alice 聊天记录" in out
        assert "- wxid: `wxid_alice`" in out
        assert "- 消息数:" in out
        assert "## " in out  # 日期标题
        assert "- **" in out  # 时间加粗

    def test_json_format(self, sample_messages, sample_target):
        out = format_chat_messages(
            sample_target, sample_messages, my_wxid="wxid_me", fmt="json"
        )
        data = json.loads(out)
        assert data["target"]["wxid"] == "wxid_alice"
        assert data["target"]["display_name"] == "Alice"
        assert data["summary"]["count"] == 3
        assert data["summary"]["my_count"] == 2
        assert data["summary"]["target_count"] == 1
        assert len(data["messages"]) == 3
        assert "time" in data["messages"][0]
        assert "sender" in data["messages"][0]
        assert "content" in data["messages"][0]

    def test_unsupported_format_raises(self, sample_messages, sample_target):
        with pytest.raises(ValueError, match="不支持的格式"):
            format_chat_messages(
                sample_target, sample_messages, my_wxid="wxid_me", fmt="xml"
            )

    def test_empty_messages_text(self, sample_target):
        """空消息列表也应能格式化（summary 应处理 0 条）。"""
        out = format_chat_messages(
            sample_target, [], my_wxid="wxid_me", fmt="text"
        )
        assert "=== 联系人: Alice ===" in out
        assert "消息数: 0" in out
        assert "时间范围: N/A" in out

    def test_json_format_empty_messages(self, sample_target):
        out = format_chat_messages(
            sample_target, [], my_wxid="wxid_me", fmt="json"
        )
        data = json.loads(out)
        assert data["summary"]["count"] == 0
        assert data["summary"]["first_time"] == ""
        assert data["messages"] == []

    def test_md_reverse(self, sample_messages, sample_target):
        """reverse=True 时日期分组倒序。"""
        out = format_chat_messages(
            sample_target, sample_messages, my_wxid="wxid_me", fmt="md", reverse=True
        )
        days = [line for line in out.split("\n") if line.startswith("## ")]
        assert len(days) == 2
        # reverse=True 时较新日期在前
        assert days[0] > days[1]

    def test_text_format_multiline_content(self, sample_target):
        """多行文本在 text 格式下用 / 替换换行。"""
        msg = ChatMessage(
            id="1",
            conversation_id="c1",
            sender_id="wxid_me",
            sender_name="me",
            timestamp=1700000000,
            type=1,
            content="line1\nline2",
            raw_content="",
        )
        out = format_chat_messages(sample_target, [msg], my_wxid="wxid_me", fmt="text")
        assert "line1 / line2" in out


# ── _speaker ─────────────────────────────────────────────────────────────────

class TestSpeaker:
    @pytest.fixture
    def target(self):
        return ChatTarget(wxid="wxid_a", display_name="Alice")

    def test_empty_sender_returns_system(self, target):
        msg = ChatMessage(
            id="1", conversation_id="c", sender_id="", sender_name="",
            timestamp=0, type=1, content="x", raw_content="",
        )
        assert _speaker(msg, target, "wxid_me") == "系统"

    def test_type_10000_returns_system(self, target):
        msg = ChatMessage(
            id="1", conversation_id="c", sender_id="wxid_x", sender_name="x",
            timestamp=0, type=10000, content="系统通知", raw_content="",
        )
        assert _speaker(msg, target, "wxid_me") == "系统"

    def test_sender_is_me(self, target):
        msg = ChatMessage(
            id="1", conversation_id="c", sender_id="wxid_me", sender_name="me",
            timestamp=0, type=1, content="hi", raw_content="",
        )
        assert _speaker(msg, target, "wxid_me") == "我"

    def test_sender_is_target_uses_sender_name(self, target):
        msg = ChatMessage(
            id="1", conversation_id="c", sender_id="wxid_a", sender_name="Alice昵称",
            timestamp=0, type=1, content="hi", raw_content="",
        )
        assert _speaker(msg, target, "wxid_me") == "Alice昵称"

    def test_sender_other_falls_back_to_target_display_name(self, target):
        msg = ChatMessage(
            id="1", conversation_id="c", sender_id="wxid_other", sender_name="",
            timestamp=0, type=1, content="hi", raw_content="",
        )
        # sender_name 为空 → 回落到 target.display_name
        assert _speaker(msg, target, "wxid_me") == "Alice"


# ── _display_content / _is_xml_message / _fold_xml_message ───────────────────

class TestDisplayContent:
    def _make(self, content: str, mtype: int = 1, mid: str = "1"):
        return ChatMessage(
            id=mid, conversation_id="c", sender_id="s", sender_name="n",
            timestamp=0, type=mtype, content=content, raw_content="",
        )

    def test_plain_text(self):
        m = self._make("hello world")
        assert _display_content(m) == "hello world"

    def test_strips_whitespace(self):
        m = self._make("  hi  ")
        assert _display_content(m) == "hi"

    def test_normalizes_crlf(self):
        m = self._make("a\r\nb\rc")
        assert _display_content(m) == "a\nb\nc"

    def test_empty_content_type_3_fallback(self):
        m = self._make("", mtype=3, mid="m1")
        assert _display_content(m) == "[图片:m1]"

    def test_empty_content_type_34_fallback(self):
        m = self._make("", mtype=34, mid="m2")
        assert _display_content(m) == "[语音:m2]"

    def test_empty_content_type_43_fallback(self):
        m = self._make("", mtype=43, mid="m3")
        assert _display_content(m) == "[视频:m3]"

    def test_empty_content_type_10000_fallback(self):
        m = self._make("", mtype=10000)
        assert _display_content(m) == "[系统消息]"

    def test_empty_content_unknown_type_fallback(self):
        m = self._make("", mtype=99, mid="m9")
        assert _display_content(m) == "[非文本消息:99:m9]"

    def test_xml_message_with_title_and_appname(self):
        xml = '<msg><appname><![CDATA[知乎]]></appname><title>文章标题</title></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[小程序: 知乎 - 文章标题]"

    def test_xml_message_with_title_only(self):
        xml = '<msg><title>仅标题</title></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[小程序: 仅标题]"

    def test_xml_message_with_appname_only(self):
        xml = '<msg><appname>豆瓣</appname></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[小程序: 豆瓣]"

    def test_xml_message_no_title_no_appname(self):
        xml = '<msg><other>xxx</other></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[XML消息]"

    def test_xml_message_with_cdata_title(self):
        xml = '<msg><title><![CDATA[带CDATA的标题]]></title></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[小程序: 带CDATA的标题]"

    def test_xml_message_with_html_entities(self):
        xml = '<msg><title>a &amp; b</title></msg>'
        m = self._make(xml)
        assert _display_content(m) == "[小程序: a & b]"


class TestIsXmlMessage:
    def test_plain_text_not_xml(self):
        assert not _is_xml_message("hello")

    def test_xml_prefix(self):
        assert _is_xml_message("<?xml version='1.0'?><msg></msg>")

    def test_msg_prefix(self):
        assert _is_xml_message("<msg></msg>")

    def test_appmsg_prefix(self):
        assert _is_xml_message("<appmsg></appmsg>")

    def test_leading_whitespace(self):
        assert _is_xml_message("   <msg></msg>")

    def test_empty_string(self):
        assert not _is_xml_message("")


class TestFoldXmlMessage:
    def test_title_cdata_and_plain_alternatives(self):
        # 同时有 CDATA 和 plain 形式（正则的 | 分支）
        xml = '<msg><title><![CDATA[CDATA版本]]></title></msg>'
        assert "CDATA版本" in _fold_xml_message(xml)

    def test_appname_cdata_and_plain_alternatives(self):
        xml = '<msg><appname><![CDATA[CDATA应用]]></appname></msg>'
        assert "CDATA应用" in _fold_xml_message(xml)

    def test_both_present(self):
        xml = '<msg><title>标题</title><appname>应用</appname></msg>'
        result = _fold_xml_message(xml)
        assert "应用" in result
        assert "标题" in result


# ── _summarize_messages / _format_summary_text / _format_summary_md ──────────

class TestSummarizeMessages:
    @pytest.fixture
    def target(self):
        return ChatTarget(wxid="wxid_a", display_name="Alice")

    def test_empty_messages(self, target):
        s = _summarize_messages([], target, "wxid_me")
        assert s["count"] == 0
        assert s["my_count"] == 0
        assert s["target_count"] == 0
        assert s["system_count"] == 0
        assert s["first_time"] == ""
        assert s["last_time"] == ""
        assert s["date_range"] == "N/A"

    def test_counts(self, target):
        msgs = [
            ChatMessage("1", "c", "wxid_me", "me", 1700000000, 1, "hi", ""),
            ChatMessage("2", "c", "wxid_me", "me", 1700000060, 1, "hi2", ""),
            ChatMessage("3", "c", "wxid_a", "Alice", 1700000120, 1, "hello", ""),
            ChatMessage("4", "c", "", "", 1700000180, 10000, "系统", ""),
        ]
        s = _summarize_messages(msgs, target, "wxid_me")
        assert s["count"] == 4
        assert s["my_count"] == 2
        assert s["target_count"] == 1
        assert s["system_count"] == 1
        assert s["display_name"] == "Alice"
        assert s["wxid"] == "wxid_a"

    def test_time_range(self, target):
        msgs = [
            ChatMessage("1", "c", "wxid_me", "me", 1700000000, 1, "hi", ""),
            ChatMessage("2", "c", "wxid_a", "Alice", 1700086400, 1, "hi", ""),
        ]
        s = _summarize_messages(msgs, target, "wxid_me")
        assert s["first_time"] != ""
        assert s["last_time"] != ""
        assert s["first_time"] != s["last_time"]


class TestFormatSummaryText:
    def test_basic(self):
        summary = {
            "display_name": "Alice",
            "wxid": "wxid_a",
            "count": 5,
            "target_count": 2,
            "my_count": 3,
            "system_count": 0,
            "date_range": "2026-07-01 ~ 2026-07-24",
        }
        lines = _format_summary_text(summary)
        assert lines[0] == "=== 联系人: Alice ==="
        assert lines[1] == "=== wxid: wxid_a ==="
        assert "消息数: 5" in lines[2]
        assert "对方 2" in lines[2]
        assert "我 3" in lines[2]
        # system_count=0 不应出现"系统"
        assert "系统" not in lines[2]
        assert lines[3] == "=== 时间范围: 2026-07-01 ~ 2026-07-24 ==="

    def test_with_system_count(self):
        summary = {
            "display_name": "Alice", "wxid": "wxid_a",
            "count": 5, "target_count": 2, "my_count": 2, "system_count": 1,
            "date_range": "N/A",
        }
        lines = _format_summary_text(summary)
        assert "系统 1" in lines[2]


class TestFormatSummaryMd:
    def test_basic(self):
        summary = {
            "display_name": "Alice", "wxid": "wxid_a",
            "count": 5, "target_count": 2, "my_count": 3, "system_count": 0,
            "date_range": "2026-07-01 ~ 2026-07-24",
        }
        lines = _format_summary_md(summary)
        assert lines[0] == "# Alice 聊天记录"
        assert lines[1] == ""
        assert "- wxid: `wxid_a`" in lines
        assert any("消息数: 5" in l for l in lines)


# ── _group_by_day ────────────────────────────────────────────────────────────

class TestGroupByDay:
    def test_single_day(self):
        msgs = [
            ChatMessage("1", "c", "s", "n", 1700000000, 1, "a", ""),
            ChatMessage("2", "c", "s", "n", 1700000060, 1, "b", ""),
        ]
        groups = _group_by_day(msgs, reverse=False)
        assert len(groups) == 1

    def test_multiple_days_sorted_ascending(self):
        msgs = [
            ChatMessage("1", "c", "s", "n", 1700000000, 1, "a", ""),
            ChatMessage("2", "c", "s", "n", 1700086400, 1, "b", ""),  # +24h
        ]
        groups = _group_by_day(msgs, reverse=False)
        assert len(groups) == 2
        # 升序：旧日期在前
        assert groups[0][0] < groups[1][0]

    def test_multiple_days_sorted_descending(self):
        msgs = [
            ChatMessage("1", "c", "s", "n", 1700000000, 1, "a", ""),
            ChatMessage("2", "c", "s", "n", 1700086400, 1, "b", ""),
        ]
        groups = _group_by_day(msgs, reverse=True)
        assert len(groups) == 2
        # 倒序：新日期在前
        assert groups[0][0] > groups[1][0]

    def test_empty_messages(self):
        groups = _group_by_day([], reverse=False)
        assert groups == []


# ── write_chat_output ────────────────────────────────────────────────────────

class TestWriteChatOutput:
    def test_writes_to_file(self, tmp_path):
        out_file = tmp_path / "sub" / "output.txt"
        write_chat_output(str(out_file), "hello")
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == "hello"

    def test_accepts_path_object(self, tmp_path):
        out_file = tmp_path / "output.txt"
        write_chat_output(out_file, "hello")
        assert out_file.read_text(encoding="utf-8") == "hello"

    def test_creates_parent_dirs(self, tmp_path):
        out_file = tmp_path / "a" / "b" / "c" / "output.txt"
        write_chat_output(str(out_file), "hello")
        assert out_file.exists()

    def test_overwrites_existing(self, tmp_path):
        out_file = tmp_path / "output.txt"
        out_file.write_text("old", encoding="utf-8")
        write_chat_output(str(out_file), "new")
        assert out_file.read_text(encoding="utf-8") == "new"

    def test_unicode_content(self, tmp_path):
        out_file = tmp_path / "output.txt"
        write_chat_output(str(out_file), "你好世界 🌍")
        assert out_file.read_text(encoding="utf-8") == "你好世界 🌍"
