"""ml/embedding/ 单元测试。

覆盖：
- cosine_similarity（embedding_classifier.py，纯数学）
- build_keyword_centroid（需 mock embedder）
- sigmoid（weak_supervised.py，纯数学）
- LogisticRegression（weak_supervised.py，纯 numpy 训练+预测）
- extract_features（需 mock embedder）
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ml.embedding.embedding_classifier import (
    cosine_similarity,
    build_keyword_centroid,
    LABEL_KEYWORDS,
)
from ml.embedding.weak_supervised import (
    sigmoid,
    LogisticRegression,
    extract_features,
)


# ═══════════════════════════════════════════════════════════════════
# cosine_similarity
# ═══════════════════════════════════════════════════════════════════

class TestCosineSimilarity:
    """cosine_similarity 计算余弦相似度。"""

    def test_identical_vectors(self):
        """相同向量 → 1.0。"""
        a = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """正交向量 → 0.0。"""
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """相反向量 → -1.0。"""
        a = np.array([1.0, 2.0])
        b = np.array([-1.0, -2.0])
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        """零向量 → 0.0（防除零）。"""
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 2.0])
        # norm(a)=0 → denominator = 0 + 1e-8 → 极小值 → 结果接近 0
        result = cosine_similarity(a, b)
        assert abs(result) < 1e-6

    def test_both_zero_vectors(self):
        """双零向量 → 0.0。"""
        a = np.array([0.0, 0.0])
        b = np.array([0.0, 0.0])
        result = cosine_similarity(a, b)
        assert abs(result) < 1e-6

    def test_single_dimension(self):
        """一维向量。"""
        a = np.array([5.0])
        b = np.array([3.0])
        # cos = (5*3) / (5*3) = 1.0
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_single_dimension_opposite(self):
        """一维相反 → -1.0。"""
        a = np.array([5.0])
        b = np.array([-3.0])
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_high_dimensional(self):
        """高维向量。"""
        a = np.arange(100, dtype=float)
        b = np.arange(100, dtype=float) * 2
        # 同方向 → 1.0
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_returns_float(self):
        """返回 float 类型。"""
        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        result = cosine_similarity(a, b)
        assert isinstance(result, float)

    def test_normalized_vectors(self):
        """已归一化向量。"""
        a = np.array([0.6, 0.8])  # norm=1
        b = np.array([0.8, 0.6])  # norm=1
        # cos = 0.6*0.8 + 0.8*0.6 = 0.96
        assert cosine_similarity(a, b) == pytest.approx(0.96)

    def test_negative_values(self):
        """含负值。"""
        a = np.array([1.0, -1.0])
        b = np.array([-1.0, 1.0])
        # cos = (-1 + -1) / (sqrt(2) * sqrt(2)) = -2/2 = -1.0
        assert cosine_similarity(a, b) == pytest.approx(-1.0)


# ═══════════════════════════════════════════════════════════════════
# build_keyword_centroid
# ═══════════════════════════════════════════════════════════════════

class TestBuildKeywordCentroid:
    """build_keyword_centroid 构建关键词质心向量。"""

    def test_single_keyword(self):
        """单个关键词 → 返回该词的 embedding。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([[1.0, 2.0, 3.0]])
        result = build_keyword_centroid(["hello"], mock_embedder)
        mock_embedder.encode.assert_called_once_with(["hello"])
        assert np.allclose(result, [1.0, 2.0, 3.0])

    def test_multiple_keywords_mean(self):
        """多个关键词 → 返回均值。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([
            [1.0, 2.0, 3.0],
            [3.0, 4.0, 5.0],
        ])
        result = build_keyword_centroid(["hello", "world"], mock_embedder)
        expected = np.mean([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]], axis=0)
        assert np.allclose(result, expected)

    def test_empty_keywords(self):
        """空关键词列表 → encode([]) → mean of empty → nan。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([]).reshape(0, 0)
        result = build_keyword_centroid([], mock_embedder)
        # np.mean of empty array → nan with warning
        assert np.all(np.isnan(result))

    def test_three_keywords(self):
        """三个关键词。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([
            [1.0, 1.0],
            [2.0, 2.0],
            [3.0, 3.0],
        ])
        result = build_keyword_centroid(["a", "b", "c"], mock_embedder)
        assert np.allclose(result, [2.0, 2.0])

    def test_passes_keywords_to_encode(self):
        """关键词列表原样传给 embedder.encode。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([[1.0]])
        keywords = ["你好", "在吗", "怎么样"]
        build_keyword_centroid(keywords, mock_embedder)
        mock_embedder.encode.assert_called_once_with(keywords)

    def test_returns_ndarray(self):
        """返回 numpy ndarray。"""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([[1.0, 2.0]])
        result = build_keyword_centroid(["test"], mock_embedder)
        assert isinstance(result, np.ndarray)


