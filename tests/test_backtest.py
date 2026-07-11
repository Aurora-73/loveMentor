"""Backtest 模块单元测试。

覆盖纯函数（linear_slope / calibration metrics 等），
不依赖真实数据库或案例数据。
"""
import pytest

from engine.backtest.timeseries import linear_slope


# ── linear_slope ────────────────────────────────────────────────────────────

class TestLinearSlope:
    def test_less_than_two_points(self):
        """少于 2 个点 → 0。"""
        assert linear_slope([]) == 0.0
        assert linear_slope([(0, 1)]) == 0.0

    def test_flat_line(self):
        """水平线 → 斜率 = 0。"""
        points = [(0, 5), (1, 5), (2, 5), (3, 5)]
        assert abs(linear_slope(points)) < 1e-10

    def test_positive_slope(self):
        """正斜率。"""
        points = [(0, 0), (1, 1), (2, 2), (3, 3)]
        assert abs(linear_slope(points) - 1.0) < 1e-10

    def test_negative_slope(self):
        """负斜率。"""
        points = [(0, 3), (1, 2), (2, 1), (3, 0)]
        assert abs(linear_slope(points) + 1.0) < 1e-10

    def test_no_variance_in_x(self):
        """所有点 x 相同（分母为 0）→ 0。"""
        points = [(1, 5), (1, 10), (1, 3)]
        assert linear_slope(points) == 0.0

    def test_two_points(self):
        """两点计算斜率。"""
        points = [(0, 0), (2, 4)]
        assert abs(linear_slope(points) - 2.0) < 1e-10

    def test_noisy_upward(self):
        """有噪声的上升趋势 → 斜率为正。"""
        points = [
            (0, 0.1), (1, 0.3), (2, 0.2), (3, 0.5), (4, 0.4),
            (5, 0.7), (6, 0.6), (7, 0.9), (8, 0.8), (9, 1.0),
        ]
        slope = linear_slope(points)
        assert slope > 0

    def test_slope_magnitude(self):
        """验证斜率数量级。"""
        # y = 0.01*x → 斜率 0.01
        points = [(i, 0.01 * i) for i in range(10)]
        slope = linear_slope(points)
        assert abs(slope - 0.01) < 1e-10


# ── 指标函数复用验证 ─────────────────────────────────────────────────────────

class TestMetricFunctionsBacktestCompat:
    """验证 metrics 模块中用于回测的关键函数行为一致。"""

    def test_compute_base_score_with_zero_weights(self):
        """所有权重为 0 → base_score = 0。"""
        from engine.models.metrics import Metrics, MetricValue
        from engine.analyzers.metrics import compute_base_score
        from engine.config import WeightsConfig

        m = Metrics()
        half = MetricValue(raw=0.5, normalized=0.5, confidence=1.0, sample_size=100)
        for field_name in m.all_metrics():
            setattr(m, field_name, half)

        zero_weights = {k: 0.0 for k in [
            "fback", "rlatency", "qscore", "escore", "moments",
            "msg_count", "active_days", "recent", "trend",
            "fback_quality", "escore_volatility", "qscore_personal",
            "qscore_functional", "rlatency_context", "msg_volume_trend",
            "latency_trend", "her_initiation_rate", "topic_continuation",
            "reply_quality", "session_balance", "emotional_temperature",
            "friendzone_risk", "semantic_flirt", "semantic_invitation",
            "semantic_emotion_balance",
        ]}
        w = WeightsConfig(zero_weights)
        assert compute_base_score(m, w) == 0.0

    def test_compute_signal_level_boundaries(self):
        """验证信号等级边界。"""
        from engine.analyzers.metrics import compute_signal_level

        assert compute_signal_level(1.0) == "强窗口"
        assert compute_signal_level(0.45) == "强窗口"
        assert compute_signal_level(0.44) == "中窗口"
        assert compute_signal_level(0.35) == "中窗口"
        assert compute_signal_level(0.34) == "弱窗口"
        assert compute_signal_level(0.25) == "弱窗口"
        assert compute_signal_level(0.24) == "冷淡"
        assert compute_signal_level(0.10) == "冷淡"
        assert compute_signal_level(0.09) == "无信号"
        assert compute_signal_level(0.0) == "无信号"

    def test_confidence_function(self):
        """验证 _confidence 函数分段行为。"""
        from engine.analyzers.metrics import _confidence

        assert _confidence(0) == 0.0
        assert 0.1 <= _confidence(1) <= 0.3
        assert _confidence(20) >= 0.5
        assert _confidence(100) >= 0.8
        assert _confidence(5000) > 0.95
