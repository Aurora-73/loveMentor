"""engine/backtest/calibrate.py 单元测试。

覆盖：
- load_calibration_log / save_calibration_log（YAML I/O）
- _get_slice_stage（切片阶段归属，calibrate.py 私有版本）
- compute_calibration_metrics（校准评估指标）
- leave_one_case_out_validation（留一验证）
- generate_calibration_candidates（生成校准候选值）
- validate_candidates_with_loco（用 LOCO 验证候选值）
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from engine.backtest.calibrate import (
    load_calibration_log,
    save_calibration_log,
    compute_calibration_metrics,
    _get_slice_stage,
    leave_one_case_out_validation,
    generate_calibration_candidates,
    validate_candidates_with_loco,
)


# ═══════════════════════════════════════════════════════════════════
# 测试 fixtures
# ═══════════════════════════════════════════════════════════════════

def make_slice(ref_date, composite=0.5, msg_count=20, neediness=1.0,
               signal_level="无信号", volume_ratio=1.0, initiation_ratio=0.5):
    """构造单个 time_slice 字典（与 test_analyze.py 相同结构）。"""
    return {
        "ref_date": ref_date,
        "composite": composite,
        "neediness_penalty": neediness,
        "signal_level": signal_level,
        "volume_ratio": volume_ratio,
        "initiation_ratio": initiation_ratio,
        "metrics": {
            "msg_count": {"raw": msg_count, "normalized": msg_count / 100},
            "fback": {"raw": 0.5, "normalized": 0.5},
        },
    }


@pytest.fixture
def case_config():
    """案例配置（带 stage_labels）。"""
    return {
        "id": "case_001",
        "display_name": "Alice",
        "outcome": "success",
        "outcome_date": "2026-01-15",
        "stage_labels": [
            {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01",
             "window_state": "cold", "risk_state": "low"},
            {"stage": "stage_2", "from": "2025-11-02", "to": "2025-12-15",
             "window_state": "warming", "risk_state": "low"},
            {"stage": "stage_3", "from": "2025-12-16", "to": "2026-01-15",
             "window_state": "hot", "risk_state": "high"},
        ],
    }


@pytest.fixture
def phase_a_data():
    """多案例 Phase A 数据（用于 calibrate 测试）。"""
    case_success = {
        "case_id": "case_001",
        "display_name": "Alice",
        "outcome": "success",
        "outcome_date": "2026-01-15",
        "started": "2025-10-01",
        "time_slices": [
            make_slice("2025-10-15", composite=0.40, msg_count=20),
            make_slice("2025-11-01", composite=0.45, msg_count=25),
            make_slice("2025-11-15", composite=0.50, msg_count=30),
            make_slice("2025-12-01", composite=0.55, msg_count=35),
        ],
    }
    case_failure = {
        "case_id": "case_002",
        "display_name": "Bob",
        "outcome": "failure",
        "outcome_date": "2026-01-20",
        "started": "2025-10-01",
        "time_slices": [
            make_slice("2025-10-15", composite=0.35, msg_count=20),
            make_slice("2025-11-01", composite=0.30, msg_count=25),
            make_slice("2025-11-15", composite=0.25, msg_count=30),
            make_slice("2025-12-01", composite=0.20, msg_count=35),
        ],
    }
    case_friendzone = {
        "case_id": "case_003",
        "display_name": "Carol",
        "outcome": "friendzone",
        "outcome_date": "2026-02-01",
        "started": "2025-10-01",
        "time_slices": [
            make_slice("2025-10-15", composite=0.30, msg_count=20),
            make_slice("2025-11-15", composite=0.32, msg_count=25),
        ],
    }
    return {
        "case_001": case_success,
        "case_002": case_failure,
        "case_003": case_friendzone,
    }


@pytest.fixture
def case_configs(case_config):
    """案例配置字典（按 case_id 索引）。"""
    case_b_config = {
        "id": "case_002",
        "display_name": "Bob",
        "outcome": "failure",
        "outcome_date": "2026-01-20",
        "stage_labels": [
            {"stage": "stage_1", "from": "2025-10-01", "to": "2025-12-01",
             "window_state": "cold", "risk_state": "high"},
        ],
    }
    case_c_config = {
        "id": "case_003",
        "display_name": "Carol",
        "outcome": "friendzone",
        "outcome_date": "2026-02-01",
        "stage_labels": [
            {"stage": "stage_1", "from": "2025-10-01", "to": "2026-02-01",
             "window_state": "cold", "risk_state": "low"},
        ],
    }
    return {
        "case_001": case_config,
        "case_002": case_b_config,
        "case_003": case_c_config,
    }


# ═══════════════════════════════════════════════════════════════════
# load_calibration_log / save_calibration_log
# ═══════════════════════════════════════════════════════════════════

class TestLoadSaveCalibrationLog:
    """load_calibration_log / save_calibration_log YAML I/O。"""

    def test_load_nonexistent_file_returns_empty(self, tmp_path, monkeypatch):
        """文件不存在 → 空列表。"""
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", tmp_path / "nonexistent.yaml")
        result = load_calibration_log()
        assert result == []

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """保存后加载 → 数据一致。"""
        log_path = tmp_path / "calibration_log.yaml"
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", log_path)

        entries = [
            {"date": "2026-01-01", "status": "pending", "candidates": []},
            {"date": "2026-01-15", "status": "applied", "candidates": [{"param": "test"}]},
        ]
        save_calibration_log(entries)
        assert log_path.exists()

        loaded = load_calibration_log()
        assert len(loaded) == 2
        assert loaded[0]["date"] == "2026-01-01"
        assert loaded[1]["status"] == "applied"

    def test_load_empty_file_returns_empty(self, tmp_path, monkeypatch):
        """空文件 → 空列表。"""
        log_path = tmp_path / "empty.yaml"
        log_path.write_text("", encoding="utf-8")
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", log_path)
        result = load_calibration_log()
        assert result == []

    def test_save_to_existing_directory(self, tmp_path, monkeypatch):
        """保存到已存在目录 → 成功。"""
        log_path = tmp_path / "log.yaml"
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", log_path)
        save_calibration_log([{"test": True}])
        assert log_path.exists()

    def test_save_empty_list(self, tmp_path, monkeypatch):
        """保存空列表 → 文件存在但内容为空。"""
        log_path = tmp_path / "log.yaml"
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", log_path)
        save_calibration_log([])
        assert log_path.exists()
        loaded = load_calibration_log()
        assert loaded == []

    def test_save_unicode_content(self, tmp_path, monkeypatch):
        """保存中文内容 → allow_unicode=True。"""
        log_path = tmp_path / "log.yaml"
        monkeypatch.setattr("engine.backtest.calibrate.CALIBRATION_LOG", log_path)
        entries = [{"param": "阈值", "reason": "失败案例从未触发"}]
        save_calibration_log(entries)
        content = log_path.read_text(encoding="utf-8")
        assert "阈值" in content
        assert "失败案例从未触发" in content


# ═══════════════════════════════════════════════════════════════════
# _get_slice_stage
# ═══════════════════════════════════════════════════════════════════

class TestGetSliceStage:
    """_get_slice_stage 切片阶段归属（calibrate.py 私有版本）。"""

    def test_date_in_stage(self, case_config):
        """日期在 stage 范围内 → 返回 stage 信息。"""
        result = _get_slice_stage("2025-10-15", case_config)
        assert result["stage"] == "stage_1"
        assert result["risk_state"] == "low"

    def test_date_outside_all_stages(self, case_config):
        """日期不在任何 stage 范围内 → None。"""
        assert _get_slice_stage("2025-09-01", case_config) is None

    def test_none_case_config(self):
        """case_config=None → None。"""
        assert _get_slice_stage("2025-10-15", None) is None

    def test_no_stage_labels_key(self):
        """case_config 缺 stage_labels 键 → None。"""
        assert _get_slice_stage("2025-10-15", {}) is None

    def test_stage_labels_not_in_case_config(self):
        """'stage_labels' not in case_config → None。"""
        case_config = {"id": "case_1"}  # 无 stage_labels
        assert _get_slice_stage("2025-10-15", case_config) is None

    def test_boundary_dates(self, case_config):
        """边界日期 → 属于该 stage（闭区间）。"""
        assert _get_slice_stage("2025-10-01", case_config)["stage"] == "stage_1"
        assert _get_slice_stage("2025-11-01", case_config)["stage"] == "stage_1"
        assert _get_slice_stage("2025-11-02", case_config)["stage"] == "stage_2"

    def test_missing_optional_fields(self):
        """stage_label 缺 window_state/risk_state → None。"""
        case_config = {
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01"},
            ],
        }
        result = _get_slice_stage("2025-10-15", case_config)
        assert result["stage"] == "stage_1"
        assert result["window_state"] is None
        assert result["risk_state"] is None

    def test_multiple_stages_returns_first_match(self):
        """多个 stage 重叠 → 返回第一个匹配。"""
        case_config = {
            "stage_labels": [
                {"stage": "stage_a", "from": "2025-10-01", "to": "2025-11-15",
                 "window_state": "a", "risk_state": "low"},
                {"stage": "stage_b", "from": "2025-11-01", "to": "2025-12-01",
                 "window_state": "b", "risk_state": "high"},
            ],
        }
        result = _get_slice_stage("2025-11-10", case_config)
        assert result["stage"] == "stage_a"


# ═══════════════════════════════════════════════════════════════════
# compute_calibration_metrics
# ═══════════════════════════════════════════════════════════════════

class TestComputeCalibrationMetrics:
    """compute_calibration_metrics 校准评估指标。"""

    def test_returns_dict(self, phase_a_data, case_configs):
        """返回字典。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        assert isinstance(result, dict)

    def test_overlap_ratio_present(self, phase_a_data, case_configs):
        """包含 overlap_ratio。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        assert "overlap_ratio" in result
        assert 0 <= result["overlap_ratio"] <= 1

    def test_composite_distribution_present(self, phase_a_data, case_configs):
        """包含 composite_distribution。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        assert "composite_distribution" in result
        dist = result["composite_distribution"]
        assert "count" in dist
        assert "min" in dist
        assert "max" in dist
        assert "range" in dist

    def test_stage_distribution_present(self, phase_a_data, case_configs):
        """包含 stage_distribution。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        assert "stage_distribution" in result

    def test_neediness_trigger_rate_present(self, phase_a_data, case_configs):
        """包含 neediness_trigger_rate。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        assert "neediness_trigger_rate" in result
        assert 0 <= result["neediness_trigger_rate"] <= 1

    def test_empty_data(self):
        """空数据 → 无 composite_distribution。"""
        result = compute_calibration_metrics({}, {})
        assert "overlap_ratio" in result
        assert result["overlap_ratio"] == 0.0
        # all_high_conf_slices 为空 → composite_distribution 不存在
        assert "composite_distribution" not in result

    def test_no_success_or_failure_cases(self, case_configs):
        """无 success/failure 案例 → overlap_ratio=0。"""
        case_data = {
            "case_001": {
                "display_name": "X", "outcome": "developing",
                "outcome_date": "2026-01-15",
                "time_slices": [make_slice("2025-10-15", msg_count=20)],
            },
        }
        result = compute_calibration_metrics(case_data, case_configs)
        assert result["overlap_ratio"] == 0.0

    def test_risk_composite_gap_present(self, phase_a_data, case_configs):
        """包含 risk_composite_gap（当有 high/low risk 切片时）。"""
        result = compute_calibration_metrics(phase_a_data, case_configs)
        # case_configs 中 case_002 有 risk_state=high，case_001/case_003 有 risk_state=low
        if "risk_composite_gap" in result:
            gap = result["risk_composite_gap"]
            assert "high_mean" in gap
            assert "low_mean" in gap
            assert "gap" in gap

    def test_overlap_calculation(self):
        """overlap_ratio 计算正确。"""
        # success composite 范围 [0.4, 0.6]
        # failure composite 范围 [0.2, 0.4]
        # 重叠区间 [0.4, 0.4] = 0 → overlap_ratio = 0
        case_success = {
            "display_name": "S", "outcome": "success", "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-01", composite=0.4, msg_count=20),
                make_slice("2025-11-01", composite=0.6, msg_count=20),
            ],
        }
        case_failure = {
            "display_name": "F", "outcome": "failure", "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-01", composite=0.2, msg_count=20),
                make_slice("2025-11-01", composite=0.4, msg_count=20),
            ],
        }
        result = compute_calibration_metrics(
            {"case_s": case_success, "case_f": case_failure}, {})
        # success [0.4, 0.6], failure [0.2, 0.4]
        # overlap_start = max(0.4, 0.2) = 0.4
        # overlap_end = min(0.6, 0.4) = 0.4
        # overlap_end > overlap_start? 0.4 > 0.4? False → overlap_ratio = 0
        assert result["overlap_ratio"] == 0.0


