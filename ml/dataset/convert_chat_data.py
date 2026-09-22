"""将 docs/聊天记录 中的 JSON 数据转换为语义模型标准数据集格式。

处理流程：
1. 清洗：去除水印、过滤低置信度消息、修复文本乱序
2. 构建滑动窗口（20轮，步长10）
3. 输出标准 JSONL 格式（与 samples_phase0.jsonl 一致）

输出格式（每条记录）：
{
    "sample_id": "s_000001",
    "contact_wxid": "chat_001",
    "contact_remark": "川传正妹倒追",
    "turn_count": 20,
    "start_ts": 1234567890,
    "end_ts": 1234567900,
    "messages": [
        {"turn": 1, "role": "her", "content": "...", "timestamp": 1234567890},
        ...
    ]
}
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHAT_DIR = PROJECT_ROOT / "docs" / "聊天记录"
OUTPUT_DIR = PROJECT_ROOT / "data" / "ml_dataset"
OUTPUT_FILE = OUTPUT_DIR / "samples_chat_records.jsonl"

WINDOW_SIZE = 20
STEP_SIZE = 10
MIN_TURNS = 10
CONFIDENCE_THRESHOLD = 0.7

# 水印模式（需要去除的内容）
WATERMARK_PATTERNS = [
    r"后续课程更新联系\d+",
    r"成都ph宝贝\(\d+\)",
    r"众筹",
    r"关系",
    r"Q\d+",
    r"\d{4}年\d+月\d+日\d+:\d+",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{2}:\d{2}\s*[AP]M",
    r"\d+%",
    r"@\d+%",
    r"LTE",
    r"Bell",
    r"SUPERLIKED",
    r"YOUMATCHEDWITH",
    r"oc 'ell",
    r"[·.]{3,}",
    r"YOUWNON",
    r"o\s*\d+:\d+\s*[AP]M",
    r"\d+March\d+",
    r"\d+April\d+",
    r"Your message",
    r"GIF",
    r"^\d+:\d+\s*[AP]M.*$",
    r"@\d+“",
]

# 低质量内容模式（直接过滤整条消息）
LOW_QUALITY_PATTERNS = [
    r"^\d+$",
    r"^\d+\s*$",
    r"^[·.]+$",
]


class CleanMessage:
    """清洗后的消息。"""
    def __init__(self, sender: str, content: str, timestamp: int, confidence: float = 1.0):
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.confidence = confidence
    
    def is_valid(self) -> bool:
        """检查消息是否有效。"""
        if not self.content or not isinstance(self.content, str):
            return False
        if len(self.content.strip()) == 0:
            return False
        if self.sender not in ("me", "her"):
            return False
        return True


def clean_message(raw: dict) -> CleanMessage | None:
    """清洗单条消息。"""
    if not isinstance(raw, dict):
        return None
    
    sender = raw.get("sender", "")
    content = raw.get("content", "")
    timestamp = raw.get("timestamp", 0)
    confidence = raw.get("confidence", 1.0)
    
    if not isinstance(content, str):
        content = str(content)
    
    content = content.strip()
    
    # 过滤低置信度消息
    if isinstance(confidence, (int, float)) and confidence < CONFIDENCE_THRESHOLD:
        return None
    
    # 过滤低质量内容
    for pat in LOW_QUALITY_PATTERNS:
        if re.fullmatch(pat, content):
            return None
    
    # 去除水印
    cleaned = content
    for pat in WATERMARK_PATTERNS:
        cleaned = re.sub(pat, "", cleaned)
    cleaned = cleaned.strip()
    
    # 去除前后多余空白和换行
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # 检查清洗后是否为空
    if len(cleaned) == 0:
        return None
    
    # 修复乱序文本（部分消息内容被错误拆分）
    # 例如："们可以开始聊天了我通过了你的朋友验证请求，现在我"
    # 需要还原为："我通过了你的朋友验证请求，现在我们可以开始聊天了"
    cleaned = fix_reordered_text(cleaned)
    
    return CleanMessage(sender=sender, content=cleaned, timestamp=timestamp, confidence=confidence)


def fix_reordered_text(text: str) -> str:
    """尝试修复乱序文本。
    
    常见模式：
    - "们可以开始聊天了我通过了你的朋友验证请求，现在我" → 开头的"们"应该在结尾
    """
    # 模式1：开头是"们"或"我"等，且结尾有"我"
    if text.startswith("们") and "我" in text:
        parts = text.split("我")
        if len(parts) > 1:
            reconstructed = "我" + "我".join(parts[1:]) + "们"
            if len(reconstructed) == len(text):
                return reconstructed
    
    return text


def load_and_clean_file(path: Path) -> list[CleanMessage]:
    """加载并清洗一个 JSON 文件。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    
    if not isinstance(data, list):
        return []
    
    messages = []
    for raw in data:
        cleaned = clean_message(raw)
        if cleaned and cleaned.is_valid():
            messages.append(cleaned)
    
    return messages


