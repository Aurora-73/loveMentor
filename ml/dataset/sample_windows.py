"""Sample conversation windows for semantic analysis annotation.

Phase 0: Generate window samples for baseline classification.
Output: data/ml_dataset/samples_phase0.jsonl

Configuration:
- window_size = 20 turns
- step_size = 10 turns
- min_messages = 30 per conversation
- min_turns = 10 per window
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataset.data_loader import (
    get_my_ids,
    window_to_dict,
    list_private_conversations,
    load_messages,
    build_windows,
    ConversationWindow,
)
from dataset.filter_conversations import is_business_conversation


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "raw" / "core.db"
OUTPUT_PATH = PROJECT_ROOT / "data" / "ml_dataset" / "samples_phase0.jsonl"

TARGET_COUNT = 5000
WINDOW_SIZE = 20
STEP_SIZE = 10
MIN_MESSAGES = 30
MIN_TURNS = 10

MAX_WINDOWS_PER_CONV = 100


def sample_stratified(db_path, target_count=TARGET_COUNT, max_windows_per_conv=MAX_WINDOWS_PER_CONV):
    conn = sqlite3.connect(str(db_path))
    my_ids = get_my_ids(conn)

    convs = list_private_conversations(conn, min_messages=MIN_MESSAGES)
    print(f"Found {len(convs)} conversations with >= {MIN_MESSAGES} messages")

    filtered_convs = []
    for wxid, name, msg_count in convs:
        messages = load_messages(conn, wxid)
        if not is_business_conversation(messages):
            filtered_convs.append((wxid, name, msg_count))
        else:
            print(f"  Filtered out business chat: {name} ({wxid})")

    print(f"After business filter: {len(filtered_convs)} conversations")

    all_windows = []
    per_conv_count = {}
    sample_counter = 0

    for wxid, name, msg_count in filtered_convs:
        messages = load_messages(conn, wxid)
        windows = build_windows(messages, WINDOW_SIZE, STEP_SIZE, MIN_TURNS)
        if max_windows_per_conv:
            windows = windows[:max_windows_per_conv]

        for win_turns in windows:
            sample_counter += 1
            win = ConversationWindow(
                sample_id=f"s_{sample_counter:06d}",
                contact_wxid=wxid,
                contact_remark=name,
                start_ts=win_turns[0].timestamp,
                end_ts=win_turns[-1].timestamp,
                turn_count=len(win_turns),
                messages=win_turns,
            )
            per_conv_count[wxid] = per_conv_count.get(wxid, 0) + 1
            all_windows.append(window_to_dict(win, my_ids))

    conn.close()

    print(f"Total windows collected: {len(all_windows)}")
    print(f"Unique conversations: {len(per_conv_count)}")

    random.seed(42)
    random.shuffle(all_windows)

    if len(all_windows) <= target_count:
        print(f"  (fewer than target {target_count}, taking all)")
        return all_windows

    return all_windows[:target_count]


def main():
    print("=" * 60)
    print("Phase 0: Sampling conversation windows")
    print(f"  window={WINDOW_SIZE}, stride={STEP_SIZE}, min_turns={MIN_TURNS}")
    print("=" * 60)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    samples = sample_stratified(DB_PATH)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(samples)} samples to:")
    print(f"  {OUTPUT_PATH}")

    if samples:
        contacts = set(s["contact_wxid"] for s in samples)
        print(f"\nDataset stats:")
        print(f"  Samples: {len(samples)}")
        print(f"  Unique contacts: {len(contacts)}")
        avg_turns = sum(s["turn_count"] for s in samples) / len(samples)
        print(f"  Avg turns per window: {avg_turns:.1f}")


if __name__ == "__main__":
    main()
