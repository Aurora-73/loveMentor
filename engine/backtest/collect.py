"""回测数据采集脚本。

对每个案例在多个时间切片上计算指标和公式，输出 JSON 数据。

核心特性：
  - 主切片：14天固定间隔
  - 事件对齐窗口：关键事件前后 ±7/14/30天
  - 切片级标签：stage/window_state/risk_state（从 stage_labels 派生）
  - 派生字段：next_30d_outcome, distance_to_outcome_days

用法：
    python -m engine.backtest.collect              # 采集所有案例（Phase A）
    python -m engine.backtest.collect --phase B    # 采集公式层（Phase B）
    python -m engine.backtest.collect --case case_001  # 只采集指定案例
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.config import load_config, OUTPUTS_DIR
from engine.importers.db_init import get_db
from engine.identity import resolve_contact
from engine.analyzers.metrics import compute_metrics_for_contact
from engine.backtest.load_cases import load_cases as _load_cases
from engine.formulas import (
    formula_params, formula_ivi, formula_spe, formula_ews,
    formula_action, formula_is, formula_gap_effect, formula_eev, formula_cs,
)


BACKTEST_DIR = OUTPUTS_DIR / "backtest"


def load_cases(case_filter=None):
    cases = _load_cases()
    if case_filter:
        cases = [c for c in cases if c["id"] == case_filter]
    return cases


def generate_time_slices(case, slice_days=14):
    """生成时间切片列表。
    
    主切片：14天固定间隔
    补充切片：事件对齐窗口（关键事件前后 ±7/14/30天）
    
    started ──slice_days──T1──slice_days──T2──...──Tn── outcome_date
    """
    started = datetime.fromisoformat(case["started"])
    outcome_date = datetime.fromisoformat(case["outcome_date"])
    
    slices = []
    
    current = started
    while current <= outcome_date:
        slices.append(current)
        current += timedelta(days=slice_days)
    
    if slices and slices[-1] != outcome_date:
        slices.append(outcome_date)
    
    event_dates = extract_event_dates(case)
    if event_dates:
        for event_date in event_dates:
            for offset in [-30, -14, -7, 0, 7, 14, 30]:
                aligned_date = event_date + timedelta(days=offset)
                if started <= aligned_date <= outcome_date:
                    if aligned_date not in slices:
                        slices.append(aligned_date)
    
    slices = sorted(set(slices))
    
    return slices


def extract_event_dates(case):
    """提取案例中的关键事件日期。
    
    来源：stage_labels 的边界日期 + key_events
    """
    dates = set()
    
    outcome_date = datetime.fromisoformat(case["outcome_date"])
    dates.add(outcome_date)
    
    stage_labels = case.get("stage_labels", [])
    for label in stage_labels:
        dates.add(datetime.fromisoformat(label["from"]))
        dates.add(datetime.fromisoformat(label["to"]))
    
    key_events = case.get("key_events", [])
    for event in key_events:
        dates.add(datetime.fromisoformat(event["date"]))
    
    return sorted(dates)


def get_slice_stage_label(slice_ref_date, case):
    """根据案例的 stage_labels 判断切片属于哪个阶段。"""
    ref_date = datetime.fromisoformat(slice_ref_date)
    outcome_date = datetime.fromisoformat(case["outcome_date"])
    
    stage_labels = case.get("stage_labels", [])
    for label in stage_labels:
        from_date = datetime.fromisoformat(label["from"])
        to_date = datetime.fromisoformat(label["to"])
        if from_date <= ref_date <= to_date:
            return {
                "stage": label["stage"],
                "window_state": label.get("window_state"),
                "risk_state": label.get("risk_state"),
            }
    
    return None


def compute_derived_labels(slice_ref_date, case):
    """计算派生的切片级标签。"""
    ref_date = datetime.fromisoformat(slice_ref_date)
    outcome_date = datetime.fromisoformat(case["outcome_date"])
    
    distance_to_outcome = (outcome_date - ref_date).days
    
    next_30d_outcome = None
    if distance_to_outcome <= 30:
        next_30d_outcome = case["outcome"]
    else:
        stage_info = get_slice_stage_label(slice_ref_date, case)
        if stage_info and stage_info["risk_state"] == "high":
            next_30d_outcome = "likely_failure"
        elif stage_info and stage_info["risk_state"] == "low":
            next_30d_outcome = "likely_success"
    
    distance_to_event = None
    event_dates = extract_event_dates(case)
    for event_date in event_dates:
        diff = (event_date - ref_date).days
        if diff >= 0:
            distance_to_event = diff
            break
    
    return {
        "distance_to_outcome_days": distance_to_outcome,
        "next_30d_outcome": next_30d_outcome,
        "distance_to_next_event_days": distance_to_event,
    }


def collect_phase_a(conn, config, case):
    """Phase A: 指标层采集（纯自动，不需要 manual 参数）。"""
    result = {"case_id": case["id"], "display_name": case["display_name"],
              "outcome": case["outcome"], "outcome_date": case["outcome_date"],
              "started": case["started"],
              "time_slices": []}
    
    person = resolve_contact(conn, case["display_name"]).person
    if not person or not person.accounts:
        print(f"  未找到联系人: {case['display_name']}")
        return None
    
    wxid = person.accounts[0].conversation_id or person.accounts[0].wxid
    time_slices = generate_time_slices(case)
    
    print(f"  时间切片: {len(time_slices)} 个")
    
    for ref_date in time_slices:
        to_ts = int(ref_date.timestamp())
        metrics = compute_metrics_for_contact(conn, config, wxid, person.display_name,
                                              ref_date=ref_date, to_ts=to_ts)
        
        msg_count = metrics.all_metrics().get("msg_count", None)
        msg_count_raw = msg_count.raw if msg_count else 0
        
        stage_info = get_slice_stage_label(ref_date.isoformat(), case)
        derived_labels = compute_derived_labels(ref_date.isoformat(), case)
        
        slice_data = {
            "ref_date": ref_date.isoformat(),
            "to_ts": to_ts,
            "composite": metrics.composite,
            "base_score": metrics.base_score,
            "signal_level": metrics.signal_level,
            "neediness_penalty": metrics.neediness_penalty,
            "volume_ratio": metrics.volume_ratio,
            "initiation_ratio": metrics.initiation_ratio,
            "interaction_pattern": metrics.interaction_pattern,
            "session_recency": metrics.session_recency,
            "momentum": metrics.momentum,
            "initiation_source": metrics.initiation_source,
            "media_engagement": metrics.media_engagement,
            "metrics": {k: v.to_dict() for k, v in metrics.all_metrics().items()},
            "msg_count_raw": msg_count_raw,
            "stage": stage_info["stage"] if stage_info else None,
            "window_state": stage_info["window_state"] if stage_info else None,
            "risk_state": stage_info["risk_state"] if stage_info else None,
            "distance_to_outcome_days": derived_labels["distance_to_outcome_days"],
            "next_30d_outcome": derived_labels["next_30d_outcome"],
            "distance_to_next_event_days": derived_labels["distance_to_next_event_days"],
        }
        result["time_slices"].append(slice_data)
    
    return result


def collect_phase_b(conn, config, case, sensitivity_mode=False):
    """Phase B: 公式层采集（需要 manual 参数）。
    
    sensitivity_mode: 敏感性分析模式，对关键参数做扫描
    """
    result = {"case_id": case["id"], "display_name": case["display_name"],
              "outcome": case["outcome"], "outcome_date": case["outcome_date"],
              "started": case["started"],
              "time_slices": []}
    
    person = resolve_contact(conn, case["display_name"]).person
    if not person or not person.accounts:
        print(f"  未找到联系人: {case['display_name']}")
        return None
    
    wxid = person.accounts[0].conversation_id or person.accounts[0].wxid
    time_slices = generate_time_slices(case)
    
    manual_truth = case.get("manual_truth", {})
    
    print(f"  时间切片: {len(time_slices)} 个")
    
    for ref_date in time_slices:
        to_ts = int(ref_date.timestamp())
        
        fp = formula_params(case["display_name"], conn=conn,
                            ref_date=ref_date, to_ts=to_ts)
        if isinstance(fp, str):
            print(f"    跳过 {ref_date.date()}: {fp}")
            continue
        
        auto = fp["auto"]
        manual = fp["manual"]
        
        stage_info = get_slice_stage_label(ref_date.isoformat(), case)
        derived_labels = compute_derived_labels(ref_date.isoformat(), case)
        
        slice_data = {
            "ref_date": ref_date.isoformat(),
            "to_ts": to_ts,
            "auto_params": auto,
            "raw_metrics": fp["raw_metrics"],
            "stage": stage_info["stage"] if stage_info else None,
            "window_state": stage_info["window_state"] if stage_info else None,
            "risk_state": stage_info["risk_state"] if stage_info else None,
            "distance_to_outcome_days": derived_labels["distance_to_outcome_days"],
            "next_30d_outcome": derived_labels["next_30d_outcome"],
            "distance_to_next_event_days": derived_labels["distance_to_next_event_days"],
            "rounds": [],
            "sensitivity_scan": [],
        }
        
        rounds_config = [
            ("default", {k: v["default"] for k, v in manual.items()}),
            ("truth", {k: manual_truth.get(k.lower(), v["default"])
                      for k, v in manual.items()}),
        ]
        
        for round_name, manual_values in rounds_config:
            manual_values["__round_name"] = round_name
            round_data = _compute_formula_round(auto, manual, manual_values, fp["raw_metrics"])
            slice_data["rounds"].append(round_data)
        
        if sensitivity_mode:
            sensitivity_scan = _run_sensitivity_scan(auto, manual, fp["raw_metrics"])
            slice_data["sensitivity_scan"] = sensitivity_scan
        
        result["time_slices"].append(slice_data)
    
    return result


def _compute_formula_round(auto, manual, manual_values, raw_metrics):
    """计算单个 round 的公式结果。"""
    pface = manual_values.get("Pface", 0.5)
    ddepth = manual_values.get("Ddepth", 0.5)
    target_ddepth = manual_values.get("Target_Ddepth", 0.5)
    backstage = manual_values.get("Backstage", 0.3)
    cp_index = manual_values.get("Cp_Index", 0.3)
    internal_d = manual_values.get("Internal_D", 0.5)
    external_r = manual_values.get("External_R", 0.4)
    p_succ = manual_values.get("P_succ", 0.5)
    p_fail = manual_values.get("P_fail", 0.3)
    
    ivi = formula_ivi(
        sp=auto["Sp"],
        fback=auto["Fback"],
        user_investment=auto["User_Investment"],
        pface=pface,
    )
    
    target_latency_raw = raw_metrics.get("avg_her_seconds", 300.0)
    target_latency = max(30.0, target_latency_raw) if target_latency_raw > 0 else 300.0
    spe = formula_spe(
        user_ddepth=ddepth,
        target_ddepth=target_ddepth,
        target_latency=target_latency,
        user_latency=60.0,
    )
    
    gap_effect = formula_gap_effect(act=auto["Ve"], exp=auto["Exp"])["gap_effect"]
    escalation_bonus = manual_values.get("Escalation_Bonus", 0.8)
    power_drop_risk = manual_values.get("Power_Drop_Risk", 0.5)
    eev = formula_eev(p_succ=p_succ, escalation_bonus=escalation_bonus,
                      p_fail=p_fail, power_drop_risk=power_drop_risk)["eev"]
    
    ews = formula_ews(
        gap_effect=gap_effect,
        cp_index=cp_index,
        eev=eev,
        scarcity_loss=auto["Scarcity_Loss"],
    )
    
    cs = formula_cs(internal_d=internal_d, external_r=external_r)
    
    action = formula_action(
        ivi=ivi["ivi"],
        spe=spe["spe"],
        ews=ews["ews"],
        cs=cs["cs"],
        ev=auto["EV"],
    )
    
    is_score = formula_is(backstage=backstage, pface=pface)
    
    return {
        "name": manual_values.get("__round_name", "default"),
        "manual_values": {k: v for k, v in manual_values.items() if k != "__round_name"},
        "ivi": ivi,
        "spe": spe,
        "ews": ews,
        "cs": cs,
        "is": is_score,
        "action": action,
    }


def _run_sensitivity_scan(auto, manual, raw_metrics):
    """对关键参数做敏感性扫描。
    
    Pface: 0.1 → 0.9（步长0.2）
    Ddepth: 0.1 → 0.9（步长0.2）
    Cp_Index: 0.0 → 1.0（步长0.2）
    """
    scans = []
    
    base_values = {k: v["default"] for k, v in manual.items()}
    
    param_scans = [
        ("Pface", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("Ddepth", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("Target_Ddepth", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("Cp_Index", [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        ("Backstage", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("Internal_D", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("External_R", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("P_succ", [0.1, 0.3, 0.5, 0.7, 0.9]),
        ("P_fail", [0.1, 0.3, 0.5, 0.7, 0.9]),
    ]
    
    for param_name, values in param_scans:
        results = []
        for val in values:
            scan_values = base_values.copy()
            scan_values[param_name] = val
            
            ivi = formula_ivi(
                sp=auto["Sp"],
                fback=auto["Fback"],
                user_investment=auto["User_Investment"],
                pface=scan_values.get("Pface", 0.5),
            )
            
            target_latency_raw = raw_metrics.get("avg_her_seconds", 300.0)
            target_latency = max(30.0, target_latency_raw) if target_latency_raw > 0 else 300.0
            spe = formula_spe(
                user_ddepth=scan_values.get("Ddepth", 0.5),
                target_ddepth=scan_values.get("Target_Ddepth", 0.5),
                target_latency=target_latency,
                user_latency=60.0,
            )
            
            gap_effect = formula_gap_effect(act=auto["Ve"], exp=auto["Exp"])["gap_effect"]
            eev = formula_eev(
                p_succ=scan_values.get("P_succ", 0.5),
                escalation_bonus=scan_values.get("Escalation_Bonus", 0.8),
                p_fail=scan_values.get("P_fail", 0.3),
                power_drop_risk=scan_values.get("Power_Drop_Risk", 0.5),
            )["eev"]
            
            ews = formula_ews(
                gap_effect=gap_effect,
                cp_index=scan_values.get("Cp_Index", 0.3),
                eev=eev,
                scarcity_loss=auto["Scarcity_Loss"],
            )
            
            cs = formula_cs(
                internal_d=scan_values.get("Internal_D", 0.5),
                external_r=scan_values.get("External_R", 0.4),
            )
            
            action = formula_action(
                ivi=ivi["ivi"],
                spe=spe["spe"],
                ews=ews["ews"],
                cs=cs["cs"],
                ev=auto["EV"],
            )
            
            results.append({
                "param_value": val,
                "ivi": round(ivi["ivi"], 4),
                "spe": round(spe["spe"], 4),
                "ews": round(ews["ews"], 4),
                "cs": round(cs["cs"], 4),
                "action": action["action"],
            })
        
        ivi_values = [r["ivi"] for r in results]
        spe_values = [r["spe"] for r in results]
        ews_values = [r["ews"] for r in results]
        
        scans.append({
            "param": param_name,
            "values": values,
            "results": results,
            "sensitivity": {
                "ivi_range": round(max(ivi_values) - min(ivi_values), 4) if ivi_values else 0,
                "spe_range": round(max(spe_values) - min(spe_values), 4) if spe_values else 0,
                "ews_range": round(max(ews_values) - min(ews_values), 4) if ews_values else 0,
            },
        })
    
    return scans


def main():
    parser = argparse.ArgumentParser(description="回测数据采集")
    parser.add_argument("--phase", choices=["A", "B"], default="A",
                        help="采集阶段: A=指标层, B=公式层")
    parser.add_argument("--case", help="只采集指定案例 ID")
    parser.add_argument("--slice-days", type=int, default=14,
                        help="时间切片间隔（天）")
    parser.add_argument("--sensitivity", action="store_true",
                        help="敏感性分析模式（仅 Phase B），对关键参数做扫描")
    args = parser.parse_args()
    
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    
    cases = load_cases(args.case)
    if not cases:
        print("没有找到案例")
        return
    
    config = load_config()
    conn = get_db(config.db_path)
    
    try:
        for case in cases:
            print(f"\n{'='*60}")
            print(f"采集案例: {case['id']} - {case['display_name']}")
            print(f"结果: {case['outcome']}")
            print(f"时间范围: {case['started']} ~ {case['outcome_date']}")
            if args.sensitivity:
                print(f"模式: 敏感性分析")
            print(f"{'='*60}")
            
            if args.phase == "A":
                data = collect_phase_a(conn, config, case)
                output_file = BACKTEST_DIR / f"{case['id']}_phase_a.json"
            else:
                data = collect_phase_b(conn, config, case, sensitivity_mode=args.sensitivity)
                output_file = BACKTEST_DIR / f"{case['id']}_phase_b.json"
                if args.sensitivity:
                    output_file = BACKTEST_DIR / f"{case['id']}_phase_b_sensitivity.json"
            
            if data:
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"  输出: {output_file}")
        
        print(f"\n采集完成! 输出目录: {BACKTEST_DIR}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
