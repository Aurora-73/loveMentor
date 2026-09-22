"""评估 docs/聊天记录 目录中数据的质量。

分析维度：
- 文件数量和分布
- 时间戳问题（合成时间戳）
- 水印污染模式
- 置信度分布
- 消息量统计
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CHAT_DIR = Path(__file__).resolve().parents[2] / "docs" / "聊天记录"


def find_json_files(base_dir: Path) -> list[Path]:
    """递归查找所有 merged.json 和 *.json 文件。"""
    files = []
    for path in base_dir.rglob("*.json"):
        if path.name.endswith(".json"):
            files.append(path)
    return sorted(files)


def analyze_file(path: Path) -> dict[str, Any]:
    """分析单个 JSON 文件的质量指标。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"path": str(path), "error": str(e), "valid": False}

    if not isinstance(data, list):
        return {"path": str(path), "error": "不是列表格式", "valid": False}

    messages = data
    total_messages = len(messages)
    
    senders = Counter(m["sender"] for m in messages if isinstance(m, dict) and "sender" in m)
    sender_list = [m["sender"] for m in messages if isinstance(m, dict) and "sender" in m]
    
    timestamps = [m["timestamp"] for m in messages 
                  if isinstance(m, dict) and "timestamp" in m and isinstance(m["timestamp"], int)]
    confidence_vals = [m["confidence"] for m in messages 
                       if isinstance(m, dict) and "confidence" in m and isinstance(m["confidence"], (int, float))]
    
    contents = [m["content"] for m in messages 
                if isinstance(m, dict) and "content" in m and isinstance(m["content"], str)]
    
    ts_gaps = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i-1]
        if gap > 0:
            ts_gaps.append(gap)
    
    watermark_patterns = [
        r"后续课程更新联系\d+",
        r"成都ph宝贝\(\d+\)",
        r"\d{4}年\d+月\d+日\d+:\d+",
        r"Q\d+",
        r"众筹",
        r"关系",
    ]
    watermark_counts = Counter()
    for content in contents:
        for pat in watermark_patterns:
            if re.search(pat, content):
                watermark_counts[pat] += 1
    
    avg_confidence = sum(confidence_vals) / len(confidence_vals) if confidence_vals else 0
    
    return {
        "path": str(path),
        "valid": True,
        "total_messages": total_messages,
        "senders": dict(senders),
        "sender_changes": sum(1 for i in range(1, len(sender_list)) if sender_list[i] != sender_list[i-1]),
        "has_timestamps": len(timestamps) > 0,
        "avg_ts_gap_seconds": sum(ts_gaps) / len(ts_gaps) if ts_gaps else 0,
        "max_ts_gap_seconds": max(ts_gaps) if ts_gaps else 0,
        "min_ts_gap_seconds": min(ts_gaps) if ts_gaps else 0,
        "has_confidence": len(confidence_vals) > 0,
        "avg_confidence": round(avg_confidence, 4),
        "confidence_dist": {
            "low": sum(1 for c in confidence_vals if c < 0.7),
            "medium": sum(1 for c in confidence_vals if 0.7 <= c < 0.9),
            "high": sum(1 for c in confidence_vals if c >= 0.9),
        },
        "watermark_counts": dict(watermark_counts),
        "watermark_messages": sum(1 for c in contents if any(re.search(p, c) for p in watermark_patterns)),
        "avg_content_length": sum(len(c) for c in contents) / len(contents) if contents else 0,
    }


