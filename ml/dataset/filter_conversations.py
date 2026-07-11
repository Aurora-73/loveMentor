"""Conversation type filter.

Filter out business/non-relational conversations before window sampling.

Usage:
    from dataset.filter_conversations import is_business_conversation
    if not is_business_conversation(messages):
        # process this conversation
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import List


FILTER_DIR = Path(__file__).parent.parent / "lexicons" / "filters"
BUSINESS_FILTER_PATH = FILTER_DIR / "business_chat.yaml"


def load_business_filter() -> dict:
    if not BUSINESS_FILTER_PATH.exists():
        raise FileNotFoundError(f"Business filter not found: {BUSINESS_FILTER_PATH}")
    with open(BUSINESS_FILTER_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_business_conversation(messages: list) -> bool:
    """Check if a conversation is likely business/non-relational.

    Returns True if conversation should be filtered out.
    """
    if not messages:
        return False

    filter_config = load_business_filter()
    patterns = filter_config.get("patterns", [])

    for pattern in patterns:
        ptype = pattern.get("type", "keyword")

        if ptype == "keyword":
            keywords = pattern.get("value", [])
            threshold = pattern.get("threshold", 2)
            hit_count = 0
            for msg in messages:
                text = getattr(msg, "content", "")
                for kw in keywords:
                    if kw in text:
                        hit_count += 1
                        break
                if hit_count >= threshold:
                    return True

        elif ptype == "sender_ratio":
            me_ratio_threshold = pattern.get("me_ratio_threshold", 0.8)
            her_reply_avg_len = pattern.get("her_reply_avg_len", 5)

            n_messages = len(messages)
            if n_messages == 0:
                continue

            my_count = 0
            her_count = 0
            her_total_len = 0

            for msg in messages:
                sender_id = getattr(msg, "sender_id", "")
                content = getattr(msg, "content", "")
                if sender_id is not None:
                    if sender_id in ["me", "self", "wxid_me"]:
                        my_count += 1
                    else:
                        her_count += 1
                        her_total_len += len(content)

            if her_count > 0:
                avg_len = her_total_len / her_count
                if my_count / n_messages > me_ratio_threshold and avg_len < her_reply_avg_len:
                    return True

    return False
