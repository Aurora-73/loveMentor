"""ranker.py 单元测试。

覆盖 _current_week / _load_prev_ranking / _resolve_person_id /
_resolve_person_name / compute_rankings / get_coverage_info /
format_ranking_table / Ranking 模型 round-trip。

compute_metrics_for_contact 是复杂函数，使用 monkeypatch mock 避免依赖。
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from engine.analyzers import ranker
from engine.analyzers.ranker import (
    _current_week,
    _load_prev_ranking,
    _resolve_person_id,
    _resolve_person_name,
    compute_rankings,
    format_ranking_table,
    get_coverage_info,
)
from engine.models.ranking import (
    InsufficientData,
    Ranking,
    RankingChange,
    RankedPerson,
)


# 工具 fixture

@pytest.fixture
def insert_messages(tmp_db):
    """插入测试消息。"""
    _counter = 0

    def _insert(conversation_id: str, sender_id: str, content: str,
                timestamp: int, msg_type: int = 1):
        nonlocal _counter
        _counter += 1
        msg_id = f"rk_msg_{_counter}"
        tmp_db.execute(
            """INSERT OR IGNORE INTO messages
               (id, conversation_id, sender_id, timestamp, type, content, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, conversation_id, sender_id, timestamp, msg_type, content, timestamp),
        )
        tmp_db.commit()
        return msg_id

    return _insert


@pytest.fixture
def mock_metrics(monkeypatch):
    """Mock compute_metrics_for_contact，返回简化的 Metrics 对象。"""
    from engine.models.metrics import MetricValue, Metrics

    def _fake(conn, config, wxid, name, **kwargs):
        score_map = {
            "wxid_a": (0.7, 0.8, "high"),
            "wxid_b": (0.5, 0.6, "medium"),
            "wxid_c": (0.3, 0.4, "low"),
        }
        base, composite, signal = score_map.get(wxid, (0.1, 0.2, "low"))
        return Metrics(
            msg_count=MetricValue(raw=100, normalized=0.5, confidence=0.9, sample_size=100),
            base_score=base,
            composite=composite,
            signal_level=signal,
        )

    monkeypatch.setattr("engine.analyzers.ranker.compute_metrics_for_contact", _fake)


# _current_week

class TestCurrentWeek:
    def test_format_is_year_wXX(self):
        week = _current_week()
        assert len(week) == 8
        assert week[4] == "-"
        assert week[5] == "W"
        year = int(week[:4])
        week_num = int(week[6:])
        assert 2020 <= year <= 2100
        assert 1 <= week_num <= 53

    def test_matches_now(self):
        now = datetime.now()
        expected = f"{now.year}-W{now.isocalendar()[1]:02d}"
        assert _current_week() == expected


# _load_prev_ranking

