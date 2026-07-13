# -*- coding: utf-8 -*-
"""统一输入格式化 — target_other_v1 协议。

所有训练和推理路径必须唯一调用此模块，避免格式化逻辑分散。
"""
from __future__ import annotations

SCHEMA_VERSION = "target_other_v1"

ROLE_TOKENS = {
    "target": "[TARGET]",
    "other": "[OTHER]",
}

VALID_ROLES = {"me", "her"}


def format_behavior_input(
    messages: list[dict],
    target_role: str,
) -> str:
    """将消息列表格式化为模型输入文本。

    Args:
        messages: 消息列表，每条有 role ("me"/"her") 和 content。
        target_role: "me" 或 "her" — 谁是 TARGET。

    Returns:
        带 [TARGET]/[OTHER] 前缀的文本，每条消息一行。

    Raises:
        ValueError: role 不支持或 target_role 无效。
    """
    if target_role not in VALID_ROLES:
        raise ValueError(
            f"format_behavior_input: invalid target_role='{target_role}', "
            f"expected one of {VALID_ROLES}"
        )

    lines = []
    for m in messages:
        role = m.get("role")
        if role is None:
            raise ValueError(
                f"format_behavior_input: message missing 'role' field, "
                f"content={m.get('content', '')[:50]!r} "
                f"(schema={SCHEMA_VERSION})"
            )
        if role not in VALID_ROLES:
            raise ValueError(
                f"format_behavior_input: unsupported role='{role}', "
                f"expected one of {VALID_ROLES}"
            )
        marker = ROLE_TOKENS["target"] if role == target_role else ROLE_TOKENS["other"]
        lines.append(f"{marker} {m['content']}")
    return "\n".join(lines)
