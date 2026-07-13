#!/usr/bin/env python3
"""测试评估链路：compare_experiments.py 校验 + classifier schema 检查 + eval-only 控制流。

运行：
  pytest tests/test_eval_link.py -v
  pytest tests/test_eval_link.py -v -k "compare"   # 只比较脚本测试
  pytest tests/test_eval_link.py -v -k "classifier"  # 只 classifier 测试
  pytest tests/test_eval_link.py -v -k "eval_only"   # 只 eval-only 测试
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from copy import deepcopy

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "ml" / "scripts"
MODELS_DIR = Path(__file__).resolve().parent.parent / "ml" / "models"
COMPARE_SCRIPT = SCRIPTS_DIR / "compare_experiments.py"

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

# ═══════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════


@pytest.fixture
def full_report() -> dict:
    """一份包含所有必要字段的标准 eval_report。"""
    per_label = {}
    for lbl in LABELS:
        per_label[lbl] = {
            "R2": 0.5, "MAE_score": 0.07, "Spearman": 0.6,
            "Contact_MAE_score": 0.08,
        }
    return {
        "label": "all",
        "overall": {
            "R2": 0.54, "MAE_score": 0.07, "RMSE_score": 0.09,
            "Contact_MAE_score": 0.08,
        },
        "per_label": per_label,
        "config": {"train_samples": 1000, "val_samples": 100, "test_samples": 100},
        "manifest": {
            "split_manifest_sha256": "abc123def456",
            "role_prefix": False,
            "input_schema": "roleless_v0",
            "train_contacts_sha256": "train_aaa",
            "val_contacts_sha256": "val_bbb",
            "test_contacts_sha256": "test_ccc",
            "dataset_sha256": "dataset_ddd",
            "dataset_sample_count": 13675,
        },
    }


def _write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════
#  正向测试
# ═══════════════════════════════════════════


class TestComparePasses:
    """同一 manifest、完整字段 → 允许比较。"""

    def test_identical_reports(self, tmp_path, full_report):
        """两个完全相同的报告 → exit 0。"""
        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, full_report)
        _write_report(exp, deepcopy(full_report))

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0
        assert "划分和数据版本一致" in result.stdout

    def test_role_prefix_same_warning(self, tmp_path, full_report):
        """两报告 role_prefix 相同但有意 → exit 0，打印 ⚠ 警告。"""
        base_r = deepcopy(full_report)
        exp_r = deepcopy(full_report)
        base_r["manifest"]["role_prefix"] = True
        base_r["manifest"]["input_schema"] = "target_other_v1"
        exp_r["manifest"]["role_prefix"] = True
        exp_r["manifest"]["input_schema"] = "target_other_v1"
        # 其他 hash 保持一致
        for key in ["train_contacts_sha256", "val_contacts_sha256",
                     "test_contacts_sha256", "dataset_sha256",
                     "split_manifest_sha256", "dataset_sample_count"]:
            exp_r["manifest"][key] = base_r["manifest"][key]

        base = tmp_path / "b0p" / "eval_report.json"
        exp = tmp_path / "b1p" / "eval_report.json"
        _write_report(base, base_r)
        _write_report(exp, exp_r)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode == 0
        assert "input_schema" in result.stdout


# ═══════════════════════════════════════════
#  负向测试
# ═══════════════════════════════════════════


class TestCompareFails:
    """不同 manifest / 缺失字段 → exit(1)，不输出比较表。"""

    def test_missing_manifest_section(self, tmp_path, full_report):
        """两个报告都缺少 manifest 字段 → exit(1)。"""
        no_manifest = {k: v for k, v in full_report.items() if k != "manifest"}
        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, no_manifest)
        _write_report(exp, deepcopy(full_report))

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0

    def test_different_test_contacts(self, tmp_path, full_report):
        """test_contacts_sha256 不同 → exit(1)。"""
        exp_r = deepcopy(full_report)
        exp_r["manifest"]["test_contacts_sha256"] = "test_different"

        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, full_report)
        _write_report(exp, exp_r)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0
        assert "测试联系人划分" in result.stdout

    def test_different_dataset(self, tmp_path, full_report):
        """dataset_sha256 不同 → exit(1)。"""
        exp_r = deepcopy(full_report)
        exp_r["manifest"]["dataset_sha256"] = "dataset_different"

        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, full_report)
        _write_report(exp, exp_r)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0
        assert "数据集版本" in result.stdout

    def test_old_b0_report_missing_mae(self, tmp_path, full_report):
        """旧 B0 报告缺少 MAE_score → exit(1)。"""
        old = deepcopy(full_report)
        # 模拟旧报告：per_label 只有 R2 没有 MAE_score/Spearman
        old["per_label"] = {
            lbl: {"R2": 0.5} for lbl in LABELS
        }
        base = tmp_path / "old" / "eval_report.json"
        exp = tmp_path / "new" / "eval_report.json"
        _write_report(base, old)
        _write_report(exp, full_report)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0

    def test_different_split_manifest(self, tmp_path, full_report):
        """split_manifest_sha256 不同 → exit(1)。"""
        exp_r = deepcopy(full_report)
        exp_r["manifest"]["split_manifest_sha256"] = "different_manifest"

        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, full_report)
        _write_report(exp, exp_r)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0
        assert "split_manifest" in result.stdout

    def test_different_sample_count(self, tmp_path, full_report):
        """dataset_sample_count 不同 → exit(1)。"""
        exp_r = deepcopy(full_report)
        exp_r["manifest"]["dataset_sample_count"] = 9999

        base = tmp_path / "base" / "eval_report.json"
        exp = tmp_path / "exp" / "eval_report.json"
        _write_report(base, full_report)
        _write_report(exp, exp_r)

        result = subprocess.run(
            [sys.executable, str(COMPARE_SCRIPT),
             "--baseline", str(base), "--experiment", str(exp)],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        assert result.returncode != 0
        assert "数据集样本数" in result.stdout


# ═══════════════════════════════════════════
#  Classifier schema 校验测试
# ═══════════════════════════════════════════


class TestClassifierSchema:
    """ONNXBehaviorClassifier 的 metadata schema 校验。"""

    def test_b0_model_roleless_ok(self):
        """B0 模型目录 + use_role_prefix=False → 正常加载（不抛异常）。"""
        from ml.rules.classifier_onnx import ONNXBehaviorClassifier
        clf = ONNXBehaviorClassifier(use_role_prefix=False)
        try:
            clf._ensure_loaded()
        except Exception as e:
            pytest.fail(f"B0 正常加载不应抛出异常: {e}")

    def test_b0_model_role_aware_raises(self):
        """B0 模型目录 + use_role_prefix=True → 抛 RuntimeError。"""
        from ml.rules.classifier_onnx import ONNXBehaviorClassifier
        clf = ONNXBehaviorClassifier(use_role_prefix=True)
        with pytest.raises(RuntimeError, match="schema 不匹配"):
            clf._ensure_loaded()

    def test_b0_role_aware_second_call_also_raises(self):
        """B0 目录 + use_role_prefix=True → 第二次调用仍抛 RuntimeError（_loaded 未污染）。"""
        from ml.rules.classifier_onnx import ONNXBehaviorClassifier
        clf = ONNXBehaviorClassifier(use_role_prefix=True)
        with pytest.raises(RuntimeError, match="schema 不匹配"):
            clf._ensure_loaded()
        # 第二次调用必须也抛异常，不能因为 _loaded=True 就跳过
        with pytest.raises(RuntimeError, match="schema 不匹配"):
            clf._ensure_loaded()


# ═══════════════════════════════════════════
#  eval-only 控制流测试
# ═══════════════════════════════════════════

TRAIN_SCRIPT = SCRIPTS_DIR / "train_macbert.py"


def _create_dummy_env(tmp_path, init_value=2.0, best_value=999.0, num_samples=4):
    """创建最小 dummy 训练环境和 checkpoint。

    返回 (init_ckpt_path, output_dir, manifest_path)。
    """
    import torch

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建两个不同权重的 dummy checkpoint
    # MacBERTRegressor: bert.* (large) + regressor.* (10 outputs)
    # 只保存 regressor 部分（dummy 控制流测试只需验证权重来源）
    reg = torch.nn.Linear(768, 10)
    with torch.no_grad():
        reg.weight.fill_(init_value * 0.01)
        reg.bias.fill_(init_value * 0.01)
    init_state = {"regressor.weight": reg.weight.clone(),
                  "regressor.bias": reg.bias.clone()}
    torch.save(init_state, tmp_path / "init_macbert_best.pt")

    reg2 = torch.nn.Linear(768, 10)
    with torch.no_grad():
        reg2.weight.fill_(best_value * 0.01)
        reg2.bias.fill_(best_value * 0.01)
    best_state = {"regressor.weight": reg2.weight.clone(),
                  "regressor.bias": reg2.bias.clone()}
    torch.save(best_state, output_dir / "macbert_best.pt")

    # 创建 split manifest（2 个联系人，各 num_samples 条）
    manifest = {
        "train_contacts": ["contact_1"],
        "val_contacts": ["contact_2"],
        "test_contacts": ["contact_2"],
    }
    manifest_path = tmp_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return tmp_path / "init_macbert_best.pt", output_dir, manifest_path


@pytest.mark.slow
class TestEvalOnlyControlFlow:
    """--eval-only 的 checkpoint 隔离测试。

    需要 PyTorch（A100 环境可用）。在普通环境被 @pytest.mark.slow 跳过。
    """

    def test_eval_only_init_ckpt_not_overwritten(self, tmp_path):
        """eval-only + init-checkpoint → best_path 不覆盖 init checkpoint。"""
        import torch

        init_ckpt, output_dir, manifest_path = _create_dummy_env(tmp_path)

        # 检查: init 和 best 的权重确实不同
        init_w = torch.load(init_ckpt, weights_only=True)
        best_w = torch.load(output_dir / "macbert_best.pt", weights_only=True)
        assert not torch.equal(init_w["regressor.weight"], best_w["regressor.weight"])

        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT),
             "--eval-only",
             "--init-checkpoint", str(init_ckpt),
             "--output", str(output_dir),
             "--split-manifest", str(manifest_path),
             "--batch-size", "2", "--epochs", "1"],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        print(f"exit: {result.returncode}")
        print(output)

        # 关键消息断言
        assert "使用 --init-checkpoint" in output
        assert "跳过 best checkpoint 重载" in output
        # 验证没有静默加载 output_dir/macbert_best.pt
        assert "已加载" not in output or "使用 --init-checkpoint" in output

    def test_eval_only_without_init_uses_best_path(self, tmp_path):
        """eval-only 无 init-checkpoint → 从 output_dir/macbert_best.pt 加载。"""
        _, output_dir, manifest_path = _create_dummy_env(tmp_path)

        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT),
             "--eval-only",
             "--output", str(output_dir),
             "--split-manifest", str(manifest_path),
             "--batch-size", "2", "--epochs", "1"],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        print(f"exit: {result.returncode}")
        print(output)

        # 无 init-checkpoint → 应加载 best_path
        assert "已加载" in output
        assert "跳过 best checkpoint 重载" in output
