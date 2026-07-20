# -*- coding: utf-8 -*-
"""
微信 UI 图标模板匹配模块（TemplateMatcher）。

基于 v5/v6 验证结论：
- 图标模板匹配 conf=1.0000，速度快 10-100 倍（0.01-0.21s vs 字体匹配 0.5-3.5s）
- TM_CCOEFF_NORMED 是最佳匹配方法（归一化后对亮度/对比度不敏感）
- ico 文件用 TM_CCORR_NORMED 更稳定（v6 验证 0.85-0.89）
- 搜索区域限定可大幅提升速度（全图 0.5s → 限定区域 0.01s）

作为 UI 元素定位的首选方法（v3.0 架构 Layer 1）。
字体匹配（font_matcher.py）仅用于 display_name 等可变文字（Layer 2）。

典型工作流：
    from template_matcher import match_template_best

    # 定位搜索栏
    match = match_template_best(scene, "wx_icon/搜索栏.png", threshold=0.85)
    if match:
        print(f"搜索栏位置: ({match.center_x}, {match.center_y}), conf={match.confidence}")

    # 定位发送按钮（可发送态）
    match = match_template_best(
        scene, "wx_icon/send_green_full.png",
        search_region=(int(w*0.5), int(h*0.6), w, h),
        threshold=0.85
    )
"""
import os
from dataclasses import dataclass
from typing import Optional, List, Tuple

import cv2
import numpy as np

try:
    from logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# 公共图片读写工具（支持中文路径和 ico 格式）
from image_utils import imread_unicode, imwrite_unicode


# ============ 默认配置 ============

# 模板根目录（wx_icon/）
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wx_icon")

# 默认匹配阈值（v5 验证：0.70 可区分存在/不存在，关键场景 0.85+）
DEFAULT_THRESHOLD = 0.70
STRICT_THRESHOLD = 0.85

# 默认匹配方法（v5 验证最佳）
DEFAULT_METHOD = cv2.TM_CCOEFF_NORMED

# ico 文件推荐方法（v6 验证：TM_CCORR_NORMED 对 ico 更稳定）
ICO_METHOD = cv2.TM_CCORR_NORMED

# 模板缓存（避免重复读取）
_template_cache: dict[str, np.ndarray] = {}


# ============ 数据结构 ============

@dataclass
class TemplateMatch:
    """模板匹配结果。"""
    center_x: int                        # 中心 x 坐标
    center_y: int                        # 中心 y 坐标
    confidence: float                    # 置信度（0-1）
    rect: Tuple[int, int, int, int]      # (left, top, right, bottom) 在场景图中的位置
    template_size: Tuple[int, int]       # (width, height) 模板尺寸
    template_path: str = ""              # 模板文件路径（用于调试）


# ============ 工具函数 ============
# imread_unicode / imwrite_unicode 已抽取到 image_utils.py（公共模块）
# 避免与 font_matcher.py 重复实现


def _resolve_template_path(template_path: str) -> str:
    """解析模板路径（支持相对路径和绝对路径）。

    - 绝对路径：直接返回
    - 相对路径：相对于 TEMPLATE_DIR 解析（如 "搜索栏.png" → "wx_icon/搜索栏.png"）
    - 仅文件名：自动加上 "wx_icon/" 前缀（如 "搜索栏" → "wx_icon/搜索栏.png"）
    """
    if os.path.isabs(template_path) and os.path.exists(template_path):
        return template_path

    # 尝试相对当前工作目录
    if os.path.exists(template_path):
        return template_path

    # 尝试相对于 wx_icon/ 目录
    full_path = os.path.join(TEMPLATE_DIR, template_path)
    if os.path.exists(full_path):
        return full_path

    # 尝试加上 .png 后缀
    if not template_path.endswith('.png') and not template_path.endswith('.ico'):
        full_path_with_ext = os.path.join(TEMPLATE_DIR, template_path + '.png')
        if os.path.exists(full_path_with_ext):
            return full_path_with_ext

    # 返回最可能的全路径（让后续读取报错）
    return full_path