# ═══════════════════════════════════════════════════════════════════
# leave_one_case_out_validation
# ═══════════════════════════════════════════════════════════════════

class TestLeaveOneCaseOutValidation:
    """leave_one_case_out_validation 留一验证。"""

    def test_returns_tuple_of_results_and_error(self, phase_a_data, case_configs):
        """返回 (results, error) 元组。"""
        results, error = leave_one_case_out_validation(phase_a_data, case_configs)
        assert error is None
        assert isinstance(results, list)

    def test_single_case_returns_error(self, case_configs):
        """案例数 < 2 → 返回 (None, error_msg)。"""
        case_data = {
            "case_001": {
                "display_name": "Only", "outcome": "success",
                "outcome_date": "2026-01-15",
                "time_slices": [make_slice("2025-10-15", msg_count=20)],
            },
        }
        results, error = leave_one_case_out_validation(case_data, case_configs)
        assert results is None
        assert error is not None
        assert "不足" in error

    def test_empty_data_returns_error(self):
        """空数据 → 返回 (None, error)。"""
        results, error = leave_one_case_out_validation({}, {})
        assert results is None
        assert error is not None

    def test_n_folds_equals_n_cases(self, phase_a_data, case_configs):
        """折数等于案例数。"""
        results, error = leave_one_case_out_validation(phase_a_data, case_configs)
        assert error is None
        assert len(results) == len(phase_a_data)

    def test_result_contains_required_fields(self, phase_a_data, case_configs):
        """结果包含必需字段。"""
        results, error = leave_one_case_out_validation(phase_a_data, case_configs)
        for r in results:
            assert "leave_out_case" in r
            assert "leave_out_name" in r
            assert "leave_out_outcome" in r
            assert "training_cases" in r
            assert "train_overlap" in r
            assert "test_overlap" in r
            assert "train_risk_gap" in r
            assert "test_risk_gap" in r
            assert "improved" in r

    def test_training_cases_count(self, phase_a_data, case_configs):
        """training_cases = 总案例数 - 1。"""
        results, _ = leave_one_case_out_validation(phase_a_data, case_configs)
        n_cases = len(phase_a_data)
        for r in results:
            assert r["training_cases"] == n_cases - 1

    def test_improved_is_boolean(self, phase_a_data, case_configs):
        """improved 是布尔值。"""
        results, _ = leave_one_case_out_validation(phase_a_data, case_configs)
        for r in results:
            assert isinstance(r["improved"], bool)


