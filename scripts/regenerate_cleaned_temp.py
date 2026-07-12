"""从原始 batch 重新生成 cleaned 版本（保留全部样本，不过滤）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml.cleaning_patterns import clean_message

BATCHES_DIR = Path("ml/dataset/batches")
OUTPUT_DIR = BATCHES_DIR / "rerun" / "cleaned"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for path in sorted(BATCHES_DIR.glob("batch_*.jsonl")):
    batch = path.name
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    out_samples = []
    kept = 0
    total = len(samples)
    for s in samples:
        valid = []
        for m in s.get("messages", []):
            c = clean_message(m.get("content", ""))
            if c:
                valid.append({
                    "role": m["role"],
                    "content": c,
                    "timestamp": m.get("timestamp", 0),
                })
        out = {
            "sample_id": s.get("sample_id"),
            "contact_wxid": s.get("contact_wxid"),
            "contact_remark": s.get("contact_remark"),
            "turn_count": len(valid),
            "messages": valid,
        }
        out_samples.append(out)
        if valid:
            kept += 1

    out_path = OUTPUT_DIR / batch
    with open(out_path, "w", encoding="utf-8") as f:
        for s in out_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    empty = total - kept
    print(f"{batch}: {total} 样本, 清洗后非空: {kept}, 全空(全删): {empty}")

print(f"\n写出到: {OUTPUT_DIR}")