class TestLoadPrevRanking:
    def test_no_rankings_dir_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path / "nonexistent")
        assert _load_prev_ranking() == {}

    def test_empty_dir_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        assert _load_prev_ranking() == {}

    def test_loads_latest_yaml(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        for week in ["2026-W01", "2026-W02", "2026-W03"]:
            data = {
                "week": week,
                "rankings": [
                    {"person_id": f"p_{week}", "base_score": 0.5,
                     "composite": 0.6, "name": "X"},
                ],
            }
            (tmp_path / f"{week}.yaml").write_text(
                yaml.dump(data, allow_unicode=True), encoding="utf-8"
            )
        result = _load_prev_ranking()
        assert "p_2026-W03" in result
        assert result["p_2026-W03"]["composite"] == 0.6

    def test_handles_empty_yaml_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        (tmp_path / "2026-W01.yaml").write_text("", encoding="utf-8")
        assert _load_prev_ranking() == {}

    def test_handles_yaml_without_rankings_key(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        (tmp_path / "2026-W01.yaml").write_text(
            yaml.dump({"week": "2026-W01"}, allow_unicode=True),
            encoding="utf-8",
        )
        assert _load_prev_ranking() == {}

    def test_fallback_to_legacy_id_field(self, monkeypatch, tmp_path):
        """旧格式使用 _id 而非 person_id，应回退到 _id。"""
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        data = {
            "rankings": [
                {"_id": "legacy_p1", "base_score": 0.3, "composite": 0.4},
            ],
        }
        (tmp_path / "2026-W01.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )
        result = _load_prev_ranking()
        assert "legacy_p1" in result
        assert result["legacy_p1"]["base_score"] == 0.3

    def test_rank_field_is_index_plus_one(self, monkeypatch, tmp_path):
        """rank 字段是 index+1（按列表顺序）。"""
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        data = {
            "rankings": [
                {"person_id": "p1", "base_score": 0.5, "composite": 0.7},
                {"person_id": "p2", "base_score": 0.4, "composite": 0.6},
                {"person_id": "p3", "base_score": 0.3, "composite": 0.5},
            ],
        }
        (tmp_path / "2026-W01.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )
        result = _load_prev_ranking()
        assert result["p1"]["rank"] == 1
        assert result["p2"]["rank"] == 2
        assert result["p3"]["rank"] == 3


# _resolve_person_id / _resolve_person_name

class TestResolvePerson:
    def test_resolve_person_id_with_identity(self, tmp_db, setup_people):
        setup_people("person_alice", "Alice", "wxid_alice")
        pid = _resolve_person_id(tmp_db, "wxid_alice")
        assert pid == "person_alice"

    def test_resolve_person_id_fallback_to_hash(self, tmp_db):
        pid = _resolve_person_id(tmp_db, "wxid_nobody")
        expected = f"person_{hashlib.md5(b'wxid_nobody').hexdigest()[:8]}"
        assert pid == expected

    def test_resolve_person_name_with_identity(self, tmp_db, setup_people):
        setup_people("person_bob", "Bob", "wxid_bob")
        assert _resolve_person_name(tmp_db, "wxid_bob") == "Bob"

    def test_resolve_person_name_without_identity(self, tmp_db):
        assert _resolve_person_name(tmp_db, "wxid_nobody") is None


# compute_rankings

class TestComputeRankings:
    def test_empty_db_returns_empty_ranking(self, tmp_db, test_config, monkeypatch, tmp_path):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        ranking = compute_rankings(tmp_db, test_config)
        assert ranking.total_candidates == 0
        assert ranking.rankings == []
        assert ranking.insufficient_data == []
        assert ranking.week

    def test_single_contact_ranked(self, tmp_db, test_config, mock_metrics,
                                    monkeypatch, tmp_path, setup_contacts, insert_messages):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        setup_contacts("wxid_a", "Alice", display_name="Alice")
        for i in range(25):
            insert_messages("wxid_a", "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        assert ranking.total_candidates == 1
        assert len(ranking.rankings) == 1
        assert ranking.rankings[0].name == "Alice"
        assert ranking.rankings[0].rank == 1

    def test_insufficient_messages(self, tmp_db, test_config, mock_metrics,
                                    monkeypatch, tmp_path, setup_contacts, insert_messages):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        setup_contacts("wxid_a", "Alice", display_name="Alice")
        for i in range(5):
            insert_messages("wxid_a", "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        assert len(ranking.rankings) == 0
        assert len(ranking.insufficient_data) == 1
        assert ranking.insufficient_data[0].name == "Alice"
        assert ranking.insufficient_data[0].message_count == 5

    def test_ranking_sorted_by_composite_desc(self, tmp_db, test_config, mock_metrics,
                                               monkeypatch, tmp_path, setup_contacts, insert_messages):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        for wxid, name in [("wxid_a", "A"), ("wxid_b", "B"), ("wxid_c", "C")]:
            setup_contacts(wxid, name, display_name=name)
            for i in range(25):
                insert_messages(wxid, "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        assert len(ranking.rankings) == 3
        assert ranking.rankings[0].name == "A"
        assert ranking.rankings[1].name == "B"
        assert ranking.rankings[2].name == "C"
        assert ranking.rankings[0].rank == 1
        assert ranking.rankings[2].rank == 3

    def test_ranking_tiebreak_by_base_score(self, tmp_db, test_config, monkeypatch,
                                             tmp_path, setup_contacts, insert_messages):
        """composite 相同时按 base_score 降序。"""
        from engine.models.metrics import MetricValue, Metrics

        def _fake_tie(conn, config, wxid, name, **kwargs):
            score_map = {
                "wxid_x": (0.6, 0.7, "high"),
                "wxid_y": (0.4, 0.7, "medium"),
            }
            base, composite, signal = score_map.get(wxid, (0.1, 0.2, "low"))
            return Metrics(
                msg_count=MetricValue(raw=100, normalized=0.5, confidence=0.9, sample_size=100),
                base_score=base,
                composite=composite,
                signal_level=signal,
            )

        monkeypatch.setattr("engine.analyzers.ranker.compute_metrics_for_contact", _fake_tie)
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)

        for wxid, name in [("wxid_x", "X"), ("wxid_y", "Y")]:
            setup_contacts(wxid, name, display_name=name)
            for i in range(25):
                insert_messages(wxid, "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        assert ranking.rankings[0].name == "X"
        assert ranking.rankings[1].name == "Y"

    def test_delta_rank_calculation(self, tmp_db, test_config, mock_metrics,
                                     monkeypatch, tmp_path, setup_contacts,
                                     setup_people, insert_messages):
        """delta_rank = prev_rank - current_rank（上升为正）。"""
        setup_people("person_a", "Alice", "wxid_a")
        setup_people("person_b", "Bob", "wxid_b")

        prev_dir = tmp_path
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", prev_dir)
        prev_data = {
            "week": "2026-W01",
            "rankings": [
                {"person_id": "person_b", "base_score": 0.5, "composite": 0.9, "name": "Bob"},
                {"person_id": "person_a", "base_score": 0.5, "composite": 0.5, "name": "Alice"},
            ],
        }
        (prev_dir / "2026-W01.yaml").write_text(
            yaml.dump(prev_data, allow_unicode=True), encoding="utf-8"
        )

        for wxid, name in [("wxid_a", "Alice"), ("wxid_b", "Bob")]:
            setup_contacts(wxid, name, display_name=name)
            for i in range(25):
                insert_messages(wxid, "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        # mock_metrics: wxid_a composite=0.8, wxid_b composite=0.6
        # 本周：A 排第 1，B 排第 2
        # 上周：A 排第 2，B 排第 1
        a_rank = next(r for r in ranking.rankings if r.name == "Alice")
        b_rank = next(r for r in ranking.rankings if r.name == "Bob")
        assert a_rank.delta_rank == 1
        assert b_rank.delta_rank == -1

    def test_risers_detection_by_composite(self, tmp_db, test_config, mock_metrics,
                                            monkeypatch, tmp_path, setup_contacts,
                                            setup_people, insert_messages):
        """delta_composite >= 0.05 触发 riser，<= -0.05 触发 faller。"""
        setup_people("person_a", "Alice", "wxid_a")
        setup_people("person_b", "Bob", "wxid_b")

        prev_dir = tmp_path
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", prev_dir)
        # 上周 A composite=0.1（本周 0.8，delta=0.7 → riser）
        # 上周 B composite=0.9（本周 0.6，delta=-0.3 → faller）
        prev_data = {
            "rankings": [
                {"person_id": "person_b", "base_score": 0.5, "composite": 0.9},
                {"person_id": "person_a", "base_score": 0.5, "composite": 0.1},
            ],
        }
        (prev_dir / "2026-W01.yaml").write_text(
            yaml.dump(prev_data, allow_unicode=True), encoding="utf-8"
        )

        for wxid, name in [("wxid_a", "Alice"), ("wxid_b", "Bob")]:
            setup_contacts(wxid, name, display_name=name)
            for i in range(25):
                insert_messages(wxid, "wxid_me", f"m{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        riser_names = [r.name for r in ranking.risers]
        faller_names = [f.name for f in ranking.fallers]
        assert "Alice" in riser_names
        assert "Bob" in faller_names

    def test_total_candidates_count(self, tmp_db, test_config, mock_metrics,
                                     monkeypatch, tmp_path, setup_contacts, insert_messages):
        monkeypatch.setattr(ranker, "OUTPUTS_RANKINGS_DIR", tmp_path)
        setup_contacts("wxid_a", "Alice", display_name="Alice")
        setup_contacts("wxid_b", "Bob", display_name="Bob")
        for i in range(25):
            insert_messages("wxid_a", "wxid_me", f"a{i}", 1700000000 + i)
        for i in range(5):
            insert_messages("wxid_b", "wxid_me", f"b{i}", 1700000000 + i)

        ranking = compute_rankings(tmp_db, test_config)
        assert ranking.total_candidates == 2
        assert len(ranking.rankings) == 1
        assert len(ranking.insufficient_data) == 1


# get_coverage_info

class TestGetCoverageInfo:
    def test_empty_db_returns_none(self, tmp_db):
        assert get_coverage_info(tmp_db) is None

    def test_with_conversations(self, tmp_db):
        """有会话数据时返回覆盖率字符串。

        get_coverage_info 查询 conversations 表行数和 sync_state 表，
        conftest 未创建 sync_state 表，需手动创建。
        """
        # 创建 sync_state 表（conftest 未提供）
        tmp_db.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                session_id TEXT PRIMARY KEY,
                watermark INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_sync_at INTEGER NOT NULL,
                last_error TEXT
            )
        """)
        # 插入会话和同步状态
        tmp_db.execute(
            "INSERT OR IGNORE INTO conversations (id, type, display_name, contact_id, updated_at) "
            "VALUES (?, 'private', ?, ?, ?)",
            ("wxid_a", "Alice", "wxid_a", int(time.time())),
        )
        tmp_db.execute(
            "INSERT INTO sync_state (session_id, watermark, message_count, last_sync_at, last_error) "
            "VALUES (?, ?, ?, ?, NULL)",
            ("session_1", 100, 50, int(time.time())),
        )
        tmp_db.commit()
        result = get_coverage_info(tmp_db)
        assert result is not None
        assert "数据可信度" in result
        assert "会话覆盖率" in result

    def test_handles_missing_sync_state_table(self, tmp_db):
        """sync_state 表不存在时返回 None（异常捕获）。"""
        # conftest 未创建 sync_state 表，查询会抛异常被捕获
        # 但 conversations 表也为空，先返回 None（total_conv == 0）
        assert get_coverage_info(tmp_db) is None


# format_ranking_table

class TestFormatRankingTable:
    def test_empty_rankings_returns_placeholder(self):
        ranking = Ranking(week="2026-W01")
        out = format_ranking_table(ranking)
        assert "暂无排名数据" in out

    def test_basic_table(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_composite=0.1, delta_rank=0),
                RankedPerson(rank=2, name="Bob", base_score=0.5,
                             composite=0.6, signal_level="medium",
                             delta_composite=-0.05, delta_rank=-1),
            ],
        )
        out = format_ranking_table(ranking)
        assert "2026-W01" in out
        assert "Alice" in out
        assert "Bob" in out
        assert "high" in out
        assert "medium" in out

    def test_table_with_insufficient_data(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high"),
            ],
            insufficient_data=[
                InsufficientData(name="Charlie", message_count=5),
            ],
        )
        out = format_ranking_table(ranking)
        assert "Charlie" in out
        assert "数据不足" in out

    def test_table_with_tags(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             tags=["多账号(2)", "置顶"]),
            ],
        )
        out = format_ranking_table(ranking)
        assert "多账号(2)" in out
        assert "置顶" in out

    def test_table_with_coverage_info(self, tmp_db):
        """传入 conn 时附加覆盖率信息（需 sync_state 表）。"""
        # 创建 sync_state 表（conftest 未提供）
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
            ("session_1", 100, 50, int(time.time())),
        )
        tmp_db.commit()
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high"),
            ],
        )
        out = format_ranking_table(ranking, conn=tmp_db)
        assert "数据可信度" in out

    def test_trend_arrow_up(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_rank=2, delta_composite=0.1),
            ],
        )
        out = format_ranking_table(ranking)
        assert "↑2" in out

    def test_trend_arrow_down(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_rank=-3, delta_composite=0.1),
            ],
        )
        out = format_ranking_table(ranking)
        assert "↓3" in out

    def test_trend_arrow_neutral(self):
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_rank=0, delta_composite=0.1),
            ],
        )
        out = format_ranking_table(ranking)
        assert "→" in out

    def test_positive_delta_composite_has_plus_sign(self):
        """代码用 :.3f 格式化，delta=0.123 显示为 +0.123。"""
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_composite=0.123),
            ],
        )
        out = format_ranking_table(ranking)
        assert "+0.123" in out

    def test_negative_delta_composite_no_plus_sign(self):
        """负值不带 + 号，-0.123。"""
        ranking = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", base_score=0.7,
                             composite=0.8, signal_level="high",
                             delta_composite=-0.123),
            ],
        )
        out = format_ranking_table(ranking)
        assert "-0.123" in out
        assert "+-0.123" not in out


# Ranking 模型 round-trip

class TestRankingModelRoundTrip:
    def test_to_yaml_and_from_yaml_roundtrip(self):
        original = Ranking(
            week="2026-W01",
            generated_at="2026-01-01T00:00:00",
            total_candidates=2,
            rankings=[
                RankedPerson(rank=1, name="Alice", _id="p1", person_id="p1",
                             base_score=0.7, composite=0.8, signal_level="high",
                             stage="stage_3", delta_rank=1, delta_composite=0.1,
                             tags=["置顶"]),
                RankedPerson(rank=2, name="Bob", _id="p2", person_id="p2",
                             base_score=0.5, composite=0.6, signal_level="medium",
                             stage="stage_2", delta_rank=-1, delta_composite=-0.05,
                             tags=[]),
            ],
            risers=[RankingChange(name="Alice", reason="排名上升")],
            fallers=[RankingChange(name="Bob", reason="排名下降")],
            insufficient_data=[InsufficientData(name="Charlie", message_count=3)],
        )
        yaml_data = original.to_yaml()
        restored = Ranking.from_yaml(yaml_data)

        assert restored.week == "2026-W01"
        assert restored.generated_at == "2026-01-01T00:00:00"
        assert restored.total_candidates == 2
        assert len(restored.rankings) == 2
        assert restored.rankings[0].name == "Alice"
        assert restored.rankings[0].person_id == "p1"
        assert restored.rankings[0].base_score == 0.7
        assert restored.rankings[1].name == "Bob"
        assert len(restored.risers) == 1
        assert restored.risers[0].name == "Alice"
        assert len(restored.fallers) == 1
        assert len(restored.insufficient_data) == 1
        assert restored.insufficient_data[0].name == "Charlie"

    def test_to_yaml_round_trip_preserves_tags(self):
        original = Ranking(
            week="2026-W01",
            rankings=[
                RankedPerson(rank=1, name="Alice", person_id="p1",
                             tags=["多账号(2)", "置顶"]),
            ],
        )
        restored = Ranking.from_yaml(original.to_yaml())
        assert restored.rankings[0].tags == ["多账号(2)", "置顶"]

    def test_from_yaml_handles_legacy_id_field(self):
        """旧格式只有 _id 没有 person_id。"""
        data = {
            "week": "2026-W01",
            "rankings": [
                {"_id": "legacy_p1", "name": "X", "base_score": 0.5,
                 "composite": 0.6, "signal_level": "high"},
            ],
        }
        restored = Ranking.from_yaml(data)
        assert restored.rankings[0].person_id == "legacy_p1"
        assert restored.rankings[0]._id == "legacy_p1"

    def test_from_yaml_empty_rankings(self):
        data = {"week": "2026-W01"}
        restored = Ranking.from_yaml(data)
        assert restored.rankings == []
        assert restored.risers == []
        assert restored.fallers == []
        assert restored.insufficient_data == []
