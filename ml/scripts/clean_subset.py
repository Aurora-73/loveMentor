#!/usr/bin/env python3
"""字符串级清洗 — 无状态，每次独立。Trae 运行，指定具体字符串进行清洗。

用法:
  # 移除子串 + 删除整条消息 + 删除行
  python ml/scripts/clean_subset.py ^
    --ref ml/dataset/batches/_work/batch_001_offset_0.jsonl ^
    --out ml/dataset/batches/_work/batch_001_offset_0_clean.jsonl ^
    --remove "瑞恩情感RYAN PUA" ^
    --remove "Type a message" ^
    --drop-msg "转换完成" ^
    --drop-line "4G"

  # 只移除子串
  python ml/scripts/clean_subset.py ^
    --ref xxx.jsonl --out xxx_clean.jsonl ^
    --remove "瑞恩情感RYAN PUA"

参数:
  --ref FILE          输入文件（read_unlabeled.py 生成的参考文件）
  --out FILE          输出文件（清洗后的 JSONL）
  --remove TEXT       从消息内容中移除精确子串（可重复指定）
  --drop-msg TEXT     删除内容完全匹配的整条消息（可重复指定）
  --drop-line TEXT    删除包含此文本的行（从多行消息中移除该行，可重复）

约束:
  - 纯字符串操作，无正则/模式匹配
  - 无状态：相同输入 + 相同参数 → 相同输出
  - 不修改原始文件，只写入 --out
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def clean_content(content: str, remove: list[str], drop_line: list[str]) -> str:
    """对单条消息内容应用清洗。"""
    # --remove: 移除精确子串
    for rm in remove:
        content = content.replace(rm, "")

    # --drop-line: 删除包含指定文本的行
    if drop_line:
        lines = content.split("\n")
        kept = [ln for ln in lines if not any(dl in ln for dl in drop_line)]
        content = "\n".join(kept)

    return content.strip()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="对样本子集进行字符串清洗")
    parser.add_argument("--ref", required=True, help="参考文件路径 (read_unlabeled.py 生成)")
    parser.add_argument("--out", required=True, help="输出文件路径")
    parser.add_argument("--remove", action="append", default=[], help="从内容中移除精确子串")
    parser.add_argument("--drop-msg", action="append", default=[], help="删除内容完全匹配的消息")
    parser.add_argument("--drop-line", action="append", default=[], help="删除包含此文本的行")
    args = parser.parse_args()

    ref_path = Path(args.ref)
    if not ref_path.exists():
        print(f"错误：找不到参考文件 {ref_path}")
        sys.exit(1)

    with open(ref_path, encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    total_msgs_before = sum(len(s["messages"]) for s in samples)
    drop_msg_set = [t.strip() for t in args.drop_msg]

    cleaned = []
    for s in samples:
        valid = []
        for m in s["messages"]:
            content = m["content"]

            # --drop-msg: 内容完全匹配则跳过整条消息
            if content.strip() in drop_msg_set:
                continue

            content = clean_content(content, args.remove, args.drop_line)
            if content:
                valid.append({
                    "role": m["role"],
                    "content": content,
                    "timestamp": m.get("timestamp", 0),
                })

        cleaned.append({
            "sample_id": s["sample_id"],
            "contact_wxid": s.get("contact_wxid", ""),
            "contact_remark": s.get("contact_remark", ""),
            "turn_count": len(valid),
            "messages": valid,
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for s in cleaned:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    total_msgs_after = sum(len(s["messages"]) for s in cleaned)
    print(f"清洗完成: {len(samples)} 个样本, {total_msgs_before} → {total_msgs_after} 条消息")
    print(f"输出: {out_path}")


if __name__ == "__main__":
    main()
