"""engine/backtest/load_cases.py 单元测试。

覆盖：
- load_cases（YAML 文件加载，优先级 + fallback）
- get_retro_cases（retrospective.py 格式）
- get_ts_cases（timeseries.py 格式）
- get_annotated_cases（analyze_annotated.py 格式）
- get_validate_cases（validate.py 格式 + 默认前 3）
- get_test_slope_cases（前 4 个案例）
- get_test_slope_window_cases（前 6 个案例 + outcome 映射）
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch, mock_open
from unittest.mock import MagicMock

import pytest
import yaml

from engine.backtest.load_cases import (
    load_cases,
    get_retro_cases,
    get_ts_cases,
    get_annotated_cases,
    get_validate_cases,
    get_test_slope_cases,
    get_test_slope_window_cases,
)


# ═══════════════════════════════════════════════════════════════════
# 测试 fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_cases():
    """标准测试案例数据。"""
    return [
        {
            "wxid": "wxid_a1", "name": "Alice", "outcome": "success",
            "retro": {"key_date": "2026-01-15", "note": "成功案例"},
            "ts": {"start_date": "2025-10-01", "end_date": "2026-01-15", "note": "ts 测试"},
            "annotated": {"note": "已标注"},
            "validate": True,
        },
        {
            "wxid": "wxid_b2", "name": "Bob", "outcome": "failure",
            "retro": {"key_date": "2026-02-20", "note": "失败案例"},
            "ts": {"start_date": "2025-11-01", "end_date": "2026-02-20", "note": ""},
            "annotated": {"note": ""},
            "validate": True,
        },
        {
            "wxid": "wxid_c3", "name": "Carol", "outcome": "active_giveup",
            "retro": {"note": "无 key_date"},
            # 无 ts 字段
            "annotated": {"note": "放弃"},
            # 无 validate 字段
        },
        {
            "wxid": "wxid_d4", "name": "Dave", "outcome": "developing",
            "retro": {"key_date": "2026-03-01", "note": ""},
            "ts": {"start_date": "2026-01-01", "end_date": "2026-03-01"},
            "annotated": {"note": "发展中"},
        },
        {
            "wxid": "wxid_e5", "name": "Eve", "outcome": "success_to_failure",
            "retro": {"key_date": "2026-04-01"},
            "ts": {"start_date": "2025-12-01", "end_date": "2026-04-01", "note": "反转"},
            "annotated": {"note": ""},
        },
        {
            "wxid": "wxid_f6", "name": "Frank", "outcome": "success",
            "retro": {"note": ""},
            "ts": {"start_date": "2026-02-01", "end_date": "2026-05-01"},
            "annotated": {"note": ""},
        },
    ]


@pytest.fixture
def mock_load_cases(sample_cases):
    """mock load_cases 返回 sample_cases。"""
    with patch("engine.backtest.load_cases.load_cases", return_value=sample_cases):
        yield sample_cases


# ═══════════════════════════════════════════════════════════════════
# load_cases
# ═══════════════════════════════════════════════════════════════════

class TestLoadCases:
    """load_cases 从 YAML 文件加载案例。"""

    def test_loads_from_first_existing_file(self, monkeypatch, tmp_path):
        """优先加载第一个存在的文件（data/backtest/cases.yaml）。"""
        # 在 tmp_path 下创建真实文件结构
        bt_dir = tmp_path / "data" / "backtest"
        bt_dir.mkdir(parents=True)
        cases_data = {"cases": [{"wxid": "wxid_a", "name": "Alice", "outcome": "success"}]}
        (bt_dir / "cases.yaml").write_text(
            yaml.safe_dump(cases_data, allow_unicode=True), encoding="utf-8")
        # 改变工作目录到 tmp_path
        monkeypatch.chdir(tmp_path)

        result = load_cases()
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_a"
        assert result[0]["name"] == "Alice"

    def test_falls_back_to_sample_file(self, monkeypatch, tmp_path):
        """cases.yaml 不存在 → 加载 cases_sample.yaml。"""
        bt_dir = tmp_path / "data" / "backtest"
        bt_dir.mkdir(parents=True)
        cases_data = {"cases": [{"wxid": "wxid_sample", "name": "Sample", "outcome": "developing"}]}
        (bt_dir / "cases_sample.yaml").write_text(
            yaml.safe_dump(cases_data, allow_unicode=True), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_cases()
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_sample"

    def test_returns_empty_list_when_no_file_exists(self, monkeypatch, tmp_path):
        """无文件存在 → 返回空列表。"""
        monkeypatch.chdir(tmp_path)
        result = load_cases()
        assert result == []

    def test_returns_empty_list_when_cases_key_missing(self, monkeypatch, tmp_path):
        """YAML 无 cases 键 → 返回空列表。"""
        bt_dir = tmp_path / "data" / "backtest"
        bt_dir.mkdir(parents=True)
        (bt_dir / "cases.yaml").write_text("other_key: value\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_cases()
        assert result == []

    def test_priority_real_over_sample(self, monkeypatch, tmp_path):
        """cases.yaml 和 cases_sample.yaml 都存在 → 优先加载 cases.yaml。"""
        bt_dir = tmp_path / "data" / "backtest"
        bt_dir.mkdir(parents=True)
        real_data = {"cases": [{"wxid": "real", "name": "Real", "outcome": "success"}]}
        sample_data = {"cases": [{"wxid": "sample", "name": "Sample", "outcome": "failure"}]}
        (bt_dir / "cases.yaml").write_text(
            yaml.safe_dump(real_data, allow_unicode=True), encoding="utf-8")
        (bt_dir / "cases_sample.yaml").write_text(
            yaml.safe_dump(sample_data, allow_unicode=True), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_cases()
        assert len(result) == 1
        assert result[0]["wxid"] == "real"


# ═══════════════════════════════════════════════════════════════════
# get_retro_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetRetroCases:
    """get_retro_cases 返回 retrospective.py 格式。"""

    def test_returns_tuples_with_correct_fields(self, mock_load_cases):
        """返回 (wxid, name, outcome, key_date, note) 元组列表。"""
        result = get_retro_cases()
        assert len(result) == 6
        # 第 1 个：有 key_date
        wxid, name, outcome, key_date, note = result[0]
        assert wxid == "wxid_a1"
        assert name == "Alice"
        assert outcome == "success"
        assert isinstance(key_date, datetime)
        assert key_date == datetime(2026, 1, 15)
        assert note == "成功案例"

    def test_key_date_none_when_missing(self, mock_load_cases):
        """retro.key_date 缺失 → key_date=None。"""
        result = get_retro_cases()
        # 第 3 个：无 key_date
        wxid, name, outcome, key_date, note = result[2]
        assert wxid == "wxid_c3"
        assert key_date is None
        assert note == "无 key_date"

    def test_note_defaults_to_empty_string(self, mock_load_cases):
        """retro.note 缺失 → 空字符串。"""
        result = get_retro_cases()
        # 第 5 个：有 key_date 但 note 缺失
        wxid, name, outcome, key_date, note = result[4]
        assert wxid == "wxid_e5"
        assert key_date == datetime(2026, 4, 1)
        assert note == ""

    def test_key_date_parsed_correctly(self, mock_load_cases):
        """key_date 字符串被解析为 datetime 对象。"""
        result = get_retro_cases()
        _, _, _, key_date, _ = result[0]
        assert isinstance(key_date, datetime)
        assert key_date.year == 2026
        assert key_date.month == 1
        assert key_date.day == 15

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_retro_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_ts_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetTsCases:
    """get_ts_cases 返回 timeseries.py 格式。"""

    def test_returns_tuples_with_correct_fields(self, mock_load_cases):
        """返回 (wxid, name, outcome, start_date, end_date, note) 元组列表。"""
        result = get_ts_cases()
        # 案例 3 无 ts 字段 → 跳过，所以 5 个有 ts
        assert len(result) == 5
        wxid, name, outcome, start_dt, end_dt, note = result[0]
        assert wxid == "wxid_a1"
        assert name == "Alice"
        assert outcome == "success"
        assert isinstance(start_dt, datetime)
        assert isinstance(end_dt, datetime)
        assert start_dt == datetime(2025, 10, 1)
        assert end_dt == datetime(2026, 1, 15)
        assert note == "ts 测试"

    def test_case_without_ts_skipped(self, mock_load_cases):
        """无 ts 字段的案例被跳过。"""
        result = get_ts_cases()
        wxids = [r[0] for r in result]
        assert "wxid_c3" not in wxids  # Carol 无 ts 字段

    def test_case_with_missing_start_or_end_skipped(self, monkeypatch):
        """ts.start_date 或 ts.end_date 缺失 → 跳过。"""
        cases = [
            {"wxid": "wxid_a", "name": "A", "outcome": "success",
             "ts": {"start_date": "2026-01-01", "end_date": "2026-02-01"}},
            {"wxid": "wxid_b", "name": "B", "outcome": "failure",
             "ts": {"start_date": "2026-01-01"}},  # 缺 end_date
            {"wxid": "wxid_c", "name": "C", "outcome": "developing",
             "ts": {"end_date": "2026-02-01"}},  # 缺 start_date
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_ts_cases()
        assert len(result) == 1
        assert result[0][0] == "wxid_a"

    def test_note_defaults_to_empty_string(self, mock_load_cases):
        """ts.note 缺失 → 空字符串。"""
        result = get_ts_cases()
        # 第 4 个（Dave）无 note
        wxid, name, outcome, start_dt, end_dt, note = result[2]
        assert wxid == "wxid_d4"
        assert note == ""

    def test_dates_parsed_correctly(self, mock_load_cases):
        """start_date/end_date 字符串被解析为 datetime。"""
        result = get_ts_cases()
        _, _, _, start_dt, end_dt, _ = result[0]
        assert isinstance(start_dt, datetime)
        assert isinstance(end_dt, datetime)
        assert start_dt == datetime(2025, 10, 1)
        assert end_dt == datetime(2026, 1, 15)

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_ts_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_annotated_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetAnnotatedCases:
    """get_annotated_cases 返回 analyze_annotated.py 格式。"""

    def test_returns_tuples_with_correct_fields(self, mock_load_cases):
        """返回 (wxid, name, outcome, note) 元组列表。"""
        result = get_annotated_cases()
        assert len(result) == 6
        wxid, name, outcome, note = result[0]
        assert wxid == "wxid_a1"
        assert name == "Alice"
        assert outcome == "success"
        assert note == "已标注"

    def test_note_defaults_to_empty_string(self, monkeypatch):
        """annotated.note 缺失 → 空字符串。"""
        cases = [
            {"wxid": "wxid_a", "name": "A", "outcome": "success"},
            {"wxid": "wxid_b", "name": "B", "outcome": "failure",
             "annotated": {"note": "有标注"}},
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_annotated_cases()
        assert len(result) == 2
        assert result[0][3] == ""  # 第 1 个无 annotated
        assert result[1][3] == "有标注"

    def test_all_cases_included(self, mock_load_cases):
        """所有案例都被包含（不像 ts 那样跳过）。"""
        result = get_annotated_cases()
        assert len(result) == 6

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_annotated_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_validate_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetValidateCases:
    """get_validate_cases 返回 validate.py 格式。"""

    def test_returns_cases_with_validate_flag(self, mock_load_cases):
        """有 validate 字段的案例被返回。"""
        result = get_validate_cases()
        # Alice 和 Bob 有 validate=True
        assert len(result) == 2
        assert ("Alice", "wxid_a1") in result
        assert ("Bob", "wxid_b2") in result

    def test_returns_tuples_of_name_wxid(self, mock_load_cases):
        """返回 (name, wxid) 元组列表。"""
        result = get_validate_cases()
        for name, wxid in result:
            assert isinstance(name, str)
            assert isinstance(wxid, str)

    def test_falls_back_to_first_three_when_no_validate_flag(self, monkeypatch):
        """无 validate 字段 → 默认返回前 3 个。"""
        cases = [
            {"wxid": f"wxid_{i}", "name": f"Name{i}", "outcome": "success"}
            for i in range(5)
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_validate_cases()
        assert len(result) == 3
        assert result[0] == ("Name0", "wxid_0")
        assert result[1] == ("Name1", "wxid_1")
        assert result[2] == ("Name2", "wxid_2")

    def test_falls_back_to_all_when_fewer_than_three(self, monkeypatch):
        """案例少于 3 个 → 返回全部。"""
        cases = [
            {"wxid": "wxid_a", "name": "A", "outcome": "success"},
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_validate_cases()
        assert len(result) == 1
        assert result[0] == ("A", "wxid_a")

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_validate_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_test_slope_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetTestSlopeCases:
    """get_test_slope_cases 返回前 4 个案例。"""

    def test_returns_first_four_cases(self, mock_load_cases):
        """返回前 4 个 (name, wxid) 元组。"""
        result = get_test_slope_cases()
        assert len(result) == 4
        assert result[0] == ("Alice", "wxid_a1")
        assert result[1] == ("Bob", "wxid_b2")
        assert result[2] == ("Carol", "wxid_c3")
        assert result[3] == ("Dave", "wxid_d4")

    def test_returns_tuples_of_name_wxid(self, mock_load_cases):
        """返回 (name, wxid) 元组。"""
        result = get_test_slope_cases()
        for name, wxid in result:
            assert isinstance(name, str)
            assert isinstance(wxid, str)

    def test_fewer_than_four_returns_all(self, monkeypatch):
        """案例少于 4 个 → 返回全部。"""
        cases = [
            {"wxid": "wxid_a", "name": "A", "outcome": "success"},
            {"wxid": "wxid_b", "name": "B", "outcome": "failure"},
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_test_slope_cases()
        assert len(result) == 2

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_test_slope_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_test_slope_window_cases
# ═══════════════════════════════════════════════════════════════════

class TestGetTestSlopeWindowCases:
    """get_test_slope_window_cases 返回前 6 个案例 + outcome 映射。"""

    def test_returns_first_six_cases(self, mock_load_cases):
        """返回前 6 个 (name, wxid, outcome) 元组。"""
        result = get_test_slope_window_cases()
        assert len(result) == 6

    def test_outcome_mapping_success(self, mock_load_cases):
        """outcome='success' → 'success'。"""
        result = get_test_slope_window_cases()
        # Alice (index 0) 是 success
        name, wxid, outcome = result[0]
        assert name == "Alice"
        assert outcome == "success"

    def test_outcome_mapping_failure(self, mock_load_cases):
        """outcome='failure' → 'failure'。"""
        result = get_test_slope_window_cases()
        name, wxid, outcome = result[1]
        assert name == "Bob"
        assert outcome == "failure"

    def test_outcome_mapping_active_giveup(self, mock_load_cases):
        """outcome='active_giveup' → 'giveup'。"""
        result = get_test_slope_window_cases()
        name, wxid, outcome = result[2]
        assert name == "Carol"
        assert outcome == "giveup"

    def test_outcome_mapping_developing(self, mock_load_cases):
        """outcome='developing' → 'developing'。"""
        result = get_test_slope_window_cases()
        name, wxid, outcome = result[3]
        assert name == "Dave"
        assert outcome == "developing"

    def test_outcome_mapping_success_to_failure(self, mock_load_cases):
        """outcome='success_to_failure' → 's2f'。"""
        result = get_test_slope_window_cases()
        name, wxid, outcome = result[4]
        assert name == "Eve"
        assert outcome == "s2f"

    def test_unknown_outcome_passed_through(self, monkeypatch):
        """未知 outcome → 原样传递。"""
        cases = [
            {"wxid": "wxid_x", "name": "X", "outcome": "unknown_outcome"},
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_test_slope_window_cases()
        assert len(result) == 1
        name, wxid, outcome = result[0]
        assert outcome == "unknown_outcome"

    def test_returns_tuples_of_name_wxid_outcome(self, mock_load_cases):
        """返回 (name, wxid, outcome) 三元组。"""
        result = get_test_slope_window_cases()
        for name, wxid, outcome in result:
            assert isinstance(name, str)
            assert isinstance(wxid, str)
            assert isinstance(outcome, str)

    def test_fewer_than_six_returns_all(self, monkeypatch):
        """案例少于 6 个 → 返回全部。"""
        cases = [
            {"wxid": "wxid_a", "name": "A", "outcome": "success"},
            {"wxid": "wxid_b", "name": "B", "outcome": "failure"},
        ]
        with patch("engine.backtest.load_cases.load_cases", return_value=cases):
            result = get_test_slope_window_cases()
        assert len(result) == 2

    def test_empty_cases_returns_empty_list(self, monkeypatch):
        """空案例列表 → 空返回。"""
        with patch("engine.backtest.load_cases.load_cases", return_value=[]):
            result = get_test_slope_window_cases()
        assert result == []