# ═══════════════════════════════════════════════════════════════════
# generate_calibration_candidates
# ═══════════════════════════════════════════════════════════════════

class TestGenerateCalibrationCandidates:
    """generate_calibration_candidates 生成校准候选值。"""

    def test_returns_list(self, phase_a_data, case_configs):
        """返回列表。"""
        result = generate_calibration_candidates(phase_a_data, case_configs)
        assert isinstance(result, list)

    def test_empty_data_returns_empty(self):
        """空数据 → 空列表。"""
        result = generate_calibration_candidates({}, {})
        assert result == []

    def test_candidate_structure(self, phase_a_data, case_configs):
        """候选值结构正确（如果生成）。"""
        result = generate_calibration_candidates(phase_a_data, case_configs)
        for c in result:
            assert "param" in c
            assert "current" in c
            assert "candidate" in c
            assert "confidence" in c
            assert "reason" in c

    def test_low_trigger_rate_generates_candidate(self):
        """neediness 触发率低 → 生成 volume_ratio_threshold 候选。"""
        # 所有切片 neediness=1.0 → trigger_rate=0
        case_data = {
            "case_001": {
                "display_name": "Test", "outcome": "success",
                "outcome_date": "2026-01-15",
                "time_slices": [
                    make_slice("2025-10-01", msg_count=20, neediness=1.0, volume_ratio=1.4),
                    make_slice("2025-11-01", msg_count=20, neediness=1.0, volume_ratio=1.6),
                ],
            },
        }
        result = generate_calibration_candidates(case_data, {})
        # trigger_rate=0 < 0.1 → 应生成候选值
        vol_candidates = [c for c in result if "volume_ratio" in c["param"]]
        assert len(vol_candidates) >= 1

    def test_confidence_values(self, phase_a_data, case_configs):
        """confidence 值为 high/medium/low 之一。"""
        result = generate_calibration_candidates(phase_a_data, case_configs)
        valid_confidences = {"high", "medium", "low"}
        for c in result:
            assert c["confidence"] in valid_confidences


