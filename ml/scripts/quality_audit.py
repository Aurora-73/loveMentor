#!/usr/bin/env python3
"""标注质量审计脚本 — 检测敷衍标注 + 可回收 -1 样本。

用法:
  # 只读审计（方法 A：低变化量检测）
  python ml/scripts/quality_audit.py

  # 方法 A + B（模型偏差验证，需先跑 batch_predict.py）
  python ml/scripts/quality_audit.py --predictions data/ml_dataset/predictions.jsonl

  # 输出到文件
  python ml/scripts/quality_audit.py --output quality_report.json

  # 执行修复（移动问题样本到末尾，清除标注）
  python ml/scripts/quality_audit.py --fix [--dry-run]
  python ml/scripts/quality_audit.py --fix --predictions predictions.jsonl

  # 只看 -1 回收分析
  python ml/scripts/quality_audit.py --recycle-only
"""
from __future__ import annotations

import json
import sys
import copy
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np

# ── 路径 ──

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BATCHES_DIR = PROJECT_ROOT / "ml" / "dataset" / "batches"
CLEANED_DIR = BATCHES_DIR / "rerun" / "cleaned"
ANN_DIR = PROJECT_ROOT / "data" / "ml_dataset"

LABELS = [
    "information_exchange", "opinion_expression", "emotion_positive",
    "emotion_negative", "flirt", "question_asking", "self_disclosure",
    "invitation", "framing_boundary", "perfunctory",
]

# ── 默认阈值 ──

DEFAULT_WINDOW_SIZE = 10
DEFAULT_WINDOW_STEP = 5
DEFAULT_VARIANCE_THRESHOLD = 0.6   # 10 维 std 均值 < 0.6 → 低变化嫌疑
DEFAULT_RUN_THRESHOLD = 5          # 连续 5+ 条完全相同 → 嫌疑
DEFAULT_MODEL_MAE_THRESHOLD = 1.5  # 模型 MAE > 1.5 → 偏差大
DEFAULT_RECYCLE_MIN_MSGS = 6       # 至少 6 条消息（3 轮）才算可回收


# ═══════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_batch_paths(source_dir: Path = BATCHES_DIR) -> list[Path]:
    return sorted(source_dir.glob("batch_*.jsonl"))


def batch_num_from_path(path: Path) -> str:
    return path.name.replace("batch_", "").replace(".jsonl", "")


def load_predictions(path: Path) -> dict[str, np.ndarray]:
    """返回 {sample_id: np.array([10 个分数])}"""
    result = {}
    for record in load_jsonl(path):
        result[record["sample_id"]] = np.array(record["scores"])
    return result


def get_annotation_files() -> list[Path]:
    return sorted(ANN_DIR.glob("annotations_*.jsonl"))


def load_annotations_by_batch() -> dict[str, list[dict]]:
    """按 batch 分组加载非 discard 的标注。"""
    batch_annotations = defaultdict(list)

    # 先读所有 batch 文件得到 sample_id → batch 映射
    sid_to_batch = {}
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        for s in load_jsonl(bpath):
            sid_to_batch[s["sample_id"]] = bnum

    # 读 annotation 文件
    for apath in get_annotation_files():
        for ann in load_jsonl(apath):
            sid = ann["sample_id"]
            if sid not in sid_to_batch:
                continue
            bnum = sid_to_batch[sid]
            batch_annotations[bnum].append(ann)

    return dict(batch_annotations)


def load_samples_by_batch() -> dict[str, list[dict]]:
    """按 batch 加载样本。"""
    result = {}
    for bpath in get_batch_paths():
        bnum = batch_num_from_path(bpath)
        result[bnum] = load_jsonl(bpath)
    return result


# ═══════════════════════════════════════════
#  方法 A：低变化量检测
# ═══════════════════════════════════════════

def get_score_vector(ann: dict) -> np.ndarray | None:
    """从标注记录中提取 10 维分数向量。返回 None 如果是 discard。"""
    if ann.get("discard") or not ann.get("labels"):
        return None
    return np.array([ann["labels"].get(l, 0) for l in LABELS], dtype=float)