# ═══════════════════════════════════════════════════════════════════
# LABEL_KEYWORDS 常量
# ═══════════════════════════════════════════════════════════════════

class TestLabelKeywords:
    """LABEL_KEYWORDS 关键词字典验证。"""

    def test_has_expected_labels(self):
        """包含预期标签。"""
        expected_labels = {
            "question_asking", "self_disclosure", "emotional_expression",
            "initiative_response", "flirt", "intimacy", "cold_conflict",
            "perfunctory", "investment", "willingness",
        }
        assert set(LABEL_KEYWORDS.keys()) == expected_labels

    def test_all_values_are_lists(self):
        """所有值是列表。"""
        for label, keywords in LABEL_KEYWORDS.items():
            assert isinstance(keywords, list), f"{label} 不是列表"

    def test_all_keywords_are_strings(self):
        """所有关键词是字符串。"""
        for label, keywords in LABEL_KEYWORDS.items():
            for kw in keywords:
                assert isinstance(kw, str), f"{label} 的关键词 {kw} 不是字符串"

    def test_flirt_has_keywords(self):
        """flirt 标签有关键词。"""
        assert len(LABEL_KEYWORDS["flirt"]) > 5

    def test_perfunctory_has_short_words(self):
        """perfunctory 包含短词（嗯/哦等）。"""
        assert "嗯" in LABEL_KEYWORDS["perfunctory"]
        assert "哦" in LABEL_KEYWORDS["perfunctory"]


# ═══════════════════════════════════════════════════════════════════
# sigmoid
# ═══════════════════════════════════════════════════════════════════

class TestSigmoid:
    """sigmoid 激活函数。"""

    def test_zero_returns_half(self):
        """x=0 → 0.5。"""
        assert sigmoid(np.array([0.0])) == pytest.approx(0.5)

    def test_large_positive_returns_one(self):
        """大正数 → 接近 1。"""
        result = sigmoid(np.array([100.0]))
        assert result > 0.99

    def test_large_negative_returns_zero(self):
        """大负数 → 接近 0。"""
        result = sigmoid(np.array([-100.0]))
        assert result < 0.01

    def test_clipping_30(self):
        """x > 30 被裁剪（防溢出）。"""
        # x=30 和 x=100 应返回相同值（都被 clip 到 30）
        r1 = sigmoid(np.array([30.0]))
        r2 = sigmoid(np.array([100.0]))
        assert r1 == pytest.approx(r2)

    def test_clipping_negative_30(self):
        """x < -30 被裁剪。"""
        r1 = sigmoid(np.array([-30.0]))
        r2 = sigmoid(np.array([-100.0]))
        assert r1 == pytest.approx(r2)

    def test_array_input(self):
        """数组输入 → 数组输出。"""
        x = np.array([-1.0, 0.0, 1.0])
        result = sigmoid(x)
        assert result.shape == (3,)
        assert result[1] == pytest.approx(0.5)
        assert result[0] < 0.5
        assert result[2] > 0.5

    def test_symmetry(self):
        """sigmoid(-x) = 1 - sigmoid(x)。"""
        x = np.array([0.5, 1.0, 2.0, 5.0])
        s1 = sigmoid(x)
        s2 = sigmoid(-x)
        assert np.allclose(s1 + s2, 1.0)

    def test_returns_ndarray(self):
        """返回 ndarray。"""
        result = sigmoid(np.array([1.0]))
        assert isinstance(result, np.ndarray)

    def test_monotonic_increasing(self):
        """单调递增。"""
        x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        result = sigmoid(x)
        for i in range(len(result) - 1):
            assert result[i] < result[i + 1]


# ═══════════════════════════════════════════════════════════════════
# LogisticRegression
# ═══════════════════════════════════════════════════════════════════

