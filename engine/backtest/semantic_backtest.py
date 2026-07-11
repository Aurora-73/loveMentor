"""语义回测：用 MacBERT 分析关键案例的聊天内容，验证语义指标区分力。

核心验证目标：
  1. 成功案例 vs 失败案例的语义指标是否有差异
  2. "熹微异常"（composite 上升但失败）能否被语义指标解释
  3. 语义指标能否捕捉行为统计看不到的"聊天停在信息层面"问题
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.semantic import (
    _build_turns, _extract_windows, _classify_window_onnx,
    _compute_emotion_balance, _compute_interest_signal,
    _compute_friendship_signal, _compute_conversation_depth,
    LABELS, WINDOW_SIZE, SLIDE_SIZE, MIN_TURNS,
)


# 案例定义：wxid, 姓名, 结果, 分析起始, 分析结束, 备注
SEMANTIC_CASES = [
    # 成功案例：在一起前的互动期
    ("[REDACTED]", "[REDACTED]", "success",
     datetime(2026, 4, 1), datetime(2026, 5, 10), "在一起前30天"),
    ("[REDACTED]", "[REDACTED]", "success",
     datetime(2026, 5, 28), datetime(2026, 6, 26), "在一起前30天"),
    ("[REDACTED]", "[REDACTED]", "success",
     datetime(2026, 3, 15), datetime(2026, 4, 14), "在一起前30天"),

    # 成功转失败：在一起前
    ("[REDACTED]", "[REDACTED]", "success_to_failure",
     datetime(2025, 10, 5), datetime(2025, 11, 4), "在一起前30天"),

    # 半步成功
    ("wxid_ztmsqkphqjgp22", "biophilia", "half_success",
     datetime(2026, 3, 23), datetime(2026, 4, 22), "互动高峰期"),

    # 发展中
    ("[REDACTED]", "[REDACTED]", "developing",
     datetime(2026, 6, 8), datetime(2026, 7, 8), "最近30天"),

    # 异常失败：composite 上升但失败
    ("[REDACTED]", "[REDACTED]", "failure",
     datetime(2026, 1, 1), datetime(2026, 3, 20), "composite上升期(异常)"),

    # 友谊区
    ("[REDACTED]", "[REDACTED]", "friendzone",
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


def analyze_case(conn, config, wxid, name, start_dt, end_dt):
    """对单个案例做语义分析。"""
    messages = query_messages_in_range(conn, config, wxid, start_dt, end_dt)
    if len(messages) < 5:
        return None

    turns = _build_turns(messages, config.my_wxid)
    windows_turns = _extract_windows(turns)
    if not windows_turns:
        return None

    # 用 MacBERT 分析每个窗口
    window_scores = []
    for wt in windows_turns:
        scores, labels = _classify_window_onnx(wt)
        window_scores.append(scores)

    # 取最近3个窗口的均值
    recent = window_scores[-3:] if len(window_scores) >= 3 else window_scores
    avg_scores = {}
    for label in LABELS:
        vals = [w.get(label, 0) for w in recent]
        avg_scores[label] = round(sum(vals) / len(vals), 2)

    # 派生指标
    emotion_balance = _compute_emotion_balance(avg_scores)
    interest_signal = _compute_interest_signal(avg_scores)
    friendship_signal = _compute_friendship_signal(avg_scores)
    conversation_depth = _compute_conversation_depth(avg_scores)

    # info_vs_emotion: 信息交换占比 vs 情感占比
    info = avg_scores.get("information_exchange", 0)
    emo_pos = avg_scores.get("emotion_positive", 0)
    emo_neg = avg_scores.get("emotion_negative", 0)
    flirt = avg_scores.get("flirt", 0)
    info_vs_emotion = round(info / (emo_pos + emo_neg + flirt + 0.1), 2)

    return {
        "msg_count": len(messages),
        "window_count": len(window_scores),
        "avg_scores": avg_scores,
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

    print("=" * 140)
    print("语义回测：MacBERT 语义指标区分力验证")
    print("=" * 140)

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

    outcome_names = {
        "success": "✅成功",
        "success_to_failure": "⚠️成功转失败",
        "half_success": "🟡半步成功",
        "developing": "🔄发展中",
        "friendzone": "🟦友谊区",
        "failure": "❌失败",
    }

    # 输出明细
    print("\n" + "=" * 140)
    print("10 维行为标签明细（0-9分）")
    print("=" * 140)
    header = f"{'姓名':<12} {'结果':<14} " + " ".join(f"{l[:6]:<8}" for l in LABELS)
    print(header)
    print("-" * 140)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        scores_str = " ".join(f"{r['avg_scores'].get(l, 0):<8.2f}" for l in LABELS)
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} {scores_str}")

    # 派生指标
    print("\n" + "=" * 140)
    print("派生指标（Layer 2 融合）")
    print("=" * 140)
    print(f"\n{'姓名':<12} {'结果':<14} {'emo_bal':<10} {'interest':<10} {'friend':<10} {'depth':<10} {'info/emo':<10} {'备注'}")
    print("-" * 100)
    for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{r['emotion_balance']:<10.3f} {r['interest_signal']:<10.3f} "
              f"{r['friendship_signal']:<10.3f} {r['conversation_depth']:<10.3f} "
              f"{r['info_vs_emotion']:<10.2f} {r['note']}")

    # 分组均值
    print("\n" + "=" * 140)
    print("按结果类型分组的语义指标均值")
    print("=" * 140)
    groups = defaultdict(list)
    for r in results:
        groups[r["outcome"]].append(r)

    print(f"\n{'结果类型':<16} {'人数':<5} {'emo_bal':<10} {'interest':<10} {'friend':<10} {'depth':<10} {'info/emo':<10} {'flirt':<8}")
    print("-" * 90)
    for outcome in ["success", "success_to_failure", "half_success", "developing", "friendzone", "failure"]:
        items = groups.get(outcome, [])
        if not items:
            continue
        n = len(items)
        avg = lambda k: sum(r[k] for r in items) / n
        avg_flirt = sum(r["avg_scores"].get("flirt", 0) for r in items) / n
        print(f"{outcome_names.get(outcome, outcome):<16} {n:<5} "
              f"{avg('emotion_balance'):<10.3f} {avg('interest_signal'):<10.3f} "
              f"{avg('friendship_signal'):<10.3f} {avg('conversation_depth'):<10.3f} "
              f"{avg('info_vs_emotion'):<10.2f} {avg_flirt:<8.2f}")

    # 关键区分度
    print("\n" + "=" * 140)
    print("关键区分度分析")
    print("=" * 140)
    success_types = ["success", "half_success", "developing"]
    failure_types = ["friendzone", "failure"]

    success_items = [r for r in results if r["outcome"] in success_types]
    failure_items = [r for r in results if r["outcome"] in failure_types]

    if success_items and failure_items:
        print(f"\n成功类({len(success_items)}人) vs 失败类({len(failure_items)}人):")
        print(f"{'指标':<20} {'成功类':<12} {'失败类':<12} {'差异':<12} {'区分度'}")
        print("-" * 70)
        for metric in ["emotion_balance", "interest_signal", "friendship_signal", "conversation_depth", "info_vs_emotion"]:
            s_avg = sum(r[metric] for r in success_items) / len(success_items)
            f_avg = sum(r[metric] for r in failure_items) / len(failure_items)
            diff = s_avg - f_avg
            quality = "强" if abs(diff) > 0.2 else ("中" if abs(diff) > 0.1 else "弱")
            print(f"{metric:<20} {s_avg:<12.4f} {f_avg:<12.4f} {diff:<+12.4f} {quality}")

        # 单独看 flirt
        s_flirt = sum(r["avg_scores"].get("flirt", 0) for r in success_items) / len(success_items)
        f_flirt = sum(r["avg_scores"].get("flirt", 0) for r in failure_items) / len(failure_items)
        print(f"{'flirt(原始分)':<20} {s_flirt:<12.4f} {f_flirt:<12.4f} {s_flirt - f_flirt:<+12.4f} {'强' if abs(s_flirt-f_flirt)>1.0 else '弱'}")

    # 熹微异常分析
    print("\n" + "=" * 140)
    print("熹微异常分析（composite 上升但失败）")
    print("=" * 140)
    xiwei = next((r for r in results if r["name"] == "[REDACTED]"), None)
    if xiwei:
        print(f"\n熹微的语义画像:")
        print(f"  information_exchange: {xiwei['avg_scores'].get('information_exchange', 0):.2f} (信息交换)")
        print(f"  emotion_positive:    {xiwei['avg_scores'].get('emotion_positive', 0):.2f} (正向情绪)")
        print(f"  flirt:               {xiwei['avg_scores'].get('flirt', 0):.2f} (暧昧)")
        print(f"  self_disclosure:     {xiwei['avg_scores'].get('self_disclosure', 0):.2f} (自我披露)")
        print(f"  invitation:          {xiwei['avg_scores'].get('invitation', 0):.2f} (邀约)")
        print(f"  framing_boundary:    {xiwei['avg_scores'].get('framing_boundary', 0):.2f} (关系框架)")
        print(f"  interest_signal:     {xiwei['interest_signal']:.3f}")
        print(f"  conversation_depth:  {xiwei['conversation_depth']:.3f}")
        print(f"  info_vs_emotion:     {xiwei['info_vs_emotion']:.2f} (信息/情感比, 越高越偏信息交换)")

        print(f"\n  解读: {'聊天停在信息层面, 缺少情感升级和暧昧' if xiwei['info_vs_emotion'] > 2.0 and xiwei['avg_scores'].get('flirt', 0) < 2.0 else '需进一步分析'}")

    # 导出
    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "semantic_backtest.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        header_parts = ["姓名", "结果", "消息数", "窗口数"] + LABELS + ["emotion_balance", "interest_signal", "friendship_signal", "conversation_depth", "info_vs_emotion", "备注"]
        f.write(",".join(header_parts) + "\n")
        for r in sorted(results, key=lambda x: x["interest_signal"], reverse=True):
            parts = [r["name"], r["outcome"], str(r["msg_count"]), str(r["window_count"])]
            parts += [f"{r['avg_scores'].get(l, 0):.2f}" for l in LABELS]
            parts += [f"{r['emotion_balance']:.3f}", f"{r['interest_signal']:.3f}",
                      f"{r['friendship_signal']:.3f}", f"{r['conversation_depth']:.3f}",
                      f"{r['info_vs_emotion']:.2f}", r["note"]]
            f.write(",".join(parts) + "\n")
    print(f"\n语义回测数据已导出到: {output_path}")


if __name__ == "__main__":
    main()