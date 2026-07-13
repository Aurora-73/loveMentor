#!/bin/bash
# B0' eval-only（刷新带分域指标的评估报告）→ B1' 训练
# 用法: bash scripts/run_b1_experiments.sh
# 输出: models/baseline_b0_prime/eval_report.json（含 slices.clean/slices.external）
#       models/role_aware_b1_prime/（B1' 模型 + 评估报告）

set -e

cd /home2/cme_code/lm/ml
PY=/home2/cme_code/convert/python_env/bin/python3

echo "============================================"
echo "步骤 1/2: B0' --eval-only（补充分域指标）"
echo "============================================"
$PY scripts/train_macbert.py \
  --epochs 1 --batch-size 32 \
  --split-manifest models/canonical_manifest.json \
  --init-checkpoint models/baseline_b0_prime/macbert_best.pt \
  --eval-only \
  --output models/baseline_b0_prime/

echo ""
echo "============================================"
echo "步骤 2/2: B1' 训练（从 MacBERT base，加角色前缀）"
echo "============================================"
$PY scripts/train_macbert.py \
  --epochs 20 --batch-size 32 --lr 2e-5 \
  --role-prefix \
  --split-manifest models/canonical_manifest.json \
  --output models/role_aware_b1_prime/

echo ""
echo "============================================"
echo "完成！"
echo "B0' 分域报告: models/baseline_b0_prime/eval_report.json"
echo "B1' 输出目录: models/role_aware_b1_prime/"
echo ""
echo "B1' 完成后运行比较："
echo "\$PY scripts/compare_experiments.py \\"
echo "  --baseline models/baseline_b0_prime/eval_report.json \\"
echo "  --experiment models/role_aware_b1_prime/eval_report.json"
echo "============================================"
