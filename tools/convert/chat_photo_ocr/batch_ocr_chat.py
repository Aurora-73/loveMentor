"""批量 OCR 聊天截图，每张图输出同名的 .txt + .json。

递归扫描目录中的图片文件，对每张图独立执行 OCR → 气泡分组 → 发送方判断，
在图片同目录生成同名 .txt（带发送方标签的可读文本）和 .json（结构化数据）。

输出不经过 loveMentor 主流程，专门用于 wiki 素材（如 A07 聊天案例）的批量 OCR。

Usage:
    python tools/batch_ocr_chat.py "docs/百度网盘/【A07】几百套聊天案例合集" --batch
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ocr_engine_paddle import ocr_batch
from screenshot_parser import ParsedMessage, infer_base_timestamp, parse_screenshot


# ---------------------------------------------------------------------------
# 图片查找
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def find_image_files(directory: Path) -> list[Path]:
    images: list[Path] = []
    for f in directory.rglob("*"):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(f)
    return sorted(images)


def output_path_for(img_path: Path) -> tuple[Path, Path]:
    """返回 (txt路径, json路径)，与图片同名不同后缀。"""
    base = img_path.parent / img_path.stem
    return base.with_suffix(".txt"), base.with_suffix(".json")


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def format_text(messages: list[ParsedMessage]) -> str:
    lines = []
    for msg in messages:
        side = "我" if msg.sender == "me" else "她"
        t = datetime.fromtimestamp(msg.timestamp).strftime("%m-%d %H:%M")
        content_lines = msg.content.split("\n")
        for i, cl in enumerate(content_lines):
            lines.append(f"[{t}] {side}: {cl}" if i == 0 else f"       {cl}")
    return "\n".join(lines)


def format_json(messages: list[ParsedMessage]) -> list[dict]:
    return [
        {"sender": m.sender, "content": m.content, "timestamp": m.timestamp, "confidence": round(m.confidence, 3)}
        for m in messages
    ]


# ---------------------------------------------------------------------------
# 核心处理
# ---------------------------------------------------------------------------

def process_image(image_path: Path, ocr_results_map: dict[str, list]) -> int:
    """对单张图片解析 → 输出同名的 .txt / .json。返回消息条数。"""
    try:
        ocr_results = ocr_results_map.get(str(image_path), [])
        if not ocr_results:
            return 0

        messages = parse_screenshot(
            image_path,
            ocr_results,
            base_timestamp=infer_base_timestamp(image_path),
        )
        if not messages:
            return 0

        txt_path, json_path = output_path_for(image_path)
        txt_path.write_text(format_text(messages), encoding="utf-8")
        json_path.write_text(json.dumps(format_json(messages), ensure_ascii=False, indent=2), encoding="utf-8")

        me = sum(1 for m in messages if m.sender == "me")
        her = sum(1 for m in messages if m.sender == "her")
        print(f"    {image_path.name} → {len(messages)}条 (我{me} 她{her})")
        return len(messages)
    except Exception:
        print(f"    解析失败: {image_path}")
        traceback.print_exc()
        return 0


def process_directory(image_paths: list[Path]) -> tuple[int, int]:
    """处理一个目录下的所有图片。返回 (图片数, 消息总数)。"""
    if not image_paths:
        return 0, 0

    leaf_dir = image_paths[0].parent
    print(f"\n{'='*60}")
    print(f"目录: {leaf_dir}")
    print(f"图片: {len(image_paths)} 张")

    t0 = time.time()
    ocr_results_map = ocr_batch(image_paths)
    total_msg = 0
    valid = 0

    for img_path in image_paths:
        n = process_image(img_path, ocr_results_map)
        if n > 0:
            valid += 1
        total_msg += n

    t1 = time.time()
    print(f"耗时: {t1-t0:.1f}s  |  识别: {valid}/{len(image_paths)} 张  |  消息: {total_msg} 条")
    return valid, total_msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="批量 OCR 聊天截图，每张图输出同名 .txt/.json")
    parser.add_argument("directory", type=str, help="截图目录路径")
    parser.add_argument("--batch", action="store_true", help="批量模式：递归处理所有子目录")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"错误: 目录不存在: {directory}")
        sys.exit(1)

    print(f"扫描: {directory}")
    all_images = find_image_files(directory)
    print(f"图片: {len(all_images)} 张")
    if not all_images:
        print("无图片")
        sys.exit(0)

    t_start = time.time()

    if args.batch:
        # 按叶子目录分组，每组单独处理
        groups: dict[Path, list[Path]] = {}
        for img in all_images:
            leaf = img.parent.resolve()
            groups.setdefault(leaf, []).append(img)
        for leaf, imgs in groups.items():
            imgs.sort(key=lambda p: p.name)
        sorted_leaves = sorted(groups.items(), key=lambda x: x[0])

        print(f"目录: {len(sorted_leaves)} 个\n")
        total_imgs = 0
        total_msg = 0
        for leaf, imgs in sorted_leaves:
            n_img, n_msg = process_directory(imgs)
            total_imgs += n_img
            total_msg += n_msg
    else:
        n_img, n_msg = process_directory(all_images)
        total_imgs = n_img
        total_msg = n_msg

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完成: {total_imgs}/{len(all_images)} 张识别, {total_msg} 条消息, 耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
