# -*- coding: utf-8 -*-
"""图片读写公共工具（支持中文路径和 ico 格式）。

统一 font_matcher.py 和 template_matcher.py 中重复的 imread_unicode 实现。

v6 验证发现：
- cv2.imread 不支持中文路径
- cv2.imdecode 不支持 ico 文件
- 解决方案：用 PIL.Image.open 解码，再转 cv2 格式
"""
from typing import Optional

import cv2
import numpy as np
from PIL import Image

try:
    from logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)


def imread_unicode(path: str) -> Optional[np.ndarray]:
    """读取图片（支持中文路径和 ico 格式）。

    Args:
        path: 图片路径（支持中文）

    Returns:
        BGR 格式的 numpy 数组，失败返回 None
    """
    try:
        pil_img = Image.open(path)
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.error(f"读取图片失败: {path}, 错误: {e}")
        return None


def imwrite_unicode(path: str, img: np.ndarray) -> bool:
    """保存图片（支持中文路径）。

    v6 验证发现：cv2.imwrite 不支持中文路径，需用 imencode + tofile。

    Args:
        path: 保存路径
        img: BGR 格式的图片

    Returns:
        是否成功
    """
    try:
        ext = path.rsplit('.', 1)[-1] if '.' in path else 'png'
        result, encoded = cv2.imencode(f'.{ext}', img)
        if result:
            encoded.tofile(path)
            return True
        return False
    except Exception as e:
        logger.error(f"保存图片失败: {path}, 错误: {e}")
        return False
