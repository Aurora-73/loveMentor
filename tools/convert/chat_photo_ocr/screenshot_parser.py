"""截图解析器。

解析聊天截图，识别消息气泡，区分发送方，提取时间戳。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from ocr_engine_paddle import OCRResult


@dataclass
class ParsedMessage:
    """解析后的消息。"""
    sender: str      # 'me' 或 'her'
    content: str
    timestamp: int   # Unix timestamp
    confidence: float


def get_image_size(image_path: str | Path) -> tuple[int, int]:
    """获取图片尺寸 (width, height)。"""
    with Image.open(image_path) as img:
        return img.size


def _extract_date_from_filename(filename: str) -> datetime | None:
    """从截图文件名提取日期时间。

    支持格式：
    - Screenshot_2026-06-05-19-53-56-57_xxx.jpg
    - 2026-06-05_19-53-56.jpg
    - 20260605_195356.jpg
    """
    # 格式 1: Screenshot_2026-06-05-19-53-56-57_xxx.jpg
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", filename)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            pass

    # 格式 2: 2026-06-05_19-53-56.jpg
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", filename)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            pass

    # 格式 3: 20260605_195356.jpg
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", filename)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            pass

    return None


def infer_base_datetime(
    image_path: str | Path,
    base_timestamp: int = 0,
) -> datetime:
    """推断截图的基准时间。

    优先级：
    1. 调用方显式传入的 base_timestamp
    2. 文件名中可解析的日期时间
    3. 文件修改时间（保证结果稳定，不依赖当前时间）
    """
    if base_timestamp > 0:
        return datetime.fromtimestamp(base_timestamp)

    filename_dt = _extract_date_from_filename(Path(image_path).name)
    if filename_dt is not None:
        return filename_dt

    return datetime.fromtimestamp(Path(image_path).stat().st_mtime)


def infer_base_timestamp(
    image_path: str | Path,
    base_timestamp: int = 0,
) -> int:
    """返回稳定的基准时间戳。"""
    return int(infer_base_datetime(image_path, base_timestamp=base_timestamp).timestamp())


def _normalize_period_hour(period: str | None, hour: int) -> int:
    """将中文时段修正为 24 小时制。"""
    if period in {"下午", "晚上"} and hour < 12:
        return hour + 12
    if period in {"凌晨"} and hour == 12:
        return 0
    if period in {"上午", "早上"} and hour == 12:
        return 0
    return hour


def _parse_time_text(time_text: str, base_date: datetime) -> int | None:
    """解析时间文本为 Unix 时间戳。

    支持格式：
    - "下午 3:42" / "上午 10:30"
    - "昨天 18:30"
    - "今天 00:01" / "明天 09:15" / "前天 21:05"
    - "06-05 19:53"
    - "19:53"
    """
    time_text = time_text.strip()

    # 格式 1: "下午 3:42" / "上午 10:30" / "晚上 8:16"
    m = re.match(r"(上午|下午|晚上|凌晨|早上)\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        period = m.group(1)
        hour = int(m.group(2))
        minute = int(m.group(3))
        hour = _normalize_period_hour(period, hour)
        dt = base_date.replace(hour=hour, minute=minute, second=0)
        return int(dt.timestamp())

    # 格式 2: "昨天 18:30" / "昨日 18:30"
    m = re.match(r"(昨天|昨日)\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        hour = int(m.group(2))
        minute = int(m.group(3))
        dt = (base_date - timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
        return int(dt.timestamp())

    # 格式 2.5: "今天 00:01" / "明天 09:15" / "前天 21:05"
    m = re.match(r"(今天|明天|前天)\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        day_word = m.group(1)
        hour = int(m.group(2))
        minute = int(m.group(3))
        day_offset = {
            "前天": -2,
            "今天": 0,
            "明天": 1,
        }[day_word]
        dt = (base_date + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0)
        return int(dt.timestamp())

    # 格式 3: "06-05 19:53"
    m = re.match(r"(\d{2})-(\d{2})\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        hour = int(m.group(3))
        minute = int(m.group(4))
        try:
            dt = base_date.replace(month=month, day=day, hour=hour, minute=minute, second=0)
            return int(dt.timestamp())
        except ValueError:
            pass

    # 格式 4: "19:53"
    m = re.match(r"(\d{1,2}):(\d{2})$", time_text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        dt = base_date.replace(hour=hour, minute=minute, second=0)
        return int(dt.timestamp())

    # 格式 5: "1月12日晚上20:16" 或 "1月12日下午3:42"
    m = re.match(r"(\d{1,2})月(\d{1,2})日(上午|下午|晚上|凌晨|早上)?\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        period = m.group(3)
        hour = _normalize_period_hour(period, int(m.group(4)))
        minute = int(m.group(5))
        try:
            dt = base_date.replace(month=month, day=day, hour=hour, minute=minute, second=0)
            return int(dt.timestamp())
        except ValueError:
            pass

    # 格式 6: "星期一 19:53"
    m = re.match(r"(星期一|星期二|星期三|星期四|星期五|星期六|星期日)\s*(\d{1,2}):(\d{2})$", time_text)
    if m:
        hour = int(m.group(2))
        minute = int(m.group(3))
        dt = base_date.replace(hour=hour, minute=minute, second=0)
        return int(dt.timestamp())

    return None


def _parse_date_text(date_text: str, base_date: datetime) -> datetime | None:
    """解析纯日期文本，沿用基准年的时间分量。"""
    date_text = date_text.strip()

    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日{1,2}$", date_text)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        try:
            return base_date.replace(year=year, month=month, day=day)
        except ValueError:
            return None

    m = re.match(r"^(\d{1,2})月(\d{1,2})日{1,2}$", date_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        try:
            return base_date.replace(month=month, day=day)
        except ValueError:
            return None

    return None


def _is_time_text(text: str) -> bool:
    """判断文本是否是时间戳。"""
    patterns = [
        r"^(上午|下午|晚上|凌晨|早上)\s*\d{1,2}:\d{2}$",
        r"^(昨天|昨日)\s*\d{1,2}:\d{2}$",
        r"^(今天|明天|前天)\s*\d{1,2}:\d{2}$",
        r"^\d{2}-\d{2}\s*\d{1,2}:\d{2}$",
        r"^\d{1,2}:\d{2}$",
        # 中文日期格式: 1月12日晚上20:16、1月12日下午3:42
        r"^\d{1,2}月\d{1,2}日(上午|下午|晚上|凌晨|早上)?\s*\d{1,2}:\d{2}",
        # 纯日期: 1月12日、2026年1月12日、1月12日日（OCR 重复）
        r"^\d{1,4}年?\d{1,2}月\d{1,2}日{1,2}$",
        # 网络状态指示器
        r"^\d+\.?\d*[kKMG]/s",
        r"^\d+B/s$",
        r"^昨日\s*\d{1,2}:\d{2}$",
        # 星期X HH:MM
        r"^(星期一|星期二|星期三|星期四|星期五|星期六|星期日)\s*\d{1,2}:\d{2}",
        r"^(星期一|星期二|星期三|星期四|星期五|星期六|星期日)$",
    ]
    return any(re.match(p, text.strip()) for p in patterns)


def _is_system_message(text: str) -> bool:
    """判断是否是系统消息（非聊天内容）。"""
    system_patterns = [
        r"以下是新消息",
        r"以上是历史消息",
        r"你已添加了",
        r"你撤回了一条消息",
        r"对方撤回了一条消息",
        r"红包",
        r"转账",
        r"拍了拍",
        r"\[图片\]",
        r"\[视频\]",
        r"\[语音\]",
        r"\[文件\]",
        r"\[位置\]",
        # 应用内功能关键词
        r"^imgPlay$",
        r"img\s*Play",
        r"^收付款$",
        r"^确认收款$",
        r"^转账给",
        r"^对方收款",
        r"^服务通知",
        r"^微信运动",
        r"^我的地址",
        # 表情/贴纸占位
        r"^\[动画表情\]",
        r"^\[表情\]",
        r"^\[动画\]",
        # 网络/系统状态
        r"^\d+\.?\d*[kKMG]/s",
        r"^使用(数据流量|无线网络)",
        # OCR 常见噪声
        r"^OMARTIST$",
        # 运营商名称（截图顶栏）
        r"中国(联通|移动|电信)",
        # 电量/信号
        r"^\d{1,3}%$",
        # 应用顶栏文字
        r"^<微信",
        r"^<返回",
        r"^\s*微信\s*$",
        r"^聊天信息$",
        r"^通讯录$",
        r"^发现$",
    ]
    return any(re.search(p, text) for p in system_patterns)


def _line_lane(result: OCRResult, image_width: int) -> str:
    """按横向位置粗分 left / center / right。"""
    if image_width <= 0:
        return "center"

    x_ratio = result.center_x / image_width
    if x_ratio < 0.38:
        return "left"
    if x_ratio > 0.62:
        return "right"
    return "center"


def _x_overlap_ratio(a: OCRResult, b: OCRResult) -> float:
    """计算两个 OCR 框在 x 轴上的重叠比例。"""
    overlap = max(0, min(a.right, b.right) - max(a.left, b.left))
    min_width = max(1, min(a.right - a.left, b.right - b.left))
    return overlap / min_width


def _group_by_bubble(ocr_results: list[OCRResult], image_width: int) -> list[list[OCRResult]]:
    """将 OCR 结果按消息气泡分组。

    逻辑：
    1. 系统消息和时间戳单独成组
    2. 相邻文本需要同时满足纵向接近、横向同侧或明显重叠，才会合并
    """
    if not ocr_results:
        return []

    groups: list[list[OCRResult]] = []
    current_group: list[OCRResult] = [ocr_results[0]]

    for i in range(1, len(ocr_results)):
        prev = ocr_results[i - 1]
        curr = ocr_results[i]

        # 计算垂直间距
        y_gap = curr.top - prev.bottom
        prev_special = _is_system_message(prev.text) or _is_time_text(prev.text)
        curr_special = _is_system_message(curr.text) or _is_time_text(curr.text)
        same_lane = _line_lane(prev, image_width) == _line_lane(curr, image_width)
        strong_x_overlap = _x_overlap_ratio(prev, curr) >= 0.5
        aligned_edge = abs(prev.left - curr.left) <= 28 or abs(prev.right - curr.right) <= 28

        # 系统消息/时间戳始终独立；普通文本还要满足纵向和横向都接近才合并
        if (
            prev_special
            or curr_special
            or y_gap > 20
            or not (same_lane or strong_x_overlap or aligned_edge)
        ):
            groups.append(current_group)
            current_group = [curr]
        else:
            current_group.append(curr)

    if current_group:
        groups.append(current_group)

    return groups


def _determine_senders(
    groups: list[list[OCRResult]],
    image_width: int,
) -> list[str]:
    """根据所有气泡的 x 位置聚类判断发送方。

    用 k-means (k=2) 自动发现左右两侧的天然聚类中心，
    左侧聚类 → "her"（对方），右侧聚类 → "me"（自己）。

    优势：不依赖硬编码阈值，自适应不同聊天平台的布局差异。
    当只有一个聚类时（单侧消息），直接判断全为同一发送方。
    """
    if not groups:
        return []

    # 归一化 x 中心坐标 (0.0 = 左边缘, 1.0 = 右边缘)
    x_positions = []
    for group in groups:
        avg_x = sum(r.center_x for r in group) / len(group)
        x_positions.append(avg_x / image_width)

    # 只用边缘位置初始化聚类（排除居中的时间/系统消息干扰）
    edge_positions = [x for x in x_positions if x < 0.35 or x > 0.65]

    # ----- 情况 1: 只有一侧有消息 -----
    if len(edge_positions) < 2:
        avg_x = sum(x_positions) / len(x_positions)
        default = "me" if avg_x > 0.5 else "her"
        return [default] * len(groups)

    # ----- 情况 2: 双侧消息，k-means 聚类 -----
    c_left = min(edge_positions)
    c_right = max(edge_positions)

    for _ in range(20):
        left_group = []
        right_group = []
        for x in x_positions:
            if abs(x - c_left) <= abs(x - c_right):
                left_group.append(x)
            else:
                right_group.append(x)
        if left_group:
            new_left = sum(left_group) / len(left_group)
        else:
            new_left = c_left
        if right_group:
            new_right = sum(right_group) / len(right_group)
        else:
            new_right = c_right
        if abs(new_left - c_left) < 0.005 and abs(new_right - c_right) < 0.005:
            break
        c_left, c_right = new_left, new_right

    # 如果聚类中心太接近，说明实际只有一侧有内容
    if abs(c_right - c_left) < 0.15:
        mid = (c_left + c_right) / 2
        return ["me" if mid > 0.5 else "her"] * len(groups)

    # 分配发送方：离左中心近 = her，离右中心近 = me
    senders = []
    for x in x_positions:
        if abs(x - c_left) < abs(x - c_right):
            senders.append("her")
        else:
            senders.append("me")

    return senders


def _resolve_time_marker(
    marker_text: str,
    base_date: datetime,
) -> tuple[datetime, int | None]:
    """解析时间/日期标记，并返回更新后的基准时间。"""
    parsed_ts = _parse_time_text(marker_text, base_date)
    if parsed_ts is not None:
        parsed_dt = datetime.fromtimestamp(parsed_ts)
        return parsed_dt, parsed_ts

    parsed_date = _parse_date_text(marker_text, base_date)
    if parsed_date is not None:
        return parsed_date, None

    return base_date, None


def parse_screenshot(
    image_path: str | Path,
    ocr_results: list[OCRResult],
    base_timestamp: int = 0,
) -> list[ParsedMessage]:
    """解析单张截图，返回消息列表。

    Args:
        image_path: 截图文件路径
        ocr_results: OCR 识别结果
        base_timestamp: 基准时间戳（消息从此时间开始逐秒递增）

    Returns:
        ParsedMessage 列表，按 y 坐标从上到下排列
    """
    if not ocr_results:
        return []

    # 获取图片尺寸
    width, _ = get_image_size(image_path)
    current_base_date = infer_base_datetime(image_path, base_timestamp=base_timestamp)
    current_timestamp = int(current_base_date.timestamp())
    pending_timestamp: int | None = None

    # 按气泡分组
    groups = _group_by_bubble(ocr_results, width)

    # 过滤：跳过系统消息；时间戳更新后续消息的时间基线
    content_groups: list[tuple[list[OCRResult], int]] = []
    for group in groups:
        texts = [r.text for r in group]
        combined_text = "".join(texts).strip()
        if not combined_text:
            continue
        if _is_system_message(combined_text):
            continue
        if len(group) == 1 and _is_time_text(group[0].text):
            current_base_date, parsed_ts = _resolve_time_marker(group[0].text, current_base_date)
            if parsed_ts is not None:
                pending_timestamp = parsed_ts
                current_timestamp = parsed_ts
            else:
                current_timestamp = int(current_base_date.timestamp())
            continue
        assigned_timestamp = pending_timestamp if pending_timestamp is not None else current_timestamp
        content_groups.append((group, assigned_timestamp))
        current_timestamp = assigned_timestamp + 1
        pending_timestamp = None

    if not content_groups:
        return []

    # 批量判断发送方（聚类分析所有气泡的 x 位置）
    senders = _determine_senders([group for group, _ in content_groups], width)

    messages: list[ParsedMessage] = []

    for (group, timestamp), sender in zip(content_groups, senders):
        # 合并多行文本
        content = "\n".join(r.text for r in group)

        # 计算平均置信度
        avg_confidence = sum(r.confidence for r in group) / len(group)

        messages.append(ParsedMessage(
            sender=sender,
            content=content,
            timestamp=timestamp,
            confidence=avg_confidence,
        ))

    return messages


def parse_screenshots(
    screenshot_dir: str | Path,
    ocr_results_map: dict[str, list[OCRResult]],
    base_timestamp: int = 0,
) -> list[ParsedMessage]:
    """解析多张截图，返回合并后的消息列表。

    Args:
        screenshot_dir: 截图目录
        ocr_results_map: {图片路径: OCRResult 列表} 字典
        base_timestamp: 基准时间戳（从此开始逐秒递增）

    Returns:
        所有截图的消息合并后的列表，按文件名顺序排列
    """
    all_messages: list[ParsedMessage] = []

    # 按文件名排序（契约：文件名越小 = 聊天内容越早）
    sorted_paths = sorted(ocr_results_map.keys(), key=lambda p: Path(p).name)

    cursor_timestamp = base_timestamp
    for image_path in sorted_paths:
        ocr_results = ocr_results_map[image_path]
        image_base_timestamp = cursor_timestamp if base_timestamp > 0 else infer_base_timestamp(image_path)
        messages = parse_screenshot(image_path, ocr_results, base_timestamp=image_base_timestamp)
        all_messages.extend(messages)
        if base_timestamp > 0 and messages:
            cursor_timestamp = messages[-1].timestamp + 1

    return all_messages
