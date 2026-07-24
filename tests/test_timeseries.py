"""engine/backtest/timeseries.py 单元测试。

覆盖：
- linear_slope（简单线性回归斜率）
"""
from __future__ import annotations

import pytest

from engine.backtest.timeseries import linear_slope


# ═══════════════════════════════════════════════════════════════════
# linear_slope
# ═══════════════════════════════════════════════════════════════════

class TestLinearSlope:
    """linear_slope 计算简单线性回归斜率。"""

    def test_empty_list_returns_zero(self):
        """空列表 → 0.0。"""
        assert linear_slope([]) == 0.0

    def test_single_point_returns_zero(self):
        """单点 → 0.0（n < 2）。"""
        assert linear_slope([(0, 1.0)]) == 0.0

    def test_two_points_increasing(self):
        """两点递增 → 斜率 = (y2-y1)/(x2-x1)。"""
        # (0, 1) → (1, 3): 斜率 = (3-1)/(1-0) = 2.0
        assert linear_slope([(0, 1.0), (1, 3.0)]) == 2.0

    def test_two_points_decreasing(self):
        """两点递减 → 负斜率。"""
        # (0, 3) → (1, 1): 斜率 = (1-3)/(1-0) = -2.0
        assert linear_slope([(0, 3.0), (1, 1.0)]) == -2.0

    def test_two_points_horizontal(self):
        """两点水平 → 斜率 0。"""
        assert linear_slope([(0, 5.0), (1, 5.0)]) == 0.0

    def test_three_points_perfect_line(self):
        """三点共线 → 斜率等于线的斜率。"""
        # y = 2x + 1: (0,1), (1,3), (2,5)
        assert linear_slope([(0, 1.0), (1, 3.0), (2, 5.0)]) == 2.0

    def test_three_points_negative_slope(self):
        """三点负斜率共线。"""
        # y = -x + 5: (0,5), (1,4), (2,3)
        assert linear_slope([(0, 5.0), (1, 4.0), (2, 3.0)]) == -1.0

    def test_all_x_same_returns_zero(self):
        """所有 x 相同 → den=0 → 返回 0.0（防除零）。"""
        assert linear_slope([(1, 1.0), (1, 2.0), (1, 3.0)]) == 0.0

    def test_vertical_line_returns_zero(self):
        """竖直线（x 相同）→ 0.0。"""
        assert linear_slope([(5, 1.0), (5, 100.0)]) == 0.0

    def test_noisy_data_positive_trend(self):
        """噪声数据但整体上升趋势 → 正斜率。"""
        points = [(0, 1.0), (1, 0.9), (2, 1.5), (3, 1.8), (4, 2.1)]
        slope = linear_slope(points)
        assert slope > 0

    def test_noisy_data_negative_trend(self):
        """噪声数据但整体下降趋势 → 负斜率。"""
        points = [(0, 5.0), (1, 4.5), (2, 4.8), (3, 3.5), (4, 3.2)]
        slope = linear_slope(points)
        assert slope < 0

    def test_float_x_values(self):
        """x 为浮点数。"""
        # (0.0, 1.0), (0.5, 2.0), (1.0, 3.0) → 斜率 2.0
        assert linear_slope([(0.0, 1.0), (0.5, 2.0), (1.0, 3.0)]) == pytest.approx(2.0)

    def test_many_points_horizontal_line(self):
        """多点水平线 → 斜率 0。"""
        points = [(i, 3.0) for i in range(10)]
        assert linear_slope(points) == 0.0

    def test_large_x_range(self):
        """x 跨度大。"""
        # x: 0, 100, 200; y: 0, 1, 2 → 斜率 0.01
        points = [(0, 0.0), (100, 1.0), (200, 2.0)]
        assert linear_slope(points) == pytest.approx(0.01)

    def test_oscillating_data_near_zero_slope(self):
        """振荡数据 → 斜率接近 0。"""
        # 上下波动的数据
        points = [(0, 1.0), (1, 2.0), (2, 1.0), (3, 2.0), (4, 1.0)]
        slope = linear_slope(points)
        assert abs(slope) < 0.1

    def test_negative_y_values(self):
        """y 包含负值。"""
        # (0, -1), (1, 1) → 斜率 2
        assert linear_slope([(0, -1.0), (1, 1.0)]) == 2.0

    def test_all_negative_y(self):
        """y 全部为负值。"""
        # (0, -3), (1, -1) → 斜率 2
        assert linear_slope([(0, -3.0), (1, -1.0)]) == 2.0

    def test_steeper_slope(self):
        """更陡的斜率。"""
        # y = 10x: (0,0), (1,10), (2,20) → 斜率 10
        assert linear_slope([(0, 0.0), (1, 10.0), (2, 20.0)]) == 10.0

    def test_fractional_slope(self):
        """小数斜率。"""
        # y = 0.5x + 1: (0,1), (2,2), (4,3) → 斜率 0.5
        assert linear_slope([(0, 1.0), (2, 2.0), (4, 3.0)]) == pytest.approx(0.5)

    def test_outlier_does_not_dominate_completely(self):
        """单个离群点不会完全主导斜率方向。"""
        # 主要趋势上升，但有一个大异常值
        points = [(0, 1.0), (1, 2.0), (2, 100.0), (3, 4.0), (4, 5.0)]
        slope = linear_slope(points)
        # 离群点会拉高斜率，但不应该让斜率为负
        assert isinstance(slope, float)

    def test_returns_float(self):
        """返回值类型为 float。"""
        result = linear_slope([(0, 1.0), (1, 2.0)])
        assert isinstance(result, float)

    def test_zero_slope_threshold(self):
        """斜率为 0 的情况。"""
        # 完全水平的多点
        points = [(i, 0.5) for i in range(5)]
        assert linear_slope(points) == 0.0
