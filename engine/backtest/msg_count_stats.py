"""统计数据库中所有私聊联系人的总消息数，按数量排序。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.config import load_config
from engine.analyzers.exclude import parse_labels


EXCLUDE_LABELS = {"同门", "非攻略对象", "群友"}


def main():
    config = load_config()
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row

    # 获取所有私聊联系人的消息数（conversations.type='private'）
    # contacts 表存放 remark 和 labels，需要 LEFT JOIN
    rows = conn.execute(
        """
        SELECT c.id AS wxid,
               COALESCE(c.display_name, c.id) AS display_name,
               ct.remark AS remark,
               ct.labels AS labels,
               COUNT(m.id) AS message_count,
               MIN(m.timestamp) AS first_ts,
               MAX(m.timestamp) AS last_ts
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        LEFT JOIN contacts ct ON ct.id = c.id
        WHERE c.type = 'private'
        GROUP BY c.id
        HAVING message_count >= 30
        ORDER BY message_count DESC
        """
    ).fetchall()

    # 获取标签信息用于过滤
    filtered = []
    for r in rows:
        labels = parse_labels(r["labels"])
        matched = [lb for lb in labels if lb in EXCLUDE_LABELS]
        if not matched:
            r_dict = dict(r)
            r_dict["labels_list"] = labels
            filtered.append(r_dict)

    # 输出统计表
    print(f"总联系人（≥30条消息，已排除同门/非攻略对象/群友）: {len(filtered)}")
    print("=" * 130)
    print(f"{'排名':<5} {'姓名':<20} {'备注':<15} {'消息数':<10} {'首次联系':<22} {'最后联系':<22} {'天数':<6} {'日均':<8} {'标签'}")
    print("-" * 130)

    import datetime
    for idx, r in enumerate(filtered, 1):
        first_dt = datetime.datetime.fromtimestamp(r["first_ts"]).strftime("%Y-%m-%d %H:%M")
        last_dt = datetime.datetime.fromtimestamp(r["last_ts"]).strftime("%Y-%m-%d %H:%M")
        span_days = max(1, (r["last_ts"] - r["first_ts"]) / 86400)
        daily_avg = r["message_count"] / span_days
        labels_str = ",".join(r["labels_list"]) if r["labels_list"] else "-"
        remark = r["remark"] or ""
        print(f"{idx:<5} {r['display_name']:<20} {remark:<15} {r['message_count']:<10} "
              f"{first_dt:<22} {last_dt:<22} {span_days:<6.0f} {daily_avg:<8.1f} {labels_str}")

    # 按消息数分段统计
    print("\n" + "=" * 80)
    print("消息数分段统计:")
    print("-" * 80)

    bins = [
        (10000, "10000+"),
        (5000, "5000-10000"),
        (2000, "2000-5000"),
        (1000, "1000-2000"),
        (500, "500-1000"),
        (200, "200-500"),
        (50, "50-200"),
        (0, "30-50"),
    ]

    for threshold, label in bins:
        count = sum(1 for r in filtered if r["message_count"] > threshold)
        print(f"  {label}: {count}人")

    # 导出 CSV
    output_path = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "backtest" / "msg_count_stats.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("排名,姓名,wxid,备注,消息数,首次联系,最后联系,跨度天数,日均消息,标签\n")
        for idx, r in enumerate(filtered, 1):
            first_dt = datetime.datetime.fromtimestamp(r["first_ts"]).strftime("%Y-%m-%d %H:%M")
            last_dt = datetime.datetime.fromtimestamp(r["last_ts"]).strftime("%Y-%m-%d %H:%M")
            span_days = max(1, (r["last_ts"] - r["first_ts"]) / 86400)
            daily_avg = r["message_count"] / span_days
            labels_str = ",".join(r["labels_list"]) if r["labels_list"] else "-"
            f.write(f"{idx},{r['display_name']},{r['wxid']},{r['remark'] or ''},"
                    f"{r['message_count']},{first_dt},{last_dt},{span_days:.0f},{daily_avg:.1f},{labels_str}\n")

    print(f"\n详细数据已导出到: {output_path}")
    conn.close()


if __name__ == "__main__":
    main()