# ═══════════════════════════════════════════════════════════════════
# validate_candidates_with_loco
# ═══════════════════════════════════════════════════════════════════

class TestValidateCandidatesWithLoco:
    """validate_candidates_with_loco 用 LOCO 结果验证候选值。"""

    def test_empty_loco_returns_empty(self):
        """loco_results 为空 → 空列表。"""
        candidates = [{"param": "test", "current": "a", "candidate": "b"}]
        result = validate_candidates_with_loco(candidates, [])
        assert result == []

    def test_none_loco_returns_empty(self):
        """loco_results 为 None → 空列表。"""
        candidates = [{"param": "test"}]
        result = validate_candidates_with_loco(candidates, None)
        assert result == []

    def test_high_pass_rate_adds_confidence(self):
        """通过率 > 0.5 → 添加 loco_confidence。"""
        candidates = [{"param": "test", "current": "a", "candidate": "b"}]
        loco_results = [
            {"improved": True}, {"improved": True}, {"improved": False},
        ]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert len(result) == 1
        assert "loco_pass_rate" in result[0]
        assert "loco_confidence" in result[0]
        # 2/3 通过 → loco_confidence = "medium"（>= 0.5 但 < 0.7）
        assert result[0]["loco_confidence"] == "medium"

    def test_very_high_pass_rate(self):
        """通过率 >= 0.7 → loco_confidence = high。"""
        candidates = [{"param": "test"}]
        loco_results = [
            {"improved": True}, {"improved": True}, {"improved": True},
        ]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert result[0]["loco_confidence"] == "high"

    def test_low_pass_rate_adds_note(self):
        """通过率 <= 0.5 → loco_confidence = low + loco_note。"""
        candidates = [{"param": "test"}]
        loco_results = [
            {"improved": False}, {"improved": False}, {"improved": False},
        ]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert result[0]["loco_confidence"] == "low"
        assert "loco_note" in result[0]
        assert "留一验证未通过" in result[0]["loco_note"]

    def test_pass_rate_format(self):
        """loco_pass_rate 格式为 'passes/total'。"""
        candidates = [{"param": "test"}]
        loco_results = [{"improved": True}, {"improved": False}]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert result[0]["loco_pass_rate"] == "1/2"

    def test_multiple_candidates(self):
        """多个候选值都被处理。"""
        candidates = [
            {"param": "param1", "current": "a", "candidate": "b"},
            {"param": "param2", "current": "c", "candidate": "d"},
            {"param": "param3", "current": "e", "candidate": "f"},
        ]
        loco_results = [{"improved": True}, {"improved": True}]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert len(result) == 3
        for c in result:
            assert "loco_pass_rate" in c
            assert "loco_confidence" in c

    def test_empty_candidates_returns_empty(self):
        """候选值列表为空 → 空返回。"""
        loco_results = [{"improved": True}]
        result = validate_candidates_with_loco([], loco_results)
        assert result == []

    def test_preserves_original_candidate_fields(self):
        """保留候选值原有字段。"""
        candidates = [{
            "param": "test_param",
            "current": ">2.0",
            "candidate": ">1.3",
            "confidence": "high",
            "reason": "当前触发率过低",
        }]
        loco_results = [{"improved": True}, {"improved": True}]
        result = validate_candidates_with_loco(candidates, loco_results)
        assert result[0]["param"] == "test_param"
        assert result[0]["current"] == ">2.0"
        assert result[0]["candidate"] == ">1.3"
        assert result[0]["confidence"] == "high"
        assert result[0]["reason"] == "当前触发率过低"