def _load_template(template_path: str) -> Optional[np.ndarray]:
    """加载模板（带缓存）。

    Args:
        template_path: 模板路径（支持中文）

    Returns:
        BGR 格式的模板，失败返回 None
    """
    resolved = _resolve_template_path(template_path)

    if resolved in _template_cache:
        return _template_cache[resolved]

    if not os.path.exists(resolved):
        logger.error(f"模板文件不存在: {template_path} (解析为 {resolved})")
        return None

    template = imread_unicode(resolved)
    if template is None:
        return None

    _template_cache[resolved] = template
    logger.debug(f"加载模板: {resolved}, 尺寸={template.shape[1]}x{template.shape[0]}")
    return template


def _crop_search_region(scene: np.ndarray,
                        search_region: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
    """裁剪搜索区域。

    Args:
        scene: 完整场景图
        search_region: (x1, y1, x2, y2)，None 表示全图

    Returns:
        裁剪后的子图
    """
    if search_region is None:
        return scene

    x1, y1, x2, y2 = search_region
    h, w = scene.shape[:2]

    # 边界保护
    x1 = max(0, min(int(x1), w))
    y1 = max(0, min(int(y1), h))
    x2 = max(0, min(int(x2), w))
    y2 = max(0, min(int(y2), h))

    if x2 <= x1 or y2 <= y1:
        logger.warning(f"搜索区域无效: {search_region}, 场景尺寸={w}x{h}")
        return scene

    return scene[y1:y2, x1:x2]


def _select_method(template_path: str, method: Optional[int] = None) -> int:
    """选择匹配方法（ico 文件用 TM_CCORR_NORMED，其他用 TM_CCOEFF_NORMED）。

    v6 验证结论：
    - TM_CCOEFF_NORMED 对 PNG 模板最佳（归一化对亮度/对比度不敏感）
    - TM_CCORR_NORMED 对 ico 文件更稳定（0.85-0.89 vs TM_CCOEFF_NORMED 较低）
    """
    if method is not None:
        return method

    lower_path = template_path.lower()
    if lower_path.endswith('.ico'):
        return ICO_METHOD
    return DEFAULT_METHOD


# ============ 核心匹配 API ============

def match_template(
    scene: np.ndarray,
    template_path: str,
    threshold: float = DEFAULT_THRESHOLD,
    search_region: Optional[Tuple[int, int, int, int]] = None,
    method: Optional[int] = None,
    max_results: int = 10,
    min_distance: int = 10,
) -> List[TemplateMatch]:
    """图标模板匹配，返回所有匹配位置。

    v5/v6 验证结论：
    - TM_CCOEFF_NORMED 是最佳匹配方法（归一化后对亮度/对比度不敏感）
    - 图标模板不需要多尺度（模板尺寸固定，直接匹配）
    - 搜索区域限定可大幅提升速度（0.01-0.21s）

    Args:
        scene: BGR 格式的场景图
        template_path: 模板路径（支持相对路径如 "搜索栏.png" 或绝对路径）
        threshold: 匹配阈值（默认 0.70，关键场景建议 0.85+）
        search_region: (x1, y1, x2, y2) 搜索区域，None 表示全图
        method: 匹配方法（None 时自动选择：ico 用 TM_CCORR_NORMED，其他用 TM_CCOEFF_NORMED）
        max_results: 最大返回结果数
        min_distance: 非极大值抑制最小距离（像素）

    Returns:
        匹配结果列表（按置信度降序），空列表表示未匹配
    """
    if scene is None or scene.size == 0:
        logger.error("场景图为空")
        return []

    template = _load_template(template_path)
    if template is None:
        return []

    selected_method = _select_method(template_path, method)

    # 裁剪搜索区域
    region_offset = (0, 0)
    if search_region is not None:
        x1, y1, x2, y2 = search_region
        region_offset = (x1, y1)
        search_scene = _crop_search_region(scene, search_region)
    else:
        search_scene = scene

    th, tw = template.shape[:2]
    sh, sw = search_scene.shape[:2]

    if th > sh or tw > sw:
        logger.debug(
            f"模板大于搜索区域: 模板={tw}x{th}, 搜索区域={sw}x{sh}, 模板={template_path}"
        )
        return []

    # 执行模板匹配
    try:
        result = cv2.matchTemplate(search_scene, template, selected_method)
    except cv2.error as e:
        logger.error(f"cv2.matchTemplate 失败: {e}, 模板={template_path}")
        return []

    # 根据 method 解析置信度
    # TM_SQDIFF 和 TM_SQDIFF_NORMED: 越小越好（0=完美匹配）
    # 其他: 越大越好（1=完美匹配）
    is_sqdiff = selected_method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED)

    # 收集所有超过阈值的位置
    matches: List[TemplateMatch] = []

    # 用 max_val / min_val 检查是否有任何匹配
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # 收集候选位置（NMS 前的原始结果）
    if is_sqdiff:
        # SQDIFF: 越小越好，threshold 是上限
        locations = np.where(result <= threshold)
        confidences = 1.0 - result  # 转换为越大越好的置信度
    else:
        # CCOEFF/CCORR: 越大越好
        locations = np.where(result >= threshold)
        confidences = result

    if len(locations[0]) == 0:
        logger.debug(
            f"未找到匹配: 模板={template_path}, 阈值={threshold:.2f}, "
            f"最佳={'%.4f' % (min_val if is_sqdiff else max_val)}"
        )
        return []

    # 构建候选列表
    candidates = []
    for y, x in zip(*locations):
        conf = float(confidences[y, x])
        candidates.append((conf, int(x), int(y)))

    # 按置信度降序排序
    candidates.sort(key=lambda c: c[0], reverse=True)

    # 非极大值抑制（NMS）
    kept: List[Tuple[float, int, int]] = []
    for conf, x, y in candidates:
        # 转换为场景图坐标
        abs_x = x + region_offset[0]
        abs_y = y + region_offset[1]

        # 检查与已选结果的距离
        too_close = False
        for _, kx, ky in kept:
            dx = abs_x - kx
            dy = abs_y - ky
            if dx * dx + dy * dy < min_distance * min_distance:
                too_close = True
                break

        if not too_close:
            kept.append((conf, abs_x, abs_y))
            if len(kept) >= max_results:
                break

    # 构建 TemplateMatch 对象
    for conf, x, y in kept:
        rect = (x, y, x + tw, y + th)
        match = TemplateMatch(
            center_x=x + tw // 2,
            center_y=y + th // 2,
            confidence=conf,
            rect=rect,
            template_size=(tw, th),
            template_path=template_path,
        )
        matches.append(match)

    logger.debug(
        f"模板匹配: {template_path}, 阈值={threshold:.2f}, "
        f"找到 {len(matches)} 个结果, 最佳 conf={matches[0].confidence:.4f}"
    )
    return matches


