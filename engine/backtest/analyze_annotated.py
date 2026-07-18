"""基于用户标注分析各案例在新指标下的表现，验证区分度。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import get_annotated_cases


ANNOTATED_CASES = get_annotated_cases()


def main():
    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row

    print(f"标注案例数: {len(ANNOTATED_CASES)}")
    print("=" * 160)

    results = []
    for wxid, name, outcome, note in ANNOTATED_CASES:
        try:
            metrics = compute_metrics_for_contact(conn, config, wxid, name)
            results.append({
                "name": name,
                "outcome": outcome,
                "note": note,
                "composite": metrics.composite,
                "signal": metrics.signal_level,
                "her_init": metrics.her_initiation_rate.normalized,
                "topic_cont": metrics.topic_continuation.normalized,
                "reply_qual": metrics.reply_quality.normalized,
                "sess_bal": metrics.session_balance.normalized,
                "emo_temp": metrics.emotional_temperature.normalized,
                "fz_risk": metrics.friendzone_risk.normalized,
                "fback": metrics.fback.normalized,
                "neediness": metrics.neediness_penalty,
            })
        except Exception as e:
            print(f"{name}: 失败 - {e}")

    conn.close()

    print("\n" + "=" * 160)
    print("按结果类型分组的指标均值")
    print("=" * 160)

    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        groups[r["outcome"]].append(r)

    outcome_names = {
        "success": "✅成功",
        "success_to_failure": "⚠️成功转失败",
        "half_success": "🟡半步成功",
        "developing": "🔄发展中",
        "active_giveup": "🔸主动放弃",
        "passive_giveup": "🔹被动放弃",
        "friendzone": "🟦友谊区",
        "awkward": "🟪线下尴尬",
        "topic_mismatch": "🟫话题不合",
        "lost_contact": "⚫断联",
        "failure": "❌失败",
    }

    print(f"\n{'结果类型':<16} {'人数':<5} {'composite':<10} {'her_init':<10} {'topic_cont':<10} {'reply_qual':<10} {'sess_bal':<8} {'emo_temp':<8} {'fz_risk':<8}")
    print("-" * 100)

    for outcome in ["success", "success_to_failure", "half_success", "developing",
                    "active_giveup", "passive_giveup", "friendzone", "awkward",
                    "topic_mismatch", "lost_contact", "failure"]:
        items = groups.get(outcome, [])
        if not items:
            continue
        n = len(items)
        avg_comp = sum(r["composite"] for r in items) / n
        avg_her = sum(r["her_init"] for r in items) / n
        avg_topic = sum(r["topic_cont"] for r in items) / n
        avg_reply = sum(r["reply_qual"] for r in items) / n
        avg_bal = sum(r["sess_bal"] for r in items) / n
        avg_emo = sum(r["emo_temp"] for r in items) / n
        avg_fz = sum(r["fz_risk"] for r in items) / n
        print(f"{outcome_names.get(outcome, outcome):<16} {n:<5} {avg_comp:<10.4f} {avg_her:<10.4f} {avg_topic:<10.4f} {avg_reply:<10.4f} {avg_bal:<8.3f} {avg_emo:<8.3f} {avg_fz:<8.3f}")

    print("\n" + "=" * 160)
    print("所有标注案例明细（按 composite 降序）")
    print("=" * 160)

    sorted_results = sorted(results, key=lambda x: x["composite"], reverse=True)
    print(f"\n{'姓名':<12} {'结果':<16} {'composite':<10} {'signal':<8} {'her_init':<10} {'topic_cont':<10} {'reply_qual':<10} {'sess_bal':<8} {'emo_temp':<8} {'fz_risk':<8} {'备注'}")
    print("-" * 160)

    for r in sorted_results:
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<16} "
              f"{r['composite']:<10.4f} {r['signal']:<8} "
              f"{r['her_init']:<10.4f} {r['topic_cont']:<10.4f} {r['reply_qual']:<10.4f} "
              f"{r['sess_bal']:<8.3f} {r['emo_temp']:<8.3f} {r['fz_risk']:<8.3f} {r['note']}")

    print("\n" + "=" * 160)
    print("关键区分度分析")
    print("=" * 160)

    success_types = ["success", "half_success", "developing"]
    failure_types = ["friendzone", "topic_mismatch", "lost_contact", "failure"]

    success_items = [r for r in results if r["outcome"] in success_types]
    failure_items = [r for r in results if r["outcome"] in failure_types]

    if success_items and failure_items:
        print(f"\n成功类({len(success_items)}人) vs 失败类({len(failure_items)}人):")
        print(f"{'指标':<15} {'成功类均值':<12} {'失败类均值':<12} {'差异':<12} {'区分度'}")
        print("-" * 70)

        for metric in ["composite", "her_init", "topic_cont", "reply_qual", "sess_bal", "emo_temp"]:
            s_avg = sum(r[metric] for r in success_items) / len(success_items)
            f_avg = sum(r[metric] for r in failure_items) / len(failure_items)
            diff = s_avg - f_avg
            quality = "强" if diff > 0.3 else ("中" if diff > 0.1 else "弱")
            print(f"{metric:<15} {s_avg:<12.4f} {f_avg:<12.4f} {diff:<12.4f} {quality}")

    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "annotated_cases_v2.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("姓名,结果类型,composite,signal,her_init,topic_cont,reply_qual,sess_bal,emo_temp,fz_risk,fback,neediness,备注\n")
        for r in sorted_results:
            f.write(f"{r['name']},{r['outcome']},{r['composite']:.4f},{r['signal']},"
                    f"{r['her_init']:.4f},{r['topic_cont']:.4f},{r['reply_qual']:.4f},"
                    f"{r['sess_bal']:.4f},{r['emo_temp']:.4f},{r['fz_risk']:.4f},"
                    f"{r['fback']:.4f},{r['neediness']:.4f},{r['note']}\n")

    print(f"\n标注案例数据已导出到: {output_path}")


if __name__ == "__main__":
    main()
