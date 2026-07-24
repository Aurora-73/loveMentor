"""ml/evaluation/evaluate.py 单元测试。

覆盖：
- cohens_kappa（Cohen's Kappa 二分类标注一致性）
- binary_metrics（precision/recall/f1/accuracy）
- evaluate_predictions（JSONL 文件评估）
- parse_annotation_template（MD 模板解析）
- template_to_jsonl（MD 转 JSONL）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.evaluation.evaluate import (
    cohens_kappa,
    binary_metrics,
    evaluate_predictions,
    parse_annotation_template,
    template_to_jsonl,
    LABELS,
)


# ═══════════════════════════════════════════════════════════════════
# cohens_kappa
# ═══════════════════════════════════════════════════════════════════

class TestCohensKappa:
    """cohens_kappa 计算 Cohen's Kappa。"""

    def test_perfect_agreement(self):
        """完全一致 → kappa=1.0。"""
        y1 = [True, False, True, False]
        y2 = [True, False, True, False]
        assert cohens_kappa(y1, y2) == 1.0

    def test_empty_lists_returns_zero(self):
        """空列表 → 0.0。"""
        assert cohens_kappa([], []) == 0.0

    def test_all_positive_perfect(self):
        """全正且完全一致 → pe=1.0 → 返回 0.0（除零保护）。"""
        y1 = [True, True, True]
        y2 = [True, True, True]
        # p1_pos=1.0, p2_pos=1.0 → pe=1.0 → return 0.0
        assert cohens_kappa(y1, y2) == 0.0

    def test_all_negative_perfect(self):
        """全负且完全一致 → pe=1.0 → 返回 0.0。"""
        y1 = [False, False, False]
        y2 = [False, False, False]
        # p1_pos=0.0, p2_pos=0.0 → pe = 0*0 + 1*1 = 1.0 → return 0.0
        assert cohens_kappa(y1, y2) == 0.0

    def test_random_agreement(self):
        """随机一致 → kappa 接近 0。"""
        # 50% 正负，完全独立标注
        y1 = [True, False, True, False, True, False, True, False]
        y2 = [False, True, False, True, False, True, False, True]
        kappa = cohens_kappa(y1, y2)
        # 完全相反 → po=0, pe=0.5 → kappa = (0-0.5)/(1-0.5) = -1.0
        assert kappa == -1.0

    def test_partial_agreement(self):
        """部分一致 → 0 < kappa < 1。"""
        y1 = [True, False, True, False, True, True]
        y2 = [True, False, False, False, True, True]
        # agree=5 (位置 0,1,3,4,5), n=6 → po=5/6
        # p1_pos=4/6, p2_pos=3/6 → pe = (4/6)*(3/6) + (2/6)*(3/6) = 12/36 + 6/36 = 18/36 = 0.5
        # kappa = (5/6 - 0.5) / (1 - 0.5) = (0.833-0.5)/0.5 = 0.667
        kappa = cohens_kappa(y1, y2)
        assert 0 < kappa < 1.0
        assert abs(kappa - 0.6667) < 0.01

    def test_different_lengths_assertion_error(self):
        """长度不一致 → AssertionError。"""
        with pytest.raises(AssertionError):
            cohens_kappa([True, False], [True])

    def test_single_element_perfect(self):
        """单元素完全一致 → pe=1.0 → 0.0。"""
        assert cohens_kappa([True], [True]) == 0.0

    def test_single_element_different(self):
        """单元素不一致 → pe=0.0 → kappa=-1.0。"""
        # p1_pos=1.0, p2_pos=0.0 → pe = 1*0 + 0*1 = 0
        # po=0, kappa = (0-0)/(1-0) = 0
        # 实际：pe=0, po=0 → kappa = 0/1 = 0
        result = cohens_kappa([True], [False])
        # po=0, pe=0 → (0-0)/(1-0) = 0
        assert result == 0.0

    def test_negative_kappa(self):
        """一致性低于随机 → 负 kappa。"""
        y1 = [True, True, True, False]
        y2 = [False, False, False, True]
        kappa = cohens_kappa(y1, y2)
        assert kappa < 0


