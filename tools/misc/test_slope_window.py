"""验证不同窗口长度下 composite_slope 的区分力。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config
from engine.importers.db_init import get_db
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import get_test_slope_window_cases


def main():
    config = load_config()
    conn = get_db(config.db_path)

    try:
        test_cases = get_test_slope_window_cases()

        configs = [
            (3, 7, "14天窗"),
            (4, 14, "42天窗"),
            (6, 14, "70天窗"),
        ]

        for sp, si, label in configs:
            print(f"\n{'=' * 80}")
            print(f"窗口: {label} (sample_points={sp}, interval={si}d)")
            print(f"{'=' * 80}")
            print(f"{'姓名':<10} {'结果':<12} {'slope.raw':<12} {'norm':<8} {'trend':<8} {'history'}")
            print("-" * 80)

            for name, wxid, outcome in test_cases:
                m = compute_metrics_for_contact(
                    conn, config, wxid, name, compute_slope=True,
                )
                from engine.analyzers.metrics import compute_composite_slope
                slope = compute_composite_slope(
                    conn, config, wxid, name,
                    sample_points=sp, sample_interval_days=si,
                )
                trend = slope.extra.get("trend_label", "?")
                history = " → ".join(
                    f"{h['composite']:.3f}" for h in slope.extra.get("history", [])
                )
                print(f"{name:<10} {outcome:<12} {slope.raw:<12.6f} {slope.normalized:<8.4f} {trend:<8} {history}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