def sliding_window_analysis(
    annotations: list[dict],
    window_size: int = DEFAULT_WINDOW_SIZE,
    step: int = DEFAULT_WINDOW_STEP,
) -> list[dict]:
    """滑动窗口检测低变化量。

    返回标注在窗口中心附近的索引列表，以及窗口统计信息。
    """
    # 提取分数向量（跳过 discard）
    indices = []
    vectors = []
    for i, ann in enumerate(annotations):
        v = get_score_vector(ann)
        if v is not None:
            indices.append(i)
            vectors.append(v)

    if len(vectors) < window_size:
        return []

    flags = []

    # 连续相同检测（不依赖窗口）
    run_start = 0
    for i in range(1, len(vectors)):
        if np.array_equal(vectors[i], vectors[i - 1]):
            continue
        run_len = i - run_start
        if run_len >= DEFAULT_RUN_THRESHOLD:
            # 标记这个 run 中的所有样本
            for j in range(run_start, i):
                flags.append({
                    "ann_index": indices[j],
                    "sample_id": annotations[indices[j]]["sample_id"],
                    "reason": "consecutive_identical",
                    "run_length": run_len,
                    "scores": vectors[j].tolist(),
                    "window_var": 0.0,
                })
        run_start = i
    # Last run
    run_len = len(vectors) - run_start
    if run_len >= DEFAULT_RUN_THRESHOLD:
        for j in range(run_start, len(vectors)):
            flags.append({
                "ann_index": indices[j],
                "sample_id": annotations[indices[j]]["sample_id"],
                "reason": "consecutive_identical",
                "run_length": run_len,
                "scores": vectors[j].tolist(),
                "window_var": 0.0,
            })

    # 滑动窗口方差检测
    flagged_sids = {f["sample_id"] for f in flags}
    for start_idx in range(0, len(vectors) - window_size + 1, step):
        window = vectors[start_idx:start_idx + window_size]
        window_indices = indices[start_idx:start_idx + window_size]

        # 计算窗口内每列的标准差
        window_array = np.array(window)
        per_label_std = np.std(window_array, axis=0)
        mean_std = float(np.mean(per_label_std))

        if mean_std >= DEFAULT_VARIANCE_THRESHOLD:
            continue

        # 标记窗口内的所有样本
        for pos, vi in zip(window_indices, window):
            sid = annotations[pos]["sample_id"]
            if sid in flagged_sids:
                continue  # 已通过 consecutive_identical 标过
            flags.append({
                "ann_index": pos,
                "sample_id": sid,
                "reason": "low_variation",
                "scores": vi.tolist(),
                "window_var": round(mean_std, 3),
                "per_label_std": {l: round(float(s), 2) for l, s in zip(LABELS, per_label_std)},
            })
            flagged_sids.add(sid)

    return flags


# ═══════════════════════════════════════════
#  方法 B：模型偏差验证
# ═══════════════════════════════════════════

def verify_with_model(
    flags: list[dict],
    annotations: list[dict],
    predictions: dict[str, np.ndarray],
) -> list[dict]:
    """对 flagged 样本验证模型偏差。

    返回包含 model_mae 的更新后的 flag 列表。
    """
    for f in flags:
        sid = f["sample_id"]
        if sid not in predictions:
            f["model_mae"] = None
            f["model_supported"] = False
            continue

        # 找到对应的 annotation
        ann = next((a for a in annotations if a["sample_id"] == sid), None)
        if ann is None or ann.get("discard") or not ann.get("labels"):
            f["model_mae"] = None
            f["model_supported"] = False
            continue

        human = get_score_vector(ann)
        model = predictions[sid] * 9.0  # 从 [0,1] 恢复到 [0,9]

        # 计算 10 维的 MAE
        mae = float(np.mean(np.abs(human - model)))

        # 只计算值得信任的维度
        trusted_labels = ["opinion_expression", "emotion_positive", "flirt", "invitation"]
        trusted_idx = [i for i, l in enumerate(LABELS) if l in trusted_labels]
        trusted_mae = float(np.mean(np.abs(human[trusted_idx] - model[trusted_idx])))

        f["model_mae"] = round(mae, 3)
        f["trusted_mae"] = round(trusted_mae, 3)
        f["model_prediction"] = [round(float(s), 2) for s in model]
        f["model_supported"] = True

    return flags


