"""语义回测：B0' / B2 双模型三趟对比验证。

对每个回测案例同时跑三个配置：
  - b0_her : B0' roleless（生产基线），target_role="her"
  - b2_her : B2 role-aware，target_role="her"
  - b2_me  : B2 role-aware，target_role="me"

核心验证目标（见 plan/b2_deployment.md 第三部分）：
  1. B2 her-side 和 B0' 行为一致吗？（per-label MAE < 0.05 门槛）
  2. 什么场景差异最大？（差异 >1 分的案例定位）
  3. B2 me-side 在具体案例上合理吗？（her vs me 差异方向）
  4. 回测结果是否符合四条决策规则？
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.semantic import (
    _build_turns, _extract_windows, _classify_window_onnx,
    _compute_emotion_balance, _compute_interest_signal,
    _compute_friendship_signal, _compute_conversation_depth,
    LABELS,
)


# 案例定义：wxid, 姓名, 结果, 分析起始, 分析结束, 备注
# 注意：以下为脱敏测试数据，真实 wxid 和姓名已替换为通用占位符
SEMANTIC_CASES = [
    # 成功案例：在一起前的互动期
    ("wxid_test_001", "测试联系人A", "success",
     datetime(2026, 4, 1), datetime(2026, 5, 10), "在一起前30天"),
    ("wxid_test_002", "测试联系人B", "success",
     datetime(2026, 5, 28), datetime(2026, 6, 26), "在一起前30天"),
    ("wxid_test_003", "测试联系人C", "success",
     datetime(2026, 3, 15), datetime(2026, 4, 14), "在一起前30天"),

    # 成功转失败：在一起前
    ("wxid_test_004", "测试联系人D", "success_to_failure",
     datetime(2025, 10, 5), datetime(2025, 11, 4), "在一起前30天"),

    # 半步成功
    ("wxid_test_005", "测试联系人E", "half_success",
     datetime(2026, 3, 23), datetime(2026, 4, 22), "互动高峰期"),

    # 发展中
    ("wxid_test_006", "测试联系人F", "developing",
     datetime(2026, 6, 8), datetime(2026, 7, 8), "最近30天"),

    # 异常失败：composite 上升但失败
    ("wxid_test_007", "测试联系人G", "failure",
     datetime(2026, 1, 1), datetime(2026, 3, 20), "composite上升期(异常)"),

    # 友谊区
    ("wxid_test_008", "测试联系人H", "friendzone",
     datetime(2025, 12, 1), datetime(2026, 1, 30), "友谊区互动期"),
]


def query_messages_in_range(conn, config, wxid, start_dt, end_dt):
    """查询指定时间段的消息。"""
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    rows = conn.execute(
        "SELECT id, sender_id, content, timestamp, type "
        "FROM messages WHERE conversation_id = ? AND type = 1 "
        "AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp ASC",
        (wxid, start_ts, end_ts),
    ).fetchall()
    messages = []
    for row in rows:
        sender_id = row["sender_id"] or ""
        messages.append({
            "id": row["id"],
            "sender_id": sender_id,
            "is_mine": sender_id == config.my_wxid,
            "content": row["content"] or "",
            "timestamp": row["timestamp"],
        })
    return messages


def _run_pass(windows_turns, model, target_role):
    """跑一趟推理，返回每个标签最近3窗口均值。"""
    window_scores = []
    for wt in windows_turns:
        scores, _ = _classify_window_onnx(wt, model=model, target_role=target_role)
        window_scores.append(scores)

    recent = window_scores[-3:] if len(window_scores) >= 3 else window_scores
    avg_scores = {}
    for label in LABELS:
        vals = [w.get(label, 0) for w in recent]
        avg_scores[label] = round(sum(vals) / len(vals), 2)
    return avg_scores


def analyze_case(conn, config, wxid, name, start_dt, end_dt):
    """对单个案例做三趟对比语义分析（B0' her / B2 her / B2 me）。"""
    messages = query_messages_in_range(conn, config, wxid, start_dt, end_dt)
    if len(messages) < 5:
        return None

    turns = _build_turns(messages, config.my_wxid)
    windows_turns = _extract_windows(turns)
    if not windows_turns:
        return None

    # 三趟对比
    b0_her = _run_pass(windows_turns, model="b0", target_role="her")
    b2_her = _run_pass(windows_turns, model="b2", target_role="her")
    b2_me = _run_pass(windows_turns, model="b2", target_role="me")

    # 派生指标以 B2 her 为基准（决策门槛的核心对比对象）
    emotion_balance = _compute_emotion_balance(b2_her)
    interest_signal = _compute_interest_signal(b2_her)
    friendship_signal = _compute_friendship_signal(b2_her)
    conversation_depth = _compute_conversation_depth(b2_her)

    info = b2_her.get("information_exchange", 0)
    emo_pos = b2_her.get("emotion_positive", 0)
    emo_neg = b2_her.get("emotion_negative", 0)
    flirt = b2_her.get("flirt", 0)
    info_vs_emotion = round(info / (emo_pos + emo_neg + flirt + 0.1), 2)

    return {
        "msg_count": len(messages),
        "window_count": len(windows_turns),
        "b0_her": b0_her,
        "b2_her": b2_her,
        "b2_me": b2_me,
        "emotion_balance": emotion_balance,
        "interest_signal": interest_signal,
        "friendship_signal": friendship_signal,
        "conversation_depth": conversation_depth,
        "info_vs_emotion": info_vs_emotion,
    }


