"""engine/backtest/analyze.py 单元测试。

覆盖：
- filter_high_confidence_slices（按 msg_count 过滤切片）
- get_slice_stage_label（切片阶段归属判断，analyze.py 版本）
- analyze_case_timeline（案例内时序分析）
- analyze_composite_diagnosis（composite 公式诊断）
- analyze_neediness_audit（neediness_penalty 专项审计）
- analyze_signal_lead_lag（信号领先/滞后分析）
- analyze_cross_case_patterns（跨案例模式归纳）
- generate_calibration_report（生成校准报告）
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from engine.backtest.analyze import (
    filter_high_confidence_slices,
    get_slice_stage_label,
    analyze_case_timeline,
    analyze_composite_diagnosis,
    analyze_neediness_audit,
    analyze_signal_lead_lag,
    analyze_cross_case_patterns,
    generate_calibration_report,
)


# ═══════════════════════════════════════════════════════════════════
# 测试 fixtures
# ═══════════════════════════════════════════════════════════════════

def make_slice(ref_date, composite=0.5, msg_count=20, neediness=1.0,
               fback=0.5, signal_level="无信号", volume_ratio=1.0,
               initiation_ratio=0.5):
    """构造单个 time_slice 字典。"""
    return {
        "ref_date": ref_date,
        "composite": composite,
        "neediness_penalty": neediness,
        "signal_level": signal_level,
        "volume_ratio": volume_ratio,
        "initiation_ratio": initiation_ratio,
        "metrics": {
            "msg_count": {"raw": msg_count, "normalized": msg_count / 100},
            "fback": {"raw": fback, "normalized": fback},
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
def case_data():
    """单个案例的采集数据（Phase A 格式）。"""
    return {
        "case_id": "case_001",
        "display_name": "Alice",
        "outcome": "success",
        "outcome_date": "2026-01-15",
        "started": "2025-10-01",
        "time_slices": [
            make_slice("2025-10-15", composite=0.30, msg_count=15, fback=0.4),
            make_slice("2025-11-01", composite=0.35, msg_count=20, fback=0.45),
            make_slice("2025-11-15", composite=0.40, msg_count=25, fback=0.50),
            make_slice("2025-12-01", composite=0.45, msg_count=30, fback=0.55),
            make_slice("2025-12-15", composite=0.50, msg_count=35, fback=0.60),
            make_slice("2025-12-31", composite=0.55, msg_count=40, fback=0.65),
        ],
    }


@pytest.fixture
def phase_a_data(case_data):
    """多个案例的 Phase A 数据。"""
    case_b = {
        "case_id": "case_002",
        "display_name": "Bob",
        "outcome": "failure",
        "outcome_date": "2026-01-20",
        "started": "2025-10-01",
        "time_slices": [
            make_slice("2025-10-15", composite=0.40, msg_count=15, fback=0.5),
            make_slice("2025-11-01", composite=0.38, msg_count=20, fback=0.45),
            make_slice("2025-11-15", composite=0.35, msg_count=25, fback=0.40),
            make_slice("2025-12-01", composite=0.30, msg_count=30, fback=0.35),
        ],
    }
    return {"case_001": case_data, "case_002": case_b}


@pytest.fixture
def phase_b_data():
    """Phase B 数据（公式层，包含 rounds）。"""
    return {
        "case_001": {
            "case_id": "case_001",
            "display_name": "Alice",
            "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [
                {
                    "ref_date": "2025-10-15",
                    "rounds": [
                        {"name": "default", "action": {"action": "进攻"}},
                        {"name": "truth", "action": {"action": "进攻"}},
                    ],
                },
                {
                    "ref_date": "2025-11-01",
                    "rounds": [
                        {"name": "default", "action": {"action": "进攻"}},
                        {"name": "truth", "action": {"action": "进攻（谨慎）"}},
                    ],
                },
            ],
        },
    }


# ═══════════════════════════════════════════════════════════════════
# filter_high_confidence_slices
# ═══════════════════════════════════════════════════════════════════

class TestFilterHighConfidenceSlices:
    """filter_high_confidence_slices 按 msg_count 过滤切片。"""

    def test_filters_low_message_slices(self):
        """msg_count < 10 的切片被过滤。"""
        slices = [
            make_slice("2025-10-01", msg_count=5),   # 过滤
            make_slice("2025-10-15", msg_count=15),  # 保留
            make_slice("2025-11-01", msg_count=8),   # 过滤
            make_slice("2025-11-15", msg_count=20),  # 保留
        ]
        result = filter_high_confidence_slices(slices)
        assert len(result) == 2
        assert result[0]["ref_date"] == "2025-10-15"
        assert result[1]["ref_date"] == "2025-11-15"

    def test_custom_min_messages(self):
        """自定义 min_messages 阈值。"""
        slices = [
            make_slice("2025-10-01", msg_count=10),
            make_slice("2025-10-15", msg_count=20),
            make_slice("2025-11-01", msg_count=30),
        ]
        result = filter_high_confidence_slices(slices, min_messages=25)
        assert len(result) == 1
        assert result[0]["ref_date"] == "2025-11-01"

    def test_boundary_min_messages(self):
        """msg_count == min_messages → 保留（>=）。"""
        slices = [make_slice("2025-10-01", msg_count=10)]
        result = filter_high_confidence_slices(slices, min_messages=10)
        assert len(result) == 1

    def test_empty_slices(self):
        """空切片列表 → 空返回。"""
        assert filter_high_confidence_slices([]) == []

    def test_all_filtered(self):
        """所有切片都低于阈值 → 空返回。"""
        slices = [make_slice("2025-10-01", msg_count=1) for _ in range(5)]
        assert filter_high_confidence_slices(slices) == []

    def test_all_kept(self):
        """所有切片都高于阈值 → 全部保留。"""
        slices = [make_slice(f"2025-10-{i:02d}", msg_count=50) for i in range(1, 4)]
        result = filter_high_confidence_slices(slices)
        assert len(result) == 3

    def test_missing_msg_count_field(self):
        """切片缺少 metrics.msg_count → 当作 0 处理。"""
        slices = [{"ref_date": "2025-10-01", "metrics": {}}]
        result = filter_high_confidence_slices(slices, min_messages=10)
        assert result == []

    def test_missing_metrics_field(self):
        """切片缺少 metrics 字段 → 当作 0 处理。"""
        slices = [{"ref_date": "2025-10-01"}]
        result = filter_high_confidence_slices(slices, min_messages=10)
        assert result == []

    def test_missing_raw_in_msg_count(self):
        """msg_count 字典缺 raw → 当作 0 处理。"""
        slices = [{"ref_date": "2025-10-01", "metrics": {"msg_count": {}}}]
        result = filter_high_confidence_slices(slices, min_messages=10)
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# get_slice_stage_label (analyze.py 版本)
# ═══════════════════════════════════════════════════════════════════

class TestGetSliceStageLabel:
    """analyze.py 的 get_slice_stage_label（不读 outcome_date）。"""

    def test_date_in_stage(self, case_config):
        """日期在 stage 范围内 → 返回 stage 信息。"""
        result = get_slice_stage_label("2025-10-15", case_config)
        assert result["stage"] == "stage_1"
        assert result["window_state"] == "cold"

    def test_date_outside_all_stages(self, case_config):
        """日期不在任何 stage 范围内 → None。"""
        assert get_slice_stage_label("2025-09-01", case_config) is None

    def test_none_case_config(self):
        """case_config=None → None。"""
        assert get_slice_stage_label("2025-10-15", None) is None

    def test_no_stage_labels_key(self):
        """case_config 缺 stage_labels 键 → None。"""
        assert get_slice_stage_label("2025-10-15", {}) is None

    def test_empty_stage_labels(self):
        """stage_labels 为空 → None。"""
        case_config = {"stage_labels": []}
        assert get_slice_stage_label("2025-10-15", case_config) is None

    def test_boundary_dates(self, case_config):
        """边界日期 → 属于该 stage（闭区间）。"""
        assert get_slice_stage_label("2025-10-01", case_config)["stage"] == "stage_1"
        assert get_slice_stage_label("2025-11-01", case_config)["stage"] == "stage_1"
        assert get_slice_stage_label("2025-11-02", case_config)["stage"] == "stage_2"

    def test_missing_optional_fields(self):
        """stage_label 缺 window_state/risk_state → None。"""
        case_config = {
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01"},
            ],
        }
        result = get_slice_stage_label("2025-10-15", case_config)
        assert result["stage"] == "stage_1"
        assert result["window_state"] is None
        assert result["risk_state"] is None


# ═══════════════════════════════════════════════════════════════════
# analyze_case_timeline
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeCaseTimeline:
    """analyze_case_timeline 案例内时序分析。"""

    def test_returns_dict_with_required_keys(self, case_data, case_config):
        """返回字典包含必需的键。"""
        result = analyze_case_timeline(case_data, case_config)
        assert result is not None
        assert "display_name" in result
        assert "outcome" in result
        assert "timeline" in result
        assert "early_warnings" in result
        assert "metrics_eval" in result
        assert "slices_count" in result

    def test_empty_slices_returns_none(self, case_config):
        """所有切片 msg_count < 10 → None。"""
        case_data = {
            "display_name": "Empty",
            "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [make_slice("2025-10-01", msg_count=5)],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert result is None

    def test_timeline_sorted_by_ref_date(self, case_data, case_config):
        """timeline 按 ref_date 排序。"""
        result = analyze_case_timeline(case_data, case_config)
        dates = [t["ref_date"] for t in result["timeline"]]
        assert dates == sorted(dates)

    def test_timeline_includes_stage_info(self, case_data, case_config):
        """timeline 包含 stage 信息。"""
        result = analyze_case_timeline(case_data, case_config)
        for t in result["timeline"]:
            assert "stage" in t
            assert "window_state" in t
            assert "risk_state" in t

    def test_no_case_config_stage_none(self, case_data):
        """无 case_config → stage/window_state/risk_state 为 None。"""
        result = analyze_case_timeline(case_data, None)
        for t in result["timeline"]:
            assert t["stage"] is None

    def test_composite_trend_rising(self, case_data, case_config):
        """composite 上升趋势。"""
        # case_data 的 composite 从 0.30 → 0.55，明显上升
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["composite"]["has_trend"] is True
        assert result["metrics_eval"]["composite"]["trend_direction"] == "上升"

    def test_composite_trend_falling(self, case_config):
        """composite 下降趋势。"""
        case_data = {
            "display_name": "Decline",
            "outcome": "failure",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-15", composite=0.55, msg_count=20, fback=0.7),
                make_slice("2025-11-01", composite=0.50, msg_count=20, fback=0.65),
                make_slice("2025-11-15", composite=0.45, msg_count=20, fback=0.60),
                make_slice("2025-12-01", composite=0.40, msg_count=20, fback=0.55),
                make_slice("2025-12-15", composite=0.35, msg_count=20, fback=0.50),
                make_slice("2025-12-31", composite=0.30, msg_count=20, fback=0.45),
            ],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["composite"]["has_trend"] is True
        assert result["metrics_eval"]["composite"]["trend_direction"] == "下降"

    def test_composite_no_trend_flat(self, case_config):
        """composite 全程平坦 → 无趋势。"""
        case_data = {
            "display_name": "Flat",
            "outcome": "developing",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-15", composite=0.50, msg_count=20, fback=0.50),
                make_slice("2025-11-01", composite=0.51, msg_count=20, fback=0.50),
                make_slice("2025-11-15", composite=0.50, msg_count=20, fback=0.50),
                make_slice("2025-12-01", composite=0.50, msg_count=20, fback=0.50),
            ],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["composite"]["has_trend"] is False

    def test_neediness_ever_triggered(self, case_config):
        """neediness 曾触发。"""
        case_data = {
            "display_name": "Needy",
            "outcome": "failure",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-15", composite=0.5, msg_count=20, neediness=0.8),
                make_slice("2025-11-01", composite=0.5, msg_count=20, neediness=1.0),
            ],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["neediness"]["ever_triggered"] is True
        assert len(result["metrics_eval"]["neediness"]["trigger_points"]) == 1

    def test_neediness_never_triggered(self, case_data, case_config):
        """neediness 从未触发（全 1.0）。"""
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["neediness"]["ever_triggered"] is False

    def test_early_warnings_detected(self, case_config):
        """检测到早期预警（composite 下降 > 0.05）。"""
        case_data = {
            "display_name": "Warning",
            "outcome": "failure",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-15", composite=0.60, msg_count=20, fback=0.6),
                make_slice("2025-11-15", composite=0.50, msg_count=20, fback=0.5),  # composite 下降 0.10
                make_slice("2025-12-15", composite=0.40, msg_count=20, fback=0.4),  # composite 下降 0.10
            ],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert len(result["early_warnings"]) >= 1

    def test_insufficient_slices_no_trend(self, case_config):
        """切片数 < 3 → 无趋势分析。"""
        case_data = {
            "display_name": "FewSlices",
            "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-15", composite=0.3, msg_count=20),
                make_slice("2025-11-15", composite=0.6, msg_count=20),
            ],
        }
        result = analyze_case_timeline(case_data, case_config)
        assert result["metrics_eval"]["composite"]["has_trend"] is False

    def test_slices_count_matches(self, case_data, case_config):
        """slices_count 等于 timeline 长度。"""
        result = analyze_case_timeline(case_data, case_config)
        assert result["slices_count"] == len(result["timeline"])


# ═══════════════════════════════════════════════════════════════════
# analyze_composite_diagnosis
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeCompositeDiagnosis:
    """analyze_composite_diagnosis composite 公式诊断。"""

    def test_returns_dict_with_required_keys(self, phase_a_data):
        """返回字典包含必需的键。"""
        result = analyze_composite_diagnosis(phase_a_data)
        assert "composite_distribution" in result
        assert "neediness_audit" in result
        assert "signal_level_analysis" in result
        assert "issues" in result
        assert "summary" in result

    def test_summary_calculated(self, phase_a_data):
        """summary 包含 count/min/max/percentile。"""
        result = analyze_composite_diagnosis(phase_a_data)
        summary = result["summary"]
        assert summary["count"] > 0
        assert "min" in summary
        assert "p25" in summary
        assert "p50" in summary
        assert "p75" in summary
        assert "max" in summary

    def test_composite_distribution_by_group(self, phase_a_data):
        """composite_distribution 按 outcome 分组。"""
        result = analyze_composite_diagnosis(phase_a_data)
        # phase_a_data 有 success 和 failure 两组
        assert "success" in result["composite_distribution"]
        assert "failure" in result["composite_distribution"]

    def test_empty_phase_a_data(self):
        """空数据 → summary 为空字典（issues 可能含空组检查警告）。"""
        result = analyze_composite_diagnosis({})
        assert result["summary"] == {}
        # 空数据时，neediness_audit 和 signal_level_analysis 为空字典
        # 但代码会检查这些空字典并添加 issue（如"失败组从未触发"）
        assert isinstance(result["issues"], list)

    def test_unknown_outcome_skipped(self):
        """未知 outcome 的案例被跳过。"""
        case_data = {
            "case_id": "case_x",
            "display_name": "X",
            "outcome": "unknown_outcome",  # 不在 4 个已知组中
            "outcome_date": "2026-01-15",
            "time_slices": [make_slice("2025-10-15", msg_count=20)],
        }
        result = analyze_composite_diagnosis({"case_x": case_data})
        # 无已知 outcome → composite_distribution 为空
        assert result["composite_distribution"] == {}

    def test_neediness_audit_in_result(self, phase_a_data):
        """neediness_audit 包含分组触发率。"""
        result = analyze_composite_diagnosis(phase_a_data)
        # 至少有一个组的 neediness audit
        # phase_a_data 的 neediness 都是 1.0，所以 triggered=0
        for group, audit in result["neediness_audit"].items():
            assert "count" in audit
            assert "triggered" in audit
            assert "trigger_rate" in audit

    def test_signal_level_analysis(self, phase_a_data):
        """signal_level_analysis 包含分布。"""
        result = analyze_composite_diagnosis(phase_a_data)
        for group, analysis in result["signal_level_analysis"].items():
            assert "count" in analysis
            assert "distribution" in analysis
            assert "most_common" in analysis

    def test_issues_list(self, phase_a_data):
        """issues 是列表。"""
        result = analyze_composite_diagnosis(phase_a_data)
        assert isinstance(result["issues"], list)

    def test_overlap_issue_detected(self):
        """成功/失败组 composite 重叠 → 添加 issue。"""
        case_success = {
            "display_name": "Success", "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [make_slice("2025-10-15", composite=0.5, msg_count=20)],
        }
        case_failure = {
            "display_name": "Failure", "outcome": "failure",
            "outcome_date": "2026-01-15",
            "time_slices": [make_slice("2025-10-15", composite=0.5, msg_count=20)],
        }
        result = analyze_composite_diagnosis({
            "case_s": case_success, "case_f": case_failure,
        })
        # composite 重叠 → 应有 issue
        assert len(result["issues"]) >= 1


# ═══════════════════════════════════════════════════════════════════
# analyze_neediness_audit
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeNeedinessAudit:
    """analyze_neediness_audit neediness_penalty 专项审计。"""

    def test_returns_dict_with_required_keys(self, phase_a_data):
        """返回字典包含必需的键。"""
        result = analyze_neediness_audit(phase_a_data)
        assert "total_slices" in result
        assert "min_penalty" in result
        assert "max_penalty" in result
        assert "triggered_count" in result
        assert "trigger_rate" in result
        assert "case_detail" in result
        assert "volume_ratio_distribution" in result
        assert "initiation_ratio_distribution" in result

    def test_empty_data(self):
        """空数据 → total_slices=0。"""
        result = analyze_neediness_audit({})
        assert result["total_slices"] == 0
        assert result["trigger_rate"] == 0

    def test_trigger_rate_calculation(self):
        """触发率计算正确。"""
        case_data = {
            "display_name": "Test", "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-01", msg_count=20, neediness=0.8),  # 触发
                make_slice("2025-10-15", msg_count=20, neediness=1.0),  # 未触发
                make_slice("2025-11-01", msg_count=20, neediness=0.9),  # 触发
                make_slice("2025-11-15", msg_count=20, neediness=1.0),  # 未触发
            ],
        }
        result = analyze_neediness_audit({"case_1": case_data})
        assert result["total_slices"] == 4
        assert result["triggered_count"] == 2
        assert result["trigger_rate"] == 0.5

    def test_volume_ratio_distribution(self, phase_a_data):
        """volume_ratio_distribution 包含 pct_gt_2/15/13。"""
        result = analyze_neediness_audit(phase_a_data)
        vol = result["volume_ratio_distribution"]
        assert "pct_gt_2" in vol
        assert "pct_gt_15" in vol
        assert "pct_gt_13" in vol

    def test_initiation_ratio_distribution(self, phase_a_data):
        """initiation_ratio_distribution 包含 pct_gt_07/06。"""
        result = analyze_neediness_audit(phase_a_data)
        init = result["initiation_ratio_distribution"]
        assert "pct_gt_07" in init
        assert "pct_gt_06" in init

    def test_case_detail_per_case(self, phase_a_data):
        """case_detail 按案例 ID 分组。"""
        result = analyze_neediness_audit(phase_a_data)
        assert "case_001" in result["case_detail"]
        assert "case_002" in result["case_detail"]
        for case_id, detail in result["case_detail"].items():
            assert "display_name" in detail
            assert "outcome" in detail
            assert "trigger_rate" in detail

    def test_min_max_penalty(self):
        """min_penalty/max_penalty 正确。"""
        case_data = {
            "display_name": "Test", "outcome": "success",
            "outcome_date": "2026-01-15",
            "time_slices": [
                make_slice("2025-10-01", msg_count=20, neediness=0.7),
                make_slice("2025-10-15", msg_count=20, neediness=0.9),
                make_slice("2025-11-01", msg_count=20, neediness=1.0),
            ],
        }
        result = analyze_neediness_audit({"case_1": case_data})
        assert result["min_penalty"] == 0.7
        assert result["max_penalty"] == 1.0


# ═══════════════════════════════════════════════════════════════════
# analyze_signal_lead_lag
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeSignalLeadLag:
    """analyze_signal_lead_lag 信号领先/滞后分析。"""

    def test_returns_list(self, phase_a_data, phase_b_data):
        """返回列表。"""
        result = analyze_signal_lead_lag(phase_a_data, phase_b_data)
        assert isinstance(result, list)

    def test_case_without_phase_b_skipped(self, phase_a_data, phase_b_data):
        """无 Phase B 数据的案例被跳过。"""
        # phase_a_data 有 case_001 和 case_002，phase_b_data 只有 case_001
        result = analyze_signal_lead_lag(phase_a_data, phase_b_data)
        # 只返回 case_001 的结果
        assert len(result) == 1
        assert result[0]["case_id"] == "case_001"

    def test_result_contains_required_fields(self, phase_a_data, phase_b_data):
        """结果包含必需字段。"""
        result = analyze_signal_lead_lag(phase_a_data, phase_b_data)
        for r in result:
            assert "case_id" in r
            assert "display_name" in r
            assert "outcome" in r
            assert "first_correct_date" in r
            assert "lead_days" in r
            assert "correct_signal" in r
            assert "rounds_differ" in r

    def test_success_outcome_expected_actions(self, phase_a_data, phase_b_data):
        """success outcome 的正确行动是'进攻'类。"""
        result = analyze_signal_lead_lag(phase_a_data, phase_b_data)
        # case_001 是 success，rounds 都是"进攻"，应首次就正确
        success_result = next(r for r in result if r["outcome"] == "success")
        assert success_result["first_correct_date"] is not None

    def test_empty_data(self):
        """空数据 → 空列表。"""
        assert analyze_signal_lead_lag({}, {}) == []

    def test_rounds_differ_detected(self, phase_a_data, phase_b_data):
        """检测 default 和 truth round 是否不同。"""
        result = analyze_signal_lead_lag(phase_a_data, phase_b_data)
        # case_001 的 2025-11-01 切片 default="进攻", truth="进攻（谨慎）"
        assert any(r["rounds_differ"] for r in result)


# ═══════════════════════════════════════════════════════════════════
# analyze_cross_case_patterns
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeCrossCasePatterns:
    """analyze_cross_case_patterns 跨案例模式归纳。"""

    def test_returns_list(self, phase_a_data, phase_b_data, case_config):
        """返回列表。"""
        case_configs = {"case_001": case_config}
        result = analyze_cross_case_patterns(phase_a_data, phase_b_data, case_configs)
        assert isinstance(result, list)

    def test_result_contains_required_fields(self, phase_a_data, phase_b_data, case_config):
        """结果包含必需字段。"""
        case_configs = {"case_001": case_config}
        result = analyze_cross_case_patterns(phase_a_data, phase_b_data, case_configs)
        for p in result:
            assert "case_id" in p
            assert "display_name" in p
            assert "outcome" in p
            assert "composite_trend" in p
            assert "fback_trend" in p
            assert "neediness_triggered" in p
            assert "early_warnings_count" in p
            assert "lead_days" in p

    def test_empty_data(self):
        """空数据 → 空列表。"""
        assert analyze_cross_case_patterns({}, {}, {}) == []

    def test_case_without_phase_b(self, phase_a_data, case_config):
        """无 Phase B 的案例 → lead_days=None。"""
        case_configs = {"case_001": case_config, "case_002": case_config}
        result = analyze_cross_case_patterns(phase_a_data, {}, case_configs)
        # case_002 无 phase_b → lead_days=None
        case_002 = next(p for p in result if p["case_id"] == "case_002")
        assert case_002["lead_days"] is None


# ═══════════════════════════════════════════════════════════════════
# generate_calibration_report
# ═══════════════════════════════════════════════════════════════════

class TestGenerateCalibrationReport:
    """generate_calibration_report 生成校准报告。"""

    def test_returns_markdown_string(self, phase_a_data, phase_b_data, case_config):
        """返回 Markdown 字符串。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert isinstance(report, str)
        assert len(report) > 0

    def test_report_has_title(self, phase_a_data, phase_b_data, case_config):
        """报告包含标题。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert "# 回测校准报告" in report

    def test_report_has_sections(self, phase_a_data, phase_b_data, case_config):
        """报告包含 6 个主要 section。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert "## 一、案例内时序分析" in report
        assert "## 二、composite公式诊断" in report
        assert "## 三、neediness_penalty专项审计" in report
        assert "## 四、信号领先/滞后分析" in report
        assert "## 五、跨案例模式归纳" in report
        assert "## 六、校准建议" in report

    def test_report_includes_case_name(self, phase_a_data, phase_b_data, case_config):
        """报告包含案例名称。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert "Alice" in report

    def test_report_includes_metadata(self, phase_a_data, phase_b_data, case_config):
        """报告包含元数据（生成时间/案例数/切片数）。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert "生成时间" in report
        assert "案例数" in report
        assert "切片数" in report

    def test_empty_data_report(self):
        """空数据 → 仍生成报告（可能为空 section）。"""
        report = generate_calibration_report({}, {}, {})
        assert "# 回测校准报告" in report

    def test_report_includes_analysis_method_note(self, phase_a_data, phase_b_data, case_config):
        """报告包含分析方法说明。"""
        case_configs = {"case_001": case_config}
        report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
        assert "案例内时序分析" in report
        assert "不做推断统计" in report