# ═══════════════════════════════════════════
#  -1 可回收分析
# ═══════════════════════════════════════════

def find_recyclable_discards(
    batch_samples: list[dict],
    annotations: list[dict],
    min_messages: int = DEFAULT_RECYCLE_MIN_MSGS,
) -> list[dict]:
    """找到可回收的 -1 样本（对话不短且被丢弃的）。"""
    ann_by_sid = {a["sample_id"]: a for a in annotations if a.get("discard")}
    sample_by_sid = {s["sample_id"]: s for s in batch_samples}

    recyclable = []
    for sid, ann in ann_by_sid.items():
        if sid not in sample_by_sid:
            continue
        msgs = sample_by_sid[sid]["messages"]
        if len(msgs) >= min_messages:
            recyclable.append({
                "sample_id": sid,
                "msg_count": len(msgs),
                "discard_reason": ann.get("discard_reason", ""),
                "ann_index": next(
                    i for i, a in enumerate(annotations) if a["sample_id"] == sid
                ),
            })

    return recyclable


# ═══════════════════════════════════════════
#  报告生成
# ═══════════════════════════════════════════

def generate_report(
    batch_flags: dict[str, list[dict]],
    batch_recyclable: dict[str, list[dict]],
    batch_annotations: dict[str, list[dict]],
    batch_samples: dict[str, list[dict]],
) -> dict:
    """生成完整的质检报告。"""
    total_flags = sum(len(v) for v in batch_flags.values())
    total_recyclable = sum(len(v) for v in batch_recyclable.values())
    total_samples = sum(len(v) for v in batch_samples.values())
    total_annotations = sum(len(v) for v in batch_annotations.values())

    summary = {
        "total_batches": len(batch_samples),
        "total_samples": total_samples,
        "total_annotations": total_annotations,
        "total_flags": total_flags,
        "total_recyclable": total_recyclable,
        "batches": {},
    }

    for bnum in sorted(batch_samples.keys()):
        samples = batch_samples.get(bnum, [])
        anns = batch_annotations.get(bnum, [])
        flags = batch_flags.get(bnum, [])
        recyclable = batch_recyclable.get(bnum, [])

        # 分类 flag 类型
        low_var = [f for f in flags if f["reason"] == "low_variation"]
        same_run = [f for f in flags if f["reason"] == "consecutive_identical"]

        # 模型偏差统计
        model_high = [
            f for f in flags
            if f.get("model_supported") and f.get("model_mae", 0) > DEFAULT_MODEL_MAE_THRESHOLD
        ]

        # -1 统计
        discards = [a for a in anns if a.get("discard")]
        non_discard = [a for a in anns if not a.get("discard")]

        batch_info = {
            "samples": len(samples),
            "annotations_total": len(anns),
            "annotations_ok": len(non_discard),
            "discards": len(discards),
            "flags_total": len(flags),
            "flags_low_variation": len(low_var),
            "flags_consecutive_identical": len(same_run),
            "flags_model_high_disagreement": len(model_high),
            "recyclable_discards": len(recyclable),
        }

        # 如果 flags 有模型数据，计算汇总
        if model_high:
            batch_info["model_mae_avg"] = round(
                np.mean([f["model_mae"] for f in flags if f.get("model_supported")]), 3
            )

        summary["batches"][bnum] = batch_info

    return summary


