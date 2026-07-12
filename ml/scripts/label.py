#!/usr/bin/env python3
"""
⚠️ 已弃用 — 由 label_batches.py 替代。

保留用于参考，标注新数据请使用:
  python ml/scripts/label_batches.py --batch XXX --submit "分数"

"""

"""对话行为标注脚本 — 批量标注 samples_phase0.jsonl。

用法:
  # 查看下一个待标注样本（单条模式）
  python ml/scripts/label.py

  # 提交单条标注
  python ml/scripts/label.py 3|8|1|6|0|1|2|0|5|1

  # 批量模式：查看下 N 个待标注样本
  python ml/scripts/label.py --batch 20

  # 批量模式：提交 N 条标注（每参数为一条样本的 10 个分数）
  python ml/scripts/label.py --batch-submit "7|8|6|1|5|5|3|7|6|1" "3|8|1|6|0|1|2|0|5|1" ...

  # 批量模式：从文件提交（每行一条样本的分数）
  python ml/scripts/label.py --batch-submit-file scores.txt

标注文件: data/ml_dataset/annotations_phase2.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def annotated_sample_ids() -> set[str]:
    try:
        return {ann["sample_id"] for ann in load_jsonl(ANNOTATIONS_PATH)}
    except (json.JSONDecodeError, KeyError):
        print("错误：annotations_phase2.jsonl 格式异常，请检查文件内容")
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
        print(f"[{role}] {msg['content']}")
    print()


def parse_scores(arg: str) -> list[int] | None:
    """解析分数。返回 None 表示放弃该样本。"""
    arg = arg.strip()
    if arg == "-1":
        return None
    parts = arg.split("|")
    if len(parts) != 10:
        print(f"错误：需要 10 个分数或 -1（放弃），收到 {len(parts)} 个")
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
    return scores


def append_annotation(sample_id: str, contact_wxid: str, scores: list[int] | None) -> None:
    record = {
        "sample_id": sample_id,
        "contact_wxid": contact_wxid,
        "discard": scores is None,
        "labels": dict(zip(LABELS, scores)) if scores else {},
    }
    ANNOTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ANNOTATIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    if not SAMPLES_PATH.exists():
        print(f"错误：找不到样本文件 {SAMPLES_PATH}")
        print("请先运行 ml/dataset/sample_windows.py 生成样本到 data/ml_dataset/")
        sys.exit(1)

    samples = load_jsonl(SAMPLES_PATH)
    done = annotated_sample_ids()
    total = len(samples)
    remaining = total - len(done)

    if remaining == 0:
        print(f"全部 {total} 条标注完成！")
        return

    # ── 批量查看模式 ──
    if len(sys.argv) >= 2 and sys.argv[1] in ("--batch", "-b"):
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 10
        batch = find_next_n(samples, done, n)
        if not batch:
            print("没有更多待标注样本")
            return
        print(f"=== 批量: {len(batch)} 条 (总计: {total}, 已标注: {len(done)}, 剩余: {remaining}) ===")
        print()
        for i, sample in enumerate(batch, 1):
            display_sample(sample, i)
        print(f"=== 批量结束 ===")
        print(f"提交格式: python label.py --batch-submit \"分数1\" \"分数2\" ... \"分数{len(batch)}\"")
        print(f"标签顺序: information_exchange|opinion_expression|emotion_positive|emotion_negative|flirt|question_asking|self_disclosure|invitation|framing_boundary|perfunctory")
        return

    # ── 批量提交模式 ──
    if len(sys.argv) >= 2 and sys.argv[1] in ("--batch-submit", "-bs"):
        score_args = sys.argv[2:]
        if not score_args:
            print("错误：--batch-submit 后需要提供分数参数")
            sys.exit(1)
        batch = find_next_n(samples, done, len(score_args))
        if len(batch) != len(score_args):
            print(f"错误：提供了 {len(score_args)} 组分数，但有 {len(batch)} 个待标注样本")
            sys.exit(1)
        for sample, arg in zip(batch, score_args):
            scores = parse_scores(arg)
            append_annotation(sample["sample_id"], sample["contact_wxid"], scores)
            status = "OK" if scores else "SKIP"
            print(f"[{status}] {sample['sample_id']}: {arg}")
        new_done = len(done) + len(batch)
        print(f"\n进度: {new_done}/{total} ({new_done/total*100:.1f}%)")
        return

    # ── 批量提交文件模式 ──
    if len(sys.argv) >= 2 and sys.argv[1] in ("--batch-submit-file", "-bsf"):
        if len(sys.argv) < 3:
            print("错误：--batch-submit-file 后需要提供文件路径")
            sys.exit(1)
        filepath = Path(sys.argv[2])
        if not filepath.exists():
            print(f"错误：文件不存在 {filepath}")
            sys.exit(1)
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        batch = find_next_n(samples, done, len(lines))
        if len(batch) != len(lines):
            print(f"错误：文件中有 {len(lines)} 行分数，但有 {len(batch)} 个待标注样本")
            sys.exit(1)
        for sample, arg in zip(batch, lines):
            scores = parse_scores(arg)
            append_annotation(sample["sample_id"], sample["contact_wxid"], scores)
            status = "OK" if scores else "SKIP"
            print(f"[{status}] {sample['sample_id']}: {arg}")
        new_done = len(done) + len(batch)
        print(f"\n进度: {new_done}/{total} ({new_done/total*100:.1f}%)")
        return

    # ── 单条查看模式 ──
    if len(sys.argv) < 2:
        print(f"样本总数: {total}")
        print(f"已标注: {len(done)}")
        print(f"剩余: {remaining}")
        print()
        batch = find_next_n(samples, done, 1)
        if batch:
            display_sample(batch[0], 1)
        return

    # ── 单条提交模式 ──
    arg = sys.argv[1]
    scores = parse_scores(arg)
    batch = find_next_n(samples, done, 1)
    if not batch:
        print("错误：找不到下一个待标注样本（状态异常）")
        sys.exit(1)
    append_annotation(batch[0]["sample_id"], batch[0]["contact_wxid"], scores)
    status = "OK" if scores else "SKIP"
    print(f"[{status}] {batch[0]['sample_id']}")
    new_done = len(done) + 1
    print(f"进度: {new_done}/{total} ({new_done/total*100:.1f}%)")


if __name__ == "__main__":
    main()
