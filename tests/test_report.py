"""engine/agent/report.py 单元测试。

覆盖：
- agent_metrics（指标报告，返回 dict）
- agent_status（状态报告，返回 Markdown）
- agent_rank（排名表）
- agent_weekly（周报生成 + 保存文件）
- agent_compare_analysis（latest.yaml vs previous.yaml 对比）
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from engine.agent.report import (
    agent_metrics,
    agent_status,
    agent_rank,
    agent_weekly,
    agent_compare_analysis,
)
from engine.config import (
    OUTPUTS_REPORTS_DIR,
    OUTPUTS_RANKINGS_DIR,
    OUTPUTS_ANALYSIS_DIR,
    slug_display_name,
)
from engine.identity import IdentityPerson, IdentityAccount
from engine.models.metrics import Metrics, MetricValue


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _make_metrics(
    base_score: float = 0.5,
    composite: float = 0.55,
    signal_level: str = "中窗口",
    neediness_penalty: float = 1.0,
    interaction_pattern: str = "",
    session_recency: dict | None = None,
    momentum: dict | None = None,
    initiation_source: dict | None = None,
    media_engagement: dict | None = None,
    composite_slope_sample: int = 0,
) -> Metrics:
    """构造测试用 Metrics 对象。"""
    m = Metrics(
        _id="wxid_test",
        base_score=base_score,
        composite=composite,
        signal_level=signal_level,
        neediness_penalty=neediness_penalty,
        interaction_pattern=interaction_pattern,
        session_recency=session_recency or {},
        momentum=momentum or {},
        initiation_source=initiation_source or {},
        media_engagement=media_engagement or {},
    )
    m.composite_slope = MetricValue(sample_size=composite_slope_sample)
    return m


def _make_person(
    person_id: str = "p1",
    display_name: str = "Alice",
    accounts: list[IdentityAccount] | None = None,
) -> IdentityPerson:
    """构造测试用 IdentityPerson。"""
    if accounts is None:
        accounts = [
            IdentityAccount(
                id="a1", person_id=person_id, wxid="wxid_alice",
                conversation_id="wxid_alice", display_name=display_name,
            ),
        ]
    return IdentityPerson(id=person_id, display_name=display_name, accounts=accounts)


# ═══════════════════════════════════════════════════════════════════
# agent_metrics
# ═══════════════════════════════════════════════════════════════════

class TestAgentMetrics:
    """agent_metrics 返回指标字典。"""

    def test_person_not_found_returns_string(self, monkeypatch):
        """联系人未找到 → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: None)
        result = agent_metrics("Unknown")
        assert isinstance(result, str)
        assert "未找到联系人: Unknown" in result
        mock_conn.close.assert_called_once()

    def test_no_accounts_returns_string(self, monkeypatch):
        """联系人无账号 → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(id="p1", display_name="Alice", accounts=[])
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        result = agent_metrics("Alice")
        assert isinstance(result, str)
        assert "未找到联系人: Alice" in result

    def test_normal_returns_dict(self, monkeypatch):
        """正常调用 → 返回 dict 含正确字段。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics()
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name, compute_slope=False: metrics)
        result = agent_metrics("Alice")
        assert isinstance(result, dict)
        assert result["person_id"] == "p1"
        assert result["display_name"] == "Alice"
        assert len(result["accounts"]) == 1
        account = result["accounts"][0]
        assert account["wxid"] == "wxid_alice"
        assert account["display_name"] == "Alice"
        assert account["composite"] == 0.55
        assert account["base_score"] == 0.5
        assert account["signal_level"] == "中窗口"
        assert account["neediness_penalty"] == 1.0
        assert "metrics" in account
        assert "composite_slope" in account
        assert "session_recency" in account
        assert "momentum" in account
        assert "initiation_source" in account
        assert "media_engagement" in account

    def test_multiple_accounts(self, monkeypatch):
        """多账号 → 每个账号都有 metrics。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_a1",
                                conversation_id="wxid_a1", display_name="Alice"),
                IdentityAccount(id="a2", person_id="p1", wxid="wxid_a2",
                                conversation_id="wxid_a2", display_name="Alice2"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        # 两个 wxid 返回不同 metrics
        def fake_compute(conn, cfg, wxid, name, compute_slope=False):
            return _make_metrics(base_score=0.6 if wxid == "wxid_a1" else 0.3)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact", fake_compute)
        result = agent_metrics("Alice")
        assert len(result["accounts"]) == 2
        # 按 wxid 区分
        wxids = {acc["wxid"] for acc in result["accounts"]}
        assert wxids == {"wxid_a1", "wxid_a2"}

    def test_account_without_conversation_id_falls_back_to_wxid(self, monkeypatch):
        """account.conversation_id 为空 → fallback 到 wxid。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_fallback",
                                conversation_id="", display_name="Alice"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        captured_wxid = []
        def fake_compute(conn, cfg, wxid, name, compute_slope=False):
            captured_wxid.append(wxid)
            return _make_metrics()
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact", fake_compute)
        result = agent_metrics("Alice")
        assert captured_wxid == ["wxid_fallback"]
        assert result["accounts"][0]["wxid"] == "wxid_fallback"

    def test_account_without_wxid_and_conversation_id_skipped(self, monkeypatch):
        """account 无 wxid 且无 conversation_id → 跳过该账号。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="",
                                conversation_id="", display_name="Alice"),
                IdentityAccount(id="a2", person_id="p1", wxid="wxid_a2",
                                conversation_id="wxid_a2", display_name="Alice2"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name, compute_slope=False: _make_metrics())
        result = agent_metrics("Alice")
        # 只有 1 个有效账号
        assert len(result["accounts"]) == 1
        assert result["accounts"][0]["wxid"] == "wxid_a2"

    def test_compute_slope_passed_as_true(self, monkeypatch):
        """compute_slope=True 被传递给 compute_metrics_for_contact。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        captured_kwargs = {}
        def fake_compute(conn, cfg, wxid, name, compute_slope=False):
            captured_kwargs["compute_slope"] = compute_slope
            return _make_metrics()
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact", fake_compute)
        agent_metrics("Alice")
        assert captured_kwargs["compute_slope"] is True

    def test_account_display_name_falls_back_to_person_display_name(self, monkeypatch):
        """account.display_name 为空 → fallback 到 person.display_name。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_alice",
                                conversation_id="wxid_alice", display_name=""),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        captured_name = []
        def fake_compute(conn, cfg, wxid, name, compute_slope=False):
            captured_name.append(name)
            return _make_metrics()
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact", fake_compute)
        agent_metrics("Alice")
        assert captured_name == ["Alice"]


# ═══════════════════════════════════════════════════════════════════
# agent_status
# ═══════════════════════════════════════════════════════════════════

class TestAgentStatus:
    """agent_status 返回 Markdown 状态报告。"""

    def test_person_not_found_returns_string(self, monkeypatch):
        """联系人未找到 → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: None)
        result = agent_status("Unknown")
        assert isinstance(result, str)
        assert "未找到联系人: Unknown" in result
        mock_conn.close.assert_called_once()

    def test_no_accounts_returns_string(self, monkeypatch):
        """联系人无账号 → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(id="p1", display_name="Alice", accounts=[])
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        result = agent_status("Alice")
        assert "未找到联系人: Alice" in result

    def test_normal_returns_markdown(self, monkeypatch):
        """正常调用 → 返回 markdown 含基本字段。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        # mock message count
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 100}
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(base_score=0.5, composite=0.55, signal_level="中窗口")
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "# 状态: Alice" in result
        assert "- person_id: p1" in result
        assert "- 账号数: 1" in result
        assert "- 消息数: 100" in result
        assert "- base_score: 0.5000" in result
        assert "- composite: 0.5500" in result
        assert "- 信号等级: 中窗口" in result

    def test_account_label_uses_remark_first(self, monkeypatch):
        """账号标签优先使用 remark。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_alice",
                                conversation_id="wxid_alice", display_name="Alice",
                                remark="Alice备注", nickname="Alice昵称"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: _make_metrics())
        result = agent_status("Alice")
        assert "Alice备注" in result

    def test_account_label_falls_back_to_nickname(self, monkeypatch):
        """账号标签 fallback 到 nickname。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_alice",
                                conversation_id="wxid_alice", display_name="Alice",
                                remark="", nickname="Alice昵称"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: _make_metrics())
        result = agent_status("Alice")
        assert "Alice昵称" in result

    def test_neediness_penalty_displayed_when_below_one(self, monkeypatch):
        """neediness_penalty < 1.0 → 显示惩罚信息。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(neediness_penalty=0.85)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "需求感惩罚: 0.85" in result

    def test_neediness_penalty_hidden_when_one(self, monkeypatch):
        """neediness_penalty == 1.0 → 不显示惩罚信息。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(neediness_penalty=1.0)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "需求感惩罚" not in result

    def test_interaction_pattern_displayed(self, monkeypatch):
        """interaction_pattern 非空 → 显示互动模式。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(interaction_pattern="她主导")
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "- 互动模式: 她主导" in result

    def test_session_recency_displayed(self, monkeypatch):
        """session_recency 非空 → 显示最近活跃。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(session_recency={"label": "刚刚"})
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "- 最近活跃: 刚刚" in result
        assert "### 动态信号" in result

    def test_momentum_displayed(self, monkeypatch):
        """momentum 非空 → 显示动量。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(momentum={"direction": "上升", "momentum": 1.5})
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "- 动量: 上升 (1.5x)" in result

    def test_initiation_source_displayed(self, monkeypatch):
        """initiation_source 非空 → 显示发起方。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(initiation_source={"signal": "她主动"})
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "- 发起方: 她主动" in result

    def test_media_engagement_with_sticker_and_image(self, monkeypatch):
        """媒体参与度含贴纸和图片 → 显示。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(
            media_engagement={
                "sticker_count": 5, "sticker_ratio": 0.2,
                "image_count": 3, "image_ratio": 0.1,
                "distinct_stickers": 4, "mimicry_signal": "镜像",
            },
        )
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "### 媒体参与度" in result
        assert "- 贴纸: 5 条 (20%)" in result
        assert "- 图片: 3 条 (10%)" in result
        assert "- 贴纸词典: 4 种" in result
        assert "- 镜像信号: 镜像" in result

    def test_media_engagement_zero_hidden(self, monkeypatch):
        """贴纸和图片都是 0 → 不显示媒体参与度 section。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics(
            media_engagement={
                "sticker_count": 0, "sticker_ratio": 0.0,
                "image_count": 0, "image_ratio": 0.0,
            },
        )
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "### 媒体参与度" not in result

    def test_metrics_table_included(self, monkeypatch):
        """结果包含指标详情表格。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        metrics = _make_metrics()
        # 给一个指标设值
        metrics.fback = MetricValue(raw=0.8, normalized=0.6, confidence=0.5, sample_size=20)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: metrics)
        result = agent_status("Alice")
        assert "### 指标详情" in result
        assert "| 指标 | normalized | confidence | sample_size |" in result
        assert "| fback | 0.6000 | 0.50 | 20 |" in result

    def test_multiple_accounts_in_status(self, monkeypatch):
        """多账号 → 每个账号单独一个 section。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 50}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_a1",
                                conversation_id="wxid_a1", display_name="Alice"),
                IdentityAccount(id="a2", person_id="p1", wxid="wxid_a2",
                                conversation_id="wxid_a2", display_name="Alice2"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: _make_metrics())
        result = agent_status("Alice")
        assert "- 账号数: 2" in result
        assert "## 账号 1:" in result
        assert "## 账号 2:" in result

    def test_message_count_zero_when_no_row(self, monkeypatch):
        """msg_row 为 None → message_count = 0。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person()
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: _make_metrics())
        result = agent_status("Alice")
        assert "- 消息数: 0" in result

    def test_wxid_truncated_to_25_chars_in_header(self, monkeypatch):
        """wxid 在 section 标题中被截断到 25 字符。"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        # 用 a 和 b 区分前后部分，避免子串误判
        long_wxid = "wxid_" + "a" * 20 + "b" * 20  # 45 字符
        person = _make_person(
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid=long_wxid,
                                conversation_id=long_wxid, display_name="Alice"),
            ],
        )
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        monkeypatch.setattr("engine.analyzers.metrics.compute_metrics_for_contact",
                            lambda conn, cfg, wxid, name: _make_metrics())
        result = agent_status("Alice")
        # 应只显示前 25 字符（wxid_ + 20个a），后 20 个 b 不应出现
        assert long_wxid[:25] in result
        assert "b" * 20 not in result


