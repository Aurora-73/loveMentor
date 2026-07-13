"""回测数据分析脚本 - 案例内时序分析模式。

读取采集的 JSON 数据，以 ground truth 为标准审判系统参数是否合理。

核心逻辑：
  以案例内时序分析为主（每个案例自己的时间曲线）
  组间对比仅作辅助交叉验证
  只用描述性统计，不做推断统计（t检验/p值）

用法：
    python -m engine.backtest.analyze    # 分析所有采集数据
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.backtest.load_cases import load_cases as _load_cases
from engine.config import OUTPUTS_DIR


BACKTEST_DIR = OUTPUTS_DIR / "backtest"
REPORT_FILE = BACKTEST_DIR / "calibration_report.md"


def load_collected_data():
    data = {}
    for f in BACKTEST_DIR.glob("*.json"):
        if f.name.startswith("."):
            continue
        with open(f, "r", encoding="utf-8") as fp:
            case_data = json.load(fp)
            case_id = case_data["case_id"]
            phase = "A" if "_phase_a" in f.name else "B"
            if case_id not in data:
                data[case_id] = {}
            data[case_id][phase] = case_data
    return data


def load_cases_config():
    cases_list = _load_cases()
    return {case["id"]: case for case in cases_list}


def filter_high_confidence_slices(slices, min_messages=10):
    filtered = []
    for s in slices:
        msg_count = s.get("metrics", {}).get("msg_count", {}).get("raw", 0)
        if msg_count >= min_messages:
            filtered.append(s)
    return filtered


def get_slice_stage_label(slice_ref_date, case_config):
    """根据案例的 stage_labels 判断切片属于哪个阶段。"""
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


def analyze_case_timeline(case_data, case_config=None):
    """维度1：案例内时序分析（主分析）。
    
    对单个案例分析指标随时间的变化，识别转折点和预警能力。
    """
    slices = filter_high_confidence_slices(case_data["time_slices"])
    if not slices:
        return None
    
    slices.sort(key=lambda s: s["ref_date"])
    
    timeline = []
    for s in slices:
        ref_date = datetime.fromisoformat(s["ref_date"])
        stage_info = get_slice_stage_label(s["ref_date"], case_config)
        
        timeline.append({
            "ref_date": s["ref_date"],
            "composite": s["composite"],
            "fback": s["metrics"].get("fback", {}).get("normalized", 0),
            "fback_raw": s["metrics"].get("fback", {}).get("raw", 0),
            "neediness": s["neediness_penalty"],
            "msg_count": s["metrics"].get("msg_count", {}).get("raw", 0),
            "signal_level": s["signal_level"],
            "stage": stage_info["stage"] if stage_info else None,
            "window_state": stage_info["window_state"] if stage_info else None,
            "risk_state": stage_info["risk_state"] if stage_info else None,
        })
    
    outcome_date = datetime.fromisoformat(case_data["outcome_date"])
    
    early_warnings = []
    for i in range(len(timeline) - 1):
        current = timeline[i]
        next_slice = timeline[i + 1]
        current_date = datetime.fromisoformat(current["ref_date"])
        
        days_to_outcome = (outcome_date - current_date).days
        
        if days_to_outcome <= 0:
            continue
        
        composite_drop = current["composite"] - next_slice["composite"]
        fback_drop = current["fback"] - next_slice["fback"]
        
        if composite_drop > 0.05 or fback_drop > 0.1:
            early_warnings.append({
                "date": current["ref_date"],
                "days_to_outcome": days_to_outcome,
                "trigger": f"composite下降{composite_drop:.3f}" if composite_drop > 0.05 else "",
                "fback_trigger": f"fback下降{fback_drop:.3f}" if fback_drop > 0.1 else "",
            })
    
    metrics_eval = {
        "composite": {
            "has_trend": False,
            "trend_direction": None,
            "warnings": [],
        },
        "fback": {
            "has_trend": False,
            "trend_direction": None,
            "warnings": [],
        },
        "neediness": {
            "ever_triggered": any(t["neediness"] < 1.0 for t in timeline),
            "trigger_points": [t for t in timeline if t["neediness"] < 1.0],
        },
    }
    
    if len(timeline) >= 3:
        first_half = timeline[:len(timeline)//2]
        second_half = timeline[len(timeline)//2:]
        
        first_composite = sum(t["composite"] for t in first_half) / len(first_half)
        second_composite = sum(t["composite"] for t in second_half) / len(second_half)
        if abs(first_composite - second_composite) > 0.03:
            metrics_eval["composite"]["has_trend"] = True
            metrics_eval["composite"]["trend_direction"] = "下降" if second_composite < first_composite else "上升"
        
        first_fback = sum(t["fback"] for t in first_half) / len(first_half)
        second_fback = sum(t["fback"] for t in second_half) / len(second_half)
        if abs(first_fback - second_fback) > 0.05:
            metrics_eval["fback"]["has_trend"] = True
            metrics_eval["fback"]["trend_direction"] = "下降" if second_fback < first_fback else "上升"
    
    for ew in early_warnings:
        if ew["trigger"]:
            metrics_eval["composite"]["warnings"].append(ew)
        if ew["fback_trigger"]:
            metrics_eval["fback"]["warnings"].append(ew)
    
    return {
        "display_name": case_data["display_name"],
        "outcome": case_data["outcome"],
        "outcome_date": case_data["outcome_date"],
        "timeline": timeline,
        "early_warnings": early_warnings,
        "metrics_eval": metrics_eval,
        "slices_count": len(timeline),
    }


def analyze_composite_diagnosis(phase_a_data):
    """维度2：composite公式诊断。
    
    全量切片分布统计，不做组间推断。
    """
    all_composites = []
    composites_by_group = {"success": [], "failure": [], "friendzone": [], "success_to_failure": []}
    neediness_by_group = {"success": [], "failure": [], "friendzone": [], "success_to_failure": []}
    signal_levels_by_group = {"success": [], "failure": [], "friendzone": [], "success_to_failure": []}
    
    for case_id, case_data in phase_a_data.items():
        outcome = case_data["outcome"]
        if outcome not in composites_by_group:
            continue
        slices = filter_high_confidence_slices(case_data["time_slices"])
        if not slices:
            continue
        
        for s in slices:
            all_composites.append(s["composite"])
            composites_by_group[outcome].append(s["composite"])
            neediness_by_group[outcome].append(s["neediness_penalty"])
            signal_levels_by_group[outcome].append(s["signal_level"])
    
    diagnosis = {
        "composite_distribution": {},
        "neediness_audit": {},
        "signal_level_analysis": {},
        "issues": [],
        "summary": {},
    }
    
    if all_composites:
        sorted_composites = sorted(all_composites)
        n = len(sorted_composites)
        diagnosis["summary"] = {
            "count": n,
            "min": sorted_composites[0],
            "p25": sorted_composites[max(0, n//4)],
            "p50": sorted_composites[max(0, n//2)],
            "p75": sorted_composites[max(0, n*3//4)],
            "max": sorted_composites[-1],
        }
    
    for group_name, values in composites_by_group.items():
        if values:
            diagnosis["composite_distribution"][group_name] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
            }
    
    for group_name, values in neediness_by_group.items():
        if values:
            triggered = sum(1 for v in values if v < 1.0)
            diagnosis["neediness_audit"][group_name] = {
                "count": len(values),
                "triggered": triggered,
                "trigger_rate": triggered / len(values),
                "min": min(values),
                "max": max(values),
            }
    
    for group_name, values in signal_levels_by_group.items():
        if values:
            level_dist = {}
            for v in values:
                level_dist[v] = level_dist.get(v, 0) + 1
            diagnosis["signal_level_analysis"][group_name] = {
                "count": len(values),
                "distribution": level_dist,
                "most_common": max(level_dist, key=level_dist.get),
            }
    
    success_composites = composites_by_group["success"]
    failure_composites = composites_by_group["failure"]
    
    if success_composites and failure_composites:
        success_range = (min(success_composites), max(success_composites))
        failure_range = (min(failure_composites), max(failure_composites))
        overlap_start = max(success_range[0], failure_range[0])
        overlap_end = min(success_range[1], failure_range[1])
        
        if overlap_end > overlap_start:
            diagnosis["issues"].append(f"composite分布完全重叠：成功组{success_range}，失败组{failure_range}，重叠区间[{overlap_start:.3f}, {overlap_end:.3f}]")
    
    if diagnosis["neediness_audit"].get("failure", {}).get("trigger_rate", 0) == 0:
        diagnosis["issues"].append("neediness_penalty在失败组中从未触发")
    
    if diagnosis["neediness_audit"].get("success_to_failure", {}).get("trigger_rate", 0) == 0:
        diagnosis["issues"].append("neediness_penalty在先成后败组中从未触发")
    
    if diagnosis["signal_level_analysis"].get("success", {}).get("most_common") in ["冷淡", "无信号"]:
        diagnosis["issues"].append("成功案例的signal_level大多为'冷淡'或'无信号'，阈值可能偏高")
    
    for level in ["中窗口", "强窗口"]:
        for group in signal_levels_by_group.values():
            if level in group:
                break
        else:
            diagnosis["issues"].append(f"'{level}'信号等级无任何切片达到")
    
    return diagnosis


def analyze_signal_lead_lag(phase_a_data, phase_b_data):
    """维度3：信号领先/滞后分析。
    
    看公式在结果出来前多少天能发出正确信号。
    """
    results = []
    
    for case_id, case_a in phase_a_data.items():
        case_b = phase_b_data.get(case_id)
        if not case_b:
            continue
        
        outcome = case_a["outcome"]
        outcome_date = datetime.fromisoformat(case_a["outcome_date"])
        
        slices = filter_high_confidence_slices(case_a["time_slices"])
        if not slices:
            continue
        
        expected_action_for_outcome = {
            "success": ["进攻", "进攻（谨慎）"],
            "failure": ["重置", "维持"],
            "friendzone": ["维持"],
            "success_to_failure": ["重置"],
        }
        
        expected_actions = expected_action_for_outcome.get(outcome, [])
        
        first_correct_date = None
        last_wrong_date = None
        rounds_differ = False
        
        for s in slices:
            ref_date = datetime.fromisoformat(s["ref_date"])
            
            slice_b = next((sb for sb in case_b["time_slices"] if sb["ref_date"] == s["ref_date"]), None)
            if not slice_b:
                continue
            
            if len(slice_b["rounds"]) >= 2:
                default_action = slice_b["rounds"][0]["action"]["action"]
                truth_action = slice_b["rounds"][1]["action"]["action"]
                if default_action != truth_action:
                    rounds_differ = True
                actual_action = truth_action
            else:
                actual_action = slice_b["rounds"][0]["action"]["action"]
            
            is_correct = actual_action in expected_actions
            
            if is_correct and first_correct_date is None:
                first_correct_date = ref_date
            elif not is_correct:
                last_wrong_date = ref_date
        
        if first_correct_date:
            lead_days = (outcome_date - first_correct_date).days
        else:
            lead_days = None
        
        results.append({
            "case_id": case_id,
            "display_name": case_a["display_name"],
            "outcome": outcome,
            "slices_count": len(slices),
            "first_correct_date": first_correct_date.isoformat() if first_correct_date else None,
            "lead_days": lead_days,
            "correct_signal": "✅" if lead_days and lead_days > 7 else "⚠️" if lead_days else "❌",
            "rounds_differ": rounds_differ,
        })
    
    return results


def analyze_neediness_audit(phase_a_data):
    """维度4：neediness_penalty专项审计。"""
    all_neediness = []
    volume_ratios = []
    initiation_ratios = []
    case_neediness = {}
    
    for case_id, case_data in phase_a_data.items():
        slices = filter_high_confidence_slices(case_data["time_slices"])
        case_neediness[case_id] = {
            "display_name": case_data["display_name"],
            "outcome": case_data["outcome"],
            "penalties": [],
            "volume_ratios": [],
            "initiation_ratios": [],
        }
        
        for s in slices:
            all_neediness.append(s["neediness_penalty"])
            volume_ratios.append(s.get("volume_ratio", 1.0))
            initiation_ratios.append(s.get("initiation_ratio", 0.5))
            
            case_neediness[case_id]["penalties"].append(s["neediness_penalty"])
            case_neediness[case_id]["volume_ratios"].append(s.get("volume_ratio", 1.0))
            case_neediness[case_id]["initiation_ratios"].append(s.get("initiation_ratio", 0.5))
    
    audit = {
        "total_slices": len(all_neediness),
        "min_penalty": min(all_neediness) if all_neediness else 0,
        "max_penalty": max(all_neediness) if all_neediness else 0,
        "triggered_count": sum(1 for v in all_neediness if v < 1.0),
        "trigger_rate": sum(1 for v in all_neediness if v < 1.0) / len(all_neediness) if all_neediness else 0,
        "case_detail": {},
        "volume_ratio_distribution": {
            "count": len(volume_ratios),
            "min": min(volume_ratios) if volume_ratios else 0,
            "max": max(volume_ratios) if volume_ratios else 0,
            "mean": sum(volume_ratios) / len(volume_ratios) if volume_ratios else 0,
            "pct_gt_2": sum(1 for v in volume_ratios if v > 2.0) / len(volume_ratios) if volume_ratios else 0,
            "pct_gt_15": sum(1 for v in volume_ratios if v > 1.5) / len(volume_ratios) if volume_ratios else 0,
            "pct_gt_13": sum(1 for v in volume_ratios if v > 1.3) / len(volume_ratios) if volume_ratios else 0,
        },
        "initiation_ratio_distribution": {
            "count": len(initiation_ratios),
            "min": min(initiation_ratios) if initiation_ratios else 0,
            "max": max(initiation_ratios) if initiation_ratios else 0,
            "mean": sum(initiation_ratios) / len(initiation_ratios) if initiation_ratios else 0,
            "pct_gt_07": sum(1 for v in initiation_ratios if v > 0.7) / len(initiation_ratios) if initiation_ratios else 0,
            "pct_gt_06": sum(1 for v in initiation_ratios if v > 0.6) / len(initiation_ratios) if initiation_ratios else 0,
        },
    }
    
    for case_id, data in case_neediness.items():
        penalties = data["penalties"]
        audit["case_detail"][case_id] = {
            "display_name": data["display_name"],
            "outcome": data["outcome"],
            "count": len(penalties),
            "triggered": sum(1 for p in penalties if p < 1.0),
            "trigger_rate": sum(1 for p in penalties if p < 1.0) / len(penalties) if penalties else 0,
            "min_penalty": min(penalties) if penalties else 1.0,
            "vol_ratio_mean": sum(data["volume_ratios"]) / len(data["volume_ratios"]) if data["volume_ratios"] else 0,
            "init_ratio_mean": sum(data["initiation_ratios"]) / len(data["initiation_ratios"]) if data["initiation_ratios"] else 0,
        }
    
    return audit


def analyze_cross_case_patterns(phase_a_data, phase_b_data, case_configs):
    """维度5：跨案例模式归纳。
    
    汇总各案例的时序分析结果，找共同模式。
    """
    patterns = []
    
    for case_id, case_a in phase_a_data.items():
        case_b = phase_b_data.get(case_id)
        case_config = case_configs.get(case_id) or case_configs.get(case_a["display_name"])
        
        timeline_analysis = analyze_case_timeline(case_a, case_config)
        if not timeline_analysis:
            continue
        
        lead_lag_result = None
        if case_b:
            lead_lag_results = analyze_signal_lead_lag({case_id: case_a}, {case_id: case_b})
            if lead_lag_results:
                lead_lag_result = lead_lag_results[0]
        
        patterns.append({
            "case_id": case_id,
            "display_name": case_a["display_name"],
            "outcome": case_a["outcome"],
            "composite_trend": timeline_analysis["metrics_eval"]["composite"]["trend_direction"],
            "fback_trend": timeline_analysis["metrics_eval"]["fback"]["trend_direction"],
            "neediness_triggered": timeline_analysis["metrics_eval"]["neediness"]["ever_triggered"],
            "early_warnings_count": len(timeline_analysis["early_warnings"]),
            "lead_days": lead_lag_result["lead_days"] if lead_lag_result else None,
        })
    
    return patterns


def generate_calibration_report(phase_a_data, phase_b_data, case_configs):
    """生成校准报告（案例内时序分析模式）。"""
    parts = ["# 回测校准报告\n"]
    parts.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    total_slices = sum(len(filter_high_confidence_slices(c["time_slices"])) for c in phase_a_data.values())
    parts.append(f"> 案例数: {len(phase_a_data)} | 切片数: {total_slices}\n")
    parts.append(f"> 分析方法：案例内时序分析（主）+ 描述性组间对比（辅），不做推断统计\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 一、案例内时序分析\n")
    
    for case_id, case_data in sorted(phase_a_data.items()):
        case_config = case_configs.get(case_id) or case_configs.get(case_data["display_name"])
        timeline_analysis = analyze_case_timeline(case_data, case_config)
        
        if not timeline_analysis:
            continue
        
        parts.append(f"\n### {case_data['display_name']} ({case_data['outcome']})\n")
        parts.append(f"- 结果日期: {case_data['outcome_date']}\n")
        parts.append(f"- 切片数: {timeline_analysis['slices_count']}\n")
        
        parts.append("\n**时间曲线**\n")
        parts.append("| 日期 | composite | fback | neediness | signal_level |\n")
        parts.append("|------|-----------|-------|-----------|--------------|\n")
        
        for t in timeline_analysis["timeline"]:
            stage_mark = f" [{t['stage']}]" if t['stage'] else ""
            parts.append(f"| {t['ref_date'][:10]}{stage_mark} | {t['composite']:.4f} | {t['fback']:.3f} | {t['neediness']:.4f} | {t['signal_level']} |\n")
        
        parts.append("\n**指标预警评估**\n")
        ce = timeline_analysis["metrics_eval"]["composite"]
        fe = timeline_analysis["metrics_eval"]["fback"]
        ne = timeline_analysis["metrics_eval"]["neediness"]
        
        if ce["has_trend"]:
            parts.append(f"- composite: {'✅' if ce['trend_direction'] == '下降' and case_data['outcome'] == 'failure' else '❌'} 有{ce['trend_direction']}趋势\n")
        else:
            parts.append("- composite: ❌ 全程平坦，无趋势\n")
        
        if fe["has_trend"]:
            parts.append(f"- fback: {'✅' if fe['trend_direction'] == '下降' and case_data['outcome'] == 'failure' else '❌'} 有{fe['trend_direction']}趋势\n")
        else:
            parts.append("- fback: ❌ 全程平坦，无趋势\n")
        
        if ne["ever_triggered"]:
            parts.append(f"- neediness_penalty: ✅ 曾触发（{len(ne['trigger_points'])}次）\n")
        else:
            parts.append("- neediness_penalty: ❌ 从未触发（全程1.0）\n")
        
        if timeline_analysis["early_warnings"]:
            parts.append("\n**早期预警信号**\n")
            for ew in timeline_analysis["early_warnings"]:
                triggers = []
                if ew["trigger"]:
                    triggers.append(ew["trigger"])
                if ew["fback_trigger"]:
                    triggers.append(ew["fback_trigger"])
                parts.append(f"- {ew['date'][:10]}（距结果{ew['days_to_outcome']}天）: {', '.join(triggers)}\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 二、composite公式诊断\n")
    
    composite_diag = analyze_composite_diagnosis(phase_a_data)
    
    if composite_diag["summary"]:
        s = composite_diag["summary"]
        parts.append("### 2.1 全量切片 composite 分布\n")
        parts.append(f"- min: {s['min']:.4f} | p25: {s['p25']:.4f} | p50: {s['p50']:.4f} | p75: {s['p75']:.4f} | max: {s['max']:.4f}\n")
    
    parts.append("\n### 2.2 按结果分组分布\n")
    parts.append("| 分组 | 切片数 | min | max | mean |\n")
    parts.append("|------|--------|-----|-----|------|\n")
    for group_name, dist in composite_diag["composite_distribution"].items():
        parts.append(f"| {group_name} | {dist['count']} | {dist['min']:.4f} | {dist['max']:.4f} | {dist['mean']:.4f} |\n")
    
    parts.append("\n### 2.3 neediness_penalty触发情况\n")
    parts.append("| 分组 | 切片数 | 触发次数 | 触发率 |\n")
    parts.append("|------|--------|---------|--------|\n")
    for group_name, audit in composite_diag["neediness_audit"].items():
        parts.append(f"| {group_name} | {audit['count']} | {audit['triggered']} | {audit['trigger_rate']:.1%} |\n")
    
    parts.append("\n### 2.4 signal_level分布\n")
    parts.append("| 分组 | 切片数 | 最常见信号 | 分布 |\n")
    parts.append("|------|--------|-----------|------|\n")
    for group_name, analysis in composite_diag["signal_level_analysis"].items():
        dist_str = ", ".join(f"{k}:{v}" for k, v in analysis["distribution"].items())
        parts.append(f"| {group_name} | {analysis['count']} | {analysis['most_common']} | {dist_str} |\n")
    
    parts.append("\n### 2.5 诊断问题清单\n")
    for issue in composite_diag["issues"]:
        parts.append(f"- ❌ {issue}\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 三、neediness_penalty专项审计\n")
    
    neediness_audit = analyze_neediness_audit(phase_a_data)
    
    parts.append("### 3.1 总体情况\n")
    parts.append(f"- 总切片数: {neediness_audit['total_slices']}\n")
    parts.append(f"- penalty最小值: {neediness_audit['min_penalty']:.4f}\n")
    parts.append(f"- penalty最大值: {neediness_audit['max_penalty']:.4f}\n")
    parts.append(f"- 触发次数: {neediness_audit['triggered_count']} (触发率 {neediness_audit['trigger_rate']:.1%})\n")
    
    parts.append("\n### 3.2 逐案例触发情况\n")
    parts.append("| 案例 | 结果 | 切片数 | 触发次数 | 触发率 | 平均vol_ratio | 平均init_ratio |\n")
    parts.append("|------|------|--------|---------|--------|---------------|----------------|\n")
    for case_id, detail in neediness_audit["case_detail"].items():
        parts.append(f"| {detail['display_name']} | {detail['outcome']} | {detail['count']} | {detail['triggered']} | {detail['trigger_rate']:.1%} | {detail['vol_ratio_mean']:.2f} | {detail['init_ratio_mean']:.2f} |\n")
    
    parts.append("\n### 3.3 触发条件实际分布\n")
    vol = neediness_audit["volume_ratio_distribution"]
    parts.append(f"- volume_ratio（我消息数/她消息数）范围: [{vol['min']:.2f}, {vol['max']:.2f}]，均值: {vol['mean']:.2f}\n")
    parts.append(f"- volume_ratio > 2.0 的比例: {vol['pct_gt_2']:.1%}\n")
    parts.append(f"- volume_ratio > 1.5 的比例: {vol['pct_gt_15']:.1%}\n")
    parts.append(f"- volume_ratio > 1.3 的比例: {vol['pct_gt_13']:.1%}\n")
    
    init = neediness_audit["initiation_ratio_distribution"]
    parts.append(f"- initiation_ratio（我发起/总发起）范围: [{init['min']:.2f}, {init['max']:.2f}]，均值: {init['mean']:.2f}\n")
    parts.append(f"- initiation_ratio > 0.7 的比例: {init['pct_gt_07']:.1%}\n")
    
    parts.append("\n### 3.4 审计结论\n")
    if vol["pct_gt_2"] == 0:
        parts.append("- 当前触发条件 volume_ratio > 2.0 过于严格，实际数据中没有达到这个阈值的案例\n")
        if vol["pct_gt_15"] > 0.1:
            parts.append(f"- 建议将阈值降至 1.5，预计触发率可达 {vol['pct_gt_15']:.1%}\n")
        elif vol["pct_gt_13"] > 0.1:
            parts.append(f"- 建议将阈值降至 1.3，预计触发率可达 {vol['pct_gt_13']:.1%}\n")
    
    if init["pct_gt_07"] == 0:
        parts.append("- initiation_ratio > 0.7 的条件也过于严格，实际数据中没有达到\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 四、信号领先/滞后分析\n")
    parts.append("### 4.1 各案例预警能力\n")
    parts.append("| 案例 | 结果 | 切片数 | 首次正确信号 | 领先天数 | 正确度 |\n")
    parts.append("|------|------|--------|-------------|---------|--------|\n")
    
    lead_lag_results = analyze_signal_lead_lag(phase_a_data, phase_b_data)
    for r in lead_lag_results:
        parts.append(f"| {r['display_name']} | {r['outcome']} | {r['slices_count']} | {r['first_correct_date'] or '-'} | {r['lead_days'] or '-'} | {r['correct_signal']} |\n")
    
    lead_days_list = [r["lead_days"] for r in lead_lag_results if r["lead_days"]]
    if lead_days_list:
        avg_lead = sum(lead_days_list) / len(lead_days_list)
        parts.append(f"\n### 4.2 汇总\n")
        parts.append(f"- 平均领先天数: {avg_lead:.1f} 天\n")
        parts.append(f"- 能提前7天以上预警的案例: {sum(1 for r in lead_lag_results if r['lead_days'] and r['lead_days'] > 7)}/{len(lead_lag_results)}\n")
    
    differ_count = sum(1 for r in lead_lag_results if r.get("rounds_differ"))
    if differ_count == 0:
        parts.append("\n> ⚠️ 警告：所有案例的manual_truth为空，default和truth round结果相同。信号分析结果可能不具有实际意义。\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 五、跨案例模式归纳\n")
    parts.append("| 案例 | 结果 | composite趋势 | fback趋势 | neediness触发 | 早期预警数 | 领先天数 |\n")
    parts.append("|------|------|-------------|-----------|--------------|-----------|---------|\n")
    
    patterns = analyze_cross_case_patterns(phase_a_data, phase_b_data, case_configs)
    for p in patterns:
        parts.append(f"| {p['display_name']} | {p['outcome']} | {p['composite_trend'] or '-'} | {p['fback_trend'] or '-'} | {'✅' if p['neediness_triggered'] else '❌'} | {p['early_warnings_count']} | {p['lead_days'] or '-'} |\n")
    
    parts.append("\n**跨案例归纳**\n")
    failure_cases = [p for p in patterns if p["outcome"] in ["failure", "success_to_failure"]]
    success_cases = [p for p in patterns if p["outcome"] == "success"]
    
    if failure_cases:
        fback_warn = sum(1 for p in failure_cases if p["fback_trend"] == "下降")
        comp_warn = sum(1 for p in failure_cases if p["composite_trend"] == "下降")
        parts.append(f"- 失败案例（{len(failure_cases)}个）中：\n")
        parts.append(f"  - fback出现下降趋势：{fback_warn}/{len(failure_cases)}\n")
        parts.append(f"  - composite出现下降趋势：{comp_warn}/{len(failure_cases)}\n")
    
    if success_cases:
        parts.append(f"- 成功案例（{len(success_cases)}个）中：\n")
        parts.append(f"  - fback出现下降趋势：{sum(1 for p in success_cases if p['fback_trend'] == '下降')}/{len(success_cases)}\n")
    
    parts.append("\n---\n")
    
    parts.append("\n## 六、校准建议\n")
    
    parts.append("### 6.1 高置信度建议（描述性证据充分）\n")
    parts.append("| 参数 | 当前值 | 建议值 | 依据 |\n")
    parts.append("|------|--------|--------|------|\n")
    
    if neediness_audit["trigger_rate"] < 0.1:
        vol = neediness_audit["volume_ratio_distribution"]
        if vol["pct_gt_13"] > 0.05:
            parts.append(f"| neediness_penalty.volume_ratio_threshold | >2.0 | >1.3 | 当前触发率{neediness_audit['trigger_rate']:.1%}，降至1.3预计触发率{vol['pct_gt_13']:.1%} |\n")
        elif vol["pct_gt_15"] > 0:
            parts.append(f"| neediness_penalty.volume_ratio_threshold | >2.0 | >1.5 | 当前触发率{neediness_audit['trigger_rate']:.1%}，降至1.5预计触发率{vol['pct_gt_15']:.1%} |\n")
    
    parts.append("| composite.weights | 等权重/经验权重 | 按区分力重分配 | 当前composite成功/失败组分布完全重叠，需提高有区分力指标的权重 |\n")
    
    parts.append("\n### 6.2 需要重构的参数\n")
    parts.append("| 参数 | 问题 | 建议行动 |\n")
    parts.append("|------|------|---------|\n")
    parts.append("| composite | 成功/失败组分布完全重叠 | 需要重新设计权重分配，优先提高有区分力指标的权重 |\n")
    parts.append("| neediness_penalty | 失败案例中从未触发 | 需要降低触发阈值，使其能识别真实的需求感暴露 |\n")
    parts.append("| signal_level阈值 | 中窗口(>=0.50)和强窗口(>=0.70)无任何切片达到 | 需要根据实际分布重新设定阈值 |\n")
    
    parts.append("\n### 6.3 低置信度建议（需要更多案例）\n")
    parts.append("- 当前案例数仅8个，部分分组样本量不足，建议扩展到20+案例\n")
    parts.append("- 信号领先分析需要补充案例的manual_truth字段才能验证公式的真实预警能力\n")
    
    parts.append("\n---\n")
    
    parts.append("\n> 注意：本报告所有统计仅为描述性，切片非独立样本，不做推断统计。\n")
    
    return "\n".join(parts)


def main():
    data = load_collected_data()
    case_configs = load_cases_config()
    
    if not data:
        print("没有找到采集数据，请先运行 backtest_collect.py")
        return
    
    phase_a_data = {}
    phase_b_data = {}
    
    for case_id, phases in data.items():
        if "A" in phases:
            phase_a_data[case_id] = phases["A"]
        if "B" in phases:
            phase_b_data[case_id] = phases["B"]
    
    if not phase_a_data:
        print("没有 Phase A 数据")
        return
    
    report = generate_calibration_report(phase_a_data, phase_b_data, case_configs)
    
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"校准报告已生成: {REPORT_FILE}")


if __name__ == "__main__":
    main()