# ═══════════════════════════════════════════════════════════════════
# binary_metrics
# ═══════════════════════════════════════════════════════════════════

class TestBinaryMetrics:
    """binary_metrics 计算 precision/recall/f1/accuracy。"""

    def test_perfect_prediction(self):
        """完美预测 → 所有指标=1.0。"""
        y_true = [True, False, True, False]
        y_pred = [True, False, True, False]
        m = binary_metrics(y_true, y_pred)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0
        assert m["accuracy"] == 1.0
        assert m["tp"] == 2
        assert m["fp"] == 0
        assert m["fn"] == 0
        assert m["tn"] == 2

    def test_all_wrong(self):
        """全错 → precision/recall=0, accuracy=0。"""
        y_true = [True, False, True, False]
        y_pred = [False, True, False, True]
        m = binary_metrics(y_true, y_pred)
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0
        assert m["f1"] == 0.0
        assert m["accuracy"] == 0.0
        assert m["tp"] == 0
        assert m["fp"] == 2
        assert m["fn"] == 2
        assert m["tn"] == 0

    def test_empty_lists(self):
        """空列表 → accuracy=0（max(0,1)），precision/recall=0。"""
        m = binary_metrics([], [])
        assert m["accuracy"] == 0.0
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0
        assert m["f1"] == 0.0
        assert m["tp"] == 0
        assert m["fp"] == 0
        assert m["fn"] == 0
        assert m["tn"] == 0

    def test_only_true_positives(self):
        """只有 TP → precision=1, recall=1。"""
        y_true = [True, True, True]
        y_pred = [True, True, True]
        m = binary_metrics(y_true, y_pred)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["tp"] == 3
        assert m["support_pos"] == 3
        assert m["support_neg"] == 0

    def test_only_true_negatives(self):
        """只有 TN → precision/recall=0（无正样本）。"""
        y_true = [False, False, False]
        y_pred = [False, False, False]
        m = binary_metrics(y_true, y_pred)
        assert m["accuracy"] == 1.0
        # precision = 0/max(0,1) = 0, recall = 0/max(0,1) = 0
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0
        assert m["tn"] == 3
        assert m["support_neg"] == 3

    def test_false_positives_only(self):
        """只有 FP → precision=0, recall=0。"""
        y_true = [False, False]
        y_pred = [True, True]
        m = binary_metrics(y_true, y_pred)
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0
        assert m["fp"] == 2
        assert m["tn"] == 0

    def test_false_negatives_only(self):
        """只有 FN → precision=0, recall=0。"""
        y_true = [True, True]
        y_pred = [False, False]
        m = binary_metrics(y_true, y_pred)
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0
        assert m["fn"] == 2

    def test_mixed_errors(self):
        """混合错误 → 正确计算各指标。"""
        # tp=2, fp=1, fn=1, tn=2
        y_true = [True, True, False, True, False, False]
        y_pred = [True, False, True, True, False, False]
        m = binary_metrics(y_true, y_pred)
        assert m["tp"] == 2
        assert m["fp"] == 1
        assert m["fn"] == 1
        assert m["tn"] == 2
        # precision = 2/(2+1) = 0.6667
        assert m["precision"] == 0.6667
        # recall = 2/(2+1) = 0.6667
        assert m["recall"] == 0.6667
        # accuracy = (2+2)/6 = 0.6667
        assert m["accuracy"] == 0.6667
        # f1 = 2*0.6667*0.6667/(0.6667+0.6667) = 0.6667
        assert m["f1"] == 0.6667

    def test_support_counts(self):
        """support_pos/support_neg 正确。"""
        y_true = [True, True, False, False, True]
        y_pred = [True, False, True, False, True]
        m = binary_metrics(y_true, y_pred)
        # support_pos = tp + fn = 3
        assert m["support_pos"] == 3
        # support_neg = tn + fp = 2
        assert m["support_neg"] == 2

    def test_rounded_values(self):
        """返回值已 round 到 4 位小数。"""
        y_true = [True, False, True]
        y_pred = [True, True, False]
        m = binary_metrics(y_true, y_pred)
        # 所有浮点值应是 4 位小数
        for key in ["accuracy", "precision", "recall", "f1"]:
            assert m[key] == round(m[key], 4)