class TestLogisticRegression:
    """LogisticRegression 纯 numpy 实现。"""

    def test_fit_initializes_weights(self):
        """fit 初始化权重。"""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        y = np.array([0, 1, 1])
        model = LogisticRegression(lr=0.1, epochs=10)
        model.fit(X, y)
        assert model.w is not None
        assert len(model.w) == 2
        assert isinstance(model.b, float)

    def test_predict_proba_shape(self):
        """predict_proba 返回正确形状。"""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        y = np.array([0, 1])
        model = LogisticRegression(epochs=10)
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape == (2,)
        assert all(0 <= p <= 1 for p in proba)

    def test_predict_binary(self):
        """predict 返回 0/1。"""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        y = np.array([0, 1])
        model = LogisticRegression(epochs=10)
        model.fit(X, y)
        pred = model.predict(X)
        assert all(p in (True, False) for p in pred)

    def test_predict_custom_threshold(self):
        """自定义阈值。"""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        y = np.array([0, 1])
        model = LogisticRegression(epochs=10)
        model.fit(X, y)
        pred_low = model.predict(X, threshold=0.1)
        pred_high = model.predict(X, threshold=0.9)
        # 低阈值 → 更多 True
        assert sum(pred_low) >= sum(pred_high)

    def test_perfect_separation(self):
        """完全可分 → 高精度。"""
        # 构造完全可分的数据
        X = np.array([
            [0.1, 0.1], [0.2, 0.2], [0.3, 0.3],  # 负类
            [0.8, 0.8], [0.9, 0.9], [1.0, 1.0],  # 正类
        ])
        y = np.array([0, 0, 0, 1, 1, 1])
        model = LogisticRegression(lr=0.5, epochs=500)
        model.fit(X, y)
        pred = model.predict(X)
        # 训练数据应能完美拟合
        assert sum(pred == y) >= 5  # 至少 5/6 正确

    def test_predict_before_fit_raises(self):
        """未 fit 就 predict → ValueError（w=None，X @ None 抛错）。"""
        model = LogisticRegression()
        with pytest.raises((AttributeError, ValueError, TypeError)):
            model.predict(np.array([[1.0]]))

    def test_l2_regularization(self):
        """L2 正则化（权重不应爆炸）。"""
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        y = np.array([0, 1, 1])
        model_no_reg = LogisticRegression(lr=0.1, epochs=100, l2=0.0)
        model_reg = LogisticRegression(lr=0.1, epochs=100, l2=1.0)
        model_no_reg.fit(X, y)
        model_reg.fit(X, y)
        # 有正则化的权重范数应更小
        assert np.linalg.norm(model_reg.w) <= np.linalg.norm(model_no_reg.w) + 0.1

    def test_single_sample(self):
        """单样本训练。"""
        X = np.array([[1.0, 2.0]])
        y = np.array([1])
        model = LogisticRegression(epochs=10)
        model.fit(X, y)
        assert model.w is not None


# ═══════════════════════════════════════════════════════════════════
# extract_features
# ═══════════════════════════════════════════════════════════════════

class TestExtractFeatures:
    """extract_features 提取 embedding 特征。"""

    def _make_mock_embedder(self, dim=4):
        """创建 mock embedder。"""
        mock = MagicMock()
        mock._load_model.return_value.get_sentence_embedding_dimension.return_value = dim
        mock.encode.return_value = np.random.rand(2, dim)  # 任意 2D 数组
        return mock

    def test_returns_normalized_vector(self):
        """返回归一化向量（范数≈1）。"""
        mock_embedder = self._make_mock_embedder(dim=4)
        sample = {
            "messages": [
                {"content": "你好", "role": "her"},
                {"content": "在吗", "role": "me"},
            ],
        }
        feat = extract_features(sample, mock_embedder)
        # feat 应归一化（norm ≈ 1，因为除以 norm + 1e-8）
        assert np.linalg.norm(feat) == pytest.approx(1.0, abs=1e-4)

    def test_no_her_messages(self):
        """无 her 消息 → her_mean 用零向量。"""
        mock_embedder = self._make_mock_embedder(dim=4)
        sample = {
            "messages": [
                {"content": "你好", "role": "me"},
                {"content": "在吗", "role": "me"},
            ],
        }
        feat = extract_features(sample, mock_embedder)
        # 不应崩溃，返回归一化向量
        assert np.linalg.norm(feat) == pytest.approx(1.0, abs=1e-4)

    def test_empty_messages(self):
        """空消息列表 → all_mean 也用零向量。"""
        mock_embedder = self._make_mock_embedder(dim=4)
        sample = {"messages": []}
        feat = extract_features(sample, mock_embedder)
        # 全零 → norm=0 → feat = 0 / (0 + 1e-8) = 0
        assert np.allclose(feat, 0)

    def test_feature_dim_is_2x_embedding_dim(self):
        """特征维度 = 2 × embedding_dim（her_mean + all_mean 拼接）。"""
        dim = 5
        mock_embedder = self._make_mock_embedder(dim=dim)
        sample = {
            "messages": [
                {"content": "你好", "role": "her"},
            ],
        }
        feat = extract_features(sample, mock_embedder)
        assert feat.shape == (2 * dim,)

    def test_content_field_used(self):
        """使用 messages 的 content 字段。"""
        mock_embedder = self._make_mock_embedder(dim=4)
        sample = {
            "messages": [
                {"content": "测试内容", "role": "her"},
            ],
        }
        extract_features(sample, mock_embedder)
        # embedder.encode 应被调用
        assert mock_embedder.encode.called

    def test_role_filtering(self):
        """her 消息被正确过滤。"""
        mock_embedder = self._make_mock_embedder(dim=4)
        sample = {
            "messages": [
                {"content": "her_msg", "role": "her"},
                {"content": "me_msg", "role": "me"},
                {"content": "her_msg2", "role": "her"},
            ],
        }
        extract_features(sample, mock_embedder)
        # encode 第一次调用应只传 her 的消息
        first_call_args = mock_embedder.encode.call_args_list[0][0][0]
        assert list(first_call_args) == ["her_msg", "her_msg2"]
