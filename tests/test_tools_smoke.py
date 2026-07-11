"""tools.py 导入冒烟测试。"""
import pytest


class TestImports:
    """所有 tools.py 导出函数可正常导入。"""

    def test_read_tools(self):
        from engine.tools import brief, chat, evidence, metrics, rank, status
        from engine.tools import wiki_search, wiki_show, moments_stats
        assert callable(brief)
        assert callable(chat)
        assert callable(evidence)
        assert callable(metrics)
        assert callable(rank)
        assert callable(status)
        assert callable(wiki_search)
        assert callable(wiki_show)
        assert callable(moments_stats)

    def test_write_tools(self):
        from engine.tools import note, date, evaluate, events
        from engine.tools import save_analysis, save_from_markdown
        assert callable(note)
        assert callable(date)
        assert callable(evaluate)
        assert callable(events)
        assert callable(save_analysis)
        assert callable(save_from_markdown)

    def test_identity_tools(self):
        from engine.tools import contact, exclude, failure, sticker
        assert callable(contact)
        assert callable(exclude)
        assert callable(failure)
        assert callable(sticker)

    def test_sync_tools(self):
        from engine.tools import sync, sync_person, sync_moments, weekly
        assert callable(sync)
        assert callable(sync_person)
        assert callable(sync_moments)
        assert callable(weekly)

    def test_formula_tools(self):
        from engine.tools import (
            formula_params, formula_ivi, formula_spe, formula_ews,
            formula_is, formula_gap_effect, formula_eev, formula_cs, formula_action,
        )
        assert callable(formula_params)
        assert callable(formula_ivi)
        assert callable(formula_spe)
        assert callable(formula_ews)
        assert callable(formula_is)
        assert callable(formula_gap_effect)
        assert callable(formula_eev)
        assert callable(formula_cs)
        assert callable(formula_action)

    def test_module_consistency(self):
        """brief/chat/moments_stats 等从 tools 导入的函数，底层模块也导出相同对象。"""
        from engine.tools import brief as tools_brief
        from engine.agent.brief import agent_brief as mod_brief
        # tools.py 里的 brief 是包装函数，不是同一个对象，但都可调用
        assert callable(tools_brief)
        assert callable(mod_brief)

        from engine.tools import moments_stats as tools_moments
        from engine.agent.moments import moments_stats as mod_moments
        assert tools_moments is mod_moments

    def test_formula_params_signature(self):
        import inspect
        from engine.tools import formula_params
        sig = inspect.signature(formula_params)
        params = list(sig.parameters.keys())
        assert "name" in params
        assert "conn" in params
