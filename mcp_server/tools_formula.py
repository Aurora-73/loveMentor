"""MCP 公式工具函数（Phase 3 P3）。

纯计算函数，零副作用。formula_params 读取数据库，其余为纯计算。
参数校验：所有输入参数 clamp 到 [0, 1] 范围，超出范围的值自动截断并标注。
"""

from engine.formulas import (
    formula_params as _formula_params,
    formula_ivi as _formula_ivi,
    formula_spe as _formula_spe,
    formula_ews as _formula_ews,
    formula_is as _formula_is,
    formula_gap_effect as _formula_gap_effect,
    formula_eev as _formula_eev,
    formula_cs as _formula_cs,
    formula_action as _formula_action,
)


def _clamp_01(value: float, name: str) -> tuple[float, list[str]]:
    """将参数 clamp 到 [0, 1] 范围，返回 (clamped_value, warnings)。"""
    warnings: list[str] = []
    if value < 0.0:
        warnings.append(f"{name}={value} < 0，已 clamp 到 0")
        return 0.0, warnings
    if value > 1.0:
        warnings.append(f"{name}={value} > 1，已 clamp 到 1")
        return 1.0, warnings
    return value, warnings


def _clamp_params(params: dict) -> tuple[dict, list[str]]:
    """批量 clamp 参数，返回 (clamped_params, all_warnings)。"""
    clamped = {}
    all_warnings: list[str] = []
    for k, v in params.items():
        cv, warns = _clamp_01(v, k)
        clamped[k] = cv
        all_warnings.extend(warns)
    return clamped, all_warnings


def formula_get_params(name: str) -> dict:
    """获取公式参数（从数据库自动计算）。

    什么时候用：需要获取某人的公式参数以进行战态分析时。
    返回什么：dict 含 auto（自动参数）和 manual（需 Agent 判断的参数）。
    边界是什么：name 必填；返回的 manual 参数需要 Agent 结合上下文判断。
    """
    try:
        result = _formula_params(name)
        if isinstance(result, str):
            return {"error": "PERSON_NOT_FOUND", "message": result, "suggestion": "请检查联系人姓名是否正确"}
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查联系人姓名是否正确"}


def formula_calc_ivi(sp: float, fback: float, user_investment: float, pface: float) -> dict:
    """计算 IVI（意图真实度）。

    什么时候用：需要判断对方的好感是否真实时。
    返回什么：dict 含 ivi 值和解读。>1.0 真实好感，<0.5 真实没戏。
    边界是什么：四个参数均为 0-1 浮点数，超出范围自动 clamp。sp=社交势能, fback=反馈率, user_investment=你的投入, pface=公开面具。
    """
    try:
        clamped, warns = _clamp_params({"sp": sp, "fback": fback, "user_investment": user_investment, "pface": pface})
        result = _formula_ivi(**clamped)
        if isinstance(result, dict):
            if warns:
                result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围（0-1）"}


def formula_calc_spe(user_ddepth: float, target_ddepth: float, target_latency: float, user_latency: float) -> dict:
    """计算 SPE（社交势能）。

    什么时候用：需要评估关系中的权力平衡时。
    返回什么：dict 含 spe 值和解读。0.8-1.5 健康，<0.6 红线阻断。
    边界是什么：四个参数为深度和延迟的归一化值，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({
            "user_ddepth": user_ddepth, "target_ddepth": target_ddepth,
            "target_latency": target_latency, "user_latency": user_latency,
        })
        result = _formula_spe(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_ews(gap_effect: float, cp_index: float, eev: float, scarcity_loss: float) -> dict:
    """计算 EWS（升温窗口期）。

    什么时候用：需要判断是否到了升温的最佳时机时。
    返回什么：dict 含 ews 值和解读。>0.8 出击信号，<0.3 窗口关闭。
    边界是什么：四个参数为情绪落差、CP指数、升温期望值、稀缺性损失，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({
            "gap_effect": gap_effect, "cp_index": cp_index,
            "eev": eev, "scarcity_loss": scarcity_loss,
        })
        result = _formula_ews(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_is(backstage: float, pface: float) -> dict:
    """计算 IS（真实亲密度）。

    什么时候用：需要评估对方愿意暴露真实自我的程度时。
    返回什么：dict 含 is 值和解读。>0.5 高亲密度。
    边界是什么：backstage=后台暴露度，pface=公开面具，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({"backstage": backstage, "pface": pface})
        result = _formula_is(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_gap_effect(act: float, exp: float) -> dict:
    """计算 Gap_Effect（情绪落差刺激）。

    什么时候用：需要评估推拉策略的情绪落差效果时。
    返回什么：dict 含 gap_effect 值和解读。
    边界是什么：act=实际行为强度，exp=预期强度，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({"act": act, "exp": exp})
        result = _formula_gap_effect(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_eev(p_succ: float, escalation_bonus: float, p_fail: float, power_drop_risk: float) -> dict:
    """计算 EEV（升温期望值）。

    什么时候用：需要在发起升温动作前评估收益与风险时。
    返回什么：dict 含 eev 值和解读。
    边界是什么：p_succ=成功率，escalation_bonus=升温红利，p_fail=失败率，power_drop_risk=势能降级风险，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({
            "p_succ": p_succ, "escalation_bonus": escalation_bonus,
            "p_fail": p_fail, "power_drop_risk": power_drop_risk,
        })
        result = _formula_eev(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_cs(internal_d: float, external_r: float) -> dict:
    """计算 CS（矛盾演化状态）。

    什么时候用：需要评估矛盾积累到临界点的程度时。
    返回什么：dict 含 cs 值和解读。
    边界是什么：internal_d=内在矛盾积累，external_r=外部矛盾释放，超出范围自动 clamp。
    """
    try:
        clamped, warns = _clamp_params({"internal_d": internal_d, "external_r": external_r})
        result = _formula_cs(**clamped)
        if isinstance(result, dict) and warns:
            result["param_warnings"] = warns
        return result
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}


def formula_calc_action(ivi: float, spe: float, ews: float, cs: float = 0.0, ev: float = 0.5) -> dict:
    """终极行动决策 — 基于 IVI/SPE/EWS 的策略分发。

    什么时候用：需要综合战态公式得出最终行动建议时。
    返回什么：dict 含 action（进攻/拉扯/重置/维持）、reason、instructions。
    边界是什么：ivi/spe/ews 为三大公式结果（范围可能超 [0,1]，不 clamp）；cs=矛盾状态；ev=期望值调整。
    """
    try:
        return _formula_action(ivi=ivi, spe=spe, ews=ews, cs=cs, ev=ev)
    except Exception as e:
        return {"error": "TOOL_ERROR", "message": str(e), "suggestion": "请检查参数范围"}