# ═══════════════════════════════════════════════════════════════════
# evaluate_predictions
# ═══════════════════════════════════════════════════════════════════

class TestEvaluatePredictions:
    """evaluate_predictions 评估 JSONL 预测文件。"""

    def _write_jsonl(self, path: Path, data: list[dict]):
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def test_perfect_predictions(self, tmp_path):
        """完美预测 → precision/recall/f1=1.0（kappa 在 pe=1.0 时返回 0.0）。"""
        pred_data = [
            {"sample_id": "s_001", "labels": {"flirt": True, "perfunctory": False}},
            {"sample_id": "s_002", "labels": {"flirt": False, "perfunctory": True}},
        ]
        gold_data = [
            {"sample_id": "s_001", "labels": {"flirt": True, "perfunctory": False}},
            {"sample_id": "s_002", "labels": {"flirt": False, "perfunctory": True}},
        ]
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        self._write_jsonl(pred_path, pred_data)
        self._write_jsonl(gold_path, gold_data)

        result = evaluate_predictions(pred_path, gold_path, labels=["flirt", "perfunctory"])
        assert result["n_samples"] == 2
        assert result["n_labels"] == 2
        for label in ["flirt", "perfunctory"]:
            # 完美预测：precision/recall/f1=1.0
            assert result["per_label"][label]["precision"] == 1.0
            assert result["per_label"][label]["recall"] == 1.0
            assert result["per_label"][label]["f1"] == 1.0
            # kappa：每个标签只有一个正样本一个负样本，pe=0.5 → kappa=1.0
            # 实际：flirt: y1=[True,False], y2=[True,False] → po=1, p1_pos=0.5, p2_pos=0.5
            # pe = 0.5*0.5 + 0.5*0.5 = 0.5 → kappa = (1-0.5)/(1-0.5) = 1.0
            assert result["per_label"][label]["kappa"] == 1.0

    def test_no_common_samples_raises(self, tmp_path):
        """无共同样本 → ValueError。"""
        pred_data = [{"sample_id": "s_001", "labels": {}}]
        gold_data = [{"sample_id": "s_999", "labels": {}}]
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        self._write_jsonl(pred_path, pred_data)
        self._write_jsonl(gold_path, gold_data)

        with pytest.raises(ValueError, match="No common sample_ids"):
            evaluate_predictions(pred_path, gold_path)

    def test_missing_labels_treated_as_false(self, tmp_path):
        """缺失标签 → 当作 False。"""
        pred_data = [{"sample_id": "s_001", "labels": {}}]  # 无 flirt
        gold_data = [{"sample_id": "s_001", "labels": {"flirt": True}}]
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        self._write_jsonl(pred_path, pred_data)
        self._write_jsonl(gold_path, gold_data)

        result = evaluate_predictions(pred_path, gold_path, labels=["flirt"])
        # pred flirt=False, gold flirt=True → fn=1
        assert result["per_label"]["flirt"]["fn"] == 1
        assert result["per_label"]["flirt"]["recall"] == 0.0

    def test_macro_avg_calculated(self, tmp_path):
        """macro_avg 正确计算。"""
        pred_data = [
            {"sample_id": "s_001", "labels": {"flirt": True, "perfunctory": False}},
            {"sample_id": "s_002", "labels": {"flirt": False, "perfunctory": True}},
        ]
        gold_data = [
            {"sample_id": "s_001", "labels": {"flirt": True, "perfunctory": False}},
            {"sample_id": "s_002", "labels": {"flirt": False, "perfunctory": True}},
        ]
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        self._write_jsonl(pred_path, pred_data)
        self._write_jsonl(gold_path, gold_data)

        result = evaluate_predictions(pred_path, gold_path, labels=["flirt", "perfunctory"])
        assert "macro_avg" in result
        assert "precision" in result["macro_avg"]
        assert "recall" in result["macro_avg"]
        assert "f1" in result["macro_avg"]
        assert "kappa" in result["macro_avg"]

    def test_partial_overlap(self, tmp_path):
        """部分样本重叠。"""
        pred_data = [
            {"sample_id": "s_001", "labels": {"flirt": True}},
            {"sample_id": "s_002", "labels": {"flirt": False}},
            {"sample_id": "s_003", "labels": {"flirt": True}},  # 不在 gold 中
        ]
        gold_data = [
            {"sample_id": "s_001", "labels": {"flirt": True}},
            {"sample_id": "s_002", "labels": {"flirt": False}},
            {"sample_id": "s_004", "labels": {"flirt": False}},  # 不在 pred 中
        ]
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        self._write_jsonl(pred_path, pred_data)
        self._write_jsonl(gold_path, gold_data)

        result = evaluate_predictions(pred_path, gold_path, labels=["flirt"])
        # 只有 s_001 和 s_002 重叠
        assert result["n_samples"] == 2

    def test_empty_lines_skipped(self, tmp_path):
        """空行被跳过。"""
        pred_path = tmp_path / "pred.jsonl"
        gold_path = tmp_path / "gold.jsonl"
        # 用 json.dumps 确保 JSON 合法（true/false 而非 True/False）
        pred_path.write_text(
            '\n' + json.dumps({"sample_id": "s_001", "labels": {"flirt": True}}) + '\n\n',
            encoding="utf-8")
        gold_path.write_text(
            json.dumps({"sample_id": "s_001", "labels": {"flirt": True}}) + '\n',
            encoding="utf-8")

        result = evaluate_predictions(pred_path, gold_path, labels=["flirt"])
        assert result["n_samples"] == 1