# ═══════════════════════════════════════════════════════════════════
# agent_rank
# ═══════════════════════════════════════════════════════════════════

class TestAgentRank:
    """agent_rank 返回排名表。"""

    def test_normal_returns_string(self, monkeypatch):
        """正常调用 → 返回字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        mock_ranking = MagicMock()
        monkeypatch.setattr("engine.analyzers.ranker.compute_rankings",
                            lambda conn, cfg: mock_ranking)
        monkeypatch.setattr("engine.analyzers.ranker.format_ranking_table",
                            lambda ranking, conn=None: "排名表内容")
        result = agent_rank()
        assert result == "排名表内容"
        mock_conn.close.assert_called_once()

    def test_conn_passed_to_format_ranking_table(self, monkeypatch):
        """conn 被传递给 format_ranking_table。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        mock_ranking = MagicMock()
        monkeypatch.setattr("engine.analyzers.ranker.compute_rankings",
                            lambda conn, cfg: mock_ranking)
        captured_conn = []
        def fake_format(ranking, conn=None):
            captured_conn.append(conn)
            return "ok"
        monkeypatch.setattr("engine.analyzers.ranker.format_ranking_table", fake_format)
        agent_rank()
        assert captured_conn[0] is mock_conn

    def test_config_passed_to_compute_rankings(self, monkeypatch):
        """config 被传递给 compute_rankings。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        captured_config = []
        def fake_compute(conn, cfg):
            captured_config.append(cfg)
            return MagicMock()
        monkeypatch.setattr("engine.analyzers.ranker.compute_rankings", fake_compute)
        monkeypatch.setattr("engine.analyzers.ranker.format_ranking_table",
                            lambda ranking, conn=None: "")
        agent_rank()
        assert captured_config[0] is mock_config


# ═══════════════════════════════════════════════════════════════════
# agent_weekly
# ═══════════════════════════════════════════════════════════════════

class TestAgentWeekly:
    """agent_weekly 生成周报并保存。"""

    def test_normal_generates_report(self, monkeypatch, tmp_path):
        """正常调用 → 生成报告文件。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        # 临时替换 OUTPUTS_REPORTS_DIR 和 OUTPUTS_RANKINGS_DIR
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", tmp_path / "reports")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path / "rankings")
        mock_ranking = MagicMock()
        mock_ranking.week = "2026-W30"
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report",
                            lambda conn, cfg, deep=False: (mock_ranking, "周报 Markdown 内容"))
        monkeypatch.setattr("engine.analyzers.weekly_report.format_weekly_summary",
                            lambda ranking, conn=None: "周报摘要")
        result = agent_weekly()
        # 验证文件已生成
        report_path = tmp_path / "reports" / "2026-W30_report.md"
        assert report_path.exists()
        assert report_path.read_text(encoding="utf-8") == "周报 Markdown 内容"
        # 验证返回值
        assert "周报摘要" in result
        assert "周报已保存" in result
        assert str(report_path) in result
        assert "排名快照" in result
        mock_conn.close.assert_called_once()

    def test_deep_parameter_passed(self, monkeypatch, tmp_path):
        """deep=True 被传递给 generate_weekly_report。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", tmp_path / "reports")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path / "rankings")
        mock_ranking = MagicMock()
        mock_ranking.week = "2026-W30"
        captured_deep = []
        def fake_generate(conn, cfg, deep=False):
            captured_deep.append(deep)
            return (mock_ranking, "md")
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report", fake_generate)
        monkeypatch.setattr("engine.analyzers.weekly_report.format_weekly_summary",
                            lambda ranking, conn=None: "summary")
        agent_weekly(deep=True)
        assert captured_deep == [True]

    def test_default_deep_is_false(self, monkeypatch, tmp_path):
        """默认 deep=False。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", tmp_path / "reports")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path / "rankings")
        mock_ranking = MagicMock()
        mock_ranking.week = "2026-W30"
        captured_deep = []
        def fake_generate(conn, cfg, deep=False):
            captured_deep.append(deep)
            return (mock_ranking, "md")
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report", fake_generate)
        monkeypatch.setattr("engine.analyzers.weekly_report.format_weekly_summary",
                            lambda ranking, conn=None: "summary")
        agent_weekly()
        assert captured_deep == [False]

    def test_report_dir_created_if_not_exists(self, monkeypatch, tmp_path):
        """报告目录不存在 → 自动创建。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        reports_dir = tmp_path / "new_reports"
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", reports_dir)
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path / "rankings")
        mock_ranking = MagicMock()
        mock_ranking.week = "2026-W30"
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report",
                            lambda conn, cfg, deep=False: (mock_ranking, "md"))
        monkeypatch.setattr("engine.analyzers.weekly_report.format_weekly_summary",
                            lambda ranking, conn=None: "summary")
        assert not reports_dir.exists()
        agent_weekly()
        assert reports_dir.exists()
        assert (reports_dir / "2026-W30_report.md").exists()

    def test_conn_passed_to_format_weekly_summary(self, monkeypatch, tmp_path):
        """conn 被传递给 format_weekly_summary。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", tmp_path / "reports")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path / "rankings")
        mock_ranking = MagicMock()
        mock_ranking.week = "2026-W30"
        captured_conn = []
        def fake_format(ranking, conn=None):
            captured_conn.append(conn)
            return "summary"
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report",
                            lambda conn, cfg, deep=False: (mock_ranking, "md"))
        monkeypatch.setattr("engine.analyzers.weekly_report.format_weekly_summary", fake_format)
        agent_weekly()
        assert captured_conn[0] is mock_conn