def match_template_best(
    scene: np.ndarray,
    template_path: str,
    threshold: float = DEFAULT_THRESHOLD,
    search_region: Optional[Tuple[int, int, int, int]] = None,
    method: Optional[int] = None,
) -> Optional[TemplateMatch]:
    """返回最佳匹配（conf 最高的一个）。

    Args:
        scene: BGR 格式的场景图
        template_path: 模板路径
        threshold: 匹配阈值
        search_region: (x1, y1, x2, y2) 搜索区域，None 表示全图
        method: 匹配方法（None 时自动选择）

    Returns:
        最佳匹配，未找到返回 None
    """
    matches = match_template(
        scene, template_path,
        threshold=threshold,
        search_region=search_region,
        method=method,
        max_results=1,
    )
    return matches[0] if matches else None


def match_templates_best(
    scene: np.ndarray,
    template_paths: List[str],
    threshold: float = DEFAULT_THRESHOLD,
    search_region: Optional[Tuple[int, int, int, int]] = None,
    method: Optional[int] = None,
) -> Optional[TemplateMatch]:
    """从多个候选模板中选择最佳匹配（适用于"发送按钮双状态匹配"等场景）。

    Args:
        scene: 场景图
        template_paths: 候选模板路径列表（如 [send_green_full.png, 发送-灰色.png]）
        threshold: 匹配阈值
        search_region: 搜索区域
        method: 匹配方法

    Returns:
        所有候选中置信度最高的匹配，未找到返回 None
    """
    best_match: Optional[TemplateMatch] = None

    for path in template_paths:
        match = match_template_best(
            scene, path,
            threshold=threshold,
            search_region=search_region,
            method=method,
        )
        if match is None:
            continue

        if best_match is None or match.confidence > best_match.confidence:
            best_match = match

    return best_match


