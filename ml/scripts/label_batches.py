#!/usr/bin/env python3
"""对话行为标注脚本 — 批量标注 batches/batch_XXX.jsonl。

用法:
  # 查看 batch_001 的下一个待标注样本
  python ml/scripts/label_batches.py --batch 001

  # 查看 batch_001 的下 20 个待标注样本
  python ml/scripts/label_batches.py --batch 001 --count 20

  # 提交单条标注
  python ml/scripts/label_batches.py --batch 001 --submit "7|8|6|1|5|5|3|7|6|1"

  # 放弃该样本（必须写明理由）
  python ml/scripts/label_batches.py --batch 001 --submit "-1:全是水印"

  # 批量提交多个标注（依次对应下一个未标注样本）
  python ml/scripts/label_batches.py --batch 001 --submit "7|8|6|1|5|5|3|7|6|1" "3|8|1|6|0|1|2|0|5|1" "-1:旁白过多"

  # 查看标注进度
  python ml/scripts/label_batches.py --progress

  # 查看某批的标注结果统计
  python ml/scripts/label_batches.py --batch 001 --stats

标注文件: data/ml_dataset/annotations_XXX.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"
CLEANED_DIR = BATCHES_DIR / "rerun" / "cleaned"

def resolve_batch_dir(source: str = "original") -> Path:
    return CLEANED_DIR if source == "cleaned" else BATCHES_DIR
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


def get_annotations_path(batch_num: str, suffix: str = "") -> Path:
    base = Path(__file__).resolve().parent.parent.parent / "data" / "ml_dataset"
    tag = f"_{suffix}" if suffix else ""
    return base / f"annotations_{batch_num}{tag}.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_batch_path(batch_num: str) -> Path:
    return BATCHES_DIR / f"batch_{batch_num}.jsonl"


def annotated_sample_ids(batch_num: str, suffix: str = "") -> set[str]:
    try:
        return {ann["sample_id"] for ann in load_jsonl(get_annotations_path(batch_num, suffix))}
    except (json.JSONDecodeError, KeyError):
        print("错误：annotations 文件格式异常")
        sys.exit(1)


def find_next_n(samples: list[dict], done: set[str], n: int) -> list[dict]:
    result = []
    for s in samples:
        if s["sample_id"] not in done:
            result.append(s)
            if len(result) >= n:
                break
    return result


def display_sample(sample: dict, index: int) -> None:
    print(f"--- {index}. {sample['sample_id']} ---")
    for msg in sample["messages"]:
        role = "我" if msg["role"] == "me" else "她"
        content = msg["content"].replace("\n", " ")[:100]
        print(f"[{role}] {content}")
    print()


def parse_scores(arg: str) -> tuple[list[int] | None, str]:
    """解析分数。返回 (None, 理由) 表示放弃，(分数列表, "") 表示正常标注。"""
    arg = arg.strip()
    if arg.startswith("-1"):
        reason = ""
        if ":" in arg:
            reason = arg.split(":", 1)[1].strip()
        if not reason:
            print("错误：放弃样本必须写明理由，格式：-1:理由（如 -1:全是水印）")
            sys.exit(1)
        return None, reason
    parts = arg.split("|")
    if len(parts) != 10:
        print(f"错误：需要 10 个分数或 -1:理由（放弃），收到 {len(parts)} 个")
        sys.exit(1)
    scores = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p.isdigit():
            print(f"错误：第 {i+1} 个值 '{p}' 不是整数")
            sys.exit(1)
        v = int(p)
        if v < 0 or v > 9:
            print(f"错误：第 {i+1} 个值 {v} 不在 0-9 范围内")
            sys.exit(1)
        scores.append(v)
    return scores, ""


def append_annotation(sample_id: str, contact_wxid: str, scores: list[int] | None, batch_num: str, suffix: str = "", discard_reason: str = "") -> None:
    record = {
        "sample_id": sample_id,
        "contact_wxid": contact_wxid,
        "discard": scores is None,
        "labels": dict(zip(LABELS, scores)) if scores else {},
    }
    if discard_reason:
        record["discard_reason"] = discard_reason
    annotations_path = get_annotations_path(batch_num, suffix)
    annotations_path.parent.mkdir(parents=True, exist_ok=True)
    with open(annotations_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_all_batches(source_dir: Path = BATCHES_DIR) -> list[str]:
    batches = []
    for path in sorted(source_dir.glob("batch_*.jsonl")):
        num = path.name.replace("batch_", "").replace(".jsonl", "")
        batches.append(num)
    return batches


def show_progress() -> None:
    batches = get_all_batches()
    total_samples = 0
    total_done = 0

    print("=" * 70)
    print("标注进度")
    print("=" * 70)

    for batch_num in batches:
        path = get_batch_path(batch_num)
        samples = load_jsonl(path)
        done = annotated_sample_ids(batch_num)
        batch_total = len({s["sample_id"] for s in samples})
        batch_done = len(done)
        total_samples += batch_total
        total_done += batch_done

        status = "✓" if batch_done >= batch_total else "○"
        print(f"{status} batch_{batch_num}: {batch_done}/{batch_total} ({batch_done / batch_total * 100:.0f}%)")

    print("=" * 70)
    print(f"总计: {total_done}/{total_samples} ({total_done / total_samples * 100:.1f}%)")


def check_templating(batch_num: str, suffix: str = "") -> None:
    """检查最近提交的标注是否有模板化嫌疑（连续多条完全一样）。"""
    ann = load_jsonl(get_annotations_path(batch_num, suffix))
    normal = [a for a in ann if a.get("labels") and not a.get("discard")]

    if len(normal) < 10:
        return

    recent = normal[-20:]
    patterns = [tuple(a["labels"].values()) for a in recent]
    unique_patterns = len(set(patterns))

    warnings = []

    # 1) 最近 N 条模式太少
    if unique_patterns <= 3:
        warnings.append(
            f"⚠️ 最近 {len(recent)} 条标注只有 {unique_patterns} 种分数模式（可能模板化）"
        )

    # 2) 连续完全相同
    max_run = 1
    cur = 1
    for i in range(1, len(patterns)):
        if patterns[i] == patterns[i - 1]:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 1
    if max_run >= 5:
        warnings.append(f"⚠️ 连续 {max_run} 条分数完全相同")

    if warnings:
        print("\n" + "=" * 60, file=sys.stderr)
        for w in warnings:
            print(w, file=sys.stderr)
        print("请检查是否在认真标注，不要模板化提交。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)


def show_stats(batch_num: str, suffix: str = "") -> None:
    path = get_batch_path(batch_num)
    samples = load_jsonl(path)
    annotations = load_jsonl(get_annotations_path(batch_num, suffix))

    batch_ids = {s["sample_id"] for s in samples}
    batch_anns = [a for a in annotations if a["sample_id"] in batch_ids]

    print(f"\nbatch_{batch_num} 统计:")
    print(f"  样本数: {len(samples)}")
    print(f"  已标注: {len(batch_anns)}")

    if not batch_anns:
        return

    discard_count = sum(1 for a in batch_anns if a.get("discard"))
    ok_count = len(batch_anns) - discard_count
    print(f"  正常: {ok_count}")
    print(f"  放弃: {discard_count}")

    if discard_count > 0:
        reasons = Counter(a.get("discard_reason", "未说明") for a in batch_anns if a.get("discard"))
        print("  放弃理由:")
        for reason, cnt in reasons.most_common():
            print(f"    [{reason}] {cnt} 条")

    label_sums = Counter()
    label_counts = Counter()
    for ann in batch_anns:
        if not ann.get("discard") and ann.get("labels"):
            for label, score in ann["labels"].items():
                label_sums[label] += score
                label_counts[label] += 1

    if label_counts:
        print("\n  标签均值:")
        for label in LABELS:
            if label_counts[label] > 0:
                avg = label_sums[label] / label_counts[label]
                print(f"    {label}: {avg:.2f}")


def main() -> None:
    if "--progress" in sys.argv:
        show_progress()
        return

    if "--batch" not in sys.argv or len(sys.argv) < 3:
        print("用法:")
        print("  查看样本: python label_batches.py --batch 001 [--count N] [--source cleaned]")
        print("  提交单条: python label_batches.py --batch 001 --submit \"分数\"")
        print("  放弃样本: python label_batches.py --batch 001 --submit \"-1:理由\"")
        print("  批量提交: python label_batches.py --batch 001 --submit \"分数1\" \"分数2\" ...")
        print("  进度统计: python label_batches.py --progress")
        print("  批次统计: python label_batches.py --batch 001 --stats")
        print("  数据源: python label_batches.py --batch 001 --source cleaned --count 10")
        sys.exit(1)

    idx = sys.argv.index("--batch")
    batch_num = sys.argv[idx + 1]

    # --source cleaned 指向 rerun/cleaned/，省略则用原目录
    source = "original"
    if "--source" in sys.argv:
        src_idx = sys.argv.index("--source")
        source = sys.argv[src_idx + 1]
    source_dir = resolve_batch_dir(source)
    # cleaned 源使用独立的标注文件 annotations_XXX_rerun.jsonl
    ann_suffix = "rerun" if source == "cleaned" else ""

    batch_path = source_dir / f"batch_{batch_num}.jsonl"
    if not batch_path.exists():
        print(f"错误：找不到批次文件 {batch_path}")
        sys.exit(1)

    if "--stats" in sys.argv:
        show_stats(batch_num)
        return

    samples = load_jsonl(batch_path)
    done = annotated_sample_ids(batch_num, ann_suffix)
    remaining = sum(1 for s in samples if s["sample_id"] not in done)

    if "--submit" in sys.argv:
        submit_idx = sys.argv.index("--submit")
        score_args = sys.argv[submit_idx + 1:]
        if not score_args:
            print("错误：--submit 后需要提供分数")
            sys.exit(1)

        batch = find_next_n(samples, done, len(score_args))
        if len(batch) != len(score_args):
            print(f"错误：提供了 {len(score_args)} 组分数，但有 {len(batch)} 个待标注样本")
            sys.exit(1)

        for sample, arg in zip(batch, score_args):
            scores, discard_reason = parse_scores(arg)
            append_annotation(sample["sample_id"], sample["contact_wxid"], scores, batch_num, ann_suffix, discard_reason)
            status = "弃" if scores is None else "OK"
            detail = f" - {discard_reason}" if discard_reason else ""
            print(f"[{status}] {sample['sample_id']}: {arg}{detail}")

        new_done = len(done) + len(batch)
        total = sum(len(load_jsonl(source_dir / f"batch_{b}.jsonl")) for b in get_all_batches(source_dir))
        print(f"\n进度: {new_done}/{total} ({new_done / total * 100:.1f}%)")

        check_templating(batch_num, ann_suffix)
        return

    count = 1
    if "--count" in sys.argv:
        count_idx = sys.argv.index("--count")
        count = int(sys.argv[count_idx + 1])

    batch = find_next_n(samples, done, count)
    if not batch:
        print(f"batch_{batch_num} 已全部标注完成！")
        return

    print(f"=== batch_{batch_num}: {len(batch)} 条 (剩余: {remaining}) ===")
    print()
    for i, sample in enumerate(batch, 1):
        display_sample(sample, i)
    print(f"=== 批量结束 ===")
    print(f"提交: python label_batches.py --batch {batch_num} --submit \"分数\"")
    print(f"放弃: python label_batches.py --batch {batch_num} --submit \"-1:理由\"")


if __name__ == "__main__":
    main()
