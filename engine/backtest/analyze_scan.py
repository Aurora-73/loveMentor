"""分析全量联系人扫描结果，找出有区分度的指标和潜在案例。"""
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.analyzers.exclude import parse_labels


EXCLUDE_LABELS = {"同门", "非攻略对象", "群友"}


def main():
    config = load_config()
    
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    
    # 获取所有有消息的联系人
    rows = conn.execute(
        """
        SELECT c.id AS wxid, COALESCE(c.display_name, c.id) AS display_name,
               COUNT(m.id) AS message_count
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE c.type = 'private'
        GROUP BY c.id
        HAVING message_count >= 30
        ORDER BY message_count DESC
        """
    ).fetchall()
    
    contacts = [dict(r) for r in rows]
    
    # 获取标签信息
    contact_meta = {}
    rows = conn.execute("SELECT id, labels, remark FROM contacts").fetchall()
    for r in rows:
        contact_meta[r["id"]] = {
            "labels": parse_labels(r["labels"]),
            "remark": r["remark"] or "",
        }
    
    # 过滤掉指定标签的联系人
    filtered = []
    for c in contacts:
        wxid = c["wxid"]
        labels = contact_meta.get(wxid, {}).get("labels", [])
        matched = [lb for lb in labels if lb in EXCLUDE_LABELS]
        if not matched:
            c["labels"] = labels
            c["remark"] = contact_meta.get(wxid, {}).get("remark", "")
            filtered.append(c)
    
    print(f"待分析联系人: {len(filtered)}")
    
    # 计算指标
    results = []
    for c in filtered:
        wxid = c["wxid"]
        name = c["display_name"]
        try:
            metrics = compute_metrics_for_contact(conn, config, wxid, name)
            results.append({
                "name": name,
                "wxid": wxid,
                "remark": c["remark"],
                "msg_count": c["message_count"],
                "composite": metrics.composite,
                "fback": metrics.fback.normalized,
                "neediness": metrics.neediness_penalty,
                "signal_level": metrics.signal_level,
                "volume_ratio": metrics.volume_ratio,
                "initiation_ratio": metrics.initiation_ratio,
                "active_days": metrics.active_days.normalized,
                "reply_rate": metrics.fback.normalized,
                "reply_time": metrics.rlatency.normalized,
                "recency": metrics.recent.normalized,
                "trend": metrics.trend.normalized,
                "intensity": metrics.msg_count.normalized,
                "depth": metrics.qscore.normalized,
                "topic_diversity": metrics.escore.normalized,
                "labels": c["labels"],
            })
        except Exception:
            pass
    
    conn.close()
    
    # 按 composite 排序
    sorted_results = sorted(results, key=lambda x: x["composite"], reverse=True)
    
    # 保存详细结果到文件
    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "full_scan_results.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("排名,姓名,wxid,备注,消息数,composite,fback,neediness,signal_level,volume_ratio,initiation_ratio,active_days,reply_rate,reply_time,recency,trend,intensity,depth,topic_diversity,标签\n")
        for idx, r in enumerate(sorted_results, 1):
            labels_str = ",".join(r["labels"]) if r["labels"] else "-"
            f.write(f"{idx},{r['name']},{r['wxid']},{r['remark']},{r['msg_count']},"
                    f"{r['composite']:.4f},{r['fback']:.4f},{r['neediness']:.4f},{r['signal_level']},"
                    f"{r['volume_ratio']:.2f},{r['initiation_ratio']:.2f},{r['active_days']},"
                    f"{r['reply_rate']:.4f},{r['reply_time']:.2f},{r['recency']:.4f},"
                    f"{r['trend']:.4f},{r['intensity']:.4f},{r['depth']:.4f},{r['topic_diversity']:.4f},{labels_str}\n")
    
    print(f"\n详细结果已保存到: {output_path}")
    
    # 分析高 composite 人群（前20名）
    print("\n" + "=" * 100)
    print("高 composite 人群分析（前20名）")
    print("=" * 100)
    
    top20 = sorted_results[:20]
    print(f"\n{'排名':<4} {'姓名':<15} {'消息数':<8} {'composite':<10} {'fback':<8} {'neediness':<10} {'signal':<8} {'备注'}")
    print("-" * 100)
    for r in top20:
        print(f"{r['name']:<15} {r['msg_count']:<8} {r['composite']:<10.4f} {r['fback']:<8.3f} {r['neediness']:<10.4f} {r['signal_level']:<8} {r['remark']}")
    
    # 分析中高 composite 人群的特征
    print("\n" + "=" * 100)
    print("中高 composite (>0.30) 人群特征")
    print("=" * 100)
    
    mid_high = [r for r in sorted_results if r["composite"] > 0.30]
    print(f"\n中高 composite 人数: {len(mid_high)}")
    
    # 按 fback 分析
    fback_bins = defaultdict(list)
    for r in mid_high:
        if r["fback"] >= 0.7:
            fback_bins["高反馈(≥0.7)"].append(r)
        elif r["fback"] >= 0.4:
            fback_bins["中反馈(0.4-0.7)"].append(r)
        else:
            fback_bins["低反馈(<0.4)"].append(r)
    
    print("\n按反馈率分布:")
    for bin_name, items in fback_bins.items():
        avg_comp = sum(r["composite"] for r in items) / len(items)
        print(f"  {bin_name}: {len(items)}人, avg_composite={avg_comp:.4f}")
    
    # 按 neediness 分析
    neediness_bins = defaultdict(list)
    for r in mid_high:
        if r["neediness"] >= 0.95:
            neediness_bins["低需求感(≥0.95)"].append(r)
        elif r["neediness"] >= 0.8:
            neediness_bins["中需求感(0.8-0.95)"].append(r)
        else:
            neediness_bins["高需求感(<0.8)"].append(r)
    
    print("\n按需求感惩罚分布:")
    for bin_name, items in neediness_bins.items():
        avg_comp = sum(r["composite"] for r in items) / len(items)
        print(f"  {bin_name}: {len(items)}人, avg_composite={avg_comp:.4f}")
    
    # 分析低 composite 但消息量大的人群（潜在放弃案例）
    print("\n" + "=" * 100)
    print("低 composite 但消息量大的人群（潜在放弃案例）")
    print("=" * 100)
    
    low_comp_high_msg = sorted(
        [r for r in results if r["composite"] < 0.20 and r["msg_count"] > 500],
        key=lambda x: x["msg_count"],
        reverse=True
    )
    
    print(f"\n低 composite(<0.20) 且消息量>500: {len(low_comp_high_msg)}人")
    print(f"\n{'姓名':<15} {'消息数':<8} {'composite':<10} {'fback':<8} {'neediness':<10} {'vol_ratio':<10} {'init_ratio':<10} {'备注'}")
    print("-" * 100)
    for r in low_comp_high_msg[:20]:
        print(f"{r['name']:<15} {r['msg_count']:<8} {r['composite']:<10.4f} {r['fback']:<8.3f} {r['neediness']:<10.4f} {r['volume_ratio']:<10.2f} {r['initiation_ratio']:<10.2f} {r['remark']}")
    
    # 分析指标区分度
    print("\n" + "=" * 100)
    print("指标区分度分析")
    print("=" * 100)
    
    all_composites = [r["composite"] for r in results]
    all_fbacks = [r["fback"] for r in results]
    all_neediness = [r["neediness"] for r in results]
    all_active_days = [r["active_days"] for r in results]
    all_recency = [r["recency"] for r in results]
    all_trend = [r["trend"] for r in results]
    
    print(f"\n指标分布统计:")
    print(f"{'指标':<15} {'min':<8} {'p25':<8} {'p50':<8} {'p75':<8} {'max':<8} {'mean':<8}")
    print("-" * 70)
    
    def stat(arr):
        arr_sorted = sorted(arr)
        n = len(arr_sorted)
        return f"{min(arr):.4f} {arr_sorted[max(0, n//4)]:.4f} {arr_sorted[max(0, n//2)]:.4f} {arr_sorted[max(0, n*3//4)]:.4f} {max(arr):.4f} {sum(arr)/n:.4f}"
    
    print(f"{'composite':<15} {stat(all_composites)}")
    print(f"{'fback':<15} {stat(all_fbacks)}")
    print(f"{'neediness':<15} {stat(all_neediness)}")
    print(f"{'active_days':<15} {stat(all_active_days)}")
    print(f"{'recency':<15} {stat(all_recency)}")
    print(f"{'trend':<15} {stat(all_trend)}")
    
    # 分析 fback 和 composite 的关系
    print("\nfback 与 composite 相关性分析:")
    fback_groups = defaultdict(list)
    for r in results:
        bin_key = f"{int(r['fback'] * 10) * 0.1:.1f}-{int(r['fback'] * 10) * 0.1 + 0.1:.1f}"
        fback_groups[bin_key].append(r["composite"])
    
    for bin_key in sorted(fback_groups.keys()):
        comps = fback_groups[bin_key]
        avg_comp = sum(comps) / len(comps)
        print(f"  fback {bin_key}: {len(comps)}人, avg_composite={avg_comp:.4f}")
    
    # 分析 neediness 和 composite 的关系
    print("\nneediness 与 composite 相关性分析:")
    need_groups = defaultdict(list)
    for r in results:
        if r["neediness"] >= 0.9:
            key = "≥0.90"
        elif r["neediness"] >= 0.7:
            key = "0.70-0.89"
        elif r["neediness"] >= 0.5:
            key = "0.50-0.69"
        else:
            key = "<0.50"
        need_groups[key].append(r["composite"])
    
    for key in ["≥0.90", "0.70-0.89", "0.50-0.69", "<0.50"]:
        comps = need_groups.get(key, [])
        if comps:
            avg_comp = sum(comps) / len(comps)
            print(f"  neediness {key}: {len(comps)}人, avg_composite={avg_comp:.4f}")
    
    # 分析 signal_level 分布
    print("\n信号等级分布:")
    signal_counts = defaultdict(int)
    signal_composites = defaultdict(list)
    for r in results:
        signal_counts[r["signal_level"]] += 1
        signal_composites[r["signal_level"]].append(r["composite"])
    
    total = len(results)
    for signal in ["强窗口", "中窗口", "弱窗口", "冷淡", "无信号"]:
        count = signal_counts.get(signal, 0)
        comps = signal_composites.get(signal, [])
        avg_comp = sum(comps) / len(comps) if comps else 0
        pct = count / total * 100
        print(f"  {signal}: {count}人 ({pct:.1f}%), avg_composite={avg_comp:.4f}")
    
    # 分析潜在成功案例候选
    print("\n" + "=" * 100)
    print("潜在成功案例候选 (composite > 0.35 且非家人)")
    print("=" * 100)
    
    family_names = {"妈", "爸", "姑姑", "姐姐", "哥哥", "弟弟", "妹妹"}
    candidates = [
        r for r in sorted_results
        if r["composite"] > 0.35 and not any(f in r["name"] for f in family_names)
    ]
    
    print(f"\n候选人数: {len(candidates)}")
    print(f"\n{'姓名':<15} {'消息数':<8} {'composite':<10} {'fback':<8} {'neediness':<10} {'signal':<8} {'备注'}")
    print("-" * 100)
    for r in candidates:
        print(f"{r['name']:<15} {r['msg_count']:<8} {r['composite']:<10.4f} {r['fback']:<8.3f} {r['neediness']:<10.4f} {r['signal_level']:<8} {r['remark']}")


if __name__ == "__main__":
    main()
