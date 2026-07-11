#!/usr/bin/env python3
"""单样本清洗工具 — Trae 标注前调用，清洗水印/时间戳/旁白/案例标签。

用法:
  # 从管道输入清洗（Trae 调用方式）
  echo '{"sample_id":"...","messages":[...]}' | python ml/scripts/clean_on_fly.py

  # 从文件清洗，输出到新文件
  python ml/scripts/clean_on_fly.py dirty.jsonl > clean.jsonl

  # 清洗前先预览（不输出，只打印清洗报告）
  python ml/scripts/clean_on_fly.py --preview dirty.jsonl

清洗成功后 stdout 输出清洗后的样本（JSONL 格式），
清洗后有效轮次 < 6 则退出码 1 且无输出（表示该放弃）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 ml/ 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from ml.cleaning_patterns import clean_message


def main() -> None:
    verbose = "--preview" in sys.argv

    if verbose and len(sys.argv) > 2:
        # --preview 文件模式
        path = Path(sys.argv[2])
        with open(path, encoding="utf-8") as f:
            samples = [json.loads(l) for l in f if l.strip()]
        for s in samples:
            print(f"\n--- {s['sample_id']} ---", file=sys.stderr)
            before = sum(len(m["content"]) for m in s["messages"])
            valid = []
            for m in s["messages"]:
                c = clean_message(m["content"], verbose=True)
                if c:
                    valid.append({"role": m["role"], "content": c})
            after = sum(len(m["content"]) for m in valid)
            pct = after / before * 100 if before else 0
            print(f"  字符: {before} → {after} ({pct:.0f}%) 轮次: {len(valid)}", file=sys.stderr)
        return

    # 标准模式：stdin → stdout
    raw = sys.stdin.read().strip()
    if not raw:
        print("错误：stdin 为空。通过管道传入样本 JSON。", file=sys.stderr)
        sys.exit(1)

    try:
        sample = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"错误：JSON 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)

    valid = []
    for m in sample.get("messages", []):
        c = clean_message(m.get("content", ""))
        if c:
            valid.append({
                "role": m["role"],
                "content": c,
                "timestamp": m.get("timestamp", 0),
            })

    if len(valid) < 6:
        # 清洗后不够 6 轮，放弃
        sys.exit(1)

    cleaned = {
        "sample_id": sample.get("sample_id"),
        "contact_wxid": sample.get("contact_wxid"),
        "contact_remark": sample.get("contact_remark"),
        "turn_count": len(valid),
        "messages": valid,
    }
    sys.stdout.write(json.dumps(cleaned, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
