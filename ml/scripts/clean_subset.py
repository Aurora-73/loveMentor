#!/usr/bin/env python3
"""字符串级原地清洗 — 无状态，每次独立。与 read_unlabeled.py 使用相同的定位参数。

用法:
  # 移除子串
  python ml/scripts/clean_subset.py --batch 001 --offset 0 --remove "瑞恩情感RYAN PUA"

  # 移除子串 + 删除整条消息 + 删除行
  python ml/scripts/clean_subset.py --batch 001 --offset 0 ^
    --remove "瑞恩情感RYAN PUA" ^
    --remove "Type a message" ^
    --drop-msg "转换完成" ^
    --drop-line "4G"

参数:
  --batch BATCH    批次号，如 001（与 read_unlabeled.py 一致）
  --offset N       定位偏移（与 read_unlabeled.py 一致）
  --count N        需要清洗的样本数（默认 50）
  --remove TEXT    从消息内容中移除精确子串（可重复指定）
  --drop-msg TEXT  删除内容完全匹配的整条消息（可重复指定）
  --drop-line TEXT 删除包含此文本的行（从多行消息中移除该行，可重复）

行为:
  - 从 batch 文件中定位同一样本集，原地修改（覆盖原始文件）
  - 纯字符串操作，无正则/模式匹配
  - 无状态：相同参数 → 相同结果
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BATCHES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches"
ANNOTATIONS_DIR = Path(__file__).resolve().parent.parent / "dataset" / "annotations"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_annotated_ids(batch_num: str) -> set[str]:
    ann_path = ANNOTATIONS_DIR / f"annotations_{batch_num}.jsonl"
    return {ann["sample_id"] for ann in load_jsonl(ann_path)}


def clean_content(content: str, remove: list[str], drop_line: list[str]) -> str:
    for rm in remove:
        content = content.replace(rm, "")
    if drop_line:
        lines = content.split("\n")
        kept = [ln for ln in lines if not any(dl in ln for dl in drop_line)]
        content = "\n".join(kept)
    return content.strip()


def clean_sample(sample: dict, remove: list[str], drop_msg: list[str], drop_line: list[str]) -> dict:
    """对单个样本执行清洗，返回清洗后的样本。"""
    valid = []
    for m in sample["messages"]:
        content = m["content"]
        if content.strip() in drop_msg:
            continue
        content = clean_content(content, remove, drop_line)
        if content:
            valid.append({
                "role": m["role"],
                "content": content,
                "timestamp": m.get("timestamp", 0),
            })
    return {
        "sample_id": sample["sample_id"],
        "contact_wxid": sample.get("contact_wxid", ""),
        "contact_remark": sample.get("contact_remark", ""),
        "turn_count": len(valid) // 2,
        "messages": valid,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="对样本子集进行字符串级原地清洗")
    parser.add_argument("--batch", required=True, help="批次号，如 001")
    parser.add_argument("--offset", type=int, default=0, help="从未标注列表起始的偏移")
    parser.add_argument("--count", type=int, default=20, help="清洗数量")
    parser.add_argument("--remove", action="append", default=[], help="从内容中移除精确子串")
    parser.add_argument("--drop-msg", action="append", default=[], help="删除内容完全匹配的消息")
    parser.add_argument("--drop-line", action="append", default=[], help="删除包含此文本的行")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不修改文件）")
    args = parser.parse_args()

    if not args.remove and not args.drop_msg and not args.drop_line:
        print("错误：未指定任何清洗参数（--remove / --drop-msg / --drop-line）")
        sys.exit(1)

    batch_path = BATCHES_DIR / f"batch_{args.batch}.jsonl"
    if not batch_path.exists():
        print(f"错误：找不到批次文件 {batch_path}")
        sys.exit(1)

    # 读取 batch
    with open(batch_path, encoding="utf-8") as f:
        lines = f.readlines()
    all_samples = [json.loads(l) for l in lines if l.strip()]

    # 定位未标注样本
    annotated_ids = get_annotated_ids(args.batch)
    unlabeled_indices = [i for i, s in enumerate(all_samples) if s["sample_id"] not in annotated_ids]

    target_indices = unlabeled_indices[args.offset:args.offset + args.count]
    if not target_indices:
        print(f"错误：offset={args.offset} 超出未标注样本范围 (共 {len(unlabeled_indices)} 个)")
        sys.exit(1)

    # 清洗（使用 clean_sample() 统一逻辑）
    total_msgs_before = 0
    total_msgs_after = 0

    for idx in target_indices:
        cleaned = clean_sample(all_samples[idx], args.remove, args.drop_msg, args.drop_line)
        before = len(all_samples[idx]["messages"])
        after = len(cleaned["messages"])
        total_msgs_before += before
        total_msgs_after += after

        if args.dry_run:
            removed = before - after
            if removed > 0:
                print(f"  {all_samples[idx]['sample_id']}: {before} → {after} 条消息 (-{removed})")
            else:
                print(f"  {all_samples[idx]['sample_id']}: 无变化 ({before} 条)")
        else:
            all_samples[idx] = cleaned

    if not args.dry_run:
        with open(batch_path, "w", encoding="utf-8") as f:
            for s in all_samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    mode = " (预览模式，未修改文件)" if args.dry_run else f" (原地: {batch_path})"
    print(f"清洗完成: {len(target_indices)} 个样本, {total_msgs_before} → {total_msgs_after} 条消息{mode}")


if __name__ == "__main__":
    main()
