"""固话 me-side pilot v1 官方数据集。

1. 去重标注文件（454 行 → 453 唯一样本）
2. 按 candidates 的 contact-based split 划分 train/held_out
3. 输出到 data/ml_dataset/annotations/me_side_pilot_v1/

输出:
  me_side_pilot_v1/train.jsonl      — 309 条 pilot-train
  me_side_pilot_v1/held_out.jsonl   — 144 条 pilot-held-out
  me_side_pilot_v1/info.json        — 元信息（样本数、联系人数、标签分布等）
"""
import json
from collections import Counter
from pathlib import Path

ANNOTATIONS = Path("data/ml_dataset/annotations/annotations_meside_000.jsonl")
CANDIDATES = Path("data/ml_dataset/annotations/me_side_pilot_v1_candidates.jsonl")
OUT_DIR = Path("data/ml_dataset/annotations/me_side_pilot_v1")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 读取标注，去重
    annotations = {}
    dup_count = 0
    with open(ANNOTATIONS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sid = d["sample_id"]
            if sid in annotations:
                dup_count += 1
                # 保留第一条（内容一致的重复不冲突）
                continue
            annotations[sid] = d

    # 2. 读取候选集，获取 split 信息
    candidates = {}
    with open(CANDIDATES, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            candidates[d["sample_id"]] = d

    # 3. 按 split 划分
    train = []
    held_out = []
    missing = []
    for sid, ann in sorted(annotations.items()):
        cand = candidates.get(sid)
        split = cand.get("split") if cand else None
        if split == "train":
            train.append(ann)
        elif split == "held_out":
            held_out.append(ann)
        else:
            missing.append(sid)

    # 4. 写入输出文件
    def write_jsonl(records, path):
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_jsonl(train, OUT_DIR / "train.jsonl")
    write_jsonl(held_out, OUT_DIR / "held_out.jsonl")

    # 5. 元信息
    def label_distribution(records):
        dist = {}
        for r in records:
            for k, v in r.get("labels", {}).items():
                if k not in dist:
                    dist[k] = Counter()
                dist[k][v] += 1
        return {k: dict(sorted(v.items())) for k, v in dist.items()}

    train_contacts = set()
    for r in train:
        sid = r["sample_id"]
        c = candidates.get(sid, {})
        wxid = c.get("contact_wxid", "?")
        train_contacts.add(wxid)

    held_contacts = set()
    for r in held_out:
        sid = r["sample_id"]
        c = candidates.get(sid, {})
        wxid = c.get("contact_wxid", "?")
        held_contacts.add(wxid)

    info = {
        "dataset": "me_side_pilot_v1",
        "description": "我侧行为标注 pilot，用于 B1' zero-shot 诊断和后续联合微调",
        "total_unique_annotations": len(annotations),
        "duplicate_annotation_lines_removed": dup_count,
        "train": {
            "samples": len(train),
            "contacts": len(train_contacts),
            "label_distribution": label_distribution(train),
        },
        "held_out": {
            "samples": len(held_out),
            "contacts": len(held_contacts),
            "label_distribution": label_distribution(held_out),
        },
        "missing_split_info": {
            "count": len(missing),
            "sample_ids": missing,
        },
        "contact_overlap_with_b0_train": None,  # 后续分析填充
        "notes": [
            "train/held_out 按 contact_wxid 预切分，联系人无跨集重叠",
            "held_out 联系人大多在 B0' 训练集中出现，不是严格的新联系人 held-out",
            "用于 B1' target_role='me' zero-shot 角色切换诊断",
        ],
    }

    with open(OUT_DIR / "info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"  train.jsonl: {len(train)} samples / {len(train_contacts)} contacts")
    print(f"  held_out.jsonl: {len(held_out)} samples / {len(held_contacts)} contacts")
    print(f"  removed {dup_count} duplicate annotation lines")
    if missing:
        print(f"  WARNING: {len(missing)} samples missing split info: {missing}")
    print(f"  info written to {OUT_DIR / 'info.json'}")


if __name__ == "__main__":
    main()
