"""weekly_report.py 单元测试。

覆盖 generate_weekly_report / _run_deep_analysis / _format_markdown /
format_weekly_summary。

compute_rankings 使用 monkeypatch mock 避免依赖真实指标计算。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from engine.analyzers import weekly_report
from engine.analyzers.weekly_report import (
    _format_markdown,
    _run_deep_analysis,
    format_weekly_summary,
    generate_weekly_report,
)
from engine.models.ranking import (
    InsufficientData,
    Ranking,
    RankingChange,
    RankedPerson,
)


# 工具 fixtures

@pytest.fixture
def sample_ranking():
    """构造一个有 2 个排名 + 1 个数据不足的 Ranking。"""
    return Ranking(
        week="2026-W01",
        generated_at="2026-01-01T00:00:00",
        total_candidates=3,
        rankings=[
            RankedPerson(
                rank=1, name="Alice", _id="p1", person_id="p1",
                base_score=0.7, composite=0.8, signal_level="high",
                stage="stage_3", delta_rank=1, delta_composite=0.1,
                tags=["置顶"],
            ),
            RankedPerson(
                rank=2, name="Bob", _id="p2", person_id="p2",
                base_score=0.5, composite=0.6, signal_level="medium",
                stage="stage_2", delta_rank=-1, delta_composite=-0.05,
                tags=[],
            ),
        ],
        risers=[RankingChange(name="Alice", reason="排名上升")],
        fallers=[RankingChange(name="Bob", reason="排名下降")],
        insufficient_data=[InsufficientData(name="Charlie", message_count=5)],
    )


@pytest.fixture
def empty_ranking():
    return Ranking(
        week="2026-W01",
        generated_at="2026-01-01T00:00:00",
        total_candidates=0,
    )


@pytest.fixture
def mock_compute_rankings(monkeypatch, sample_ranking):
    """Mock compute_rankings 返回 sample_ranking。"""
    monkeypatch.setattr(
        "engine.analyzers.weekly_report.compute_rankings",
        lambda conn, config: sample_ranking,
    )


# _format_markdown

class TestFormatMarkdown:
    def test_basic_structure(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "# 恋爱助攻周报 — 2026-W01" in md
        assert "生成时间: 2026-01-01T00:00:00" in md
        assert "候选人总数: 3" in md
        assert "有效排名: 2" in md
        assert "数据不足: 1" in md

    def test_ranking_table_header(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "## 排名" in md
        assert "| 排名 | 姓名 | base | composite | 信号 | 趋势 |" in md

    def test_ranking_table_rows(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "Alice" in md
        assert "Bob" in md
        assert "0.7000" in md
        assert "0.8000" in md
        assert "high" in md
        assert "medium" in md

    def test_trend_with_rank_change(self, sample_ranking, test_config):
        """趋势列包含 delta_composite 和 rank_change 箭头。"""
        md = _format_markdown(sample_ranking, config=test_config)
        # Alice: delta_composite=0.1, delta_rank=1 → ↑1
        assert "↑1" in md
        # Bob: delta_composite=-0.05, delta_rank=-1 → ↓1
        assert "↓1" in md

    def test_risers_section(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "## 变动" in md
        assert "**上升:**" in md
        assert "Alice: 排名上升" in md

    def test_fallers_section(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "**下降:**" in md
        assert "Bob: 排名下降" in md

    def test_insufficient_data_section(self, sample_ranking, test_config):
        md = _format_markdown(sample_ranking, config=test_config)
        assert "## 数据不足" in md
        assert "Charlie" in md
        assert "5 条消息" in md

    def test_empty_ranking(self, empty_ranking, test_config):
        """空 Ranking 也能格式化。"""
        md = _format_markdown(empty_ranking, config=test_config)
        assert "# 恋爱助攻周报 — 2026-W01" in md
        assert "有效排名: 0" in md
        assert "暂无排名数据" in md

    def test_empty_ranking_no_risers_fallers(self, empty_ranking, test_config):
        """无 risers/fallers 时不显示变动 section。"""
        md = _format_markdown(empty_ranking, config=test_config)
        assert "## 变动" not in md

    def test_empty_ranking_no_insufficient(self, empty_ranking, test_config):
        """无 insufficient_data 时不显示数据不足 section。"""
        md = _format_markdown(empty_ranking, config=test_config)
        assert "## 数据不足" not in md

    def test_with_coverage_info(self, sample_ranking, test_config, tmp_db):
        """传入 conn 且有覆盖率数据时显示可信度。"""
        # 创建 sync_state 表
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                session_id TEXT PRIMARY KEY,
                watermark INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_sync_at INTEGER NOT NULL,
                last_error TEXT
            )
        """)
        tmp_db.execute(
            "INSERT OR IGNORE INTO conversations (id, type, display_name, contact_id, updated_at) "
            "VALUES (?, 'private', ?, ?, ?)",
            ("wxid_a", "Alice", "wxid_a", int(time.time())),
        )
        tmp_db.execute(
            "INSERT INTO sync_state (session_id, watermark, message_count, last_sync_at, last_error) "
            "VALUES (?, ?, ?, ?, NULL)",
            ("s1", 100, 50, int(time.time())),
        )
        tmp_db.commit()

        md = _format_markdown(sample_ranking, config=test_config, conn=tmp_db)
        assert "数据可信度" in md

    def test_no_coverage_info_when_conn_none(self, sample_ranking, test_config):
        """conn=None 时不显示覆盖率。"""
        md = _format_markdown(sample_ranking, config=test_config, conn=None)
        assert "数据可信度" not in md

    def test_deep_results_section(self, sample_ranking, test_config):
        """有 deep_results 时显示深度分析 section。"""
        deep_results = [
            {
                "name": "Alice",
                "rank": 1,
                "analysis": None,
                "error": "Agent-driven: 深度分析由 Agent 直接完成",
            },
        ]
        md = _format_markdown(sample_ranking, config=test_config, deep_results=deep_results)
        assert "## 深度分析（Top 5）" in md
        assert "### #1 Alice" in md
        assert "分析失败" in md
        assert "Agent-driven" in md

    def test_trend_positive_delta_has_plus(self, sample_ranking, test_config):
        """正 delta_composite 显示 + 号（:.3f 格式，3 位小数）。"""
        md = _format_markdown(sample_ranking, config=test_config)
        assert "+0.100" in md

    def test_trend_negative_delta_no_plus(self, sample_ranking, test_config):
        """负 delta_composite 不显示 + 号（:.3f 格式）。"""
        md = _format_markdown(sample_ranking, config=test_config)
        assert "-0.050" in md

    def test_neutral_rank_change_arrow(self, test_config):
        """delta_rank=0 显示 →。"""
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_rank=0, delta_composite=0.0),
            ],
        )
        md = _format_markdown(ranking, config=test_config)
        assert "→" in md


