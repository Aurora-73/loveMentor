#!/usr/bin/env python3
"""清洗放弃样本：去水印/时间戳/OCR噪声/教学旁白，输出到 rerun/cleaned/。

用法:
  python ml/scripts/clean_rerun.py

清洗逻辑（按顺序执行）:
  1. 广告水印：瑞恩情感/PUA平台广告等固定字符串
  2. 时间戳：英文/中文日期时间格式
  3. OCR碎片：单字符乱码、短无意义内容
  4. 教学旁白：第三人称教学叙事（非对话内容）
  5. 合并同人连续发言
  6. 过滤有效轮次不足的窗口
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 ml/ 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ml.cleaning_patterns import clean_message

RERUN_DIR = Path(__file__).resolve().parent.parent / "dataset" / "batches" / "rerun"
OUTPUT_DIR = RERUN_DIR / "cleaned"
MIN_VALID_TURNS = 10  # 清洗后至少要有 10 轮有效对话
MIN_MSG_LENGTH = 3    # 单条消息至少 3 个非空白字符（英文/中文均可）


def merge_consecutive_same_sender(messages: list[dict]) -> list[dict]:
    """合并连续同人消息。"""
    if not messages:
        return []
    turns = []
    current = messages[0]
    for msg in messages[1:]:
        if msg["role"] == current["role"]:
            current["content"] += "\n" + msg["content"]
            current["timestamp"] = msg["timestamp"]
        else:
            turns.append(current)
            current = dict(msg)
    turns.append(current)
    return turns


def main():
    rerun_files = sorted(RERUN_DIR.glob("batch_*.jsonl"))
    if not rerun_files:
        print("错误：rerun 目录没有 batch 文件")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_original = 0
    total_after = 0

    for f in rerun_files:
        with open(f, "r", encoding="utf-8") as fh:
            samples = [json.loads(line) for line in fh if line.strip()]

        total_original += len(samples)
        cleaned = []

        for s in samples:
            # 清洗每条消息
            valid_messages = []
            for m in s["messages"]:
                cleaned_content = clean_message(m["content"])
                if cleaned_content:
                    valid_messages.append({
                        "role": m["role"],
                        "content": cleaned_content,
                        "timestamp": m.get("timestamp", 0),
                    })

            if len(valid_messages) < MIN_VALID_TURNS:
                continue

            # 合并同人连续发言
            merged = merge_consecutive_same_sender(valid_messages)
            if len(merged) < MIN_VALID_TURNS:
                continue

            # 写入清洗后样本
            cleaned.append({
                "sample_id": s["sample_id"],
                "contact_wxid": s["contact_wxid"],
                "contact_remark": s["contact_remark"],
                "turn_count": len(merged),
                "messages": [
                    {
                        "turn": i + 1,
                        "role": m["role"],
                        "content": m["content"],
                        "timestamp": m.get("timestamp", 0),
                    }
                    for i, m in enumerate(merged)
                ],
            })

        batch_name = f.name
        out_path = OUTPUT_DIR / batch_name
        with open(out_path, "w", encoding="utf-8") as fh:
            for c in cleaned:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")

        recovered = len(cleaned)
        total_after += recovered
        pct = recovered / len(samples) * 100 if samples else 0
        print(f"  {batch_name}: {len(samples)} → {recovered} ({pct:.0f}% 回收)")

    print(f"\n总计: {total_original} → {total_after} ({total_after/total_original*100:.1f}% 回收)")
    print(f"输出目录: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
