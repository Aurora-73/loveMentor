"""标注质量检查脚本

检查内容:
1. 格式合法性 (JSON结构、10个标签、0-9整数)
2. 标签分布统计
3. 异常值检测 (全0、全9、极端单一)
4. 与样本ID匹配性
"""

import json
from pathlib import Path
from collections import Counter

ANNOTATIONS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "annotations_phase2.jsonl"
SAMPLES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset" / "samples_phase0.jsonl"

LABELS = [
    "information_exchange",
    "opinion_expression",
    "emotion_positive",
    "emotion_negative",
    "flirt",
    "question_asking",
    "self_disclosure",
    "invitation",
    "framing_boundary",
    "perfunctory",
]


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    annotations = load_jsonl(ANNOTATIONS_PATH)
    samples = load_jsonl(SAMPLES_PATH)

    sample_ids = {s["sample_id"] for s in samples}
    ann_ids = {a["sample_id"] for a in annotations}

    print(f"=== 标注质量检查报告 ===")
    print(f"样本总数: {len(samples)}")
    print(f"标注总数: {len(annotations)}")
    print()

    # 1. ID匹配检查
    missing = sample_ids - ann_ids
    extra = ann_ids - sample_ids
    print(f"【ID匹配】")
    print(f"  未标注的样本ID: {len(missing)}")
    print(f"  多余的标注ID: {len(extra)}")
    if missing:
        print(f"  缺失示例: {list(missing)[:5]}")
    print()

    # 2. 格式合法性检查
    format_errors = []
    for ann in annotations:
        sid = ann.get("sample_id", "?")
        labels = ann.get("labels", {})
        if not isinstance(labels, dict):
            format_errors.append(f"{sid}: labels不是dict")
            continue
        if set(labels.keys()) != set(LABELS):
            format_errors.append(f"{sid}: 标签键不匹配, 缺={set(LABELS)-set(labels.keys())}, 多={set(labels.keys())-set(LABELS)}")
            continue
        for lbl in LABELS:
            v = labels[lbl]
            if not isinstance(v, int):
                format_errors.append(f"{sid}.{lbl}: 非整数 {v!r}")
            elif v < 0 or v > 9:
                format_errors.append(f"{sid}.{lbl}: 超范围 {v}")

    print(f"【格式合法性】")
    print(f"  格式错误数: {len(format_errors)}")
    if format_errors:
        for e in format_errors[:10]:
            print(f"    {e}")
    print()

    # 3. 标签分布统计
    print(f"【标签分布统计】")
    print(f"{'标签':<25} {'均值':>6} {'最小':>4} {'最大':>4} {'0分占比':>8} {'9分占比':>8}")
    for lbl in LABELS:
        values = [ann["labels"][lbl] for ann in annotations]
        mean_v = sum(values) / len(values)
        zero_pct = sum(1 for v in values if v == 0) / len(values) * 100
        nine_pct = sum(1 for v in values if v == 9) / len(values) * 100
        print(f"  {lbl:<23} {mean_v:>6.2f} {min(values):>4} {max(values):>4} {zero_pct:>7.1f}% {nine_pct:>7.1f}%")
    print()

    # 4. 异常样本检测
    print(f"【异常样本检测】")
    all_zero = []
    all_same = []
    all_high = []
    for ann in annotations:
        vals = [ann["labels"][lbl] for lbl in LABELS]
        if all(v == 0 for v in vals):
            all_zero.append(ann["sample_id"])
        if len(set(vals)) == 1 and vals[0] != 0:
            all_same.append((ann["sample_id"], vals[0]))
        if all(v >= 7 for v in vals):
            all_high.append(ann["sample_id"])

    print(f"  全0样本: {len(all_zero)}")
    if all_zero:
        print(f"    示例: {all_zero[:5]}")
    print(f"  全同分(非0)样本: {len(all_same)}")
    if all_same:
        print(f"    示例: {all_same[:5]}")
    print(f"  全高分(≥7)样本: {len(all_high)}")
    if all_high:
        print(f"    示例: {all_high[:5]}")
    print()

    # 5. 标签间相关性快查 (perfunctory vs others)
    print(f"【perfunctory与其他标签关系】")
    perf_vals = [ann["labels"]["perfunctory"] for ann in annotations]
    info_vals = [ann["labels"]["information_exchange"] for ann in annotations]
    flirt_vals = [ann["labels"]["flirt"] for ann in annotations]
    high_perf_low_info = sum(1 for p, i in zip(perf_vals, info_vals) if p >= 6 and i <= 2)
    high_perf_low_flirt = sum(1 for p, f in zip(perf_vals, flirt_vals) if p >= 6 and f <= 2)
    print(f"  高perfunctory(≥6)且低information(≤2): {high_perf_low_info}")
    print(f"  高perfunctory(≥6)且低flirt(≤2): {high_perf_low_flirt}")
    print()

    # 6. 评分分布直方图
    print(f"【各标签评分分布】")
    for lbl in LABELS:
        values = [ann["labels"][lbl] for ann in annotations]
        dist = Counter(values)
        dist_str = " ".join(f"{k}:{dist.get(k,0):>4}" for k in range(10))
        print(f"  {lbl:<23} {dist_str}")

    print()
    print(f"=== 质量检查完成 ===")


if __name__ == "__main__":
    main()