# ============ 便捷应用函数 ============

def find_search_bar(scene: np.ndarray,
                    threshold: float = STRICT_THRESHOLD,
                    search_region: Optional[Tuple[int, int, int, int]] = None
                    ) -> Optional[TemplateMatch]:
    """定位搜索栏（v5 验证 conf=1.0000）。

    Args:
        scene: 场景图
        threshold: 阈值（默认 0.85，关键场景）
        search_region: 搜索区域（默认搜索左上 30% x 15% 区域）

    Returns:
        匹配结果，未找到返回 None
    """
    if search_region is None:
        h, w = scene.shape[:2]
        search_region = (0, 0, int(w * 0.30), int(h * 0.15))

    return match_template_best(
        scene, "搜索栏.png",
        threshold=threshold,
        search_region=search_region,
    )


def find_send_button(scene: np.ndarray,
                     threshold: float = STRICT_THRESHOLD,
                     search_region: Optional[Tuple[int, int, int, int]] = None
                     ) -> Optional[TemplateMatch]:
    """定位发送按钮（v6 验证 conf=1.0000，双状态匹配）。

    优先匹配"可发送态"（绿色按钮），失败时匹配"不可发送态"（灰色按钮）。

    Args:
        scene: 场景图
        threshold: 阈值（默认 0.85）
        search_region: 搜索区域（默认搜索右下 50% x 40% 区域）

    Returns:
        匹配结果，未找到返回 None
    """
    if search_region is None:
        h, w = scene.shape[:2]
        search_region = (int(w * 0.50), int(h * 0.60), w, h)

    # 优先匹配可发送态（绿色按钮）
    # 同时尝试 full 和 compact 两个版本
    match = match_templates_best(
        scene,
        ["send_green_full.png", "send_green_compact.png"],
        threshold=threshold,
        search_region=search_region,
    )
    if match is not None:
        return match

    # 失败时匹配不可发送态（灰色按钮）
    return match_template_best(
        scene, "发送-灰色.png",
        threshold=threshold,
        search_region=search_region,
    )


def find_section_header(scene: np.ndarray,
                        header_name: str,
                        threshold: float = STRICT_THRESHOLD,
                        search_region: Optional[Tuple[int, int, int, int]] = None
                        ) -> Optional[TemplateMatch]:
    """定位候选框标题栏（v5 验证 conf=1.0000）。

    Args:
        scene: 场景图
        header_name: 标题栏名称（如 "最常使用", "群聊", "联系人"）
        threshold: 阈值
        search_region: 搜索区域（默认中间栏区域）

    Returns:
        匹配结果，未找到返回 None
    """
    if search_region is None:
        h, w = scene.shape[:2]
        # 中间栏区域（导航栏右边界之后，会话列表右边界之前）
        # 保守估计：x=80-450, y=0-h/2
        search_region = (80, 0, min(450, int(w * 0.5)), h)

    template_path = f"{header_name}.png"
    return match_template_best(
        scene, template_path,
        threshold=threshold,
        search_region=search_region,
    )


