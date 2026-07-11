"""对所有符合条件的联系人进行指标扫描。

排除标签：同门、非攻略对象、群友
输出：composite/fback/neediness/signal_level 的汇总表
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config, DB_PATH
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.analyzers.exclude import filter_contacts, parse_labels
from engine.analyzers.metrics import get_all_contacts_with_messages


EXCLUDE_LABELS = {"同门", "非攻略对象", "群友"}


def main():
    config = load_config()
    my_wxid = config.my_wxid
    
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    
    contacts = get_all_contacts_with_messages(conn, min_messages=30)
    print(f"总联系人（≥30条消息）: {len(contacts)}")
    
    # 获取标签信息
    contact_meta = {}
    rows = conn.execute("SELECT id, labels FROM contacts").fetchall()
    for r in rows:
        contact_meta[r["id"]] = parse_labels(r["labels"])
    
    # 过滤掉指定标签的联系人
    filtered = []
    excluded_by_label = []
    for c in contacts:
        wxid = c["wxid"]
        labels = contact_meta.get(wxid, [])
        matched = [lb for lb in labels if lb in EXCLUDE_LABELS]
        if matched:
            excluded_by_label.append((c["display_name"], wxid, labels))
        else:
            c["labels"] = labels
            filtered.append(c)
    
    print(f"排除（标签）: {len(excluded_by_label)}")
    for name, wxid, labels in excluded_by_label:
        print(f"  - {name} ({wxid}): {labels}")
    
    print(f"\n待扫描联系人: {len(filtered)}")
    print("=" * 120)
    
    results = []
    for i, c in enumerate(filtered, 1):
        wxid = c["wxid"]
        name = c["display_name"]
        print(f"[{i}/{len(filtered)}] 分析: {name} ({wxid})...", end=" ")
        
        try:
            metrics = compute_metrics_for_contact(conn, config, wxid, name)
            results.append({
                "name": name,
                "wxid": wxid,
                "composite": metrics.composite,
                "fback": metrics.fback.normalized,
                "neediness": metrics.neediness_penalty,
                "signal_level": metrics.signal_level,
                "msg_count": c["message_count"],
                "volume_ratio": metrics.volume_ratio,
                "initiation_ratio": metrics.initiation_ratio,
                "labels": c["labels"],
                # Wiki 衍生指标（v2）
                "her_init": metrics.her_initiation_rate.normalized,
                "topic_cont": metrics.topic_continuation.normalized,
                "reply_qual": metrics.reply_quality.normalized,
                "sess_bal": metrics.session_balance.normalized,
                "emo_temp": metrics.emotional_temperature.normalized,
                "fz_risk": metrics.friendzone_risk.normalized,
            })
            print(f"composite={metrics.composite:.4f} signal={metrics.signal_level}")
        except Exception as e:
            print(f"失败: {e}")
    
    conn.close()
    
    # 输出汇总表
    print("\n" + "=" * 120)
    print(f"扫描结果汇总（共 {len(results)} 人）")
    print("=" * 120)
    
    print(f"\n{'排名':<4} {'姓名':<20} {'composite':<10} {'fback':<8} {'neediness':<10} {'signal':<8} {'her_init':<10} {'topic_cont':<10} {'reply_qual':<10} {'sess_bal':<8} {'emo_temp':<8} {'fz_risk':<8} {'消息数':<8} {'标签'}")
    print("-" * 150)
    
    sorted_results = sorted(results, key=lambda x: x["composite"], reverse=True)
    
    for idx, r in enumerate(sorted_results, 1):
        labels_str = ",".join(r["labels"]) if r["labels"] else "-"
        print(f"{idx:<4} {r['name']:<20} {r['composite']:<10.4f} {r['fback']:<8.3f} {r['neediness']:<10.4f} {r['signal_level']:<8} {r['her_init']:<10.4f} {r['topic_cont']:<10.4f} {r['reply_qual']:<10.4f} {r['sess_bal']:<8.3f} {r['emo_temp']:<8.3f} {r['fz_risk']:<8.3f} {r['msg_count']:<8} {labels_str}")
    
    # 统计信号分布
    signal_counts = {}
    for r in results:
        signal = r["signal_level"]
        signal_counts[signal] = signal_counts.get(signal, 0) + 1
    
    print(f"\n信号等级分布:")
    for signal, count in sorted(signal_counts.items(), key=lambda x: -x[1]):
        pct = count / len(results) * 100
        print(f"  {signal}: {count} ({pct:.1f}%)")
    
    # composite 分布统计
    composites = [r["composite"] for r in results]
    composites.sort()
    n = len(composites)
    print(f"\ncomposite 分布:")
    print(f"  min: {composites[0]:.4f}")
    print(f"  p25: {composites[max(0, n//4)]:.4f}")
    print(f"  p50: {composites[max(0, n//2)]:.4f}")
    print(f"  p75: {composites[max(0, n*3//4)]:.4f}")
    print(f"  max: {composites[-1]:.4f}")
    print(f"  mean: {sum(composites)/n:.4f}")


if __name__ == "__main__":
    main()