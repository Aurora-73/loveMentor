import yaml
import os
from pathlib import Path


def load_cases():
    """Load cases from YAML files.

    Priority: data/backtest/cases.yaml (real data, gitignored)
              data/backtest/cases_sample.yaml (sample data, tracked)
    """
    for path_str in [
        "data/backtest/cases.yaml",
        "data/backtest/cases_sample.yaml",
    ]:
        path = Path(path_str)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("cases", [])
    return []


def get_retro_cases():
    """Return cases formatted for retrospective.py.
    
    Returns: list of (wxid, name, outcome, key_date, note)
    """
    cases = load_cases()
    result = []
    for c in cases:
        key_date = c.get("retro", {}).get("key_date")
        if key_date is not None:
            from datetime import datetime
            key_date = datetime.strptime(key_date, "%Y-%m-%d")
        note = c.get("retro", {}).get("note", "")
        result.append((c["wxid"], c["name"], c["outcome"], key_date, note))
    return result


def get_ts_cases():
    """Return cases formatted for timeseries.py.
    
    Returns: list of (wxid, name, outcome, start_date, end_date, note)
    """
    cases = load_cases()
    result = []
    for c in cases:
        ts = c.get("ts", {})
        start_date = ts.get("start_date")
        end_date = ts.get("end_date")
        if start_date is None or end_date is None:
            continue
        from datetime import datetime
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        note = ts.get("note", "")
        result.append((c["wxid"], c["name"], c["outcome"], start_dt, end_dt, note))
    return result


def get_annotated_cases():
    """Return cases formatted for analyze_annotated.py.
    
    Returns: list of (wxid, name, outcome, note)
    """
    cases = load_cases()
    result = []
    for c in cases:
        note = c.get("annotated", {}).get("note", "")
        result.append((c["wxid"], c["name"], c["outcome"], note))
    return result


def get_validate_cases():
    """Return cases formatted for validate.py.
    
    Returns: list of (display_name, wxid)
    """
    cases = load_cases()
    result = []
    for c in cases:
        if "validate" in c:
            result.append((c["name"], c["wxid"]))
    if not result:
        result = [(c["name"], c["wxid"]) for c in cases[:3]]
    return result


def get_test_slope_cases():
    cases = load_cases()
    result = [(c["name"], c["wxid"]) for c in cases[:4]]
    return result


def get_test_slope_window_cases():
    cases = load_cases()
    outcome_map = {
        "success": "success",
        "failure": "failure",
        "active_giveup": "giveup",
        "developing": "developing",
        "success_to_failure": "s2f",
    }
    result = []
    for c in cases[:6]:
        outcome = outcome_map.get(c["outcome"], c["outcome"])
        result.append((c["name"], c["wxid"], outcome))
    return result