def merge_consecutive_same_sender(messages: list[CleanMessage]) -> list[CleanMessage]:
    """合并连续同发件人的消息为一轮。"""
    if not messages:
        return []
    
    turns: list[CleanMessage] = []
    current = messages[0]
    buffer = [current.content]
    
    for msg in messages[1:]:
        if msg.sender == current.sender:
            buffer.append(msg.content)
        else:
            turns.append(CleanMessage(
                sender=current.sender,
                content="\n".join(buffer),
                timestamp=current.timestamp,
                confidence=current.confidence,
            ))
            current = msg
            buffer = [msg.content]
    
    turns.append(CleanMessage(
        sender=current.sender,
        content="\n".join(buffer),
        timestamp=current.timestamp,
        confidence=current.confidence,
    ))
    
    return turns


def build_windows(turns: list[CleanMessage]) -> list[list[CleanMessage]]:
    """从轮次列表构建滑动窗口。"""
    if len(turns) < MIN_TURNS:
        return []
    
    windows: list[list[CleanMessage]] = []
    for start in range(0, len(turns) - MIN_TURNS + 1, STEP_SIZE):
        end = min(start + WINDOW_SIZE, len(turns))
        if end - start >= MIN_TURNS:
            windows.append(turns[start:end])
    
    return windows


def window_to_dict(window: list[CleanMessage], sample_id: str, chat_id: str, chat_name: str) -> dict:
    """将窗口转换为标准字典格式。"""
    messages_out = []
    for i, m in enumerate(window):
        messages_out.append({
            "turn": i + 1,
            "role": m.sender,
            "content": m.content,
            "timestamp": m.timestamp,
        })
    
    return {
        "sample_id": sample_id,
        "contact_wxid": chat_id,
        "contact_remark": chat_name,
        "turn_count": len(window),
        "start_ts": window[0].timestamp,
        "end_ts": window[-1].timestamp,
        "messages": messages_out,
    }


def iter_all_windows() -> Iterator[tuple[str, str, list[CleanMessage]]]:
    """遍历所有文件，生成窗口。
    
    Yields: (chat_id, chat_name, window)
    """
    json_files = []
    for path in CHAT_DIR.rglob("*.json"):
        if path.name.endswith(".json"):
            json_files.append(path)
    
    print(f"找到 {len(json_files)} 个 JSON 文件")
    
    chat_counter = 0
    for path in json_files:
        chat_counter += 1
        chat_id = f"chat_{chat_counter:04d}"
        chat_name = path.parent.name
        
        messages = load_and_clean_file(path)
        if not messages:
            continue
        
        turns = merge_consecutive_same_sender(messages)
        windows = build_windows(turns)
        
        for window in windows:
            yield chat_id, chat_name, window


def main():
    print("=" * 80)
    print("聊天记录 → 语义模型数据集转换")
    print("=" * 80)
    print(f"窗口大小: {WINDOW_SIZE} 轮")
    print(f"步长: {STEP_SIZE} 轮")
    print(f"最小轮数: {MIN_TURNS}")
    print(f"置信度阈值: {CONFIDENCE_THRESHOLD}")
    print("=" * 80)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    sample_counter = 0
    chat_stats = defaultdict(int)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for chat_id, chat_name, window in iter_all_windows():
            sample_counter += 1
            sample_id = f"s_{sample_counter:06d}"
            chat_stats[chat_id] += 1
            
            record = window_to_dict(window, sample_id, chat_id, chat_name)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"\n转换完成！")
    print(f"输出文件: {OUTPUT_FILE}")
    print(f"总样本数: {sample_counter}")
    print(f"总对话数: {len(chat_stats)}")
    
    if sample_counter > 0:
        avg_windows = sample_counter / len(chat_stats)
        print(f"平均每对话窗口数: {avg_windows:.1f}")
        
        # 打印前几个样本的统计
        print("\n样本示例（查看前3条）:")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 3:
                    break
                record = json.loads(line)
                print(f"\n样本 {record['sample_id']}:")
                print(f"  对话: {record['contact_remark']}")
                print(f"  轮数: {record['turn_count']}")
                print(f"  消息预览:")
                for msg in record["messages"][:5]:
                    print(f"    [{msg['role']}] {msg['content'][:50]}...")


if __name__ == "__main__":
    main()