def find_chat_icon(scene: np.ndarray,
                   active: bool = True,
                   threshold: float = STRICT_THRESHOLD,
                   search_region: Optional[Tuple[int, int, int, int]] = None
                   ) -> Optional[TemplateMatch]:
    """定位导航栏"对话"图标（v5 验证 conf=1.0000）。

    用于验证微信主窗口布局（导航栏在左侧）。

    Args:
        scene: 场景图
        active: True=激活态（当前在聊天界面），False=未激活态
        threshold: 阈值
        search_region: 搜索区域（默认左侧导航栏 x=0-80）

    Returns:
        匹配结果，未找到返回 None
    """
    if search_region is None:
        h, w = scene.shape[:2]
        search_region = (0, 0, 80, h)

    template = "对话-已激活.png" if active else "对话-未激活.png"
    return match_template_best(
        scene, template,
        threshold=threshold,
        search_region=search_region,
    )


def verify_wechat_main_window(scene: np.ndarray,
                               threshold: float = STRICT_THRESHOLD
                               ) -> bool:
    """验证当前是否为微信主窗口（通过搜索栏或对话图标）。

    任何一个匹配成功即认为主窗口存在。

    Args:
        scene: 场景图
        threshold: 阈值

    Returns:
        是否检测到微信主窗口
    """
    # 尝试搜索栏
    search_bar = find_search_bar(scene, threshold=threshold)
    if search_bar is not None:
        logger.debug(f"检测到搜索栏: conf={search_bar.confidence:.4f}")
        return True

    # 尝试对话图标
    chat_icon = find_chat_icon(scene, active=True, threshold=threshold)
    if chat_icon is not None:
        logger.debug(f"检测到对话图标: conf={chat_icon.confidence:.4f}")
        return True

    return False


# ============ 模块自检 ============

def _self_test():
    """模块自检：验证所有核心模板能正常加载。"""
    print("=" * 60)
    print("  template_matcher.py 自检")
    print("=" * 60)

    templates_to_check = [
        "搜索栏.png",
        "send_green_full.png",
        "send_green_compact.png",
        "发送-灰色.png",
        "最常使用.png",
        "群聊.png",
        "对话-已激活.png",
        "对话-未激活.png",
        "联系人.png",
        "表情按钮.png",
        "表情搜索键.png",
        '表情搜索后的“全部表情”.png',
    ]

    ico_files = ["1.ico", "2.ico", "3.ico", "4.ico", "5.ico", "6.ico"]

    print("\n[1] 核心模板加载测试:")
    loaded = 0
    for name in templates_to_check:
        path = os.path.join(TEMPLATE_DIR, name)
        if not os.path.exists(path):
            print(f"  ❌ 不存在: {name}")
            continue
        tpl = _load_template(name)
        if tpl is None:
            print(f"  ❌ 加载失败: {name}")
        else:
            h, w = tpl.shape[:2]
            print(f"  ✅ {name}: {w}x{h}")
            loaded += 1

    print(f"\n  加载成功: {loaded}/{len(templates_to_check)}")

    print("\n[2] ico 文件加载测试:")
    ico_loaded = 0
    for name in ico_files:
        path = os.path.join(TEMPLATE_DIR, name)
        if not os.path.exists(path):
            print(f"  ❌ 不存在: {name}")
            continue
        tpl = _load_template(name)
        if tpl is None:
            print(f"  ❌ 加载失败: {name}")
        else:
            h, w = tpl.shape[:2]
            print(f"  ✅ {name}: {w}x{h}")
            ico_loaded += 1

    print(f"\n  ico 加载成功: {ico_loaded}/{len(ico_files)}")

    print("\n[3] 方法选择测试:")
    for name in ["搜索栏.png", "1.ico"]:
        method = _select_method(name)
        method_name = {
            cv2.TM_CCOEFF_NORMED: "TM_CCOEFF_NORMED",
            cv2.TM_CCORR_NORMED: "TM_CCORR_NORMED",
        }.get(method, str(method))
        print(f"  {name}: {method_name}")

    print("\n[4] TEMPLATE_DIR:")
    print(f"  {TEMPLATE_DIR}")
    print(f"  存在: {os.path.exists(TEMPLATE_DIR)}")

    print("\n" + "=" * 60)
    print("  自检完成")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
