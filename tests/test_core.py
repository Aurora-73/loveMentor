"""engine/agent/core.py 单元测试。

覆盖：
- _validate_path（路径越界/不允许目录/文件不存在/合法路径）
- _build_cross_refs（交叉引用生成）
- _normalize_section_name（段名归一化）
- _extract_sections（Markdown 分段）
- _find_fact_archive（事实档案查找）
- Session（上下文管理器复用连接）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.agent.core import (
    _validate_path,
    _build_cross_refs,
    _normalize_section_name,
    _extract_sections,
    _find_fact_archive,
    Session,
    _get_conn,
    _local,
)
from engine.config import ROOT_DIR, FACTS_PEOPLE_DIR, FACTS_SELF_DIR
from engine.identity import IdentityPerson, IdentityAccount


# ═══════════════════════════════════════════════════════════════════
# _validate_path
# ═══════════════════════════════════════════════════════════════════

class TestValidatePath:
    """_validate_path 的 4 类行为：合法路径 / 路径越界 / 不允许目录 / 文件不存在。"""

    def test_path_outside_root_raises(self, tmp_path, monkeypatch):
        """路径解析后在 ROOT_DIR 之外 → ValueError。"""
        # tmp_path 在 ROOT_DIR 之外（系统 temp 目录）
        # 但 _validate_path 会先检查 startswith(ROOT_DIR)，所以应抛 ValueError
        # 即使前缀在 _ALLOWED_PREFIXES 中
        fake_file = tmp_path / "test.md"
        fake_file.write_text("hello", encoding="utf-8")
        # 使用 docs/wiki/ 前缀但实际指向 tmp_path
        # 由于 Path(path) 不解析 .. 上跳，我们需要构造一个能让 resolved 不在 ROOT_DIR 的路径
        # 但 _validate_path 先 Path(path) 再 ROOT_DIR / p，所以 p 必须是相对路径
        # 用绝对路径测试更直接
        with pytest.raises(ValueError, match="路径越界|不允许读取"):
            _validate_path(str(fake_file))

    def test_disallowed_directory_raises(self, tmp_path, monkeypatch):
        """路径在 ROOT_DIR 内但不在 _ALLOWED_PREFIXES 中 → ValueError。"""
        # 在 ROOT_DIR 下创建一个不在允许列表中的目录文件
        rel = Path("data/raw/test_disallowed.md")
        abs_path = ROOT_DIR / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            abs_path.write_text("test", encoding="utf-8")
            with pytest.raises(ValueError, match="不允许读取该目录"):
                _validate_path(str(rel))
        finally:
            if abs_path.exists():
                abs_path.unlink()

    def test_nonexistent_file_raises(self):
        """文件不存在 → ValueError。"""
        # 使用允许的前缀但文件不存在
        with pytest.raises(ValueError, match="文件不存在"):
            _validate_path("docs/wiki/nonexistent_file_for_test.md")

    def test_allowed_path_returns_resolved(self, tmp_path, monkeypatch):
        """合法路径（在 _ALLOWED_PREFIXES 内 + 文件存在）→ 返回 resolved Path。"""
        rel = Path("docs/wiki/test_validate_path_ok.md")
        abs_path = ROOT_DIR / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            abs_path.write_text("ok", encoding="utf-8")
            result = _validate_path(str(rel))
            assert result == abs_path.resolve()
            assert result.is_file()
        finally:
            if abs_path.exists():
                abs_path.unlink()


# ═══════════════════════════════════════════════════════════════════
# _build_cross_refs
# ═══════════════════════════════════════════════════════════════════

class TestBuildCrossRefs:
    """_build_cross_refs 生成 Markdown 格式的交叉引用。"""

    def test_empty_returns_header_only(self):
        """无任何参数 → 只有 --- + 标题。"""
        result = _build_cross_refs()
        assert result.startswith("---\n")
        assert "**Cross-references:**" in result
        # 无 person + 无 hits → 只有 2 行
        lines = result.split("\n")
        assert lines[0] == "---"
        assert lines[1] == "**Cross-references:**"
        assert len(lines) == 2

    def test_person_with_chat_flag(self):
        """person + has_chat → 生成 chat 引用行。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person, has_chat=True)
        assert "- chat: `Alice`" in result
        assert 'agent chat "Alice" --recent 200' in result

    def test_person_with_fact_flag(self):
        """person + has_fact → 生成 fact 引用行（含 slug + pid）。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person, has_fact=True)
        # slug_display_name("Alice") = "Alice"
        assert "- fact: `data/facts/people/Alice__p1.md`" in result
        assert 'agent evidence "Alice"' in result

    def test_person_with_event_flag(self):
        """person + has_event → 生成 event 引用行（含 pid）。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person, has_event=True)
        assert "- event: `p1`" in result
        assert 'agent evidence "Alice" --section timeline' in result

    def test_person_with_analysis_flag(self):
        """person + has_analysis → 生成 analysis 引用行。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person, has_analysis=True)
        assert "- analysis: `data/outputs/analysis/Alice__p1/latest.yaml`" in result

    def test_person_all_flags_combined(self):
        """person + 全部 4 个 flag → 4 行引用。"""
        person = IdentityPerson(id="p1", display_name="Bob")
        result = _build_cross_refs(person, has_chat=True, has_fact=True,
                                   has_event=True, has_analysis=True)
        assert result.count("\n- ") == 4  # 4 个引用行
        assert "- chat: `Bob`" in result
        assert "- fact: `data/facts/people/Bob__p1.md`" in result
        assert "- event: `p1`" in result
        assert "- analysis: `data/outputs/analysis/Bob__p1/latest.yaml`" in result

    def test_skill_hits_appended(self):
        """skill_hits 列表 → 每个 hit 生成一行。"""
        result = _build_cross_refs(skill_hits=["s1", "s2"])
        assert "- skill: `s1` → `agent material show \"s1\"`" in result
        assert "- skill: `s2` → `agent material show \"s2\"`" in result

    def test_wiki_hits_appended(self):
        """wiki_hits 列表 → 每个 hit 生成一行（无 → 前缀，只有 wiki:）。"""
        result = _build_cross_refs(wiki_hits=["w1", "w2"])
        assert "- wiki: `w1`" in result
        assert "- wiki: `w2`" in result

    def test_skill_and_wiki_hits_combined(self):
        """skill + wiki 同时存在 → 都被附加。"""
        result = _build_cross_refs(skill_hits=["s1"], wiki_hits=["w1"])
        assert "- skill: `s1`" in result
        assert "- wiki: `w1`" in result

    def test_person_and_hits_combined(self):
        """person + skill + wiki 同时存在 → 全部生成。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person, has_chat=True,
                                   skill_hits=["tip1"], wiki_hits=["wiki1"])
        assert "- chat: `Alice`" in result
        assert "- skill: `tip1`" in result
        assert "- wiki: `wiki1`" in result

    def test_display_name_with_special_chars_slugged(self):
        """display_name 含 Windows 非法字符 → 被 slug_display_name 替换为 _。"""
        person = IdentityPerson(id="p1", display_name='A/B:C')
        result = _build_cross_refs(person, has_fact=True)
        # slug: A/B:C → A_B_C
        assert "data/facts/people/A_B_C__p1.md" in result

    def test_empty_hits_lists(self):
        """空 skill_hits 和 wiki_hits → 不生成对应行（等同于 None）。"""
        result = _build_cross_refs(skill_hits=[], wiki_hits=[])
        lines = result.split("\n")
        # 只有 header 2 行
        assert len(lines) == 2

    def test_none_person_with_hits(self):
        """person=None + hits → 只生成 hits 行。"""
        result = _build_cross_refs(skill_hits=["s1"])
        assert "- skill: `s1`" in result
        # 不应有 chat/fact/event/analysis 行
        assert "- chat:" not in result
        assert "- fact:" not in result

    def test_no_flags_for_person(self):
        """person 存在但所有 flag 为 False → 不生成任何 person 引用。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _build_cross_refs(person)
        assert "- chat:" not in result
        assert "- fact:" not in result
        assert "- event:" not in result
        assert "- analysis:" not in result


# ═══════════════════════════════════════════════════════════════════
# _normalize_section_name
# ═══════════════════════════════════════════════════════════════════

class TestNormalizeSectionName:
    """_normalize_section_name 去掉前导编号和尾部括号注释。"""

    def test_plain_name_unchanged(self):
        """无编号无括号 → 原样返回。"""
        assert _normalize_section_name("场景理解") == "场景理解"

    def test_chinese_number_prefix_with_comma(self):
        """中文数字 + 顿号 → 去除前缀。"""
        assert _normalize_section_name("一、场景理解") == "场景理解"
        assert _normalize_section_name("二、对话分析") == "对话分析"
        assert _normalize_section_name("十、总结") == "总结"
        assert _normalize_section_name("十一、附录") == "附录"

    def test_arabic_number_with_dot(self):
        """阿拉伯数字 + 点 → 去除前缀。"""
        assert _normalize_section_name("1. 场景理解") == "场景理解"
        assert _normalize_section_name("2. 对话分析") == "对话分析"
        assert _normalize_section_name("10. 总结") == "总结"

    def test_arabic_number_with_paren(self):
        """阿拉伯数字 + 右括号 → 去除前缀。"""
        assert _normalize_section_name("1) 场景理解") == "场景理解"

    def test_arabic_number_with_chinese_comma(self):
        """阿拉伯数字 + 中文顿号 → 去除前缀。"""
        assert _normalize_section_name("1、场景理解") == "场景理解"

    def test_trailing_paren_annotation(self):
        """尾部括号注释 → 去除。"""
        assert _normalize_section_name("场景理解（至少3句）") == "场景理解"
        assert _normalize_section_name("对话分析(关键)") == "对话分析"

    def test_combined_prefix_and_suffix(self):
        """前缀编号 + 尾部括号 → 都去除。"""
        assert _normalize_section_name("一、场景理解（至少3句）") == "场景理解"
        assert _normalize_section_name("1. 对话分析(关键)") == "对话分析"

    def test_whitespace_stripped(self):
        """尾部空白 → strip 去除；前导空白 → 阻止 ^ 锚定正则去前缀（代码固有行为）。"""
        # 纯尾部空白：strip 生效
        assert _normalize_section_name("场景理解  ") == "场景理解"
        # 无前缀编号：前导空白被 strip 去除
        assert _normalize_section_name("  场景理解") == "场景理解"
        # 前缀编号 + 前导空白：^ 锚定正则失配，前缀保留（固有行为，调用方需先 strip）
        # 固化代码实际行为：re.sub 的 ^ 锚定原始字符串开头，前导空白使前缀不被去除
        assert _normalize_section_name("  一、场景理解  ") == "一、场景理解"

    def test_empty_string(self):
        """空字符串 → 空字符串。"""
        assert _normalize_section_name("") == ""

    def test_only_number_prefix(self):
        """只有编号无内容 → 空字符串。"""
        assert _normalize_section_name("1.") == ""
        assert _normalize_section_name("一、") == ""


# ═══════════════════════════════════════════════════════════════════
# _extract_sections
# ═══════════════════════════════════════════════════════════════════

class TestExtractSections:
    """_extract_sections 按 ## 标题分割 Markdown。"""

    def test_empty_text(self):
        """空文本 → 只有 _header section（空内容）。"""
        result = _extract_sections("")
        assert "_header" in result
        assert result["_header"] == ""

    def test_no_sections(self):
        """无 ## 标题 → 全部内容归入 _header。"""
        text = "这是一段文本\n没有标题"
        result = _extract_sections(text)
        assert list(result.keys()) == ["_header"]
        assert result["_header"] == "这是一段文本\n没有标题"

    def test_single_section(self):
        """单个 ## 标题 → 2 个 section（_header + 标题段）。"""
        text = "顶部内容\n## 场景理解\n这是场景理解的内容"
        result = _extract_sections(text)
        assert "_header" in result
        assert "场景理解" in result
        assert result["_header"] == "顶部内容"
        assert result["场景理解"] == "这是场景理解的内容"

    def test_multiple_sections(self):
        """多个 ## 标题 → 每个标题一个 section。"""
        text = "顶部\n## A\n内容A\n## B\n内容B\n## C\n内容C"
        result = _extract_sections(text)
        assert result["_header"] == "顶部"
        assert result["A"] == "内容A"
        assert result["B"] == "内容B"
        assert result["C"] == "内容C"

    def test_section_name_normalized(self):
        """段名归一化：'一、场景理解（至少3句）' → '场景理解'。"""
        text = "## 一、场景理解（至少3句）\n内容"
        result = _extract_sections(text)
        assert "场景理解" in result
        assert "一、场景理解（至少3句）" not in result
        assert result["场景理解"] == "内容"

    def test_consecutive_headers(self):
        """连续 ## 标题 → 中间 section 内容为空字符串。"""
        text = "## A\n## B\n实际内容"
        result = _extract_sections(text)
        assert result["A"] == ""
        assert result["B"] == "实际内容"

    def test_trailing_content_after_last_header(self):
        """最后一个 ## 标题后的内容 → 归入该 section。"""
        text = "## A\n内容1\n内容2"
        result = _extract_sections(text)
        assert result["A"] == "内容1\n内容2"

    def test_h1_headers_not_split(self):
        """# 一级标题不分割（只识别 ## 二级标题）。"""
        text = "# 一级标题\n## 二级标题\n内容"
        result = _extract_sections(text)
        # # 一级标题不分割，归入 _header
        assert "_header" in result
        assert "# 一级标题" in result["_header"]
        assert "二级标题" in result
        assert result["二级标题"] == "内容"

    def test_h3_headers_not_split(self):
        """### 三级标题不分割（只识别 ## 二级标题）。"""
        text = "## A\n### 子标题\n内容"
        result = _extract_sections(text)
        assert "A" in result
        # ### 子标题归入 A section 的内容
        assert "### 子标题" in result["A"]
        assert "内容" in result["A"]

    def test_content_with_blank_lines(self):
        """段内容含空行 → 保留空行（只 strip 首尾）。"""
        text = "## A\n第一行\n\n第三行"
        result = _extract_sections(text)
        assert result["A"] == "第一行\n\n第三行"

    def test_normalization_makes_keys_consistent(self):
        """归一化使不同格式的段名映射到同一 key。"""
        text1 = "## 一、场景理解（至少3句）\n内容A"
        text2 = "## 场景理解\n内容B"
        r1 = _extract_sections(text1)
        r2 = _extract_sections(text2)
        # 两个不同格式的标题归一化后都是 "场景理解"
        assert "场景理解" in r1
        assert "场景理解" in r2


