"""PaddleOCR GPU 引擎封装。

使用 PaddleOCR (PP-OCRv5) 在 GPU 上进行文字识别。
精度和速度均优于 RapidOCR ONNX 版本，适合 A100 等 GPU 环境。

安装依赖:
    pip install paddlepaddle-gpu paddleocr

接口兼容 ocr_engine.py，可直接替换 import 使用。

Usage:
    from ocr_engine_paddle import ocr_image, ocr_batch, OCRResult

    results = ocr_image("screenshot.png")           # 单张，GPU
    results = ocr_image("screenshot.png", server_model=True)  # 高精度模式
    batch = ocr_batch(["a.png", "b.png"])           # 批量
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# CACHE_DIR: data/cache/ocr，相对于项目根目录
_CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"

# ---------------------------------------------------------------------------
# 数据模型（与 ocr_engine.OCRResult 完全兼容）
# ---------------------------------------------------------------------------

OCR_CACHE_DIR = _CACHE_DIR / "ocr"
OCR_CACHE_VERSION = "v2"


@dataclass
class OCRResult:
    """单条 OCR 识别结果。"""

    text: str
    bbox: list[tuple[int, int]]  # 四个顶点坐标 [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    confidence: float

    @property
    def center_x(self) -> int:
        xs = [p[0] for p in self.bbox]
        return sum(xs) // len(xs)

    @property
    def center_y(self) -> int:
        ys = [p[1] for p in self.bbox]
        return sum(ys) // len(ys)

    @property
    def left(self) -> int:
        return min(p[0] for p in self.bbox)

    @property
    def right(self) -> int:
        return max(p[0] for p in self.bbox)

    @property
    def top(self) -> int:
        return min(p[1] for p in self.bbox)

    @property
    def bottom(self) -> int:
        return max(p[1] for p in self.bbox)


# ---------------------------------------------------------------------------
# 引擎单例
# ---------------------------------------------------------------------------

_ENGINE: Any | None = None
_ENGINE_CONFIG: dict = {}  # 记录上次初始化参数，避免重复创建


def _get_engine(
    use_gpu: bool = True,
    server_model: bool = False,
    rec_batch_size: int = 6,
) -> Any:
    """获取或初始化 PaddleOCR 引擎单例。

    首次调用时创建引擎并加载模型（~2-5 秒），后续调用复用单例。
    参数变化时会重建引擎。
    """
    global _ENGINE, _ENGINE_CONFIG

    new_config = dict(
        use_gpu=use_gpu,
        server_model=server_model,
        rec_batch_size=rec_batch_size,
    )
    if _ENGINE is not None and _ENGINE_CONFIG == new_config:
        return _ENGINE

    from paddleocr import PaddleOCR  # type: ignore[import-untyped]

    kwargs: dict = dict(lang="ch", use_gpu=use_gpu)
    if server_model:
        kwargs["det_model_name"] = "PP-OCRv5_server_det"
        kwargs["rec_model_name"] = "PP-OCRv5_server_rec"
    kwargs["rec_batch_size"] = rec_batch_size

    print(f"[PaddleOCR] 初始化引擎 GPU={use_gpu} server={server_model} rec_bs={rec_batch_size}")
    _ENGINE = PaddleOCR(**kwargs)
    _ENGINE_CONFIG = new_config
    return _ENGINE


# ---------------------------------------------------------------------------
# 缓存（文件级 MD5 哈希）
# ---------------------------------------------------------------------------


def _get_image_hash(image_path: str | Path) -> str:
    """基于文件内容生成 MD5 哈希。"""
    path = Path(image_path)
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_key(image_hash: str, *, server_model: bool, rec_batch_size: int) -> str:
    """生成含模型配置的缓存键，不同配置使用不同缓存。"""
    return f"{OCR_CACHE_VERSION}_{image_hash}_srv{int(server_model)}_bs{rec_batch_size}"


def _load_cache(cache_key: str) -> list[OCRResult] | None:
    cache_file = OCR_CACHE_DIR / f"{cache_key}.json"
    if not cache_file.is_file():
        return None
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        result: list[OCRResult] = []
        for item in data:
            # json 反序列化后列表变 list，转回 tuple 保持类型一致
            item["bbox"] = [tuple(p) for p in item["bbox"]]
            result.append(OCRResult(**item))
        return result
    except (json.JSONDecodeError, KeyError):
        return None


def _save_cache(cache_key: str, results: list[OCRResult]) -> None:
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_cache_if_needed(OCR_CACHE_DIR, max_bytes=500 * 1024 * 1024)
    cache_file = OCR_CACHE_DIR / f"{cache_key}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)


def _cleanup_cache_if_needed(cache_dir: Path, max_bytes: int) -> None:
    """缓存总大小超过 max_bytes 时删除最旧文件。"""
    files = sorted(cache_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    if total <= max_bytes:
        return
    for f in files:
        if total <= max_bytes:
            break
        size = f.stat().st_size
        f.unlink()
        total -= size


# ---------------------------------------------------------------------------
# PaddleOCR → OCRResult 转换
# ---------------------------------------------------------------------------

def _paddle_result_to_ocrresults(raw_result: list, y_offset: int = 0) -> list[OCRResult]:
    """将 PaddleOCR 单图结果转换为 OCRResult 列表。

    PaddleOCR 输出格式:
        [[[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ('文字', 置信度)], ...]
    """
    results: list[OCRResult] = []
    if not raw_result:
        return results
    for line in raw_result:
        bbox_raw = line[0]
        bbox = [(int(p[0]), int(p[1]) + y_offset) for p in bbox_raw]
        text = line[1][0]
        confidence = float(line[1][1])
        results.append(OCRResult(text=text, bbox=bbox, confidence=confidence))
    return results


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def ocr_image(
    image_path: str | Path,
    use_cache: bool = True,
    use_gpu: bool = True,
    server_model: bool = False,
    rec_batch_size: int = 6,
) -> list[OCRResult]:
    """对单张图片进行 OCR 识别，返回结果列表（按 y 坐标从上到下排序）。

    Args:
        image_path: 图片文件路径
        use_cache: 是否使用 MD5 缓存（默认 True）
        use_gpu: 是否使用 GPU（默认 True，A100 必须开）
        server_model: 是否使用 server 版高精度模型（默认 False）
                      开启后精度更高，模型约 3-5x 大，A100 上几乎无感知
        rec_batch_size: 识别阶段 batch size，A100 建议 32，小显存用 6

    Returns:
        OCRResult 列表，按 center_y 升序排列
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    # 缓存（含模型配置，不同 server_model/rec_batch_size 用不同缓存）
    cache_key = None
    if use_cache:
        image_hash = _get_image_hash(image_path)
        cache_key = _cache_key(image_hash, server_model=server_model, rec_batch_size=rec_batch_size)
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached

    engine = _get_engine(
        use_gpu=use_gpu,
        server_model=server_model,
        rec_batch_size=rec_batch_size,
    )

    # 分片高度：PaddleOCR 内部会将图缩放到 max_side=960px（det_limit_side_len），
    # 分片太大时缩放后文字太小无法检测。4000px 是 1080p 截图约 2 屏高度，
    # 缩放后约 259x960，文字可识别。可根据图片宽度调大（宽图用更小分片）。
    _MAX_DIM = 4000
    _OVERLAP = 150  # 分片重叠 px，给边界文本行保留更充足上下文

    with Image.open(image_path) as img:
        w, h = img.size

    ocr_results: list[OCRResult] = []

    if h <= _MAX_DIM:
        # 正常尺寸：直接 OCR
        result = engine.ocr(str(image_path))
        raw_lines = result[0] if result else []
        if raw_lines is None:
            raw_lines = []
        ocr_results = _paddle_result_to_ocrresults(raw_lines)
    else:
        # 超长图分片处理：保存为临时文件再 OCR（传 numpy array 给 PaddleOCR
        # 会因 RGB/BGR 通道问题导致检测率为 0）
        stride = _MAX_DIM - _OVERLAP
        for i, y_start in enumerate(range(0, h, stride)):
            y_end = min(y_start + _MAX_DIM, h)
            with Image.open(image_path) as img:
                chunk_img = img.crop((0, y_start, w, y_end))
            # 写临时文件
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            try:
                chunk_img.save(tmp_path)
                tmp.close()
                raw_result = engine.ocr(tmp_path)
            finally:
                os.unlink(tmp_path)
            raw_lines = raw_result[0] if raw_result and raw_result[0] is not None else []
            # 非首片跳过 overlap 区域内的文本（避免重复）
            if i > 0:
                raw_lines = [
                    line for line in raw_lines
                    if max(p[1] for p in line[0]) > _OVERLAP
                ]
            chunk_results = _paddle_result_to_ocrresults(raw_lines, y_offset=y_start)
            ocr_results.extend(chunk_results)
            print(f"  分片 OCR: y={y_start}-{y_end} ({len(raw_lines)} 条)")

    # 按 y 坐标排序
    ocr_results.sort(key=lambda r: r.center_y)

    if use_cache and cache_key is not None:
        _save_cache(cache_key, ocr_results)

    return ocr_results


def ocr_batch(
    image_paths: list[str | Path],
    use_cache: bool = True,
    use_gpu: bool = True,
    server_model: bool = False,
    rec_batch_size: int = 6,
) -> dict[str, list[OCRResult]]:
    """批量 OCR 识别。

    PaddleOCR 引擎实例内部有 C++ 层锁，多线程调用同一实例不会加速
    且有段错误风险。加速应通过增大 rec_batch_size 实现。
    单张失败不会影响其余图片的处理。

    Args:
        image_paths: 图片文件路径列表
        其余参数同 ocr_image()

    Returns:
        {图片路径: OCRResult 列表} 字典
    """
    results: dict[str, list[OCRResult]] = {}
    for path in image_paths:
        path_str = str(path)
        try:
            results[path_str] = ocr_image(
                path,
                use_cache=use_cache,
                use_gpu=use_gpu,
                server_model=server_model,
                rec_batch_size=rec_batch_size,
            )
        except FileNotFoundError:
            raise
        except Exception:
            print(f"OCR 失败: {path}")
            traceback.print_exc()
            results[path_str] = []
    return results


# ---------------------------------------------------------------------------
# PP-Structure 版面分析（可选高级功能）
# ---------------------------------------------------------------------------

_STRUCTURE_ENGINE: Any | None = None
_STRUCTURE_ENGINE_GPU: bool | None = None  # 记录 use_gpu，配置变化时重建


def _get_structure_engine(use_gpu: bool = True) -> Any:
    """获取 PP-Structure 引擎单例。配置变化时自动重建。"""
    global _STRUCTURE_ENGINE, _STRUCTURE_ENGINE_GPU
    if _STRUCTURE_ENGINE is not None and _STRUCTURE_ENGINE_GPU == use_gpu:
        return _STRUCTURE_ENGINE
    from paddleocr import PPStructure  # type: ignore[import-untyped]
    print(f"[PP-Structure] 初始化引擎 GPU={use_gpu}")
    _STRUCTURE_ENGINE = PPStructure(lang="ch", use_gpu=use_gpu)
    _STRUCTURE_ENGINE_GPU = use_gpu
    return _STRUCTURE_ENGINE


@dataclass
class LayoutRegion:
    """版面分析检测到的区域。"""

    type: str  # 'text', 'table', 'figure', 'title' 等
    bbox: list[tuple[int, int]]  # 四点坐标
    text: str  # 区域内文字
    confidence: float


def analyze_layout(
    image_path: str | Path,
    use_gpu: bool = True,
) -> list[LayoutRegion]:
    """使用 PP-Structure 对图片做版面分析，检测文本区域并 OCR。

    对聊天截图来说，这等价于"先检测气泡区域再 OCR"——
    每个 text 区域大致对应一个气泡。复杂布局（群聊、引用回复）
    下比全图 OCR + 几何推断可靠得多。

    Args:
        image_path: 图片文件路径
        use_gpu: 是否使用 GPU

    Returns:
        LayoutRegion 列表，按 y 坐标排序
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    engine = _get_structure_engine(use_gpu=use_gpu)
    result = engine(str(image_path))

    regions: list[LayoutRegion] = []
    for region in result:
        bbox_raw = region.get("bbox", [])
        bbox = [(int(p[0]), int(p[1])) for p in bbox_raw] if bbox_raw else []
        text = ""
        confidence = 0.0
        # PP-Structure 每个区域可能含多行
        res = region.get("res", [])
        if res:
            texts = []
            confs = []
            for line in res:
                texts.append(line.get("text", ""))
                confs.append(line.get("confidence", 0.0))
            text = "\n".join(texts)
            confidence = sum(confs) / len(confs) if confs else 0.0

        regions.append(LayoutRegion(
            type=region.get("type", "text"),
            bbox=bbox,
            text=text,
            confidence=confidence,
        ))

    regions.sort(key=lambda r: (
        min(p[1] for p in r.bbox) if r.bbox else 0
    ))
    return regions