# _run_deep_analysis

class TestRunDeepAnalysis:
    def test_returns_placeholder_results(self, sample_ranking, tmp_db, test_config):
        """_run_deep_analysis 返回占位结果（Agent-driven 架构）。"""
        results = _run_deep_analysis(sample_ranking, tmp_db, test_config)
        assert len(results) == 2  # top 5 但只有 2 个排名
        for r in results:
            assert r["analysis"] is None
            assert "Agent-driven" in r["error"]

    def test_respects_top_5_limit(self, tmp_db, test_config):
        """即使有超过 5 个排名，也只取前 5 个。"""
        rankings = [
            RankedPerson(rank=i, name=f"P{i}", person_id=f"p{i}",
                         base_score=0.5, composite=0.9 - i * 0.1,
                         signal_level="medium")
            for i in range(1, 8)  # 7 个排名
        ]
        ranking = Ranking(week="2026-W01", rankings=rankings)
        results = _run_deep_analysis(ranking, tmp_db, test_config)
        assert len(results) == 5  # 只取前 5

    def test_empty_rankings_returns_empty(self, empty_ranking, tmp_db, test_config):
        results = _run_deep_analysis(empty_ranking, tmp_db, test_config)
        assert results == []

    def test_result_includes_name_and_rank(self, sample_ranking, tmp_db, test_config):
        results = _run_deep_analysis(sample_ranking, tmp_db, test_config)
        assert results[0]["name"] == "Alice"
        assert results[0]["rank"] == 1
        assert results[1]["name"] == "Bob"
        assert results[1]["rank"] == 2


# format_weekly_summary