def main():
    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row

    print("=" * 160)
    print("语义回测：B0' / B2 双模型三趟对比验证")
    print("=" * 160)

    results = []
    for wxid, name, outcome, start_dt, end_dt, note in SEMANTIC_CASES:
        print(f"分析中: {name} ({outcome}) {start_dt.date()}~{end_dt.date()} ...", end=" ", flush=True)
        r = analyze_case(conn, config, wxid, name, start_dt, end_dt)
        if r is None:
            print("数据不足，跳过")
            continue
        r["name"] = name
        r["outcome"] = outcome
        r["note"] = note
        results.append(r)
        print(f"✓ {r['msg_count']}条消息, {r['window_count']}窗口")

    conn.close()

    if not results:
        print("无有效结果。")
        return

    outcome_names = {
        "success": "✅成功",
        "success_to_failure": "⚠️成功转失败",
        "half_success": "🟡半步成功",
        "developing": "🔄发展中",
        "friendzone": "🟦友谊区",
        "failure": "❌失败",
    }

    # ── 1. 三趟对比明细表 ────────────────────────────────────────────
    print("\n" + "=" * 160)
    print("【表1】三趟对比明细 — 每个标签的 B0' her / B2 her / B2 me 分数（0-9）")
    print("=" * 160)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        print(f"\n  {r['name']} ({outcome_names.get(r['outcome'], r['outcome'])}) — {r['note']}")
        print(f"  {'标签':<24} {'B0′her':<10} {'B2her':<10} {'B2me':<10} {'Δher':<10} {'Δme-her':<10}")
        print("  " + "-" * 80)
        for label in LABELS:
            b0 = r["b0_her"].get(label, 0)
            b2h = r["b2_her"].get(label, 0)
            b2m = r["b2_me"].get(label, 0)
            d_her = b2h - b0
            d_me_her = b2m - b2h
            print(f"  {label:<24} {b0:<10.2f} {b2h:<10.2f} {b2m:<10.2f} "
                  f"{d_her:<+10.2f} {d_me_her:<+10.2f}")

    # ── 2. 对比汇总表（按部署文档要求的输出格式）──────────────────────
    print("\n" + "=" * 160)
    print("【表2】对比汇总 — B0' her-avg / B2 her-avg / B2 me-avg / Δher / Δme-her（10标签均值）")
    print("=" * 160)
    print(f"\n{'姓名':<12} {'结果':<14} {'B0′her':<10} {'B2her':<10} {'B2me':<10} "
          f"{'Δher':<10} {'Δme-her':<10} {'备注'}")
    print("-" * 100)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        b0_avg = sum(r["b0_her"].get(l, 0) for l in LABELS) / len(LABELS)
        b2h_avg = sum(r["b2_her"].get(l, 0) for l in LABELS) / len(LABELS)
        b2m_avg = sum(r["b2_me"].get(l, 0) for l in LABELS) / len(LABELS)
        d_her = b2h_avg - b0_avg
        d_me_her = b2m_avg - b2h_avg
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{b0_avg:<10.3f} {b2h_avg:<10.3f} {b2m_avg:<10.3f} "
              f"{d_her:<+10.3f} {d_me_her:<+10.3f} {r['note']}")

    # ── 3. 派生指标（基于 B2 her）──────────────────────────────────
    print("\n" + "=" * 160)
    print("【表3】派生指标（Layer 2 融合，基于 B2 her 分数）")
    print("=" * 160)
    print(f"\n{'姓名':<12} {'结果':<14} {'emo_bal':<10} {'interest':<10} {'friend':<10} "
          f"{'depth':<10} {'info/emo':<10} {'备注'}")
    print("-" * 100)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{r['emotion_balance']:<10.3f} {r['interest_signal']:<10.3f} "
              f"{r['friendship_signal']:<10.3f} {r['conversation_depth']:<10.3f} "
              f"{r['info_vs_emotion']:<10.2f} {r['note']}")

    # ── 4. 分组均值（按结果类型）──────────────────────────────────
    print("\n" + "=" * 160)
    print("【表4】按结果类型分组的语义指标均值（基于 B2 her）")
    print("=" * 160)
    groups = defaultdict(list)
    for r in results:
        groups[r["outcome"]].append(r)

    print(f"\n{'结果类型':<16} {'人数':<5} {'emo_bal':<10} {'interest':<10} {'friend':<10} "
          f"{'depth':<10} {'info/emo':<10} {'flirt':<8}")
    print("-" * 90)
    for outcome in ["success", "success_to_failure", "half_success", "developing", "friendzone", "failure"]:
        items = groups.get(outcome, [])
        if not items:
            continue
        n = len(items)
        avg = lambda k: sum(r[k] for r in items) / n
        avg_flirt = sum(r["b2_her"].get("flirt", 0) for r in items) / n
        print(f"{outcome_names.get(outcome, outcome):<16} {n:<5} "
              f"{avg('emotion_balance'):<10.3f} {avg('interest_signal'):<10.3f} "
              f"{avg('friendship_signal'):<10.3f} {avg('conversation_depth'):<10.3f} "
              f"{avg('info_vs_emotion'):<10.2f} {avg_flirt:<8.2f}")

    # ── 5. 关键区分度（成功类 vs 失败类，三趟对比）──────────────────
    print("\n" + "=" * 160)
    print("【表5】关键区分度分析 — 成功类 vs 失败类（三趟对比）")
    print("=" * 160)
    success_types = ["success", "half_success", "developing"]
    failure_types = ["friendzone", "failure"]

    success_items = [r for r in results if r["outcome"] in success_types]
    failure_items = [r for r in results if r["outcome"] in failure_types]

    if success_items and failure_items:
        print(f"\n成功类({len(success_items)}人) vs 失败类({len(failure_items)}人):")
        print(f"{'指标':<24} {'B0′her-S':<10} {'B0′her-F':<10} {'B2her-S':<10} {'B2her-F':<10} "
              f"{'B2me-S':<10} {'B2me-F':<10} {'区分度'}")
        print("-" * 120)
        for label in LABELS:
            s_b0 = sum(r["b0_her"].get(label, 0) for r in success_items) / len(success_items)
            f_b0 = sum(r["b0_her"].get(label, 0) for r in failure_items) / len(failure_items)
            s_b2h = sum(r["b2_her"].get(label, 0) for r in success_items) / len(success_items)
            f_b2h = sum(r["b2_her"].get(label, 0) for r in failure_items) / len(failure_items)
            s_b2m = sum(r["b2_me"].get(label, 0) for r in success_items) / len(success_items)
            f_b2m = sum(r["b2_me"].get(label, 0) for r in failure_items) / len(failure_items)
            diff = s_b2h - f_b2h
            quality = "强" if abs(diff) > 1.0 else ("中" if abs(diff) > 0.5 else "弱")
            print(f"{label:<24} {s_b0:<10.3f} {f_b0:<10.3f} {s_b2h:<10.3f} {f_b2h:<10.3f} "
                  f"{s_b2m:<10.3f} {f_b2m:<10.3f} {quality}")

        # 派生指标区分度
        print(f"\n{'派生指标':<24} {'成功类':<12} {'失败类':<12} {'差异':<12} {'区分度'}")
        print("-" * 70)
        for metric in ["emotion_balance", "interest_signal", "friendship_signal", "conversation_depth", "info_vs_emotion"]:
            s_avg = sum(r[metric] for r in success_items) / len(success_items)
            f_avg = sum(r[metric] for r in failure_items) / len(failure_items)
            diff = s_avg - f_avg
            quality = "强" if abs(diff) > 0.2 else ("中" if abs(diff) > 0.1 else "弱")
            print(f"{metric:<24} {s_avg:<12.4f} {f_avg:<12.4f} {diff:<+12.4f} {quality}")

    # ── 6. 决策规则门槛检查 ────────────────────────────────────────
    print("\n" + "=" * 160)
    print("【表6】四条决策规则门槛检查")
    print("=" * 160)

    # 规则1：B2 her 相对 B0' 不出现关键标签显著退化（per-label MAE < 0.05）
    print("\n规则1：B2 her vs B0' per-label MAE（门槛 < 0.05）")
    print(f"{'标签':<24} {'MAE':<10} {'门槛':<10} {'通过'}")
    print("-" * 60)
    rule1_pass = True
    for label in LABELS:
        diffs = [abs(r["b2_her"].get(label, 0) - r["b0_her"].get(label, 0)) for r in results]
        mae = sum(diffs) / len(diffs) if diffs else 0
        passed = mae < 0.05
        if not passed:
            rule1_pass = False
        print(f"{label:<24} {mae:<10.4f} {0.05:<10.2f} {'✓' if passed else '✗'}")

    # 规则1补充：极端差异案例（|Δ| > 1.0）
    print("\n规则1补充：极端差异案例（|B2her - B0'her| > 1.0 分）")
    extreme_cases = []
    for r in results:
        for label in LABELS:
            diff = r["b2_her"].get(label, 0) - r["b0_her"].get(label, 0)
            if abs(diff) > 1.0:
                extreme_cases.append((r["name"], label, r["b0_her"].get(label, 0),
                                      r["b2_her"].get(label, 0), diff))
    if extreme_cases:
        print(f"{'姓名':<12} {'标签':<24} {'B0′her':<10} {'B2her':<10} {'Δ':<10}")
        print("-" * 70)
        for name, label, b0, b2h, diff in extreme_cases:
            print(f"{name:<12} {label:<24} {b0:<10.2f} {b2h:<10.2f} {diff:<+10.2f}")
    else:
        print("  无极端差异案例。")

    # 规则1补充：解释方向反转案例
    print("\n规则1补充：解释方向反转检查（成功/失败类的标签排序是否反转）")
    if success_items and failure_items:
        for label in LABELS:
            s_b0 = sum(r["b0_her"].get(label, 0) for r in success_items) / len(success_items)
            f_b0 = sum(r["b0_her"].get(label, 0) for r in failure_items) / len(failure_items)
            s_b2h = sum(r["b2_her"].get(label, 0) for r in success_items) / len(success_items)
            f_b2h = sum(r["b2_her"].get(label, 0) for r in failure_items) / len(failure_items)
            b0_dir = s_b0 - f_b0
            b2h_dir = s_b2h - f_b2h
            reversed_dir = (b0_dir > 0) != (b2h_dir > 0) and abs(b0_dir) > 0.1 and abs(b2h_dir) > 0.1
            if reversed_dir:
                print(f"  ⚠️ {label}: B0′ 方向={b0_dir:+.3f}, B2 方向={b2h_dir:+.3f} — 方向反转")
        print("  （未列出的标签方向一致）")

    # 规则3：B2 me-side 差异方向合理性
    print("\n规则3：B2 me-side 差异方向（her vs me 差异是否合理）")
    print(f"{'姓名':<12} {'结果':<14} {'B2her-avg':<12} {'B2me-avg':<12} {'Δme-her':<12} {'方向'}")
    print("-" * 80)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        b2h_avg = sum(r["b2_her"].get(l, 0) for l in LABELS) / len(LABELS)
        b2m_avg = sum(r["b2_me"].get(l, 0) for l in LABELS) / len(LABELS)
        d = b2m_avg - b2h_avg
        direction = "me<her" if d < -0.1 else ("me>her" if d > 0.1 else "≈")
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{b2h_avg:<12.3f} {b2m_avg:<12.3f} {d:<+12.3f} {direction}")

    # ── 7. 异常案例分析（三趟对比视角）──────────────────────────────
    print("\n" + "=" * 160)
    print("【表7】异常案例分析（composite 上升但失败）— 三趟对比")
    print("=" * 160)
    xiwei = next((r for r in results if r["name"] == "测试联系人G"), None)
    if xiwei:
        print(f"\n该案例的三趟画像（10 维标签）：")
        print(f"  {'标签':<24} {'B0′her':<10} {'B2her':<10} {'B2me':<10} {'Δher':<10} {'Δme-her':<10}")
        print("  " + "-" * 80)
        for label in LABELS:
            b0 = xiwei["b0_her"].get(label, 0)
            b2h = xiwei["b2_her"].get(label, 0)
            b2m = xiwei["b2_me"].get(label, 0)
            print(f"  {label:<24} {b0:<10.2f} {b2h:<10.2f} {b2m:<10.2f} "
                  f"{b2h-b0:<+10.2f} {b2m-b2h:<+10.2f}")

        print(f"\n  派生指标（B2 her）:")
        print(f"    interest_signal:    {xiwei['interest_signal']:.3f}")
        print(f"    conversation_depth: {xiwei['conversation_depth']:.3f}")
        print(f"    info_vs_emotion:    {xiwei['info_vs_emotion']:.2f} (信息/情感比, 越高越偏信息交换)")

        print(f"\n  解读: {'聊天停在信息层面, 缺少情感升级和暧昧' if xiwei['info_vs_emotion'] > 2.0 and xiwei['b2_her'].get('flirt', 0) < 2.0 else '需进一步分析'}")

    # ── 8. 导出 CSV ────────────────────────────────────────────────
    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "semantic_backtest_3pass.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        header_parts = ["姓名", "结果", "消息数", "窗口数"]
        for label in LABELS:
            header_parts.extend([f"{label}_b0her", f"{label}_b2her", f"{label}_b2me"])
        header_parts += ["emotion_balance", "interest_signal", "friendship_signal",
                         "conversation_depth", "info_vs_emotion", "备注"]
        f.write(",".join(header_parts) + "\n")
        for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
            parts = [r["name"], r["outcome"], str(r["msg_count"]), str(r["window_count"])]
            for label in LABELS:
                parts += [f"{r['b0_her'].get(label, 0):.2f}",
                          f"{r['b2_her'].get(label, 0):.2f}",
                          f"{r['b2_me'].get(label, 0):.2f}"]
            parts += [f"{r['emotion_balance']:.3f}", f"{r['interest_signal']:.3f}",
                      f"{r['friendship_signal']:.3f}", f"{r['conversation_depth']:.3f}",
                      f"{r['info_vs_emotion']:.2f}", r["note"]]
            f.write(",".join(parts) + "\n")
    print(f"\n三趟对比回测数据已导出到: {output_path}")

    # ── 9. 决策门槛总结 ────────────────────────────────────────────
    print("\n" + "=" * 160)
    print("【决策门槛总结】")
    print("=" * 160)
    print(f"\n规则1（上线门槛）: B2 her vs B0' per-label MAE < 0.05")
    all_maes = []
    for label in LABELS:
        diffs = [abs(r["b2_her"].get(label, 0) - r["b0_her"].get(label, 0)) for r in results]
        mae = sum(diffs) / len(diffs) if diffs else 0
        all_maes.append((label, mae))
    max_mae_label, max_mae = max(all_maes, key=lambda x: x[1])
    print(f"  最大 MAE: {max_mae_label} = {max_mae:.4f} ({'通过' if max_mae < 0.05 else '未通过'})")
    print(f"  极端差异案例数: {len(extreme_cases)}")
    print(f"  整体评估: {'通过 — B2 her 可作为默认' if rule1_pass and not extreme_cases else '需人工复核 — 存在显著差异或极端案例'}")
    print(f"\n规则3（me-side 限制）: 不直接输出确定性结论，仅作对比辅助输入")
    print(f"  ✓ 已在产品层语义中约束（见 plan/b2_deployment.md 第三部分）")
    print(f"\n规则4（回滚策略）: B2 加载失败 → 自动回退 B0'")
    print(f"  ✓ 由 get_b2() 异常传播机制保障，调用侧可 catch 后回退 get_b0()")


if __name__ == "__main__":
    main()
