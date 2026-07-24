"""engine/agent/material.py 单元测试。

覆盖：
- _search_wiki（Wiki 搜索）
- _search_analysis（分析文件搜索）
- _search_kb（知识库文件搜索）
- agent_material_search（综合搜索）
- agent_material_show（材料展示）
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from engine.agent.material import (
    _search_wiki,
    _search_analysis,
    _search_kb,
    agent_material_search,
    agent_material_show,
)
from engine.config import ROOT_DIR, OUTPUTS_ANALYSIS_DIR


# ═══════════════════════════════════════════════════════════════════
# _search_wiki
# ═══════════════════════════════════════════════════════════════════

class TestSearchWiki:
    """_search_wiki 检索 Wiki 知识库。"""

    def _make_snippet(self, title, path, page_type="entity", summary="摘要",
                      score=10.0, tags=None):
        s = MagicMock()
        s.title = title
        s.path = path
        s.page_type = page_type
        s.summary = summary
        s.score = score
        s.tags = tags or ["标签1", "标签2"]
        return s

    def test_empty_index_returns_nothing(self, monkeypatch):
        """WikiIndex.is_empty → 空。"""
        mock_index = MagicMock()
        mock_index.load.return_value = False
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        results = []
        _search_wiki(["test"], results)
        assert results == []

    def test_index_load_failure_returns_nothing(self, monkeypatch):
        """WikiIndex.load() 返回 False → 空。"""
        mock_index = MagicMock()
        mock_index.load.return_value = False
        mock_index.is_empty = False
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        results = []
        _search_wiki(["test"], results)
        assert results == []

    def test_index_empty_returns_nothing(self, monkeypatch):
        """WikiIndex.is_empty=True → 空。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = True
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        results = []
        _search_wiki(["test"], results)
        assert results == []

    def test_wiki_results_added(self, monkeypatch):
        """正常检索 → wiki 结果加入 results 列表。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippets = [
            self._make_snippet("IOI", "wiki/entities/IOI（兴趣指标）.md",
                               page_type="entity", score=15.0, tags=["IOI", "兴趣"]),
        ]
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        results = []
        _search_wiki(["ioi"], results)
        assert len(results) == 1
        assert results[0]["type"] == "wiki"
        assert results[0]["title"] == "IOI"
        assert results[0]["page_type"] == "entity"
        assert results[0]["score"] == 15.0
        assert results[0]["priority"] == 2

    def test_path_prefix_docs_kept(self, monkeypatch):
        """path 以 docs/ 开头 → 保持原样。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippets = [self._make_snippet("T", "docs/wiki/entities/X.md")]
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        results = []
        _search_wiki(["x"], results)
        assert results[0]["path"] == "docs/wiki/entities/X.md"

    def test_path_prefix_wiki_prepended(self, monkeypatch):
        """path 以 wiki/ 开头（非 docs/）→ 加 docs/ 前缀。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippets = [self._make_snippet("T", "wiki/entities/X.md")]
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        results = []
        _search_wiki(["x"], results)
        assert results[0]["path"] == "docs/wiki/wiki/entities/X.md"

    def test_path_no_prefix_prepended(self, monkeypatch):
        """path 无 docs/ 或 wiki/ 前缀 → 加 docs/wiki/wiki/ 前缀。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippets = [self._make_snippet("T", "entities/X.md")]
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        results = []
        _search_wiki(["x"], results)
        assert results[0]["path"] == "docs/wiki/wiki/entities/X.md"

    def test_tags_joined_to_keywords(self, monkeypatch):
        """tags 前 5 个拼成 keywords 字段。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        snippets = [self._make_snippet("T", "wiki/X.md", tags=["a", "b", "c", "d", "e", "f"])]
        mock_retriever.retrieve.return_value = snippets
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        results = []
        _search_wiki(["x"], results)
        # 前 5 个 tags 拼接
        assert results[0]["keywords"] == "a, b, c, d, e"

    def test_query_terms_joined_by_space(self, monkeypatch):
        """query_terms 用空格拼接传给 retriever。"""
        mock_index = MagicMock()
        mock_index.load.return_value = True
        mock_index.is_empty = False
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        monkeypatch.setattr("engine.knowledge.wiki_index.WikiIndex", lambda: mock_index)
        monkeypatch.setattr("engine.knowledge.wiki_retriever.WikiRetriever", lambda idx: mock_retriever)
        _search_wiki(["ioi", "兴趣"], [])
        # 验证 retrieve 的 query_text 参数
        call_kwargs = mock_retriever.retrieve.call_args.kwargs
        assert call_kwargs["query_text"] == "ioi 兴趣"
        assert call_kwargs["task_type"] == "ask"
        assert call_kwargs["max_chars"] == 5000
        assert call_kwargs["max_pages"] == 10


# ═══════════════════════════════════════════════════════════════════
# _search_analysis
# ═══════════════════════════════════════════════════════════════════

class TestSearchAnalysis:
    """_search_analysis 搜索分析目录中的 latest.yaml。"""

    def test_dir_not_exist_returns_empty(self, monkeypatch):
        """OUTPUTS_ANALYSIS_DIR 不存在 → 空。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR",
                            Path("/nonexistent_analysis_dir"))
        results = []
        _search_analysis(["test"], results)
        assert results == []

    def test_no_latest_yaml_skipped(self, tmp_path, monkeypatch):
        """目录内无 latest.yaml → 跳过。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        # 不创建 latest.yaml
        results = []
        _search_analysis(["alice"], results)
        assert results == []

    def test_match_found(self, tmp_path, monkeypatch):
        """YAML 内容含 query_terms → 加入结果。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text(
            "stage:\n  stage: stage_2\ndiagnosis: alice 有 IOI 信号\n",
            encoding="utf-8",
        )
        results = []
        _search_analysis(["alice"], results)
        assert len(results) == 1
        assert results[0]["type"] == "analysis"
        assert "Alice__p1" in results[0]["title"]
        assert results[0]["priority"] == 3

    def test_no_match_skipped(self, tmp_path, monkeypatch):
        """YAML 内容不含 query_terms → 跳过。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text("stage:\n  stage: stage_2\n", encoding="utf-8")
        results = []
        _search_analysis(["nonexistent_term"], results)
        assert results == []

    def test_invalid_yaml_skipped(self, tmp_path, monkeypatch):
        """YAML 解析失败 → 跳过。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text("not: valid: yaml: : :", encoding="utf-8")
        results = []
        _search_analysis(["alice"], results)
        # 不应崩溃，可能为空
        assert results == []

    def test_non_dict_yaml_skipped(self, tmp_path, monkeypatch):
        """YAML 顶层非 dict → 跳过。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text("- list\n- not dict\n", encoding="utf-8")
        results = []
        _search_analysis(["alice"], results)
        assert results == []

    def test_multiple_matches_score_differs(self, tmp_path, monkeypatch):
        """多个 YAML 匹配，score 不同（按匹配词数计）。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d1 = tmp_path / "Alice__p1"; d1.mkdir()
        (d1 / "latest.yaml").write_text("stage:\n  stage: stage_2\ndiagnosis: alice\n", encoding="utf-8")
        d2 = tmp_path / "Bob__p2"; d2.mkdir()
        (d2 / "latest.yaml").write_text("stage:\n  stage: stage_3\ndiagnosis: alice and bob\n", encoding="utf-8")
        results = []
        _search_analysis(["alice", "bob"], results)
        # 都应匹配
        assert len(results) == 2
        # Bob 匹配 2 词，Alice 匹配 1 词
        scores = {r["title"]: r["score"] for r in results}
        # 找到含 bob 的结果
        bob_result = [r for r in results if "Bob" in r["title"]][0]
        alice_result = [r for r in results if "Alice" in r["title"]][0]
        assert bob_result["score"] == 2
        assert alice_result["score"] == 1

    def test_non_dir_entries_skipped(self, tmp_path, monkeypatch):
        """非目录条目（文件）跳过。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        # 创建一个文件（不是目录）
        (tmp_path / "some_file.txt").write_text("alice", encoding="utf-8")
        results = []
        _search_analysis(["alice"], results)
        assert results == []

    def test_stage_in_title(self, tmp_path, monkeypatch):
        """结果 title 含 stage 信息。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text(
            "stage:\n  stage: stage_3\ndiagnosis: alice\n", encoding="utf-8",
        )
        results = []
        _search_analysis(["alice"], results)
        assert len(results) == 1
        assert "stage_3" in results[0]["title"]

    def test_stage_missing_uses_question_mark(self, tmp_path, monkeypatch):
        """YAML 无 stage → title 含 '?'。"""
        monkeypatch.setattr("engine.agent.material.OUTPUTS_ANALYSIS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        d = tmp_path / "Alice__p1"
        d.mkdir()
        (d / "latest.yaml").write_text("diagnosis: alice\n", encoding="utf-8")
        results = []
        _search_analysis(["alice"], results)
        assert len(results) == 1
        assert "(?)" in results[0]["title"]


# ═══════════════════════════════════════════════════════════════════
# _search_kb
# ═══════════════════════════════════════════════════════════════════

class TestSearchKb:
    """_search_kb 搜索 docs/kb 目录的 .md 文件。"""

    def test_kb_dir_not_exist_returns_empty(self, monkeypatch, tmp_path):
        """docs/kb 不存在 → 空。"""
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        results = []
        _search_kb(["test"], results)
        assert results == []

    def test_filename_match(self, monkeypatch, tmp_path):
        """文件名匹配 query_terms → 加入结果。"""
        kb_dir = tmp_path / "docs" / "kb"
        kb_dir.mkdir(parents=True)
        (kb_dir / "alice_story.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        results = []
        _search_kb(["alice"], results)
        assert len(results) == 1
        assert results[0]["type"] == "kb"
        assert results[0]["title"] == "alice_story"
        assert results[0]["priority"] == 4

    def test_path_match(self, monkeypatch, tmp_path):
        """文件路径含 query_terms → 加入结果。"""
        kb_dir = tmp_path / "docs" / "kb" / "bob_folder"
        kb_dir.mkdir(parents=True)
        (kb_dir / "file.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        results = []
        _search_kb(["bob"], results)
        assert len(results) == 1
        assert "bob_folder" in results[0]["path"]

    def test_no_match_skipped(self, monkeypatch, tmp_path):
        """文件名/路径不含 query_terms → 跳过。"""
        kb_dir = tmp_path / "docs" / "kb"
        kb_dir.mkdir(parents=True)
        (kb_dir / "other.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        results = []
        _search_kb(["alice"], results)
        assert results == []

    def test_max_200_files_limit(self, monkeypatch, tmp_path):
        """最多扫描 200 个 .md 文件（防止过大）。"""
        kb_dir = tmp_path / "docs" / "kb"
        kb_dir.mkdir(parents=True)
        # 创建 205 个文件，都不匹配 → 但只扫描前 200 个
        for i in range(205):
            (kb_dir / f"file_{i}.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        # 创建一个匹配的文件，但排在 200 之后（按 rglob 顺序）
        # 由于 rglob 顺序不确定，这里只验证不崩溃
        results = []
        _search_kb(["alice"], results)
        # 所有不匹配 → 空
        assert results == []

    def test_path_uses_forward_slash(self, monkeypatch, tmp_path):
        """path 用正斜杠（Windows 兼容）。"""
        kb_dir = tmp_path / "docs" / "kb" / "subdir"
        kb_dir.mkdir(parents=True)
        (kb_dir / "alice.md").write_text("content", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material.ROOT_DIR", tmp_path)
        results = []
        _search_kb(["alice"], results)
        assert len(results) == 1
        # 路径用正斜杠
        assert "\\" not in results[0]["path"]
        assert "/" in results[0]["path"]


# ═══════════════════════════════════════════════════════════════════
# agent_material_search
# ═══════════════════════════════════════════════════════════════════

class TestAgentMaterialSearch:
    """agent_material_search 综合搜索主函数。"""

    def test_empty_results(self, monkeypatch):
        """无任何匹配 → 输出 0 条结果。"""
        monkeypatch.setattr("engine.agent.material._search_wiki", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "cross_refs")
        result = agent_material_search(MagicMock(), MagicMock(), "nonexistent")
        assert "Material Search" in result
        assert "结果 (0 条)" in result
        assert "cross_refs" in result

    def test_results_sorted_by_priority_and_score(self, monkeypatch):
        """结果按 priority 升序，score 降序排序。"""
        def fake_wiki(q, r):
            r.append({"type": "wiki", "title": "Wiki1", "path": "p1",
                      "reason": "r", "keywords": "", "score": 10, "priority": 2, "summary": ""})
        def fake_analysis(q, r):
            r.append({"type": "analysis", "title": "Analysis1", "path": "p2",
                      "reason": "r", "keywords": "", "score": 5, "priority": 3})
        def fake_kb(q, r):
            r.append({"type": "kb", "title": "KB1", "path": "p3",
                      "reason": "r", "keywords": "", "score": 1, "priority": 4})
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", fake_analysis)
        monkeypatch.setattr("engine.agent.material._search_kb", fake_kb)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        result = agent_material_search(MagicMock(), MagicMock(), "test")
        # 顺序：wiki (priority 2) → analysis (3) → kb (4)
        assert "Wiki1" in result
        assert "Analysis1" in result
        assert "KB1" in result
        # wiki 应在 analysis 之前
        assert result.index("Wiki1") < result.index("Analysis1")
        assert result.index("Analysis1") < result.index("KB1")

    def test_results_limited_to_20(self, monkeypatch):
        """最多显示前 20 条结果。"""
        def fake_wiki(q, r):
            for i in range(25):
                r.append({
                    "type": "wiki", "title": f"Title{i}", "path": f"p{i}",
                    "reason": "r", "keywords": "", "score": 10 - i, "priority": 2, "summary": "",
                })
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        result = agent_material_search(MagicMock(), MagicMock(), "test")
        # 应只显示前 20 条
        for i in range(20):
            assert f"Title{i}" in result
        assert "Title20" not in result
        assert "Title24" not in result

    def test_wiki_hits_passed_to_cross_refs(self, monkeypatch):
        """wiki 类型结果的前 5 条 path 传给 _build_cross_refs。"""
        def fake_wiki(q, r):
            for i in range(7):
                r.append({
                    "type": "wiki", "title": f"T{i}", "path": f"wiki_path_{i}",
                    "reason": "r", "keywords": "", "score": 10, "priority": 2, "summary": "",
                })
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        captured = {}
        def fake_cross_refs(skill_hits=None, wiki_hits=None):
            captured["wiki_hits"] = wiki_hits
            return ""
        monkeypatch.setattr("engine.agent.material._build_cross_refs", fake_cross_refs)
        agent_material_search(MagicMock(), MagicMock(), "test")
        # 应只传前 5 条 wiki path
        assert len(captured["wiki_hits"]) == 5
        assert captured["wiki_hits"] == [f"wiki_path_{i}" for i in range(5)]

    def test_show_command_in_output(self, monkeypatch):
        """输出含 wiki_show 命令提示。"""
        def fake_wiki(q, r):
            r.append({"type": "wiki", "title": "T", "path": "wiki/test.md",
                      "reason": "r", "keywords": "kw", "score": 10, "priority": 2, "summary": ""})
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        result = agent_material_search(MagicMock(), MagicMock(), "test")
        assert 'wiki_show("wiki/test.md")' in result

    def test_keywords_displayed_when_present(self, monkeypatch):
        """结果含 keywords → 显示 Keywords 行。"""
        def fake_wiki(q, r):
            r.append({"type": "wiki", "title": "T", "path": "p",
                      "reason": "r", "keywords": "标签1, 标签2", "score": 10, "priority": 2, "summary": ""})
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        result = agent_material_search(MagicMock(), MagicMock(), "test")
        assert "- Keywords: 标签1, 标签2" in result

    def test_keywords_omitted_when_empty(self, monkeypatch):
        """结果无 keywords → 不显示 Keywords 行。"""
        def fake_wiki(q, r):
            r.append({"type": "wiki", "title": "T", "path": "p",
                      "reason": "r", "keywords": "", "score": 10, "priority": 2, "summary": ""})
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        result = agent_material_search(MagicMock(), MagicMock(), "test")
        assert "Keywords:" not in result

    def test_query_lowercased(self, monkeypatch):
        """query 转 lower case 用于搜索。"""
        captured = {}
        def fake_wiki(q, r):
            captured["terms"] = q
        monkeypatch.setattr("engine.agent.material._search_wiki", fake_wiki)
        monkeypatch.setattr("engine.agent.material._search_analysis", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._search_kb", lambda q, r: None)
        monkeypatch.setattr("engine.agent.material._build_cross_refs",
                            lambda skill_hits=None, wiki_hits=None: "")
        agent_material_search(MagicMock(), MagicMock(), "HELLO WORLD")
        assert captured["terms"] == ["hello", "world"]


# ═══════════════════════════════════════════════════════════════════
# agent_material_show
# ═══════════════════════════════════════════════════════════════════

class TestAgentMaterialShow:
    """agent_material_show 展示材料内容。"""

    def test_small_file_shown_all(self, tmp_path, monkeypatch):
        """小文件 → 显示全部内容。"""
        file_path = tmp_path / "test.md"
        file_path.write_text("Hello World", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material._validate_path", lambda p: file_path)
        result = agent_material_show("test.md")
        assert "Material: test.md" in result
        assert "Size: 11 chars" in result
        assert "Showing: all 11 chars" in result
        assert "Hello World" in result

    def test_large_file_truncated(self, tmp_path, monkeypatch):
        """大文件 → 截断到 max_chars。"""
        content = "a" * 200
        file_path = tmp_path / "big.md"
        file_path.write_text(content, encoding="utf-8")
        monkeypatch.setattr("engine.agent.material._validate_path", lambda p: file_path)
        result = agent_material_show("big.md", max_chars=100)
        assert "Size: 200 chars" in result
        assert "Showing: first 100 chars (truncated)" in result
        assert "truncated at 100 chars, 100 chars remaining" in result
        # 内容只含前 100 个 a
        assert "a" * 100 in result
        assert "a" * 200 not in result

    def test_exact_max_chars_not_truncated(self, tmp_path, monkeypatch):
        """文件大小 = max_chars → 不截断。"""
        content = "a" * 100
        file_path = tmp_path / "exact.md"
        file_path.write_text(content, encoding="utf-8")
        monkeypatch.setattr("engine.agent.material._validate_path", lambda p: file_path)
        result = agent_material_show("exact.md", max_chars=100)
        assert "Showing: all 100 chars" in result
        assert "truncated" not in result.lower().replace("truncated at", "")  # 不含截断提示

    def test_default_max_chars_50000(self, tmp_path, monkeypatch):
        """默认 max_chars=50000。"""
        content = "small content"
        file_path = tmp_path / "test.md"
        file_path.write_text(content, encoding="utf-8")
        monkeypatch.setattr("engine.agent.material._validate_path", lambda p: file_path)
        result = agent_material_show("test.md")
        assert "Size: 13 chars" in result
        assert "Showing: all 13 chars" in result

    def test_output_structure(self, tmp_path, monkeypatch):
        """输出含 header + size + content 分隔。"""
        file_path = tmp_path / "test.md"
        file_path.write_text("content here", encoding="utf-8")
        monkeypatch.setattr("engine.agent.material._validate_path", lambda p: file_path)
        result = agent_material_show("test.md")
        assert "# Material: test.md" in result
        assert "- Size:" in result
        assert "- Showing:" in result
        assert "---" in result
        assert "content here" in result