class TestFormatWeeklySummary:
    def test_basic_summary(self, sample_ranking):
        out = format_weekly_summary(sample_ranking)
        assert "2026-W01" in out
        assert "Alice" in out
        assert "Bob" in out

    def test_summary_with_risers(self, sample_ranking):
        out = format_weekly_summary(sample_ranking)
        assert "上升:" in out
        assert "Alice: 排名上升" in out

    def test_summary_with_fallers(self, sample_ranking):
        out = format_weekly_summary(sample_ranking)
        assert "下降:" in out
        assert "Bob: 排名下降" in out

    def test_empty_ranking_summary(self, empty_ranking):
        out = format_weekly_summary(empty_ranking)
        assert "暂无排名数据" in out

    def test_summary_with_coverage(self, sample_ranking, tmp_db):
        """传入 conn 且有数据时附加覆盖率。"""
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                session_id TEXT PRIMARY KEY,
                watermark INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_sync_at INTEGER NOT NULL,
                last_error TEXT
            )
        """)
        tmp_db.execute(
            "INSERT OR IGNORE INTO conversations (id, type, display_name, contact_id, updated_at) "
            "VALUES (?, 'private', ?, ?, ?)",
            ("wxid_a", "Alice", "wxid_a", int(time.time())),
        )
        tmp_db.execute(
            "INSERT INTO sync_state (session_id, watermark, message_count, last_sync_at, last_error) "
            "VALUES (?, ?, ?, ?, NULL)",
            ("s1", 100, 50, int(time.time())),
        )
        tmp_db.commit()
        out = format_weekly_summary(sample_ranking, conn=tmp_db)
        assert "数据可信度" in out

    def test_summary_no_coverage_when_conn_none(self, sample_ranking):
        out = format_weekly_summary(sample_ranking, conn=None)
        assert "数据可信度" not in out


# generate_weekly_report

class TestGenerateWeeklyReport:
    def test_returns_ranking_and_markdown(self, mock_compute_rankings, tmp_db,
                                          test_config, monkeypatch, tmp_path):
        """generate_weekly_report 返回 (ranking, md) 元组。"""
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking, md = generate_weekly_report(tmp_db, test_config)
        assert isinstance(ranking, Ranking)
        assert isinstance(md, str)
        assert "# 恋爱助攻周报" in md

    def test_saves_snapshot_yaml(self, mock_compute_rankings, tmp_db,
                                  test_config, monkeypatch, tmp_path):
        """生成周报时保存 YAML 快照。"""
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking, _ = generate_weekly_report(tmp_db, test_config)
        snapshot = tmp_path / f"{ranking.week}.yaml"
        assert snapshot.exists()
        # 验证 YAML 内容
        data = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
        assert data["week"] == ranking.week
        assert len(data["rankings"]) == 2

    def test_creates_rankings_dir_if_not_exists(self, mock_compute_rankings, tmp_db,
                                                 test_config, monkeypatch, tmp_path):
        """rankings 目录不存在时自动创建。"""
        target_dir = tmp_path / "nested" / "rankings"
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", target_dir)
        ranking, _ = generate_weekly_report(tmp_db, test_config)
        assert target_dir.exists()
        assert (target_dir / f"{ranking.week}.yaml").exists()

    def test_deep_mode_triggers_deep_analysis(self, mock_compute_rankings, tmp_db,
                                               test_config, monkeypatch, tmp_path):
        """deep=True 时触发深度分析（占位）。"""
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking, md = generate_weekly_report(tmp_db, test_config, deep=True)
        # 深度分析 section 应出现
        assert "## 深度分析（Top 5）" in md
        assert "Agent-driven" in md

    def test_non_deep_mode_no_deep_analysis(self, mock_compute_rankings, tmp_db,
                                             test_config, monkeypatch, tmp_path):
        """deep=False 时不触发深度分析。"""
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking, md = generate_weekly_report(tmp_db, test_config, deep=False)
        assert "## 深度分析" not in md

    def test_overwrites_existing_snapshot(self, mock_compute_rankings, tmp_db,
                                           test_config, monkeypatch, tmp_path):
        """重复生成周报应覆盖同名快照。"""
        monkeypatch.setattr(weekly_report, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking1, _ = generate_weekly_report(tmp_db, test_config)
        # 再次生成（同一周）
        ranking2, _ = generate_weeking_report_check(tmp_db, test_config, tmp_path)
        # 快照文件应只有 1 个
        snapshots = list(tmp_path.glob("*.yaml"))
        assert len(snapshots) == 1


def generate_weeking_report_check(tmp_db, test_config, tmp_path):
    """辅助函数：第二次调用 generate_weekly_report 验证覆盖。"""
    return generate_weekly_report(tmp_db, test_config)
