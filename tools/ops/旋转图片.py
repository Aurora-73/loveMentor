import os
from pathlib import Path
from typing import Tuple

from PIL import Image
import numpy as np

# Configure input folder
WORKSPACE_ROOT = Path(r'E:\BaiduNetdiskDownload\恋爱攻略_拍照')
INPUT_DIR = WORKSPACE_ROOT / 'output_clear'

SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}


def to_numpy_rgb(img: Image.Image) -> np.ndarray:
    """Convert PIL Image to RGB numpy array (H, W, 3), ignoring alpha."""
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGBA') if 'A' in img.getbands() else img.convert('RGB')
    arr = np.array(img)
    if arr.ndim == 2:  # L mode
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    return arr


def luminance(arr_rgb: np.ndarray) -> np.ndarray:
    """Compute luminance Y using Rec.709: Y = 0.2126R + 0.7152G + 0.0722B"""
    r = arr_rgb[..., 0].astype(np.float32)
    g = arr_rgb[..., 1].astype(np.float32)
    b = arr_rgb[..., 2].astype(np.float32)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def left_right_30_means(img: Image.Image) -> Tuple[float, float]:
    """Return mean luminance of left and right 30% strips for the given image."""
    arr = to_numpy_rgb(img)
    H, W, _ = arr.shape
    if W == 0 or H == 0:
        return 0.0, 0.0
    Y = luminance(arr)
    width_30 = max(1, int(round(W * 0.3)))
    left_strip = Y[:, :width_30]
    right_strip = Y[:, W - width_30:]
    return float(left_strip.mean()), float(right_strip.mean())


def ensure_landscape(img: Image.Image) -> Image.Image:
    """Rotate 90 degrees if portrait to make width > height."""
    w, h = img.size
    if w > h:
        return img
    # Rotate 90 degrees clockwise to make it landscape
    return img.rotate(-90, expand=True)


def process_image(img: Image.Image) -> Image.Image:
    """Process a single image: ensure landscape and left 30% brighter than right 30%."""
    img = ensure_landscape(img)
    left_mean, right_mean = left_right_30_means(img)
    # If left is not brighter, rotate 180 degrees to swap sides while keeping landscape
    if not (left_mean > right_mean):
        img = img.rotate(180, expand=True)
        # Optional: recheck (not strictly needed, but helpful for debugging)
        # l2, r2 = left_right_30_means(img)
        # print(f"Adjusted: left {l2:.2f} vs right {r2:.2f}")
    return img


def process_folder(input_dir: Path) -> None:
    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}")
        return
    files = [p for p in input_dir.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED_EXT]
    if not files:
        print(f"No supported images found under: {input_dir}")
        return
    print(f"Found {len(files)} images. Processing...")
    for p in files:
        try:
            with Image.open(p) as img:
                processed = process_image(img)
                # Overwrite original file
                processed.save(p)
            print(f"OK: {p}")
        except Exception as e:
            print(f"FAIL: {p} -> {e}")


if __name__ == '__main__':
    process_folder(INPUT_DIR)