def main():
    print("=" * 80)
    print("聊天记录数据质量评估")
    print("=" * 80)
    
    json_files = find_json_files(CHAT_DIR)
    print(f"\n找到 {len(json_files)} 个 JSON 文件")
    
    if not json_files:
        print("没有找到 JSON 文件，检查目录路径")
        return
    
    results = []
    for path in json_files:
        result = analyze_file(path)
        results.append(result)
    
    valid = [r for r in results if r["valid"]]
    invalid = [r for r in results if not r["valid"]]
    
    print(f"\n有效文件: {len(valid)}")
    print(f"无效文件: {len(invalid)}")
    
    if invalid:
        print("\n无效文件列表:")
        for r in invalid[:10]:
            print(f"  {r['path']}: {r['error']}")
    
    print("\n" + "=" * 80)
    print("质量指标汇总")
    print("=" * 80)
    
    if valid:
        total_messages = sum(r["total_messages"] for r in valid)
        avg_messages = total_messages / len(valid)
        print(f"\n总消息数: {total_messages:,}")
        print(f"平均每文件消息数: {avg_messages:.1f}")
        
        sender_dist = Counter()
        for r in valid:
            for sender, count in r["senders"].items():
                sender_dist[sender] += count
        print(f"\n发件人分布: {dict(sender_dist)}")
        
        avg_ts_gaps = [r["avg_ts_gap_seconds"] for r in valid if r["has_timestamps"]]
        if avg_ts_gaps:
            print(f"\n时间戳间隙统计:")
            print(f"  平均间隙: {sum(avg_ts_gaps)/len(avg_ts_gaps):.1f} 秒")
            print(f"  中位数间隙: {sorted(avg_ts_gaps)[len(avg_ts_gaps)//2]:.1f} 秒")
            print(f"  最小间隙: {min(avg_ts_gaps):.1f} 秒")
            print(f"  最大间隙: {max(avg_ts_gaps):.1f} 秒")
        
        avg_confidence = [r["avg_confidence"] for r in valid if r["has_confidence"]]
        if avg_confidence:
            print(f"\n置信度统计:")
            print(f"  平均置信度: {sum(avg_confidence)/len(avg_confidence):.4f}")
            print(f"  中位数置信度: {sorted(avg_confidence)[len(avg_confidence)//2]:.4f}")
            
            low_conf = sum(r["confidence_dist"]["low"] for r in valid)
            med_conf = sum(r["confidence_dist"]["medium"] for r in valid)
            high_conf = sum(r["confidence_dist"]["high"] for r in valid)
            total_conf = low_conf + med_conf + high_conf
            print(f"  低置信(<0.7): {low_conf} ({low_conf/total_conf*100:.1f}%)")
            print(f"  中置信(0.7-0.9): {med_conf} ({med_conf/total_conf*100:.1f}%)")
            print(f"  高置信(>=0.9): {high_conf} ({high_conf/total_conf*100:.1f}%)")
        
        watermark_messages = sum(r["watermark_messages"] for r in valid)
        total_contents = sum(len([m["content"] for m in json.load(open(r["path"], encoding="utf-8")) 
                                 if isinstance(m, dict) and "content" in m]) for r in valid)
        print(f"\n水印污染统计:")
        print(f"  含水印消息数: {watermark_messages}")
        print(f"  水印比例: {watermark_messages/total_contents*100:.1f}%")
        
        all_watermarks = Counter()
        for r in valid:
            for pat, count in r["watermark_counts"].items():
                all_watermarks[pat] += count
        print(f"\n水印模式排名:")
        for pat, count in all_watermarks.most_common(10):
            print(f"  {pat}: {count} 次")
        
        avg_content_length = [r["avg_content_length"] for r in valid]
        print(f"\n内容长度统计:")
        print(f"  平均长度: {sum(avg_content_length)/len(avg_content_length):.1f} 字符")
        print(f"  中位数长度: {sorted(avg_content_length)[len(avg_content_length)//2]:.1f} 字符")
    
    print("\n" + "=" * 80)
    print("数据质量结论")
    print("=" * 80)
    print("""
分析结论：
1. 时间戳问题：合成时间戳（所有消息间隔仅几秒），无法用于时间相关指标计算
   → 但语义模型只关注文本内容，时间戳不影响模型训练

2. 水印污染：存在"后续课程更新联系70075683"、"成都ph宝贝(13)"、日期时间戳等水印
   → 需要清洗后才能使用

3. 置信度：部分消息置信度低于 0.7，需要过滤

4. 可用性：清洗后可用于语义模型的 10 个行为标签训练（文本内容完整）

建议处理流程：
1. 去除水印和低置信度消息
2. 修复乱序文本（有些消息内容被拆分或合并）
3. 转为语义模型标准窗口格式（20轮滑动窗口）
4. 使用 LABELING_GUIDE.md 作为提示进行自动标注
    """)


if __name__ == "__main__":
    main()