# ═══════════════════════════════════════════════════════════════════
# agent_compare_analysis
# ═══════════════════════════════════════════════════════════════════

class TestAgentCompareAnalysis:
    """agent_compare_analysis 对比 latest.yaml 和 previous.yaml。"""

    def test_person_not_found_returns_string(self, monkeypatch):
        """联系人未找到 → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: None)
        result = agent_compare_analysis("Unknown")
        assert isinstance(result, str)
        assert "未找到联系人: Unknown" in result
        mock_conn.close.assert_called_once()

    def test_no_latest_returns_string(self, monkeypatch, tmp_path):
        """无 latest.yaml → 返回错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        # OUTPUTS_ANALYSIS_DIR 指向空目录
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "没有找到 Alice 的分析结论" in result

    def test_latest_only_no_previous(self, monkeypatch, tmp_path):
        """有 latest 无 previous → 首次分析。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        # 创建 person_dir 和 latest.yaml
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "互动正常",
            "strategy": "保持节奏",
            "generated_at": "2026-07-24",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "首次" in result
        assert "stage_2" in result
        assert "80%" in result
        assert "互动正常" in result
        assert "保持节奏" in result
        assert "2026-07-24" in result
        assert "无历史版本可对比" in result

    def test_latest_and_previous_stage_changed(self, monkeypatch, tmp_path):
        """有 latest 和 previous，阶段变化。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_3", "confidence": 0.9},
            "diagnosis": "暧昧期",
            "strategy": "升级关系",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.7},
            "diagnosis": "熟悉期",
            "strategy": "保持节奏",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "# Alice — 分析对比" in result
        assert "**阶段变化**: stage_2 → stage_3" in result
        assert "**置信度**: 70% → 90% (↑20%)" in result
        assert "**诊断变化**" in result
        assert "- 旧: 熟悉期" in result
        assert "- 新: 暧昧期" in result
        assert "**策略变化**" in result
        assert "- 旧: 保持节奏" in result
        assert "- 新: 升级关系" in result
        assert "**上次分析**: 2026-07-17" in result
        assert "**本次分析**: 2026-07-24" in result

    def test_stage_unchanged_no_confidence_diff(self, monkeypatch, tmp_path):
        """阶段不变 + 置信度差 ≤ 0.01 → 只显示阶段未变化。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.80},
            "diagnosis": "互动正常",
            "strategy": "保持节奏",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.80},
            "diagnosis": "互动正常",
            "strategy": "保持节奏",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "**阶段**: stage_2（未变化）" in result
        # 置信度差 ≤ 0.01 → 不显示置信度变化行
        assert "置信度" not in result
        # 诊断和策略都不变 → 不显示变化 section
        assert "诊断变化" not in result
        assert "策略变化" not in result

    def test_confidence_decreased(self, monkeypatch, tmp_path):
        """置信度下降 → 显示 ↓。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.5},
            "diagnosis": "",
            "strategy": "",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "",
            "strategy": "",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "**置信度**: 80% → 50% (↓30%)" in result

    def test_confidence_diff_below_threshold_hidden(self, monkeypatch, tmp_path):
        """置信度差 < 0.01 → 不显示置信度变化。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.805},
            "diagnosis": "诊断1",
            "strategy": "策略1",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.80},
            "diagnosis": "诊断2",
            "strategy": "策略2",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        # abs(0.005) < 0.01 → 不显示
        assert "置信度" not in result

    def test_diagnosis_unchanged_hidden(self, monkeypatch, tmp_path):
        """诊断不变 → 不显示诊断变化 section。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "相同诊断",
            "strategy": "新策略",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "相同诊断",
            "strategy": "旧策略",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "诊断变化" not in result
        assert "策略变化" in result

    def test_strategy_unchanged_hidden(self, monkeypatch, tmp_path):
        """策略不变 → 不显示策略变化 section。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "新诊断",
            "strategy": "相同策略",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "旧诊断",
            "strategy": "相同策略",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "诊断变化" in result
        assert "策略变化" not in result

    def test_empty_diagnosis_shown_as_none(self, monkeypatch, tmp_path):
        """空诊断 → 显示为"（无）"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "",
            "strategy": "",
            "generated_at": "2026-07-24",
        }
        previous_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            "diagnosis": "有诊断",
            "strategy": "有策略",
            "generated_at": "2026-07-17",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        (person_dir / "previous.yaml").write_text(yaml.safe_dump(previous_data, allow_unicode=True),
                                                    encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "- 旧: 有诊断" in result
        assert "- 新: （无）" in result

    def test_missing_stage_field_uses_unknown(self, monkeypatch, tmp_path):
        """stage 字段缺失 → stage 为"未知"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        # latest 无 stage 字段
        latest_data = {"generated_at": "2026-07-24"}
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        # 无 previous → 走首次分支
        assert "首次" in result
        assert "未知" in result

    def test_missing_generated_at_uses_unknown(self, monkeypatch, tmp_path):
        """generated_at 缺失 → 显示"未知"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("Alice")
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_2", "confidence": 0.8},
            # 无 generated_at
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("Alice")
        assert "生成时间: 未知" in result

    def test_display_name_with_special_chars_slugified(self, monkeypatch, tmp_path):
        """display_name 含特殊字符 → slug 化后路径正确。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        person = _make_person(person_id="p1", display_name="A/B:C")
        monkeypatch.setattr("engine.agent.report._resolve_person", lambda c, n: person)
        slug = slug_display_name("A/B:C")
        # slug 应该替换特殊字符
        assert "/" not in slug
        assert ":" not in slug
        person_dir = tmp_path / f"{slug}__p1"
        person_dir.mkdir(parents=True)
        latest_data = {
            "stage": {"stage": "stage_1", "confidence": 0.6},
            "generated_at": "2026-07-24",
        }
        (person_dir / "latest.yaml").write_text(yaml.safe_dump(latest_data, allow_unicode=True),
                                                  encoding="utf-8")
        monkeypatch.setattr("engine.agent.report.OUTPUTS_ANALYSIS_DIR", tmp_path)
        result = agent_compare_analysis("A/B:C")
        assert "没有找到" not in result
        assert "stage_1" in result


# ═══════════════════════════════════════════════════════════════════
# 连接管理
# ═══════════════════════════════════════════════════════════════════

class TestConnectionManagement:
    """所有函数都应在 finally 中关闭 conn。"""

    def test_agent_metrics_closes_conn_on_error(self, monkeypatch):
        """agent_metrics 在异常时也关闭 conn。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person",
                            lambda c, n: (_ for _ in ()).throw(RuntimeError("test")))
        with pytest.raises(RuntimeError):
            agent_metrics("Alice")
        mock_conn.close.assert_called_once()

    def test_agent_status_closes_conn_on_error(self, monkeypatch):
        """agent_status 在异常时也关闭 conn。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person",
                            lambda c, n: (_ for _ in ()).throw(RuntimeError("test")))
        with pytest.raises(RuntimeError):
            agent_status("Alice")
        mock_conn.close.assert_called_once()

    def test_agent_rank_closes_conn_on_error(self, monkeypatch):
        """agent_rank 在异常时也关闭 conn。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.analyzers.ranker.compute_rankings",
                            lambda conn, cfg: (_ for _ in ()).throw(RuntimeError("test")))
        with pytest.raises(RuntimeError):
            agent_rank()
        mock_conn.close.assert_called_once()

    def test_agent_weekly_closes_conn_on_error(self, monkeypatch, tmp_path):
        """agent_weekly 在异常时也关闭 conn。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report.OUTPUTS_REPORTS_DIR", tmp_path)
        monkeypatch.setattr("engine.agent.report.OUTPUTS_RANKINGS_DIR", tmp_path)
        monkeypatch.setattr("engine.analyzers.weekly_report.generate_weekly_report",
                            lambda conn, cfg, deep=False: (_ for _ in ()).throw(RuntimeError("test")))
        with pytest.raises(RuntimeError):
            agent_weekly()
        mock_conn.close.assert_called_once()

    def test_agent_compare_analysis_closes_conn_on_error(self, monkeypatch):
        """agent_compare_analysis 在异常时也关闭 conn。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.report._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.report._resolve_person",
                            lambda c, n: (_ for _ in ()).throw(RuntimeError("test")))
        with pytest.raises(RuntimeError):
            agent_compare_analysis("Alice")
        mock_conn.close.assert_called_once()
