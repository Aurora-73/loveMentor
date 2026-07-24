"""engine/backtest/collect.py 单元测试。

覆盖：
- load_cases（带 case_filter 过滤）
- generate_time_slices（时间切片生成：主切片+事件对齐窗口）
- extract_event_dates（事件日期提取：stage_labels + key_events）
- get_slice_stage_label（切片阶段归属判断）
- compute_derived_labels（派生标签：距离/next_30d_outcome）

注意：collect.py 期望的 case 数据结构使用 id/started/outcome_date/display_name/
stage_labels/key_events 等字段，与 load_cases.py 返回的 wxid/name 结构不同。
本测试直接构造符合 collect.py 期望的 case 字典。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from engine.backtest.collect import (
    load_cases,
    generate_time_slices,
    extract_event_dates,
    get_slice_stage_label,
    compute_derived_labels,
)


# ═══════════════════════════════════════════════════════════════════
# 测试 fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_case():
    """标准测试案例（collect.py 期望的数据结构）。"""
    return {
        "id": "case_001",
        "display_name": "Alice",
        "outcome": "success",
        "started": "2025-10-01",
        "outcome_date": "2026-01-15",
        "stage_labels": [
            {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01",
             "window_state": "cold", "risk_state": "low"},
            {"stage": "stage_2", "from": "2025-11-02", "to": "2025-12-15",
             "window_state": "warming", "risk_state": "low"},
            {"stage": "stage_3", "from": "2025-12-16", "to": "2026-01-15",
             "window_state": "hot", "risk_state": "high"},
        ],
        "key_events": [
            {"date": "2025-11-10", "event": "first_date"},
            {"date": "2025-12-25", "event": "christmas_together"},
        ],
    }


@pytest.fixture
def minimal_case():
    """最简案例（无 stage_labels/key_events）。"""
    return {
        "id": "case_min",
        "display_name": "Bob",
        "outcome": "failure",
        "started": "2025-12-01",
        "outcome_date": "2026-01-01",
    }


# ═══════════════════════════════════════════════════════════════════
# load_cases
# ═══════════════════════════════════════════════════════════════════

class TestLoadCases:
    """load_cases 包装 _load_cases + 按 id 过滤。"""

    def test_no_filter_returns_all(self):
        """无 case_filter → 返回全部。"""
        mock_cases = [
            {"id": "case_001", "display_name": "Alice"},
            {"id": "case_002", "display_name": "Bob"},
        ]
        with patch("engine.backtest.collect._load_cases", return_value=mock_cases):
            result = load_cases()
        assert len(result) == 2
        assert result[0]["id"] == "case_001"

    def test_filter_matching_case(self):
        """case_filter 匹配 → 只返回该案例。"""
        mock_cases = [
            {"id": "case_001", "display_name": "Alice"},
            {"id": "case_002", "display_name": "Bob"},
            {"id": "case_003", "display_name": "Carol"},
        ]
        with patch("engine.backtest.collect._load_cases", return_value=mock_cases):
            result = load_cases(case_filter="case_002")
        assert len(result) == 1
        assert result[0]["id"] == "case_002"
        assert result[0]["display_name"] == "Bob"

    def test_filter_no_match_returns_empty(self):
        """case_filter 不匹配 → 空列表。"""
        mock_cases = [{"id": "case_001", "display_name": "Alice"}]
        with patch("engine.backtest.collect._load_cases", return_value=mock_cases):
            result = load_cases(case_filter="nonexistent")
        assert result == []

    def test_filter_empty_list(self):
        """空案例列表 + filter → 空列表。"""
        with patch("engine.backtest.collect._load_cases", return_value=[]):
            result = load_cases(case_filter="anything")
        assert result == []

    def test_no_filter_empty_list(self):
        """空案例列表 + 无 filter → 空列表。"""
        with patch("engine.backtest.collect._load_cases", return_value=[]):
            result = load_cases()
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# generate_time_slices
# ═══════════════════════════════════════════════════════════════════

class TestGenerateTimeSlices:
    """generate_time_slices 生成时间切片（主切片+事件对齐窗口）。"""

    def test_basic_slices_14_days(self, minimal_case):
        """默认 14 天间隔 → 主切片。"""
        slices = generate_time_slices(minimal_case)
        # 2025-12-01 → 2026-01-01 = 31 天
        # 主切片：12-01, 12-15, 12-29, 01-01（最后补齐 outcome_date）
        assert len(slices) >= 3
        assert slices[0] == datetime(2025, 12, 1)
        assert slices[-1] == datetime(2026, 1, 1)

    def test_custom_slice_days(self, minimal_case):
        """自定义 slice_days=7。"""
        slices = generate_time_slices(minimal_case, slice_days=7)
        # 间隔 7 天 → 切片更多
        assert len(slices) >= 4
        assert slices[0] == datetime(2025, 12, 1)

    def test_outcome_date_always_included(self, minimal_case):
        """outcome_date 总是包含在切片中。"""
        slices = generate_time_slices(minimal_case, slice_days=14)
        assert datetime(2026, 1, 1) in slices

    def test_started_date_first(self, minimal_case):
        """started 是第一个切片。"""
        slices = generate_time_slices(minimal_case)
        assert slices[0] == datetime(2025, 12, 1)

    def test_slices_are_sorted(self, minimal_case):
        """切片按时间升序排列。"""
        slices = generate_time_slices(minimal_case)
        for i in range(len(slices) - 1):
            assert slices[i] <= slices[i + 1]

    def test_slices_are_unique(self, minimal_case):
        """切片无重复。"""
        slices = generate_time_slices(minimal_case)
        assert len(slices) == len(set(slices))

    def test_short_range_single_slice(self):
        """started == outcome_date → 至少 1 个切片。"""
        case = {
            "id": "case_short",
            "display_name": "Short",
            "outcome": "success",
            "started": "2026-01-01",
            "outcome_date": "2026-01-01",
        }
        slices = generate_time_slices(case)
        assert len(slices) >= 1
        assert slices[0] == datetime(2026, 1, 1)

    def test_event_aligned_slices_included(self, sample_case):
        """事件对齐切片（±7/14/30 天）被加入。"""
        slices = generate_time_slices(sample_case, slice_days=14)
        # key_events: 2025-11-10, 2025-12-25
        # 事件对齐切片包括 2025-11-10 + [-30, -14, -7, 0, 7, 14, 30] = 
        # 10-11, 10-27, 11-03, 11-10, 11-17, 11-24, 12-10
        # 2025-12-25 + 同样 offset = 11-25, 12-11, 12-18, 12-25, 01-01, 01-08, 01-24
        # 但必须在 started(10-01) 到 outcome_date(01-15) 范围内
        # 验证事件日期本身被加入
        assert datetime(2025, 11, 10) in slices
        assert datetime(2025, 12, 25) in slices
        # 验证事件对齐切片（如 +7 天）被加入
        assert datetime(2025, 11, 17) in slices  # 11-10 + 7
        assert datetime(2026, 1, 1) in slices  # 12-25 + 7

    def test_event_aligned_outside_range_excluded(self, sample_case):
        """事件对齐切片超出 started-outcome_date 范围 → 排除。"""
        slices = generate_time_slices(sample_case, slice_days=14)
        # 2025-11-10 - 30 = 2025-10-11，应在范围内（started=10-01）
        assert datetime(2025, 10, 11) in slices
        # 2025-12-25 + 30 = 2026-01-24，超出 outcome_date(01-15) → 排除
        assert datetime(2026, 1, 24) not in slices

    def test_no_stage_labels_no_event_slices(self, minimal_case):
        """无 key_events 和 stage_labels → 主切片 + outcome_date 对齐切片。

        注意：extract_event_dates 总是返回 outcome_date，所以 outcome_date 会被
        作为事件生成 ±7/14/30 天对齐切片。
        """
        slices = generate_time_slices(minimal_case, slice_days=14)
        # 主切片：12-01, 12-15, 12-29, 01-01（4 个）
        # outcome_date=01-01 作为事件 → ±7/14/30 天对齐：
        #   01-01-30=12-02, 01-01-14=12-18, 01-01-7=12-25, 01-01+0=01-01(已有),
        #   01-01+7=01-08(超出 outcome), 01-01+14=01-15(超出), 01-01+30=01-31(超出)
        #   12-02, 12-18, 12-25 是新增切片
        # 所以总切片数 >= 4，且包含 12-25
        assert datetime(2025, 12, 1) in slices
        assert datetime(2026, 1, 1) in slices
        assert datetime(2025, 12, 25) in slices  # 01-01 - 7 天
        assert datetime(2025, 12, 18) in slices  # 01-01 - 14 天

    def test_stage_label_dates_extracted_as_events(self, sample_case):
        """stage_labels 的 from/to 边界日期被作为事件日期提取。"""
        event_dates = extract_event_dates(sample_case)
        # stage_labels from/to: 2025-10-01, 2025-11-01, 2025-11-02, 2025-12-15, 2025-12-16, 2026-01-15
        # key_events: 2025-11-10, 2025-12-25
        # outcome_date: 2026-01-15
        assert datetime(2025, 10, 1) in event_dates
        assert datetime(2025, 11, 1) in event_dates
        assert datetime(2025, 12, 15) in event_dates
        assert datetime(2026, 1, 15) in event_dates


# ═══════════════════════════════════════════════════════════════════
# extract_event_dates
# ═══════════════════════════════════════════════════════════════════

class TestExtractEventDates:
    """extract_event_dates 提取关键事件日期（stage_labels + key_events + outcome_date）。"""

    def test_returns_sorted_list(self, sample_case):
        """返回排序后的日期列表。"""
        dates = extract_event_dates(sample_case)
        for i in range(len(dates) - 1):
            assert dates[i] < dates[i + 1]

    def test_outcome_date_always_included(self, sample_case):
        """outcome_date 总是被包含。"""
        dates = extract_event_dates(sample_case)
        assert datetime(2026, 1, 15) in dates

    def test_stage_label_boundaries_included(self, sample_case):
        """stage_labels 的 from/to 被包含。"""
        dates = extract_event_dates(sample_case)
        assert datetime(2025, 10, 1) in dates   # stage_1 from
        assert datetime(2025, 11, 1) in dates   # stage_1 to
        assert datetime(2025, 11, 2) in dates   # stage_2 from
        assert datetime(2025, 12, 15) in dates  # stage_2 to
        assert datetime(2025, 12, 16) in dates  # stage_3 from
        assert datetime(2026, 1, 15) in dates   # stage_3 to

    def test_key_events_included(self, sample_case):
        """key_events 的 date 被包含。"""
        dates = extract_event_dates(sample_case)
        assert datetime(2025, 11, 10) in dates
        assert datetime(2025, 12, 25) in dates

    def test_no_stage_labels(self, minimal_case):
        """无 stage_labels → 只有 outcome_date。"""
        dates = extract_event_dates(minimal_case)
        assert dates == [datetime(2026, 1, 1)]

    def test_no_key_events(self):
        """无 key_events → 只有 stage_labels + outcome_date。"""
        case = {
            "id": "case_no_keys",
            "display_name": "NoKeys",
            "outcome": "success",
            "started": "2025-10-01",
            "outcome_date": "2026-01-15",
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01"},
            ],
        }
        dates = extract_event_dates(case)
        assert datetime(2025, 10, 1) in dates
        assert datetime(2025, 11, 1) in dates
        assert datetime(2026, 1, 15) in dates

    def test_duplicates_removed(self):
        """重复日期被去重（set 处理）。"""
        case = {
            "id": "case_dup",
            "display_name": "Dup",
            "outcome": "success",
            "started": "2025-10-01",
            "outcome_date": "2026-01-15",  # 与 stage_labels to 重复
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2026-01-15"},
            ],
            "key_events": [
                {"date": "2026-01-15", "event": "same_as_outcome"},  # 重复
            ],
        }
        dates = extract_event_dates(case)
        # 2026-01-15 只出现一次
        assert dates.count(datetime(2026, 1, 15)) == 1

    def test_empty_case_returns_outcome_only(self):
        """只有 outcome_date 的最简 case。"""
        case = {
            "outcome_date": "2026-01-01",
        }
        dates = extract_event_dates(case)
        assert dates == [datetime(2026, 1, 1)]

    def test_returns_datetime_objects(self, sample_case):
        """返回值是 datetime 对象。"""
        dates = extract_event_dates(sample_case)
        for d in dates:
            assert isinstance(d, datetime)


# ═══════════════════════════════════════════════════════════════════
# get_slice_stage_label
# ═══════════════════════════════════════════════════════════════════

class TestGetSliceStageLabel:
    """get_slice_stage_label 根据 stage_labels 判断切片阶段归属。"""

    def test_date_in_first_stage(self, sample_case):
        """日期在 stage_1 范围内 → 返回 stage_1。"""
        result = get_slice_stage_label("2025-10-15", sample_case)
        assert result is not None
        assert result["stage"] == "stage_1"
        assert result["window_state"] == "cold"
        assert result["risk_state"] == "low"

    def test_date_in_second_stage(self, sample_case):
        """日期在 stage_2 范围内 → 返回 stage_2。"""
        result = get_slice_stage_label("2025-11-15", sample_case)
        assert result is not None
        assert result["stage"] == "stage_2"
        assert result["window_state"] == "warming"

    def test_date_in_third_stage(self, sample_case):
        """日期在 stage_3 范围内 → 返回 stage_3。"""
        result = get_slice_stage_label("2025-12-31", sample_case)
        assert result is not None
        assert result["stage"] == "stage_3"
        assert result["risk_state"] == "high"

    def test_date_on_stage_boundary_from(self, sample_case):
        """日期等于 stage from 边界 → 属于该 stage（闭区间）。"""
        result = get_slice_stage_label("2025-11-02", sample_case)
        assert result is not None
        assert result["stage"] == "stage_2"

    def test_date_on_stage_boundary_to(self, sample_case):
        """日期等于 stage to 边界 → 属于该 stage（闭区间）。"""
        result = get_slice_stage_label("2025-11-01", sample_case)
        assert result is not None
        assert result["stage"] == "stage_1"

    def test_date_outside_all_stages(self, sample_case):
        """日期不在任何 stage 范围内 → None。"""
        # 2025-09-01 在 started 之前
        result = get_slice_stage_label("2025-09-01", sample_case)
        assert result is None

    def test_date_after_outcome(self, sample_case):
        """日期在 outcome_date 之后 → None。"""
        result = get_slice_stage_label("2026-06-01", sample_case)
        assert result is None

    def test_no_stage_labels_returns_none(self, minimal_case):
        """无 stage_labels → None。"""
        result = get_slice_stage_label("2025-12-15", minimal_case)
        assert result is None

    def test_empty_stage_labels(self):
        """stage_labels 为空列表 → None。"""
        case = {"stage_labels": [], "outcome_date": "2026-01-01"}
        result = get_slice_stage_label("2025-12-15", case)
        assert result is None

    def test_missing_window_state_field(self):
        """stage_label 缺少 window_state → 返回 None（.get 处理）。"""
        case = {
            "outcome_date": "2026-01-01",
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2025-11-01"},
                # 无 window_state 和 risk_state
            ],
        }
        result = get_slice_stage_label("2025-10-15", case)
        assert result is not None
        assert result["stage"] == "stage_1"
        assert result["window_state"] is None
        assert result["risk_state"] is None

    def test_first_matching_stage_returned(self):
        """多个 stage 重叠时 → 返回第一个匹配的。"""
        case = {
            "outcome_date": "2026-01-01",
            "stage_labels": [
                {"stage": "stage_a", "from": "2025-10-01", "to": "2025-11-15",
                 "window_state": "a", "risk_state": "low"},
                {"stage": "stage_b", "from": "2025-11-01", "to": "2025-12-01",
                 "window_state": "b", "risk_state": "high"},
            ],
        }
        # 2025-11-10 同时在两个 stage 范围内，应返回第一个（stage_a）
        result = get_slice_stage_label("2025-11-10", case)
        assert result["stage"] == "stage_a"


# ═══════════════════════════════════════════════════════════════════
# compute_derived_labels
# ═══════════════════════════════════════════════════════════════════

class TestComputeDerivedLabels:
    """compute_derived_labels 计算派生标签（距离/next_30d_outcome）。"""

    def test_distance_to_outcome_far(self, sample_case):
        """距 outcome_date 较远 + stage_1 risk_state=low → likely_success。"""
        result = compute_derived_labels("2025-10-15", sample_case)
        # 2025-10-15 距 2026-01-15 = 92 天 > 30
        # stage_1 (10-01 to 11-01) risk_state=low → likely_success
        assert result["distance_to_outcome_days"] > 30
        assert result["next_30d_outcome"] == "likely_success"

    def test_distance_to_outcome_within_30_days(self, sample_case):
        """距 outcome_date ≤30 天 → next_30d_outcome=case['outcome']。"""
        # 2025-12-20 → 2026-01-15 = 26 天
        result = compute_derived_labels("2025-12-20", sample_case)
        assert result["distance_to_outcome_days"] == 26
        assert result["next_30d_outcome"] == "success"

    def test_distance_to_outcome_exactly_30_days(self, sample_case):
        """距 outcome_date 恰好 30 天 → next_30d_outcome=case['outcome']。"""
        # 2025-12-16 → 2026-01-15 = 30 天
        result = compute_derived_labels("2025-12-16", sample_case)
        assert result["distance_to_outcome_days"] == 30
        assert result["next_30d_outcome"] == "success"

    def test_distance_to_outcome_zero(self, sample_case):
        """日期等于 outcome_date → 距离 0，next_30d_outcome=outcome。"""
        result = compute_derived_labels("2026-01-15", sample_case)
        assert result["distance_to_outcome_days"] == 0
        assert result["next_30d_outcome"] == "success"

    def test_distance_to_outcome_negative(self, sample_case):
        """日期在 outcome_date 之后 → 负距离。"""
        # 2026-02-01 → 2026-01-15 = -17 天
        result = compute_derived_labels("2026-02-01", sample_case)
        assert result["distance_to_outcome_days"] == -17

    def test_next_30d_outcome_high_risk(self, sample_case):
        """距离 >30 天 + risk_state=high → likely_failure。"""
        # 2025-12-20 在 stage_3（risk_state=high），但距离=26天 ≤30 → 直接 outcome
        # 需要找 >30 天且 high risk 的日期
        # stage_3 从 2025-12-16 开始，2025-12-16 距离 30 天，2025-12-15 距离 31 天但在 stage_2
        # 构造一个特殊 case
        case = {
            "id": "case_risk",
            "display_name": "Risk",
            "outcome": "developing",
            "started": "2025-10-01",
            "outcome_date": "2026-02-15",
            "stage_labels": [
                {"stage": "stage_risk", "from": "2025-10-01", "to": "2025-12-31",
                 "window_state": "risky", "risk_state": "high"},
            ],
        }
        # 2025-11-01 距离 2026-02-15 = 106 天 > 30
        result = compute_derived_labels("2025-11-01", case)
        assert result["distance_to_outcome_days"] > 30
        assert result["next_30d_outcome"] == "likely_failure"

    def test_next_30d_outcome_low_risk(self):
        """距离 >30 天 + risk_state=low → likely_success。"""
        case = {
            "id": "case_low",
            "display_name": "Low",
            "outcome": "developing",
            "started": "2025-10-01",
            "outcome_date": "2026-02-15",
            "stage_labels": [
                {"stage": "stage_safe", "from": "2025-10-01", "to": "2025-12-31",
                 "window_state": "safe", "risk_state": "low"},
            ],
        }
        result = compute_derived_labels("2025-11-01", case)
        assert result["distance_to_outcome_days"] > 30
        assert result["next_30d_outcome"] == "likely_success"

    def test_next_30d_outcome_no_risk_state(self, minimal_case):
        """距离 >30 天 + 无 stage_labels → next_30d_outcome=None。"""
        # minimal_case: 2025-12-01 → 2026-01-01 = 31 天
        result = compute_derived_labels("2025-12-01", minimal_case)
        assert result["distance_to_outcome_days"] == 31
        assert result["next_30d_outcome"] is None

    def test_next_30d_outcome_no_risk_state_field(self):
        """距离 >30 天 + stage_label 缺 risk_state → next_30d_outcome=None。"""
        case = {
            "id": "case_no_risk",
            "display_name": "NoRisk",
            "outcome": "developing",
            "started": "2025-10-01",
            "outcome_date": "2026-02-15",
            "stage_labels": [
                {"stage": "stage_1", "from": "2025-10-01", "to": "2025-12-31"},
                # 无 risk_state
            ],
        }
        result = compute_derived_labels("2025-11-01", case)
        assert result["distance_to_outcome_days"] > 30
        assert result["next_30d_outcome"] is None

    def test_distance_to_next_event_found(self, sample_case):
        """存在未来事件 → distance_to_next_event_days 为正数。"""
        # 事件日期：10-01, 11-01, 11-02, 11-10, 12-15, 12-16, 12-25, 01-15
        # 切片日期 2025-11-05 → 下一个事件是 11-10 → 5 天
        result = compute_derived_labels("2025-11-05", sample_case)
        assert result["distance_to_next_event_days"] == 5

    def test_distance_to_next_event_on_event_date(self, sample_case):
        """切片日期等于事件日期 → 距离 0。"""
        # 2025-11-10 是事件日期
        result = compute_derived_labels("2025-11-10", sample_case)
        assert result["distance_to_next_event_days"] == 0

    def test_distance_to_next_event_after_all_events(self, sample_case):
        """切片日期在所有事件之后 → 找不到未来事件 → None。"""
        # 2026-02-01 在所有事件之后
        result = compute_derived_labels("2026-02-01", sample_case)
        # 没有未来事件，distance_to_next_event_days 保持 None
        assert result["distance_to_next_event_days"] is None

    def test_distance_to_next_event_returns_first_future(self, sample_case):
        """返回第一个未来事件距离（不是最近的）。"""
        # 切片 2025-11-09 → 下一个事件是 11-10 (1 天)，不是 12-15 (36 天)
        result = compute_derived_labels("2025-11-09", sample_case)
        assert result["distance_to_next_event_days"] == 1

    def test_returns_dict_with_three_keys(self, sample_case):
        """返回字典包含 3 个键。"""
        result = compute_derived_labels("2025-11-15", sample_case)
        assert "distance_to_outcome_days" in result
        assert "next_30d_outcome" in result
        assert "distance_to_next_event_days" in result
        assert len(result) == 3

    def test_distance_to_outcome_days_is_int(self, sample_case):
        """distance_to_outcome_days 是 int 类型。"""
        result = compute_derived_labels("2025-11-15", sample_case)
        assert isinstance(result["distance_to_outcome_days"], int)
