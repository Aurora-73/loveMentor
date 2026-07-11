"""Semantic analysis dataset: data loading and window building.

Core infrastructure for loading messages from SQLite and building
sliding windows of consecutive turns.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pandas as pd


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Message:
    timestamp: int
    sender_id: str
    content: str
    msg_type: int = 1  # 1 = text

    @property
    def is_text(self) -> bool:
        return self.msg_type == 1 and bool(self.content)


@dataclass
class ConversationWindow:
    """A sliding window of conversation turns."""
    sample_id: str
    contact_wxid: str
    contact_remark: str
    start_ts: int
    end_ts: int
    turn_count: int  # number of turns (merged consecutive same-sender messages)
    messages: list[Message] = field(default_factory=list)

    def her_messages(self, my_ids: set[str]) -> list[Message]:
        return [m for m in self.messages if m.sender_id not in my_ids]

    def my_messages(self, my_ids: set[str]) -> list[Message]:
        return [m for m in self.messages if m.sender_id in my_ids]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_my_ids(conn: sqlite3.Connection) -> set[str]:
    """Get local account wxid(s).

    Strategy: pick the sender_id with the most outgoing text messages.
    In personal chat datasets this is extremely reliable — you always
    send more messages than any single contact.
    """
    rows = conn.execute("""
        SELECT sender_id, COUNT(*) as cnt
        FROM messages
        WHERE type = 1 AND content IS NOT NULL AND length(content) > 0
        GROUP BY sender_id
        ORDER BY cnt DESC
        LIMIT 3
    """).fetchall()
    if not rows:
        return set()
    return {rows[0][0]}


def list_private_conversations(
    conn: sqlite3.Connection,
    min_messages: int = 50,
) -> list[tuple[str, str, int]]:
    """List private conversations with at least min_messages text messages.

    Returns list of (contact_wxid, display_name, message_count) sorted by message count desc.
    """
    rows = conn.execute("""
        SELECT
            c.id,
            COALESCE(ct.remark, ct.display_name, ct.nickname, c.display_name, c.id) as name,
            COUNT(m.id) as msg_count
        FROM conversations c
        LEFT JOIN contacts ct ON ct.id = c.id
        JOIN messages m ON m.conversation_id = c.id
        WHERE c.type = 'private'
          AND m.type = 1
          AND m.content IS NOT NULL
          AND length(m.content) > 0
        GROUP BY c.id
        HAVING msg_count >= ?
        ORDER BY msg_count DESC
    """, (min_messages,)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def load_messages(
    conn: sqlite3.Connection,
    contact_wxid: str,
) -> list[Message]:
    """Load all text messages for a conversation, sorted by timestamp."""
    rows = conn.execute("""
        SELECT timestamp, sender_id, content, type
        FROM messages
        WHERE conversation_id = ?
          AND type = 1
          AND content IS NOT NULL
          AND length(content) > 0
        ORDER BY timestamp ASC
    """, (contact_wxid,)).fetchall()
    return [
        Message(timestamp=r[0], sender_id=r[1], content=r[2], msg_type=r[3])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Window building
# ---------------------------------------------------------------------------

def _merge_consecutive_same_sender(messages: list[Message]) -> list[Message]:
    """Merge consecutive messages from the same sender into one turn.

    Concatenates content with newlines, keeps the first message's timestamp.
    """
    if not messages:
        return []
    turns: list[Message] = []
    current_sender = messages[0].sender_id
    current_content = messages[0].content
    current_ts = messages[0].timestamp

    for msg in messages[1:]:
        if msg.sender_id == current_sender:
            current_content += "\n" + msg.content
        else:
            turns.append(Message(
                timestamp=current_ts,
                sender_id=current_sender,
                content=current_content,
            ))
            current_sender = msg.sender_id
            current_content = msg.content
            current_ts = msg.timestamp

    turns.append(Message(
        timestamp=current_ts,
        sender_id=current_sender,
        content=current_content,
    ))
    return turns


def build_windows(
    messages: list[Message],
    window_size: int = 20,
    step_size: int = 10,
    min_turns: int = 10,
) -> list[list[Message]]:
    """Build sliding windows from conversation turns.

    Args:
        messages: raw message list
        window_size: number of turns per window
        step_size: step size between windows (in turns)
        min_turns: minimum turns required for a valid window

    Returns:
        List of windows, each window is a list of Message (turns).
    """
    turns = _merge_consecutive_same_sender(messages)
    if len(turns) < min_turns:
        return []

    windows: list[list[Message]] = []
    for start in range(0, len(turns) - min_turns + 1, step_size):
        end = min(start + window_size, len(turns))
        if end - start >= min_turns:
            windows.append(turns[start:end])
    return windows


# ---------------------------------------------------------------------------
# High-level sampling API
# ---------------------------------------------------------------------------

def iter_all_windows(
    db_path: str | Path,
    window_size: int = 20,
    step_size: int = 10,
    min_messages: int = 50,
    min_turns: int = 10,
    max_conversations: int | None = None,
    max_windows_per_conv: int | None = None,
) -> Iterator[ConversationWindow]:
    """Iterate over all windows from all qualifying conversations.

    Yields ConversationWindow objects with unique sample_ids.
    """
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        my_ids = get_my_ids(conn)
        convs = list_private_conversations(conn, min_messages=min_messages)
        if max_conversations:
            convs = convs[:max_conversations]

        sample_counter = 0
        for wxid, name, _msg_count in convs:
            messages = load_messages(conn, wxid)
            windows = build_windows(messages, window_size, step_size, min_turns)
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
                yield win
    finally:
        conn.close()


def window_to_dict(win: ConversationWindow, my_ids: set[str]) -> dict:
    """Convert a ConversationWindow to a JSON-serializable dict.

    Includes the full message content for annotation.
    """
    messages_out = []
    for i, m in enumerate(win.messages):
        role = "me" if m.sender_id in my_ids else "her"
        messages_out.append({
            "turn": i + 1,
            "role": role,
            "content": m.content,
            "timestamp": m.timestamp,
        })

    return {
        "sample_id": win.sample_id,
        "contact_wxid": win.contact_wxid,
        "contact_remark": win.contact_remark,
        "turn_count": win.turn_count,
        "start_ts": win.start_ts,
        "end_ts": win.end_ts,
        "messages": messages_out,
    }
