"""回测基础设施验证脚本。

测试 ref_date 和 to_ts 参数是否正确生效，确保不会"偷看未来"。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import datetime
from engine.config import load_config
from engine.importers.db_init import get_db
from engine.identity import resolve_contact
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.formulas import formula_params
from engine.backtest.load_cases import get_validate_cases


def main():
    config = load_config()
    conn = get_db(config.db_path)
    
    try:
        test_cases = get_validate_cases()
        
        for display_name, wxid in test_cases:
            print(f"\n{'='*60}")
            print(f"测试案例: {display_name} ({wxid[:20]}...)")
            print(f"{'='*60}")
            
            print("\n--- 1. 实时计算（无 ref_date/to_ts）---")
            m_now = compute_metrics_for_contact(conn, config, wxid, display_name)
            print(f"  composite: {m_now.composite:.4f}")
            print(f"  fback: {m_now.fback.raw:.4f}")
            print(f"  neediness_penalty: {m_now.neediness_penalty:.4f}")
            print(f"  msg_count: {m_now.msg_count.raw}")
            print(f"  signal_level: {m_now.signal_level}")
            
            print("\n--- 2. 历史时间切片（2025-12-01）---")
            ref_date = datetime(2025, 12, 1)
            to_ts = int(ref_date.timestamp())
            m_hist = compute_metrics_for_contact(conn, config, wxid, display_name,
                                                 ref_date=ref_date, to_ts=to_ts)
            print(f"  ref_date: {ref_date.strftime('%Y-%m-%d')}")
            print(f"  composite: {m_hist.composite:.4f}")
            print(f"  fback: {m_hist.fback.raw:.4f}")
            print(f"  neediness_penalty: {m_hist.neediness_penalty:.4f}")
            print(f"  msg_count: {m_hist.msg_count.raw}")
            print(f"  signal_level: {m_hist.signal_level}")
            
            print("\n--- 3. 变化对比 ---")
            print(f"  msg_count 变化: {m_now.msg_count.raw} → {m_hist.msg_count.raw}")
            print(f"  neediness_penalty 变化: {m_now.neediness_penalty:.4f} → {m_hist.neediness_penalty:.4f}")
            
            print("\n--- 4. 公式参数（历史时间）---")
            fp = formula_params(display_name, conn=conn, ref_date=ref_date, to_ts=to_ts)
            if isinstance(fp, dict):
                print(f"  Sp: {fp['auto']['Sp']:.2f}")
                print(f"  Fback: {fp['auto']['Fback']:.2f}")
                print(f"  User_Investment: {fp['auto']['User_Investment']:.2f}")
                print(f"  Cp_Index default: {fp['manual']['Cp_Index']['default']}")
            else:
                print(f"  错误: {fp}")
            
            print()
            
    finally:
        conn.close()


if __name__ == "__main__":
    main()
