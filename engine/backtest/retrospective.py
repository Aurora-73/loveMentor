"""时间点回溯分析：计算每个案例在关键时间点的指标，验证预测能力。

关键时间点定义：
  - 成功案例：在一起前 1-7 天（"临门一脚"期）
  - 成功转失败：在一起前 1-7 天
  - 半步成功/发展中/失败：互动最密集期（最后联系前30天，或自定义高峰期）

通过回溯计算，验证"在一起前"的指标是否真能预测成功。
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import get_retro_cases
from engine.importers.db_init import connect_db


RETRO_CASES = get_retro_cases()


def find_peak_date(conn, contact_wxid, window_days=30):
    """找到联系人消息最密集的 window_days 窗口的结束日期。"""
    rows = conn.execute(
        "SELECT timestamp FROM messages WHERE conversation_id = ? AND type = 1 ORDER BY timestamp",
        (contact_wxid,),
    ).fetchall()
    if len(rows) < 2:
        return None
    timestamps = [r["timestamp"] for r in rows]
    window_seconds = window_days * 86400
    best_count = 0
    best_end = timestamps[-1]
    for i, t in enumerate(timestamps):
        count = sum(1 for tt in timestamps if t <= tt <= t + window_seconds)
        if count > best_count:
            best_count = count
            best_end = t + window_seconds
            if best_end > timestamps[-1]:
                best_end = timestamps[-1]
    return datetime.fromtimestamp(best_end)


def main():
    config = load_config()
    conn = connect_db(config.db_path)

    print("=" * 170)
    print("时间点回溯分析：验证'在一起前'的指标预测能力")
    print("=" * 170)

    results = []
    for wxid, name, outcome, key_date, note in RETRO_CASES:
        if key_date is None:
            key_date = find_peak_date(conn, wxid)
            if key_date is None:
                print(f"{name}: 无足够数据，跳过")
                continue
            note = note + f"(自动定位高峰:{key_date.strftime('%Y-%m-%d')})"

        to_ts = int(key_date.timestamp())
        try:
            metrics = compute_metrics_for_contact(conn, config, wxid, name,
                                                   ref_date=key_date, to_ts=to_ts)
            results.append({
                "name": name,
                "outcome": outcome,
                "key_date": key_date.strftime("%Y-%m-%d"),
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

    print(f"\n{'姓名':<12} {'结果':<14} {'回溯日期':<12} {'composite':<10} {'signal':<8} {'her_init':<10} {'topic_cont':<10} {'reply_qual':<10} {'sess_bal':<8} {'emo_temp':<8} {'fz_risk':<8} {'备注'}")
    print("-" * 170)

    sorted_results = sorted(results, key=lambda x: x["composite"], reverse=True)
    for r in sorted_results:
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{r['key_date']:<12} {r['composite']:<10.4f} {r['signal']:<8} "
              f"{r['her_init']:<10.4f} {r['topic_cont']:<10.4f} {r['reply_qual']:<10.4f} "
              f"{r['sess_bal']:<8.3f} {r['emo_temp']:<8.3f} {r['fz_risk']:<8.3f} {r['note']}")

    print("\n" + "=" * 170)
    print("按结果类型分组的回溯指标均值")
    print("=" * 170)

    groups = defaultdict(list)
    for r in results:
        groups[r["outcome"]].append(r)

    print(f"\n{'结果类型':<16} {'人数':<5} {'composite':<10} {'her_init':<10} {'topic_cont':<10} {'reply_qual':<10} {'sess_bal':<8} {'emo_temp':<8} {'fz_risk':<8}")
    print("-" * 100)

    for outcome in ["success", "success_to_failure", "half_success", "developing",
                    "active_giveup", "passive_giveup", "friendzone", "awkward",
                    "topic_mismatch", "lost_contact", "failure"]:
        items = groups.get(outcome, [])
        if not items:
            continue
        n = len(items)
        avg = lambda k: sum(r[k] for r in items) / n
        print(f"{outcome_names.get(outcome, outcome):<16} {n:<5} "
              f"{avg('composite'):<10.4f} {avg('her_init'):<10.4f} {avg('topic_cont'):<10.4f} "
              f"{avg('reply_qual'):<10.4f} {avg('sess_bal'):<8.3f} {avg('emo_temp'):<8.3f} {avg('fz_risk'):<8.3f}")

    print("\n" + "=" * 170)
    print("关键区分度分析（回溯数据）")
    print("=" * 170)

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

    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "retrospective_analysis.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("姓名,结果类型,回溯日期,composite,signal,her_init,topic_cont,reply_qual,sess_bal,emo_temp,fz_risk,fback,neediness,备注\n")
        for r in sorted_results:
            f.write(f"{r['name']},{r['outcome']},{r['key_date']},{r['composite']:.4f},{r['signal']},"
                    f"{r['her_init']:.4f},{r['topic_cont']:.4f},{r['reply_qual']:.4f},"
                    f"{r['sess_bal']:.4f},{r['emo_temp']:.4f},{r['fz_risk']:.4f},"
                    f"{r['fback']:.4f},{r['neediness']:.4f},{r['note']}\n")
    print(f"\n回溯分析数据已导出到: {output_path}")


if __name__ == "__main__":
    main()