# ═══════════════════════════════════════════════════════════════════
# parse_annotation_template
# ═══════════════════════════════════════════════════════════════════

class TestParseAnnotationTemplate:
    """parse_annotation_template 解析 MD 标注模板。"""

    def test_parse_single_sample(self, tmp_path):
        """解析单个样本。"""
        md_content = """# 标注模板

## 样本 1: s_000001 (Alice)

- flirt: [1]
- perfunctory: [0]
- question_asking: [1]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        assert len(results) == 1
        assert results[0]["sample_id"] == "s_000001"
        assert results[0]["labels"]["flirt"] is True
        assert results[0]["labels"]["perfunctory"] is False
        assert results[0]["labels"]["question_asking"] is True

    def test_parse_multiple_samples(self, tmp_path):
        """解析多个样本。"""
        md_content = """## 样本 1: s_001 (Alice)

- flirt: [1]

## 样本 2: s_002 (Bob)

- flirt: [0]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        assert len(results) == 2
        assert results[0]["sample_id"] == "s_001"
        assert results[0]["labels"]["flirt"] is True
        assert results[1]["sample_id"] == "s_002"
        assert results[1]["labels"]["flirt"] is False

    def test_empty_file(self, tmp_path):
        """空文件 → 空列表。"""
        md_path = tmp_path / "empty.md"
        md_path.write_text("", encoding="utf-8")
        assert parse_annotation_template(md_path) == []

    def test_no_samples(self, tmp_path):
        """无样本头 → 空列表。"""
        md_path = tmp_path / "no_samples.md"
        md_path.write_text("- flirt: [1]\n- perfunctory: [0]\n", encoding="utf-8")
        assert parse_annotation_template(md_path) == []

    def test_sample_with_no_labels(self, tmp_path):
        """样本无标签 → labels 为空字典。"""
        md_content = "## 样本 1: s_001 (Alice)\n"
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        assert len(results) == 1
        assert results[0]["sample_id"] == "s_001"
        assert results[0]["labels"] == {}

    def test_label_value_0_is_false(self, tmp_path):
        """标签值 [0] → False。"""
        md_content = """## 样本 1: s_001

- flirt: [0]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        assert results[0]["labels"]["flirt"] is False

    def test_label_value_1_is_true(self, tmp_path):
        """标签值 [1] → True。"""
        md_content = """## 样本 1: s_001

