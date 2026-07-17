#!/usr/bin/env python3
"""Me-side 行为标注脚本 — 标注 me_side_pilot_v1 中"我"的 10 个行为维度。

以 0-9 分评价"我"在对话中的每个行为维度。
读取 annotations/me_side_pilot_v1_candidates.jsonl，写入 annotations_meside_000.jsonl。
她侧分数默认隐藏，提交后显示用于复核。

用法:
  # 查看下一个待标注样本（默认 1 条）
  python ml/scripts/label_meside.py

  # 查看下 5 条
  python ml/scripts/label_meside.py --count 5

  # 提交单条标注（10 个 0-9 分数，| 分隔，按 LABELS 顺序）
  python ml/scripts/label_meside.py --submit "7|8|6|1|5|5|3|7|6|1"

  # 放弃该样本（必须写明理由）
  python ml/scripts/label_meside.py --submit "-1:全是水印"

  # 批量提交
  python ml/scripts/label_meside.py --submit "7|8|6|1|5|5|3|7|6|1" "3|8|1|6|0|1|2|0|5|1"

  # 查看标注进度
  python ml/scripts/label_meside.py --progress

  # 查看统计
  python ml/scripts/label_meside.py --stats

分数顺序（10 个标签）:
  1. information_exchange   — 我陈述事实信息
  2. opinion_expression     — 我表达观点或评价
  3. emotion_positive       — 我表现出正向情绪
  4. emotion_negative       — 我表现出负向情绪
  5. flirt                  — 我暧昧、调侃或撒娇
  6. question_asking        — 我主动提问
  7. self_disclosure        — 我主动分享个人信息
  8. invitation             — 我邀约或积极回应邀约
  9. framing_boundary       — 我使用朋友/兄弟等关系框架词汇
  10. perfunctory           — 我敷衍回应
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent.parent

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

CANDIDATES_PATH = ROOT / "data" / "ml_dataset" / "annotations" / "me_side_pilot_v1_candidates.jsonl"
ANN_PATH = ROOT / "data" / "ml_dataset" / "annotations" / "annotations_meside_000.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def annotated_sample_ids() -> set[str]:
    """已标注的 sample_id 集合。忽略 meta 行。"""
    anns = load_jsonl(ANN_PATH)
    return {a["sample_id"] for a in anns if "sample_id" in a}


def find_next_n(candidates: list[dict], done: set[str], n: int) -> list[dict]:
    result = []
    for c in candidates:
        if c["sample_id"] not in done:
            result.append(c)
            if len(result) >= n:
                break
    return result


BEHAVIOR_HINTS = {
    "flirt": "⚠️ 只计算我方主动行为（调侃、撒娇、暧昧，不包括回应她暧昧）",
    "invitation": "⚠️ 只计算我方主动邀约或积极接话推进见面",
    "question_asking": "⚠️ 只计算我方主动提问（不包括嗯/哦/是吗等敷衍回应）",
    "perfunctory": "⚠️ 只计算我方敷衍回应（嗯、哦、行吧、表情包无实质内容）",
}


def display_sample(candidate: dict, index: int, hide_her: bool = True) -> None:
    """打印一个样本的完整对话。默认隐藏她侧分数以避免锚定偏差。"""
    sid = candidate["sample_id"]
    bucket = candidate.get("selection_bucket", "?")
    reason = candidate.get("selection_reason", "?")
    msgs = candidate.get("messages", [])

    print(f"--- {index}. {sid} (桶: {bucket}, {reason}, {len(msgs)}条消息) ---")

    for msg in msgs:
        role = "我" if msg.get("role") == "me" else "她"
        content = msg.get("content", "")
        print(f"  [{role}] {content}")

    print()
    if hide_her:
        print("  [她侧分数已隐藏 — 提交后将显示用于复核]")
    else:
        her_scores = candidate.get("her_scores", {})
        print("  她侧已有分数（复核参考）:")
        for label, score in sorted(her_scores.items()):
            bar = "█" * max(0, min(10, int(score))) + "░" * max(0, 10 - max(0, min(10, int(score))))
            print(f"    {label:25s} {score:.1f}  {bar}")
    print()

    print("  请标注我的行为（0-9，按以下顺序以 | 分隔）:")
    for i, label in enumerate(LABELS, 1):
        hint = BEHAVIOR_HINTS.get(label, "")
        if hint:
            print(f"    {i:2d}. {label:25s} {hint}")
        else:
            print(f"    {i:2d}. {label}")
    print()


def parse_scores(arg: str) -> tuple[list[int] | None, str]:
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


def append_annotation(sample_id: str, scores: list[int] | None, discard_reason: str = "") -> None:
    record = {
        "sample_id": sample_id,
        "target": "me",
        "discard": scores is None,
        "labels": dict(zip(LABELS, scores)) if scores else {},
    }
    if discard_reason:
        record["discard_reason"] = discard_reason
    ANN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ANN_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def show_progress() -> None:
    if not CANDIDATES_PATH.exists():
        print("诊断候选文件不存在。请先运行: python ml/scripts/prepare_meside_annotation.py")
        return

    with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
        total = sum(1 for _ in f if _.strip())

    done = annotated_sample_ids()
    remaining = total - len(done)
    pct = len(done) / total * 100 if total > 0 else 0

    print("=" * 50)
    print("Me-side 标注进度")
    print("=" * 50)
    print(f"总计: {total} 条候选")
    print(f"已标: {len(done)} 条 ({pct:.1f}%)")
    print(f"剩余: {remaining} 条")
    print("=" * 50)

    # 按分桶统计
    if done:
        candidates = load_jsonl(CANDIDATES_PATH)
        bucket_count = Counter()
        bucket_done = Counter()
        for c in candidates:
            b = c.get("selection_bucket", "?")
            bucket_count[b] += 1
            if c["sample_id"] in done:
                bucket_done[b] += 1
        print("\n按分桶:")
        for bucket, total_b in sorted(bucket_count.items()):
            done_b = bucket_done.get(bucket, 0)
            status = "✓" if done_b >= total_b else "○"
            print(f"  {status} {bucket:<15} {done_b}/{total_b} ({done_b/total_b*100:.0f}%)")


def show_stats() -> None:
    """显示已标注的 me-side 统计。"""
    anns = load_jsonl(ANN_PATH)
    valid = [a for a in anns if a.get("labels") and not a.get("discard") and "sample_id" in a]

    if not valid:
        print("暂无有效标注。")
        return

    print(f"\nMe-side 标注统计:")
    print(f"  有效标注: {len(valid)}")

    label_sums = Counter()
    for a in valid:
        for label, score in a["labels"].items():
            label_sums[label] += score

    print("\n  标签均值:")
    for label in LABELS:
        avg = label_sums[label] / len(valid)
        bar = "█" * max(0, min(10, int(avg))) + "░" * max(0, 10 - max(0, min(10, int(avg))))
        print(f"    {label:25s} {avg:.2f}  {bar}")


def main() -> None:
    if not CANDIDATES_PATH.exists():
        print(f"候选文件不存在: {CANDIDATES_PATH}")
        print("请先运行: python ml/scripts/prepare_meside_annotation.py")
        sys.exit(1)

    if "--progress" in sys.argv:
        show_progress()
        return

    if "--stats" in sys.argv:
        show_stats()
        return

    candidates = load_jsonl(CANDIDATES_PATH)
    done = annotated_sample_ids()
    remaining = len(candidates) - len(done)

    if "--submit" in sys.argv:
        submit_idx = sys.argv.index("--submit")
        score_args = [a for a in sys.argv[submit_idx + 1:] if not a.startswith("--")]
        if not score_args:
            print("错误：--submit 后需要提供分数")
            sys.exit(1)

        # 找接下来 N 个未标注样本
        batch = find_next_n(candidates, done, len(score_args))
        if len(batch) != len(score_args):
            print(f"错误：提供了 {len(score_args)} 组分数，但只有 {len(batch)} 个待标注样本")
            sys.exit(1)

        for sample, arg in zip(batch, score_args):
            scores, discard_reason = parse_scores(arg)
            append_annotation(sample["sample_id"], scores, discard_reason)
            status = "弃" if scores is None else "OK"
            detail = f" - {discard_reason}" if discard_reason else ""
            print(f"[{status}] {sample['sample_id']}: {arg}{detail}")
            if scores is not None:
                # 提交后展示她侧分数用于复核
                her = sample.get("her_scores", {})
                print(f"         她侧复核:")
                for lbl, sc in sorted(her.items()):
                    print(f"           {lbl:25s} {sc:.1f}")
                print()

        pct = (len(done) + len(batch)) / len(candidates) * 100
        print(f"\n进度: {len(done) + len(batch)}/{len(candidates)} ({pct:.1f}%)")
        return

    # 默认模式：查看下 N 条
    count = 1
    if "--count" in sys.argv:
        count_idx = sys.argv.index("--count")
        count = int(sys.argv[count_idx + 1])

    batch = find_next_n(candidates, done, count)
    if not batch:
        print("所有候选已标注完成！")
        return

    print(f"=== Me-side 标注: {len(batch)} 条 (剩余: {remaining}) ===")
    print()
    for i, sample in enumerate(batch, 1):
        display_sample(sample, i)

    print(f"=== 批量结束 ===")
    print(f"提交: python ml/scripts/label_meside.py --submit \"分数\"")
    print(f"放弃: python ml/scripts/label_meside.py --submit \"-1:理由\"")
    print()
    print("10 个标签顺序:")
    for i, label in enumerate(LABELS, 1):
        print(f"  {i}. {label}")
    print()
    print(f"剩余待标注: {remaining} 条")


if __name__ == "__main__":
    main()