def print_report(report: dict) -> None:
    """输出可读的报告到 stdout。"""
    print(f"\n{'=' * 80}")
    print(f"标注质量审计报告")
    print(f"{'=' * 80}")

    total_flagged = 0
    total_recyclable = 0

    for bnum in sorted(report["batches"].keys()):
        bi = report["batches"][bnum]
        f = bi["flags_total"]
        r = bi["recyclable_discards"]
        total_flagged += f
        total_recyclable += r

        icon = "✓" if f == 0 else "●"
        print(f"\n{icon} batch_{bnum}:")
        print(f"    标注: {bi['annotations_ok']} 正常 / {bi['discards']} 丢弃")
        if f > 0:
            parts = []
            if bi["flags_low_variation"] > 0:
                parts.append(f"低变化 {bi['flags_low_variation']} 条")
            if bi["flags_consecutive_identical"] > 0:
                parts.append(f"连续相同 {bi['flags_consecutive_identical']} 条")
            if bi.get("flags_model_high_disagreement", 0) > 0:
                parts.append(f"模型偏差大 {bi['flags_model_high_disagreement']} 条")
            print(f"    ⚠ 嫌疑: {', '.join(parts)}")
        if r > 0:
            print(f"    ♻ 可回收 -1: {r} 条")

    print(f"\n{'=' * 80}")
    print(f"总计: {report['total_batches']} 个 batch")
    print(f"      {report['total_annotations']} 条标注")
    print(f"      {total_flagged} 条敷衍嫌疑")
    print(f"      {total_recyclable} 条可回收 -1")
    print(f"{'=' * 80}")


def print_detailed_flags(
    batch_flags: dict[str, list[dict]],
    batch_recyclable: dict[str, list[dict]],
    annotations: dict[str, list[dict]],
    samples: dict[str, list[dict]],
) -> None:
    """输出有嫌疑的具体样本信息。"""

    # ── 各 batch 的敷衍嫌疑 ──
    has_any = any(len(v) > 0 for v in batch_flags.values())
    if has_any:
        print(f"\n{'=' * 80}")
        print("敷衍嫌疑详情")
        print(f"{'=' * 80}")

        for bnum in sorted(batch_flags.keys()):
            flags = batch_flags[bnum]
            if not flags:
                continue

            print(f"\n--- batch_{bnum}: {len(flags)} 条嫌疑 ---")
            # 按 ann_index 排序
            flags_sorted = sorted(flags, key=lambda f: f["ann_index"])

            for f in flags_sorted:
                reason = "连续相同" if f["reason"] == "consecutive_identical" else "低变化"
                detail = f"  [{reason}] {f['sample_id']}  scores={f['scores']}"
                if f.get("model_supported"):
                    detail += f"  MAE={f['model_mae']}"
                    detail += f"  pred={f['model_prediction']}"
                print(detail)

    # ── 可回收 -1 ──
    has_any_recyclable = any(len(v) > 0 for v in batch_recyclable.values())
    if has_any_recyclable:
        print(f"\n{'=' * 80}")
        print("可回收 -1 详情")
        print(f"{'=' * 80}")

        # 收集所有批次的标记信息
        union_sids = {}
        for bnum, samples_list in samples.items():
            sid_to_ann = {}
            for a in annotations.get(bnum, []):
                if a.get("discard") and a["sample_id"] not in sid_to_ann:
                    sid_to_ann[a["sample_id"]] = a
            union_sids[bnum] = sid_to_ann

        for bnum in sorted(batch_recyclable.keys()):
            recyclable = batch_recyclable[bnum]
            if not recyclable:
                continue

            print(f"\n--- batch_{bnum}: {len(recyclable)} 条可回收 ---")
            for r in sorted(recyclable, key=lambda x: x["ann_index"]):
                reason = r["discard_reason"][:40] if r["discard_reason"] else "未说明"
                print(f"  {r['sample_id']}  msgs={r['msg_count']}  reason=\"{reason}\"")


# ═══════════════════════════════════════════
#  修复模式（--fix）
# ═══════════════════════════════════════════