# ═══════════════════════════════════════════════════════════════════
# _find_fact_archive
# ═══════════════════════════════════════════════════════════════════

class TestFindFactArchive:
    """_find_fact_archive 在 FACTS_PEOPLE_DIR 和 FACTS_SELF_DIR 中查找 .md 文件。"""

    def test_no_archive_returns_none(self, tmp_path, monkeypatch):
        """无匹配文件 → None。"""
        # 用 monkeypatch 把 FACTS_PEOPLE_DIR 和 FACTS_SELF_DIR 指向临时空目录
        empty_dir = tmp_path / "empty_facts"
        empty_dir.mkdir()
        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", empty_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", empty_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        assert _find_fact_archive(person) is None

    def test_finds_archive_in_people_dir(self, tmp_path, monkeypatch):
        """在 FACTS_PEOPLE_DIR 找到匹配 pid 的 .md 文件。"""
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        self_dir = tmp_path / "self"
        self_dir.mkdir()
        # 创建一个 .md 文件，stem 包含 person.id
        archive_file = people_dir / "Alice__p1.md"
        archive_file.write_text("fact content", encoding="utf-8")
        # 创建一个干扰文件
        (people_dir / "Bob__p2.md").write_text("other", encoding="utf-8")

        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _find_fact_archive(person)
        assert result == archive_file

    def test_finds_archive_in_self_dir(self, tmp_path, monkeypatch):
        """在 FACTS_SELF_DIR 找到匹配 pid 的 .md 文件。"""
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        self_dir = tmp_path / "self"
        self_dir.mkdir()
        archive_file = self_dir / "self__p1.md"
        archive_file.write_text("self fact", encoding="utf-8")

        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Self")
        result = _find_fact_archive(person)
        assert result == archive_file

    def test_people_dir_takes_priority_over_self_dir(self, tmp_path, monkeypatch):
        """两个目录都有匹配 → people 优先（因为 FACTS_PEOPLE_DIR 在循环中先迭代）。"""
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        self_dir = tmp_path / "self"
        self_dir.mkdir()
        people_file = people_dir / "Alice__p1.md"
        people_file.write_text("people", encoding="utf-8")
        self_file = self_dir / "Alice__p1.md"
        self_file.write_text("self", encoding="utf-8")

        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _find_fact_archive(person)
        assert result == people_file  # people 优先

    def test_ignores_non_md_files(self, tmp_path, monkeypatch):
        """非 .md 文件被忽略（如 .yaml / .txt）。"""
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        self_dir = tmp_path / "self"
        self_dir.mkdir()
        # 只有 .yaml 文件
        (people_dir / "Alice__p1.yaml").write_text("yaml", encoding="utf-8")
        (people_dir / "Alice__p1.txt").write_text("txt", encoding="utf-8")

        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        assert _find_fact_archive(person) is None

    def test_pid_substring_match(self, tmp_path, monkeypatch):
        """pid 是 stem 的子串即可匹配（不要求完全匹配）。"""
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        self_dir = tmp_path / "self"
        self_dir.mkdir()
        # stem 是 "Alice__p1_v2"，pid 是 "p1"，应该匹配
        archive_file = people_dir / "Alice__p1_v2.md"
        archive_file.write_text("content", encoding="utf-8")

        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        result = _find_fact_archive(person)
        assert result == archive_file

    def test_nonexistent_dir_skipped(self, tmp_path, monkeypatch):
        """目录不存在 → 跳过，不抛异常。"""
        people_dir = tmp_path / "nonexistent_people"
        self_dir = tmp_path / "nonexistent_self"
        # 不创建目录
        monkeypatch.setattr("engine.agent.core.FACTS_PEOPLE_DIR", people_dir)
        monkeypatch.setattr("engine.agent.core.FACTS_SELF_DIR", self_dir)
        person = IdentityPerson(id="p1", display_name="Alice")
        # 不抛异常，返回 None
        assert _find_fact_archive(person) is None


