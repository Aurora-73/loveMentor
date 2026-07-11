"""时间序列趋势分析：计算每个案例的 composite 时间曲线，分析上升/下降趋势。

Wiki 依据：IOI 兴趣指标——"看密度和趋势，不看单个信号"。
核心假设：
  - 成功案例的 composite 在"在一起前"应持续上升
  - 失败案例的 composite 先升后降（或波动/停滞）
  - 趋势斜率比单点值更有预测力
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import get_ts_cases


TS_CASES = get_ts_cases()


def linear_slope(points):
    """简单线性回归斜率。points = [(x, y), ...]，x 为天数序号。"""
    n = len(points)
    if n < 2:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def main():
    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row

    print("=" * 130)
    print("时间序列趋势分析：composite 曲线斜率 vs 最终结果")
    print("=" * 130)

    results = []
    sample_interval_days = 7

    for wxid, name, outcome, start_dt, end_dt, note in TS_CASES:
        points = []
        current = start_dt
        while current <= end_dt:
            points.append(current)
            current += timedelta(days=sample_interval_days)

        if len(points) < 3:
            print(f"{name}: 采样点不足({len(points)}), 跳过")
            continue

        series = []
        for i, pt in enumerate(points):
            to_ts = int(pt.timestamp())
            try:
                metrics = compute_metrics_for_contact(conn, config, wxid, name,
                                                       ref_date=pt, to_ts=to_ts)
                series.append((i, metrics.composite, metrics.signal_level,
                              metrics.her_initiation_rate.normalized,
                              metrics.topic_continuation.normalized,
                              metrics.session_balance.normalized))
            except Exception:
                pass

        if len(series) < 3:
            print(f"{name}: 有效点不足({len(series)}), 跳过")
            continue

        comp_points = [(s[0], s[1]) for s in series]
        comp_slope = linear_slope(comp_points)

        her_points = [(s[0], s[3]) for s in series]
        her_slope = linear_slope(her_points)

        start_comp = series[0][1]
        end_comp = series[-1][1]
        max_comp = max(s[1] for s in series)
        min_comp = min(s[1] for s in series)
        comp_change = end_comp - start_comp

        if comp_slope > 0.005:
            trend = "上升"
        elif comp_slope < -0.005:
            trend = "下降"
        else:
            trend = "平稳"

        results.append({
            "name": name,
            "outcome": outcome,
            "note": note,
            "n_points": len(series),
            "start_comp": start_comp,
            "end_comp": end_comp,
            "max_comp": max_comp,
            "min_comp": min_comp,
            "comp_change": comp_change,
            "comp_slope": comp_slope,
            "her_slope": her_slope,
            "trend": trend,
            "series": series,
        })
        print(f"{name}({outcome}): {len(series)}点, composite {start_comp:.3f}->{end_comp:.3f}, 斜率={comp_slope:.5f}, 趋势={trend}")

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

    print("\n" + "=" * 130)
    print("趋势汇总（按 composite 斜率降序）")
    print("=" * 130)
    print(f"\n{'姓名':<12} {'结果':<14} {'点数':<5} {'起始':<8} {'结束':<8} {'最高':<8} {'变化':<8} {'斜率':<10} {'her斜率':<10} {'趋势'}")
    print("-" * 110)

    sorted_results = sorted(results, key=lambda x: x["comp_slope"], reverse=True)
    for r in sorted_results:
        print(f"{r['name']:<12} {outcome_names.get(r['outcome'], r['outcome']):<14} "
              f"{r['n_points']:<5} {r['start_comp']:<8.4f} {r['end_comp']:<8.4f} "
              f"{r['max_comp']:<8.4f} {r['comp_change']:<+8.4f} "
              f"{r['comp_slope']:<10.5f} {r['her_slope']:<10.5f} {r['trend']}")

    print("\n" + "=" * 130)
    print("按结果类型分组的趋势均值")
    print("=" * 130)

    groups = defaultdict(list)
    for r in results:
        groups[r["outcome"]].append(r)

    print(f"\n{'结果类型':<16} {'人数':<5} {'avg斜率':<10} {'avg起始':<10} {'avg结束':<10} {'avg变化':<10} {'上升人数'}")
    print("-" * 80)

    for outcome in ["success", "success_to_failure", "half_success", "developing",
                    "active_giveup", "friendzone", "awkward", "topic_mismatch",
                    "lost_contact", "failure"]:
        items = groups.get(outcome, [])
        if not items:
            continue
        n = len(items)
        avg_slope = sum(r["comp_slope"] for r in items) / n
        avg_start = sum(r["start_comp"] for r in items) / n
        avg_end = sum(r["end_comp"] for r in items) / n
        avg_change = sum(r["comp_change"] for r in items) / n
        rising = sum(1 for r in items if r["trend"] == "上升")
        print(f"{outcome_names.get(outcome, outcome):<16} {n:<5} "
              f"{avg_slope:<10.5f} {avg_start:<10.4f} {avg_end:<10.4f} "
              f"{avg_change:<+10.4f} {rising}/{n}")

    print("\n" + "=" * 130)
    print("关键区分度：composite 趋势斜率")
    print("=" * 130)

    success_types = ["success", "half_success", "developing"]
    failure_types = ["friendzone", "topic_mismatch", "lost_contact", "failure"]

    success_items = [r for r in results if r["outcome"] in success_types]
    failure_items = [r for r in results if r["outcome"] in failure_types]

    if success_items and failure_items:
        s_slope = sum(r["comp_slope"] for r in success_items) / len(success_items)
        f_slope = sum(r["comp_slope"] for r in failure_items) / len(failure_items)
        s_rising = sum(1 for r in success_items if r["trend"] == "上升")
        f_rising = sum(1 for r in failure_items if r["trend"] == "上升")

        print(f"\n成功类({len(success_items)}人): avg斜率={s_slope:.5f}, 上升{s_rising}/{len(success_items)}")
        print(f"失败类({len(failure_items)}人): avg斜率={f_slope:.5f}, 上升{f_rising}/{len(failure_items)}")
        print(f"斜率差异: {s_slope - f_slope:.5f}")
        print(f"\n结论: {'趋势斜率有区分度' if abs(s_slope - f_slope) > 0.003 else '趋势斜率区分度不足'}")

    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "timeseries_trend.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("姓名,结果,采样点序号,composite,signal,her_init,topic_cont,sess_bal\n")
        for r in sorted_results:
            for s in r["series"]:
                f.write(f"{r['name']},{r['outcome']},{s[0]},{s[1]:.4f},{s[2]},{s[3]:.4f},{s[4]:.4f},{s[5]:.4f}\n")
    print(f"\n时间序列数据已导出到: {output_path}")

    summary_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "trend_summary.csv"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("姓名,结果,点数,起始composite,结束composite,最高composite,变化,斜率,her斜率,趋势,备注\n")
        for r in sorted_results:
            f.write(f"{r['name']},{r['outcome']},{r['n_points']},{r['start_comp']:.4f},"
                    f"{r['end_comp']:.4f},{r['max_comp']:.4f},{r['comp_change']:.4f},"
                    f"{r['comp_slope']:.5f},{r['her_slope']:.5f},{r['trend']},{r['note']}\n")
    print(f"趋势汇总已导出到: {summary_path}")


if __name__ == "__main__":
    main()
