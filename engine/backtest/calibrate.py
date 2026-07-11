"""回测校准闭环脚本。

实现校准闭环流程和留一验证（Leave-One-Case-Out），防止过拟合。

用法：
    python -m engine.backtest.calibrate                # 运行留一验证
    python -m engine.backtest.calibrate --dry-run      # 仅模拟，不写日志
"""

import argparse
import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.config import OUTPUTS_DIR
from engine.backtest.analyze import (
    load_collected_data, load_cases_config, filter_high_confidence_slices,
    analyze_case_timeline, analyze_composite_diagnosis, analyze_neediness_audit,
)


BACKTEST_DIR = OUTPUTS_DIR / "backtest"
CALIBRATION_LOG = BACKTEST_DIR / "calibration_log.yaml"


def load_calibration_log():
    if CALIBRATION_LOG.exists():
        with open(CALIBRATION_LOG, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    return []


def save_calibration_log(log_entries):
    with open(CALIBRATION_LOG, "w", encoding="utf-8") as f:
        yaml.dump(log_entries, f, allow_unicode=True, default_flow_style=False)


def compute_calibration_metrics(phase_a_data, case_configs):
    """计算校准评估指标（不做推断统计）。"""
    metrics = {}
    
    all_high_conf_slices = []
    slices_by_stage = {}
    
    for case_id, case_data in phase_a_data.items():
        case_config = case_configs.get(case_id) or case_configs.get(case_data["display_name"])
        slices = filter_high_confidence_slices(case_data["time_slices"])
        
        for s in slices:
            all_high_conf_slices.append(s)
            
            stage_info = _get_slice_stage(s["ref_date"], case_config)
            stage = stage_info["stage"] if stage_info else "unknown"
            if stage not in slices_by_stage:
                slices_by_stage[stage] = []
            slices_by_stage[stage].append(s)
    
    success_outcome_slices = []
    failure_outcome_slices = []
    
    for case_id, case_data in phase_a_data.items():
        outcome = case_data["outcome"]
        slices = filter_high_confidence_slices(case_data["time_slices"])
        
        if outcome in ["success"]:
            success_outcome_slices.extend(slices)
        elif outcome in ["failure", "success_to_failure", "friendzone"]:
            failure_outcome_slices.extend(slices)
    
    success_composites = [s["composite"] for s in success_outcome_slices]
    failure_composites = [s["composite"] for s in failure_outcome_slices]
    
    overlap_ratio = 0.0
    if success_composites and failure_composites:
        success_min, success_max = min(success_composites), max(success_composites)
        failure_min, failure_max = min(failure_composites), max(failure_composites)
        
        overlap_start = max(success_min, failure_min)
        overlap_end = min(success_max, failure_max)
        
        if overlap_end > overlap_start:
            total_range = max(success_max, failure_max) - min(success_min, failure_min)
            if total_range > 0:
                overlap_ratio = (overlap_end - overlap_start) / total_range
    
    all_composites = [s["composite"] for s in all_high_conf_slices]
    if all_composites:
        metrics["composite_distribution"] = {
            "count": len(all_composites),
            "min": min(all_composites),
            "max": max(all_composites),
            "range": max(all_composites) - min(all_composites),
        }
    
    metrics["overlap_ratio"] = overlap_ratio
    
    metrics["stage_distribution"] = {}
    for stage, slices in slices_by_stage.items():
        if slices:
            composites = [s["composite"] for s in slices]
            metrics["stage_distribution"][stage] = {
                "count": len(slices),
                "composite_mean": sum(composites) / len(composites),
                "composite_min": min(composites),
                "composite_max": max(composites),
            }
    
    neediness_triggered = sum(1 for s in all_high_conf_slices if s["neediness_penalty"] < 1.0)
    metrics["neediness_trigger_rate"] = neediness_triggered / len(all_high_conf_slices) if all_high_conf_slices else 0
    
    risk_high_slices = []
    risk_low_slices = []
    for case_id, case_data in phase_a_data.items():
        case_config = case_configs.get(case_id) or case_configs.get(case_data["display_name"])
        slices = filter_high_confidence_slices(case_data["time_slices"])
        
        for s in slices:
            stage_info = _get_slice_stage(s["ref_date"], case_config)
            risk_state = stage_info["risk_state"] if stage_info else None
            
            if risk_state == "high":
                risk_high_slices.append(s["composite"])
            elif risk_state == "low":
                risk_low_slices.append(s["composite"])
    
    if risk_high_slices and risk_low_slices:
        metrics["risk_composite_gap"] = {
            "high_mean": sum(risk_high_slices) / len(risk_high_slices),
            "low_mean": sum(risk_low_slices) / len(risk_low_slices),
            "gap": (sum(risk_high_slices) / len(risk_high_slices)) - (sum(risk_low_slices) / len(risk_low_slices)),
        }
    
    return metrics


def _get_slice_stage(slice_ref_date, case_config):
    if not case_config or "stage_labels" not in case_config:
        return None
    
    ref_date = datetime.fromisoformat(slice_ref_date)
    
    for label in case_config["stage_labels"]:
        from_date = datetime.fromisoformat(label["from"])
        to_date = datetime.fromisoformat(label["to"])
        if from_date <= ref_date <= to_date:
            return {
                "stage": label["stage"],
                "window_state": label.get("window_state"),
                "risk_state": label.get("risk_state"),
            }
    return None


def leave_one_case_out_validation(phase_a_data, case_configs):
    """执行留一验证。
    
    对每个案例留出，用其余案例计算阈值，在留出案例上验证效果。
    """
    case_ids = list(phase_a_data.keys())
    if len(case_ids) < 2:
        return None, "案例数不足，无法进行留一验证"
    
    results = []
    
    for leave_out_id in case_ids:
        training_data = {k: v for k, v in phase_a_data.items() if k != leave_out_id}
        test_data = {leave_out_id: phase_a_data[leave_out_id]}
        
        train_metrics = compute_calibration_metrics(training_data, case_configs)
        test_metrics = compute_calibration_metrics(test_data, case_configs)
        
        train_overlap = train_metrics.get("overlap_ratio", 1.0)
        test_overlap = test_metrics.get("overlap_ratio", 1.0)
        
        train_risk_gap = train_metrics.get("risk_composite_gap", {}).get("gap", 0)
        test_risk_gap = test_metrics.get("risk_composite_gap", {}).get("gap", 0)
        
        improved = False
        if train_overlap < test_overlap:
            improved = True
        elif train_risk_gap > 0 and test_risk_gap > train_risk_gap * 0.5:
            improved = True
        
        results.append({
            "leave_out_case": leave_out_id,
            "leave_out_name": phase_a_data[leave_out_id]["display_name"],
            "leave_out_outcome": phase_a_data[leave_out_id]["outcome"],
            "training_cases": len(training_data),
            "train_overlap": train_overlap,
            "test_overlap": test_overlap,
            "train_risk_gap": train_risk_gap,
            "test_risk_gap": test_risk_gap,
            "improved": improved,
        })
    
    return results, None


def generate_calibration_candidates(phase_a_data, case_configs):
    """基于描述性统计生成校准候选值。"""
    candidates = []
    
    neediness_audit = analyze_neediness_audit(phase_a_data)
    vol_dist = neediness_audit["volume_ratio_distribution"]
    
    if neediness_audit["trigger_rate"] < 0.1:
        if vol_dist["pct_gt_13"] > 0.05:
            candidates.append({
                "param": "neediness_penalty.volume_ratio_threshold",
                "current": ">2.0",
                "candidate": ">1.3",
                "confidence": "high",
                "reason": f"当前触发率{neediness_audit['trigger_rate']:.1%}，降至1.3预计触发率{vol_dist['pct_gt_13']:.1%}",
            })
        elif vol_dist["pct_gt_15"] > 0:
            candidates.append({
                "param": "neediness_penalty.volume_ratio_threshold",
                "current": ">2.0",
                "candidate": ">1.5",
                "confidence": "medium",
                "reason": f"当前触发率{neediness_audit['trigger_rate']:.1%}，降至1.5预计触发率{vol_dist['pct_gt_15']:.1%}",
            })
    
    init_dist = neediness_audit["initiation_ratio_distribution"]
    if init_dist["pct_gt_07"] == 0 and init_dist["pct_gt_06"] > 0.05:
        candidates.append({
            "param": "neediness_penalty.initiation_ratio_threshold",
            "current": ">0.7",
            "candidate": ">0.6",
            "confidence": "medium",
            "reason": f"initiation_ratio > 0.7 的比例为0%，降至0.6预计触发率{init_dist.get('pct_gt_06', 0):.1%}",
        })
    
    composite_diag = analyze_composite_diagnosis(phase_a_data)
    summary = composite_diag.get("summary", {})
    comp_range = summary.get("max", 0) - summary.get("min", 0) if summary else 0
    
    if summary and comp_range < 0.2:
        candidates.append({
            "param": "composite.signal_medium_threshold",
            "current": ">=0.35",
            "candidate": f">={summary.get('p75', 0.30):.2f}",
            "confidence": "medium",
            "reason": f"composite全部分布范围仅{comp_range:.4f}，当前中窗口阈值0.35无切片达到",
        })
    
    return candidates


def validate_candidates_with_loco(candidates, loco_results):
    """用留一验证结果评估候选值的可靠性。"""
    if not loco_results:
        return []
    
    passes_count = sum(1 for r in loco_results if r["improved"])
    total_count = len(loco_results)
    pass_rate = passes_count / total_count if total_count > 0 else 0
    
    validated = []
    for candidate in candidates:
        if pass_rate > 0.5:
            candidate["loco_pass_rate"] = f"{passes_count}/{total_count}"
            if pass_rate >= 0.7:
                candidate["loco_confidence"] = "high"
            elif pass_rate >= 0.5:
                candidate["loco_confidence"] = "medium"
            else:
                candidate["loco_confidence"] = "low"
        else:
            candidate["loco_pass_rate"] = f"{passes_count}/{total_count}"
            candidate["loco_confidence"] = "low"
            candidate["loco_note"] = "留一验证未通过，建议增加案例数"
        
        validated.append(candidate)
    
    return validated


def run_calibration(dry_run=False):
    """执行完整校准流程。"""
    print("=" * 60)
    print("回测校准闭环")
    print("=" * 60)
    
    data = load_collected_data()
    case_configs = load_cases_config()
    
    if not data:
        print("错误：没有找到采集数据")
        return
    
    phase_a_data = {}
    for case_id, phases in data.items():
        if "A" in phases:
            phase_a_data[case_id] = phases["A"]
    
    if not phase_a_data:
        print("错误：没有 Phase A 数据")
        return
    
    print(f"\n数据概览：")
    print(f"  案例数: {len(phase_a_data)}")
    total_slices = sum(len(filter_high_confidence_slices(c["time_slices"])) for c in phase_a_data.values())
    print(f"  高置信度切片数: {total_slices}")
    
    print("\n" + "=" * 60)
    print("步骤1：计算当前基线指标")
    print("=" * 60)
    
    baseline_metrics = compute_calibration_metrics(phase_a_data, case_configs)
    print(f"\n当前基线:")
    print(f"  composite 分布范围: [{baseline_metrics.get('composite_distribution', {}).get('min', 0):.4f}, {baseline_metrics.get('composite_distribution', {}).get('max', 0):.4f}]")
    print(f"  成功/失败组重叠比例: {baseline_metrics.get('overlap_ratio', 0):.1%}")
    print(f"  neediness 触发率: {baseline_metrics.get('neediness_trigger_rate', 0):.1%}")
    
    risk_gap = baseline_metrics.get("risk_composite_gap", {})
    if risk_gap:
        print(f"  高风险 vs 低风险 composite 差异: {risk_gap.get('gap', 0):.4f}")
    
    print("\n" + "=" * 60)
    print("步骤2：留一验证（Leave-One-Case-Out）")
    print("=" * 60)
    
    loco_results, error = leave_one_case_out_validation(phase_a_data, case_configs)
    if error:
        print(f"  跳过: {error}")
    else:
        print(f"\n留一验证结果 ({len(loco_results)} 折):")
        passes = sum(1 for r in loco_results if r["improved"])
        print(f"  通过: {passes}/{len(loco_results)}")
        
        print("\n  详细结果:")
        print("  " + "-" * 50)
        for r in loco_results:
            status = "✅" if r["improved"] else "❌"
            print(f"  {status} {r['leave_out_name']} ({r['leave_out_outcome']}):")
            print(f"    训练集重叠: {r['train_overlap']:.1%} | 测试集重叠: {r['test_overlap']:.1%}")
            if r["train_risk_gap"] or r["test_risk_gap"]:
                print(f"    训练集风险差异: {r['train_risk_gap']:.4f} | 测试集风险差异: {r['test_risk_gap']:.4f}")
    
    print("\n" + "=" * 60)
    print("步骤3：生成校准候选值")
    print("=" * 60)
    
    candidates = generate_calibration_candidates(phase_a_data, case_configs)
    
    if loco_results:
        candidates = validate_candidates_with_loco(candidates, loco_results)
    
    print(f"\n生成 {len(candidates)} 个校准候选值:")
    print("  " + "-" * 50)
    for c in candidates:
        confidence = c.get("confidence", "medium")
        loco_conf = c.get("loco_confidence", "-")
        print(f"  [{confidence}/{loco_conf}] {c['param']}:")
        print(f"    当前值: {c['current']}")
        print(f"    候选值: {c['candidate']}")
        print(f"    理由: {c['reason']}")
        if c.get("loco_note"):
            print(f"    备注: {c['loco_note']}")
    
    print("\n" + "=" * 60)
    print("步骤4：记录校准日志")
    print("=" * 60)
    
    log_entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "cases_used": list(phase_a_data.keys()),
        "total_slices": total_slices,
        "baseline_metrics": baseline_metrics,
        "loco_validation": {
            "passes": passes if loco_results else 0,
            "total": len(loco_results) if loco_results else 0,
            "results": loco_results,
        },
        "candidates": candidates,
        "status": "pending",
    }
    
    if not dry_run:
        log_entries = load_calibration_log()
        log_entries.append(log_entry)
        save_calibration_log(log_entries)
        print(f"\n校准日志已保存: {CALIBRATION_LOG}")
    else:
        print("\n[模拟模式] 校准日志未写入")
    
    print("\n" + "=" * 60)
    print("校准流程完成")
    print("=" * 60)
    print("\n下一步：")
    print("  1. 审核候选值，选择要应用的参数")
    print("  2. 修改 config.yaml / formulas.py / metrics.py")
    print("  3. 重新采集数据（或用缓存重算 composite）")
    print("  4. 重新运行 analyze.py 和 calibrate.py")
    print("  5. 更新校准日志的 status 为 'applied'")
    
    return log_entry


def main():
    parser = argparse.ArgumentParser(description="回测校准闭环")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅模拟，不写校准日志")
    args = parser.parse_args()
    
    run_calibration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()