def fix_batch(
    bnum: str,
    flagged_sids: set[str],
    recyclable_sids: set[str],
    samples: list[dict],
    annotations: list[dict],
    ann_path: Path,
    dry_run: bool = False,
) -> dict:
    """将问题样本移动到 batch 末尾，清除对应标注。

    返回修改统计。
    """
    move_sids = flagged_sids | recyclable_sids
    batch_path = BATCHES_DIR / f"batch_{bnum}.jsonl"

    if not batch_path.exists():
        return {"error": f"batch file not found: {batch_path}"}

    changes = {"moved": len(move_sids), "removed_annotations": 0, "flagged": len(flagged_sids), "recycled": len(recyclable_sids)}

    if dry_run:
        return changes

    # ── 修改 batch 文件（把问题样本移到末尾）──
    keep = []
    move = []
    for s in samples:
        if s["sample_id"] in move_sids:
            move.append(s)
        else:
            keep.append(s)

    if not move:
        return changes

    reordered = keep + move
    with open(batch_path, "w", encoding="utf-8") as f:
        for s in reordered:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # ── 删除对应的标注 ──
    remaining_annotations = [
        a for a in annotations if a["sample_id"] not in move_sids
    ]
    removed_count = len(annotations) - len(remaining_annotations)
    changes["removed_annotations"] = removed_count

    with open(ann_path, "w", encoding="utf-8") as f:
        for a in remaining_annotations:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    return changes