- flirt: [1]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        assert results[0]["labels"]["flirt"] is True

    def test_sample_id_with_special_chars(self, tmp_path):
        """sample_id 含特殊字符。"""
        md_content = """## 样本 1: s_001_special (Alice)

- flirt: [1]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")

        results = parse_annotation_template(md_path)
        # \S+ 匹配到第一个空白，所以 s_001_special 被完整捕获
        assert results[0]["sample_id"] == "s_001_special"


# ═══════════════════════════════════════════════════════════════════
# template_to_jsonl
# ═══════════════════════════════════════════════════════════════════

class TestTemplateToJsonl:
    """template_to_jsonl 将 MD 模板转为 JSONL。"""

    def test_conversion_creates_jsonl(self, tmp_path):
        """转换生成 JSONL 文件。"""
        md_content = """## 样本 1: s_001

- flirt: [1]
- perfunctory: [0]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")
        output_path = tmp_path / "output.jsonl"

        template_to_jsonl(md_path, output_path)

        assert output_path.exists()
        lines = output_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["sample_id"] == "s_001"
        assert data["labels"]["flirt"] is True
        assert data["labels"]["perfunctory"] is False

    def test_multiple_samples_in_jsonl(self, tmp_path):
        """多个样本 → 多行 JSONL。"""
        md_content = """## 样本 1: s_001

- flirt: [1]

## 样本 2: s_002

- flirt: [0]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")
        output_path = tmp_path / "output.jsonl"

        template_to_jsonl(md_path, output_path)

        lines = output_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["sample_id"] == "s_001"
        assert json.loads(lines[1])["sample_id"] == "s_002"

    def test_empty_template_empty_jsonl(self, tmp_path):
        """空模板 → 空文件（无行）。"""
        md_path = tmp_path / "empty.md"
        md_path.write_text("", encoding="utf-8")
        output_path = tmp_path / "output.jsonl"

        template_to_jsonl(md_path, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8").strip()
        assert content == ""

    def test_unicode_preserved(self, tmp_path):
        """Unicode 内容保留（ensure_ascii=False）。"""
        md_content = """## 样本 1: s_001 (爱丽丝)

- flirt: [1]
"""
        md_path = tmp_path / "template.md"
        md_path.write_text(md_content, encoding="utf-8")
        output_path = tmp_path / "output.jsonl"

        template_to_jsonl(md_path, output_path)

        content = output_path.read_text(encoding="utf-8")
        # 中文应保留（不被转义为 \\uXXXX）
        assert "爱丽丝" in content or "s_001" in content


# ═══════════════════════════════════════════════════════════════════
# LABELS 常量
# ═══════════════════════════════════════════════════════════════════

class TestLabelsConstant:
    """LABELS 常量验证。"""

    def test_labels_count(self):
        """10 个标签。"""
        assert len(LABELS) == 10

    def test_labels_contains_expected(self):
        """包含预期标签。"""
        expected = {
            "information_exchange", "opinion_expression",
            "emotion_positive", "emotion_negative",
            "flirt", "question_asking", "self_disclosure",
            "invitation", "framing_boundary", "perfunctory",
        }
        assert set(LABELS) == expected

    def test_framing_boundary_present(self):
        """framing_boundary 替代 friend_zoning（项目记忆约束）。"""
        assert "framing_boundary" in LABELS
        assert "friend_zoning" not in LABELS
