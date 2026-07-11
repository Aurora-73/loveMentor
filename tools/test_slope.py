"""验证 composite_slope 指标计算。"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config
from engine.importers.db_init import get_db
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import get_test_slope_cases


def main():
    config = load_config()
    conn = get_db(config.db_path)

    try:
        test_cases = get_test_slope_cases()

        print("=" * 90)
        print("composite_slope 验证（compute_slope=True）")
        print("=" * 90)
        print(f"\n{'姓名':<10} {'composite':<10} {'slope.raw':<12} {'slope.norm':<12} {'trend_label':<10} {'confidence':<10}")
        print("-" * 70)

        for name, wxid in test_cases:
            m = compute_metrics_for_contact(conn, config, wxid, name, compute_slope=True)
            slope = m.composite_slope
            label = slope.extra.get("trend_label", "?")
            print(f"{name:<10} {m.composite:<10.4f} {slope.raw:<12.6f} {slope.normalized:<12.4f} {label:<10} {slope.confidence:<10.2f}")

            for h in slope.extra.get("history", []):
                print(f"  day_offset={h['day_offset']:>3d}  composite={h['composite']:.4f}  msg_count={h['msg_count']}")

        print("\n" + "=" * 90)
        print("向后兼容验证（compute_slope=False，默认）")
        print("=" * 90)
        m = compute_metrics_for_contact(conn, config, test_cases[0][1], test_cases[0][0])
        print(f"composite_slope.sample_size = {m.composite_slope.sample_size} (应为 0)")
        print(f"composite_slope.normalized = {m.composite_slope.normalized} (应为 0.0)")
        print(f"composite = {m.composite} (应与之前一致)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