# ═══════════════════════════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════════════════════════

class TestSession:
    """Session 上下文管理器，复用同一个 DB 连接。"""

    def test_session_provides_conn_and_config(self, monkeypatch):
        """Session 进入时返回 (conn, config)，conn 是 sqlite3.Connection。"""
        # mock get_db 和 load_config
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        # 清理可能的残留 session 状态
        if hasattr(_local, "session_conn"):
            del _local.session_conn
            del _local.session_config

        with Session() as (conn, config):
            assert conn is mock_conn
            assert config is mock_config

    def test_session_sets_local_attrs(self, monkeypatch):
        """Session 进入时设置 _local.session_conn 和 _local.session_config。"""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        if hasattr(_local, "session_conn"):
            del _local.session_conn
            del _local.session_config

        with Session() as (conn, config):
            assert _local.session_conn is mock_conn
            assert _local.session_config is mock_config

    def test_session_clears_local_attrs_on_exit(self, monkeypatch):
        """Session 退出时清理 _local.session_conn 和 _local.session_config。"""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        if hasattr(_local, "session_conn"):
            del _local.session_conn
            del _local.session_config

        with Session() as (conn, config):
            pass

        # 退出后 session_conn 应被清理
        assert not hasattr(_local, "session_conn") or _local.session_conn is None

    def test_session_closes_conn_on_exit(self, monkeypatch):
        """Session 退出时调用 conn.close()。"""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        with Session() as (conn, config):
            pass

        mock_conn.close.assert_called_once()

    def test_session_clears_local_even_on_exception(self, monkeypatch):
        """Session 内抛异常时仍然清理 _local。"""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        if hasattr(_local, "session_conn"):
            del _local.session_conn
            del _local.session_config

        with pytest.raises(RuntimeError, match="test error"):
            with Session() as (conn, config):
                raise RuntimeError("test error")

        # 异常后 session_conn 应被清理
        assert not hasattr(_local, "session_conn") or _local.session_conn is None


# ═══════════════════════════════════════════════════════════════════
# _get_conn
# ═══════════════════════════════════════════════════════════════════

class TestGetConn:
    """_get_conn 优先复用 Session 连接，否则新建。"""

    def test_get_conn_uses_session_conn_if_present(self, monkeypatch):
        """有 Session 时复用 _local.session_conn。"""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        _local.session_conn = mock_conn
        _local.session_config = mock_config
        try:
            conn, config = _get_conn()
            assert conn is mock_conn
            assert config is mock_config
        finally:
            # 清理测试残留
            _local.session_conn = None
            _local.session_config = None

    def test_get_conn_creates_new_when_no_session(self, monkeypatch):
        """无 Session 时新建连接。"""
        # 确保 _local 没有 session_conn
        if hasattr(_local, "session_conn"):
            _local.session_conn = None
            _local.session_config = None

        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_config = MagicMock()
        monkeypatch.setattr("engine.importers.db_init.get_db", lambda path: mock_conn)
        monkeypatch.setattr("engine.agent.core.load_config", lambda: mock_config)

        conn, config = _get_conn()
        assert conn is mock_conn
        assert config is mock_config