# ═══════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="标注质量审计")
    parser.add_argument("--predictions", default=None,
                        help="模型预测结果文件（由 batch_predict.py 生成）")
    parser.add_argument("--output", default=None,
                        help="报告输出路径（JSON 格式）")
    parser.add_argument("--fix", action="store_true",
                        help="执行修复（移动样本到末尾 + 清除标注）")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式（不实际修改文件）")
    parser.add_argument("--recycle-only", action="store_true",
                        help="只分析 -1 回收")
    parser.add_argument("--window-size", type=int, default=DEFAULT_WINDOW_SIZE)
    parser.add_argument("--window-step", type=int, default=DEFAULT_WINDOW_STEP)
    parser.add_argument("--var-threshold", type=float, default=DEFAULT_VARIANCE_THRESHOLD,
                        help=f"窗口方差阈值（默认 {DEFAULT_VARIANCE_THRESHOLD}）")
    parser.add_argument("--model-mae", type=float, default=DEFAULT_MODEL_MAE_THRESHOLD,
                        help=f"模型 MAE 阈值（默认 {DEFAULT_MODEL_MAE_THRESHOLD}）")
    parser.add_argument("--min-msgs", type=int, default=DEFAULT_RECYCLE_MIN_MSGS,
                        help=f"-1 回收最小消息数（默认 {DEFAULT_RECYCLE_MIN_MSGS}）")
    parser.add_argument("--detailed", action="store_true",
                        help="输出嫌疑样本详情")
    parser.add_argument("--mae-percentile", type=float, default=None,
                        help="按批次百分位过滤模型MAE（如 80 = 只保留MAE在批次前20%的）")
    args = parser.parse_args()

    # ── 加载数据 ──
    samples = load_samples_by_batch()
    all_annotations = load_annotations_by_batch()

    # ── 加载模型预测（可选）──
    predictions = {}
    if args.predictions or args.mae_percentile:
        pred_path = Path(args.predictions or ANN_DIR / "predictions.jsonl")
        if pred_path.exists():
            predictions = load_predictions(pred_path)
            print(f"Loaded predictions: {len(predictions)} samples")
        else:
            print(f"Warning: predictions file not found: {pred_path}")

    # ── 计算每批次的 MAE 百分位阈值（如果启用 percentile 过滤）──
    batch_mae_percentiles = {}
    if args.mae_percentile is not None and predictions:
        apath = ANN_DIR
        for bnum, batch_samples in samples.items():
            maes = []
            for ann in all_annotations.get(bnum, []):
                sid = ann["sample_id"]
                if ann.get("discard") or not ann.get("labels") or sid not in predictions:
                    continue
                human = get_score_vector(ann)
                model = predictions[sid] * 9.0
                mae = float(np.mean(np.abs(human - model)))
                maes.append(mae)
            if maes:
                batch_mae_percentiles[bnum] = np.percentile(maes, args.mae_percentile)
        print(f"Using MAE > P{args.mae_percentile} threshold per batch")

    # ── 运行分析 ──
    batch_flags = {}
    batch_recyclable = {}

    for bnum in sorted(samples.keys()):
        anns = all_annotations.get(bnum, [])
        batch_samples = samples[bnum]

        # 方法 A
        if not args.recycle_only:
            flags = sliding_window_analysis(
                anns, args.window_size, args.window_step,
            )
            # 方法 B
            if predictions and flags:
                flags = verify_with_model(flags, anns, predictions)

            # 按批次百分位过滤（只保留低变化样本中模型偏差大的）
            if args.mae_percentile is not None and predictions:
                th = batch_mae_percentiles.get(bnum, float("inf"))
                filtered = []
                for f in flags:
                    if f["reason"] == "consecutive_identical":
                        filtered.append(f)  # 连续相同无条件保留
                    elif f.get("model_mae") is not None and f["model_mae"] > th:
                        filtered.append(f)
                batch_flags[bnum] = filtered
            else:
                batch_flags[bnum] = flags

        # -1 回收分析
        recyclable = find_recyclable_discards(batch_samples, anns, args.min_msgs)
        batch_recyclable[bnum] = recyclable

    # ── 报告 ──
    report = generate_report(batch_flags, batch_recyclable, all_annotations, samples)
    print_report(report)

    if args.detailed:
        print_detailed_flags(batch_flags, batch_recyclable, all_annotations, samples)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 把详细 flag 信息附加到报告
        report["_flags"] = {
            bnum: sorted(f, key=lambda x: x["ann_index"])
            for bnum, f in batch_flags.items()
        }
        report["_recyclable"] = {
            bnum: sorted(r, key=lambda x: x["ann_index"])
            for bnum, r in batch_recyclable.items()
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {out_path}")

    # ── 修复模式 ──
    if args.fix:
        print(f"\n{'=' * 80}")
        print("执行修复模式")
        print(f"{'=' * 80}")

        # 找到每个 batch 对应的 annotation 文件
        ann_file_for_batch = {}
        for apath in get_annotation_files():
            for ann in load_jsonl(apath):
                sid = ann["sample_id"]
                for bnum, batch_samples in samples.items():
                    if any(s["sample_id"] == sid for s in batch_samples):
                        ann_file_for_batch[bnum] = apath
                        break

        total_moved = 0
        for bnum in sorted(samples.keys()):
            flagged = {f["sample_id"] for f in batch_flags.get(bnum, [])}
            recyclable = {r["sample_id"] for r in batch_recyclable.get(bnum, [])}

            if not flagged and not recyclable:
                continue

            result = fix_batch(
                bnum=bnum,
                flagged_sids=flagged,
                recyclable_sids=recyclable,
                samples=samples[bnum],
                annotations=all_annotations.get(bnum, []),
                ann_path=ann_file_for_batch.get(bnum, ANN_DIR / f"annotations_{bnum}.jsonl"),
                dry_run=args.dry_run,
            )

            if args.dry_run:
                print(f"  [DRY RUN] batch_{bnum}: 将移动 {result['moved']} 条（敷衍 {result['flagged']} + 回收 {result['recycled']}）")
            else:
                print(f"  batch_{bnum}: 移动 {result['moved']} 条（敷衍 {result['flagged']} + 回收 {result['recycled']}），删除标注 {result['removed_annotations']} 条")
            total_moved += result["moved"]

        print(f"\n总计: {'[DRY RUN] ' if args.dry_run else ''}移动 {total_moved} 条样本")
        if not args.dry_run:
            print("请 git commit 确认修改，然后交给 Trae 重清洗重标注。")
        else:
            print("确认无误后，去掉 --dry-run 执行实际修复。")


if __name__ == "__main__":
    main()
