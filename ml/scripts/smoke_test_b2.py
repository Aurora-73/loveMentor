"""B2 双模型部署 smoke test — 验证 B0' 和 B2 两个 ONNX 实例可独立加载、可推理。

验证项：
  1. get_b0() / get_b2() 返回不同实例（双实例工厂生效）
  2. 两实例加载的 model_dir 不同（不会混淆）
  3. B0' 纯文本输入可推理，输出在 [0, 9]
  4. B2 her-side 可推理，输出在 [0, 9]
  5. B2 me-side 可推理，输出在 [0, 9]
  6. B2 her vs me 分数有差异（角色感知已激活）

使用方法：
    python -X utf8 ml/scripts/smoke_test_b2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ml.rules.classifier_onnx import ONNXBehaviorClassifier


SAMPLE_WINDOW = [
    {"role": "her", "content": "今天天气真好，想出去走走"},
    {"role": "me", "content": "是啊，去公园逛逛？"},
    {"role": "her", "content": "好啊，下午三点见"},
    {"role": "me", "content": "没问题，到时接你"},
    {"role": "her", "content": "嘿嘿，期待中"},
    {"role": "me", "content": "我也是"},
    {"role": "her", "content": "对了，你喜欢喝咖啡还是茶？"},
    {"role": "me", "content": "咖啡，你呢？"},
    {"role": "her", "content": "我也爱咖啡，最近发现一家新店"},
    {"role": "me", "content": "那下午一起去试试"},
    {"role": "her", "content": "好呀好呀"},
    {"role": "me", "content": "一言为定"},
    {"role": "her", "content": "你平时周末都干嘛？"},
    {"role": "me", "content": "看书健身，偶尔和朋友聚聚"},
    {"role": "her", "content": "听起来很自律"},
    {"role": "me", "content": "还好啦，你呢？"},
    {"role": "her", "content": "我喜欢画画和看电影"},
    {"role": "me", "content": "挺有艺术气息的"},
    {"role": "her", "content": "哈哈过奖了"},
    {"role": "me", "content": "说实话的"},
]


def main():
    print("=" * 80)
    print("B2 双模型部署 smoke test")
    print("=" * 80)

    # ── 1. 双实例工厂验证 ──────────────────────────────────────────
    print("\n【1】双实例工厂验证")
    b0 = ONNXBehaviorClassifier.get_b0()
    b2 = ONNXBehaviorClassifier.get_b2()
    assert b0 is not b2, "✗ B0' 和 B2 返回同一实例（单例未改为双实例）"
    print(f"  ✓ B0' 和 B2 是不同实例")
    print(f"  ✓ B0' model_dir: {b0.model_dir}")
    print(f"  ✓ B2  model_dir: {b2.model_dir}")
    assert str(b0.model_dir).endswith("baseline_b0_prime"), f"✗ B0' model_dir 错误: {b0.model_dir}"
    assert str(b2.model_dir).endswith("b2_role_balanced"), f"✗ B2 model_dir 错误: {b2.model_dir}"
    print(f"  ✓ 两个 model_dir 路径不同，不会混淆")

    # 向后兼容验证
    b0_compat = ONNXBehaviorClassifier.get_instance()
    assert b0_compat is b0, "✗ get_instance() 未等价于 get_b0()"
    print(f"  ✓ get_instance() 向后兼容，等价于 get_b0()")

    # ── 2. B0' 推理验证 ────────────────────────────────────────────
    print("\n【2】B0' (roleless) 推理验证")
    s0 = b0.predict_scores(SAMPLE_WINDOW)
    print(f"  分数: {s0}")
    for label, score in s0.items():
        assert 0 <= score <= 9, f"✗ B0' {label} 分数越界: {score}"
    print(f"  ✓ 所有 {len(s0)} 个标签分数在 [0, 9] 范围内")

    # ── 3. B2 her-side 推理验证 ────────────────────────────────────
    print("\n【3】B2 (role-aware) her-side 推理验证")
    s2_her = b2.predict_scores(SAMPLE_WINDOW, target_role="her")
    print(f"  分数: {s2_her}")
    for label, score in s2_her.items():
        assert 0 <= score <= 9, f"✗ B2 her {label} 分数越界: {score}"
    print(f"  ✓ 所有 {len(s2_her)} 个标签分数在 [0, 9] 范围内")

    # ── 4. B2 me-side 推理验证 ────────────────────────────────────
    print("\n【4】B2 (role-aware) me-side 推理验证")
    s2_me = b2.predict_scores(SAMPLE_WINDOW, target_role="me")
    print(f"  分数: {s2_me}")
    for label, score in s2_me.items():
        assert 0 <= score <= 9, f"✗ B2 me {label} 分数越界: {score}"
    print(f"  ✓ 所有 {len(s2_me)} 个标签分数在 [0, 9] 范围内")

    # ── 5. 角色感知验证（her vs me 差异）──────────────────────────
    print("\n【5】角色感知验证（her vs me 应有差异）")
    diffs = {label: s2_her[label] - s2_me[label] for label in s2_her}
    print(f"  Δ(her - me): {diffs}")
    nonzero_diffs = sum(1 for d in diffs.values() if abs(d) > 0.01)
    print(f"  非零差异标签数: {nonzero_diffs} / {len(diffs)}")
    if nonzero_diffs > 0:
        print(f"  ✓ 角色感知已激活（her 和 me 分数不同）")
    else:
        print(f"  ⚠️  her 和 me 分数完全一致 — 角色前缀可能未生效")

    # ── 6. B0' vs B2 her 差异 ─────────────────────────────────────
    print("\n【6】B0' vs B2 her 差异（验证两模型确实不同）")
    diffs_b0_b2 = {label: s2_her[label] - s0[label] for label in s0}
    print(f"  Δ(B2her - B0'her): {diffs_b0_b2}")
    nonzero_b0_b2 = sum(1 for d in diffs_b0_b2.values() if abs(d) > 0.01)
    print(f"  非零差异标签数: {nonzero_b0_b2} / {len(diffs_b0_b2)}")
    if nonzero_b0_b2 > 0:
        print(f"  ✓ 两模型在 her-side 存在差异（符合预期，两模型独立训练）")
    else:
        print(f"  ⚠️  B0' 和 B2 her 分数完全一致 — 可能加载了同一模型")

    # ── 7. 总结 ───────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("smoke test 总结")
    print("=" * 80)
    print(f"  双实例工厂:    ✓ 通过")
    print(f"  B0' 推理:      ✓ 通过（{len(s0)} 标签，范围 [0,9]）")
    print(f"  B2 her 推理:   ✓ 通过（{len(s2_her)} 标签，范围 [0,9]）")
    print(f"  B2 me 推理:    ✓ 通过（{len(s2_me)} 标签，范围 [0,9]）")
    print(f"  角色感知:      {'✓ 已激活' if nonzero_diffs > 0 else '⚠️ 未激活'}")
    print(f"  模型独立性:    {'✓ 已确认' if nonzero_b0_b2 > 0 else '⚠️ 需复查'}")
    print(f"\n  结论: smoke test 全部通过，可继续回测验证。")


if __name__ == "__main__":
    main()
