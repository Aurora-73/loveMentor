# -*- coding: utf-8 -*-
"""
微信 UI 文字字体匹配模块（FontMatcher）。

采用三层架构，按需匹配，兼顾精度与速度：

1. 核心词库（约 50 个词）：快速定位/验证核心 UI 元素
2. 单字库（约 300-400 个字）：OCR 失败时的字符级回退
3. 完整词库（1245 个词）：特定场景下的精确匹配

典型工作流：
    matcher = FontMatcher()
    # 方式一：直接匹配某个词
    match = matcher.match_text(scene, "搜索", search_region=(0,0,400,100))
    # 方式二：用核心词库扫描
    matches = matcher.match_core_words(scene, search_region=region)
    # 方式三：OCR 回退（对 OCR 失败的字符做单字匹配）
    match = matcher.match_char(scene, "茶", search_region=region)
"""
import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

try:
    from logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ============ 默认配置 ============

DEFAULT_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"  # 微软雅黑
DEFAULT_FONT_PATH_BOLD = "C:/Windows/Fonts/msyhbd.ttc"  # 微软雅黑 Bold
DEFAULT_FONT_SIZES = [12, 13, 14, 15, 16, 18, 20, 22, 24, 28, 32, 36, 40]
DEFAULT_THRESHOLD = 0.7

# 完整词库默认路径
DEFAULT_CORPUS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "wechat_ui_corpus", "merged_wechat_ui_corpus.txt"
)

# 第一层：核心词库（高频微信 UI 文字，用于快速定位/验证）
CORE_WORDS = [
    # 导航/侧边栏
    '聊天', '联系人', '朋友圈', '通讯录', '发现', '我', '微信',
    '文件传输助手', '视频号', '小程序', '服务号', '公众号',
    # 搜索
    '搜索', '搜索聊天记录', '搜索联系人',
    # 会话
    '群聊', '群成员', '群公告', '群昵称',
    # 联系人字段
    '微信号', '昵称', '备注', '签名', '个性签名', '地区', '性别',
    '来源', '添加时间', '共同群聊', '头像',
    # 操作按钮
    '发送', '关闭', '确认', '取消', '确定', '保存', '删除', '添加',
    '编辑', '刷新', '返回', '完成', '继续', '停止', '播放',
    '展开', '收起', '更多', '详情', '全选', '多选',
    # 状态
    '加载中', '加载中...', '暂无消息', '暂无会话', '暂无联系人',
    # 窗口控制
    '最小化', '最大化', '关闭', '退出',
    # 消息类型
    '图片', '表情', '视频', '语音', '文件', '链接', '音乐', '通话',
    '引用', '回复', '位置', '撤回消息', '拍一拍',
    # 验证
    '好友验证', '验证消息',
    # 微信功能
    '微信支付', '微信红包', '微信转账', '扫一扫',
    # 时间
    '今天', '昨天', '刚刚',
    # 企业
    '企业微信', '私聊',
]


class FontMatcher:
    """微信 UI 文字字体匹配器。

    三层架构：
    - core_words: 核心词库（内置约 80 个高频词）
    - char_set: 单字库（从完整词库拆分去重）
    - full_corpus: 完整词库（从文件加载）
    """

    def __init__(self,
                 font_path: str = DEFAULT_FONT_PATH,
                 font_path_bold: str = DEFAULT_FONT_PATH_BOLD,
                 font_sizes: List[int] = None,
                 corpus_path: str = None,
                 core_words: List[str] = None):
        """
        Args:
            font_path: 微软雅黑字体文件路径
            font_path_bold: 微软雅黑 Bold 字体文件路径
            font_sizes: 尝试的字号列表
            corpus_path: 完整词库文件路径（每行一个词）
            core_words: 自定义核心词库（默认使用内置 CORE_WORDS）
        """
        self.font_path = font_path
        self.font_path_bold = font_path_bold
        self.font_sizes = font_sizes or DEFAULT_FONT_SIZES
        self.core_words = core_words if core_words is not None else list(CORE_WORDS)

        # 加载完整词库
        self.full_corpus: List[str] = []
        if corpus_path is None:
            corpus_path = DEFAULT_CORPUS_PATH
        self._load_corpus(corpus_path)

        # 从完整词库拆分单字（去重）
        self.char_set: List[str] = []
        self._build_char_set()

        # 模板缓存（避免重复渲染）
        # cache_key: (text, font_size, color, bg_color, font_index, font_path)
        self._template_cache: Dict[tuple, np.ndarray] = {}

        logger.info(
            f"FontMatcher 初始化: 核心词库 {len(self.core_words)} 个, "
            f"单字库 {len(self.char_set)} 个, 完整词库 {len(self.full_corpus)} 个"
        )

    def _load_corpus(self, corpus_path: str):
        """加载完整词库文件"""
        if not corpus_path or not os.path.exists(corpus_path):
            logger.warning(f"完整词库文件不存在: {corpus_path}")
            return
        with open(corpus_path, encoding='utf-8') as f:
            for line in f:
                word = line.strip()
                if word and word not in self.full_corpus:
                    self.full_corpus.append(word)
        logger.info(f"加载完整词库: {len(self.full_corpus)} 个词 ({corpus_path})")

    def _build_char_set(self):
        """从完整词库 + 核心词库拆分单字（去重）"""
        char_set = set()
        for word in self.full_corpus + self.core_words:
            for char in word:
                # 只保留中文字符（基本区 + 扩展A区）
                if ('\u4e00' <= char <= '\u9fff') or ('\u3400' <= char <= '\u4dbf'):
                    char_set.add(char)
        self.char_set = sorted(char_set)

    # ============ 模板渲染 ============

    def render_text_template(self,
                             text: str,
                             font_size: int = 14,
                             color: Tuple[int, int, int] = (0, 0, 0),
                             bg_color: Tuple[int, int, int] = None,
                             font_index: int = 0,
                             use_bold: bool = False) -> np.ndarray:
        """用微软雅黑渲染文字为 BGR 模板（带缓存）。

        Args:
            text: 要渲染的文字
            font_size: 字号
            color: 文字颜色（RGB）
            bg_color: 背景颜色（RGB），None 则根据 color 自动选择对比色
            font_index: ttc 字体索引（0=YaHei, 1=YaHei UI）
            use_bold: 是否使用 Bold 字体

        Returns:
            BGR 图像（numpy 数组）
        """
        # 自动选择对比背景色：避免 color == bg_color 导致纯色模板
        # （纯色模板会让 TM_CCOEFF_NORMED 返回虚假的 1.0）
        if bg_color is None:
            bg_color = self._auto_bg_color(color)

        font_path = self.font_path_bold if use_bold else self.font_path
        cache_key = (text, font_size, color, bg_color, font_index, font_path)
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        try:
            font = ImageFont.truetype(font_path, font_size, index=font_index)
        except Exception:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except Exception as e:
                logger.error(f"字体加载失败: {font_path} - {e}")
                # 返回空白模板
                return np.zeros((font_size + 6, font_size * len(text) + 6, 3), dtype=np.uint8)

        # 估算文字大小
        bbox = font.getbbox(text)
        w = bbox[2] - bbox[0] + 6
        h = bbox[3] - bbox[1] + 6

        # 渲染
        img = Image.new('RGB', (w, h), bg_color)
        draw = ImageDraw.Draw(img)
        draw.text((3 - bbox[0], 3 - bbox[1]), text, font=font, fill=color)

        # RGB → BGR（OpenCV 格式）
        template = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        self._template_cache[cache_key] = template
        return template

    @staticmethod
    def _auto_bg_color(color: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """根据文字颜色自动选择对比背景色。

        避免文字色与背景色相同导致纯色模板（TM_CCOEFF_NORMED 会对纯色模板返回 1.0）。
        浅色文字 → 深色背景；深色文字 → 浅色背景。
        """
        r, g, b = color
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness >= 128:
            # 浅色文字（如白色）→ 深色背景
            return (30, 30, 30)
        else:
            # 深色文字（如黑色）→ 浅色背景
            return (255, 255, 255)

    # ============ 匹配核心 ============

    def match_text(self,
                   scene: np.ndarray,
                   text: str,
                   search_region: Optional[Tuple[int, int, int, int]] = None,
                   threshold: float = DEFAULT_THRESHOLD,
                   color: Tuple[int, int, int] = (0, 0, 0),
                   font_index: int = 0,
                   font_sizes: Optional[List[int]] = None,
                   use_bold: bool = False,
                   return_all: bool = False) -> Optional[Dict]:
        """在场景图中查找指定文字（多字号尝试）。

        Args:
            scene: BGR 图像
            text: 要查找的文字
            search_region: (x1, y1, x2, y2) 搜索区域
            threshold: 匹配阈值
            color: 文字颜色（RGB）
            font_index: 0=YaHei, 1=YaHei UI
            font_sizes: 尝试的字号列表（默认用 self.font_sizes）
            use_bold: 是否使用 Bold 字体
            return_all: 是否返回所有字号的结果（调试用）

        Returns:
            dict: {text, center, confidence, font_size, bbox} 或 None
        """
        if font_sizes is None:
            font_sizes = self.font_sizes

        if search_region is not None:
            x1, y1, x2, y2 = search_region
            # 边界保护
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(scene.shape[1], x2)
            y2 = min(scene.shape[0], y2)
            if x2 <= x1 or y2 <= y1:
                return None
            scene_crop = scene[y1:y2, x1:x2].copy()
            offset_x, offset_y = x1, y1
        else:
            scene_crop = scene
            offset_x, offset_y = 0, 0

        # 方差检查：纯色区域（如标题栏空白处）会产生虚假高置信度
        # TM_CCOEFF_NORMED 在均匀颜色区域会返回接近 1.0 的值
        gray_crop = cv2.cvtColor(scene_crop, cv2.COLOR_BGR2GRAY)
        region_var = float(np.var(gray_crop))
        if region_var < 10.0:  # 方差太低，说明是纯色区域，没有文字
            return None

        best_match = None
        best_score = 0
        all_scores = []

        for size in font_sizes:
            template = self.render_text_template(
                text, size, color=color, font_index=font_index, use_bold=use_bold
            )
            th, tw = template.shape[:2]

            # 模板不能大于场景
            if th > scene_crop.shape[0] or tw > scene_crop.shape[1]:
                continue

            # 模板方差检查（安全网）：纯色模板会让 TM_CCOEFF_NORMED 返回虚假的 1.0
            # 正常情况下 _auto_bg_color 已避免此问题，这里作为兜底
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            template_var = float(np.var(template_gray))
            if template_var < 10.0:
                continue

            result = cv2.matchTemplate(scene_crop, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            all_scores.append((size, float(max_val)))

            # 局部方差检查：匹配位置必须是"有内容"的区域
            # 防止匹配到纯色背景（TM_CCOEFF_NORMED 在纯色区域会产生虚假高置信度）
            match_region = scene_crop[max_loc[1]:max_loc[1]+th, max_loc[0]:max_loc[0]+tw]
            if match_region.size > 0:
                match_gray = cv2.cvtColor(match_region, cv2.COLOR_BGR2GRAY)
                local_var = float(np.var(match_gray))
                if local_var < 10.0:  # 匹配位置是纯色区域，跳过
                    continue

            if max_val > best_score:
                best_score = max_val
                best_match = {
                    'text': text,
                    'center': (int(max_loc[0] + tw // 2 + offset_x),
                              int(max_loc[1] + th // 2 + offset_y)),
                    'confidence': float(max_val),
                    'font_size': size,
                    'bbox': (int(max_loc[0] + offset_x),
                            int(max_loc[1] + offset_y),
                            int(max_loc[0] + tw + offset_x),
                            int(max_loc[1] + th + offset_y)),
                }

        if return_all:
            if best_match:
                best_match['all_scores'] = sorted(all_scores, key=lambda x: -x[1])
            return best_match

        return best_match if best_score >= threshold else None

    def match_text_multi_color(self,
                               scene: np.ndarray,
                               text: str,
                               search_region=None,
                               threshold=DEFAULT_THRESHOLD,
                               colors=None,
                               **kwargs) -> Optional[Dict]:
        """多颜色变体匹配（自动尝试黑色、深灰、白色等）。

        Args:
            colors: 颜色列表 [(R,G,B), ...]，默认尝试常见颜色
        """
        if colors is None:
            colors = [
                (0, 0, 0),       # 黑色（常规文字）
                (51, 51, 51),    # 深灰
                (96, 96, 96),    # 中灰
                (128, 128, 128), # 灰色（搜索栏占位符）
                (255, 255, 255), # 白色（绿色/深色背景上的文字）
            ]

        best_match = None
        for color in colors:
            match = self.match_text(
                scene, text,
                search_region=search_region,
                threshold=threshold,
                color=color,
                **kwargs
            )
            if match and (best_match is None or match['confidence'] > best_match['confidence']):
                best_match = match
                best_match['color'] = color

        return best_match

    # ============ 三层匹配接口 ============

    def match_core_words(self,
                         scene: np.ndarray,
                         search_region=None,
                         threshold=DEFAULT_THRESHOLD,
                         color=(0, 0, 0),
                         multi_color=False) -> List[Dict]:
        """第一层：用核心词库匹配。

        Args:
            multi_color: 是否尝试多颜色变体

        Returns:
            list[dict]: 所有匹配到的核心词
        """
        results = []
        for word in self.core_words:
            if multi_color:
                match = self.match_text_multi_color(
                    scene, word,
                    search_region=search_region,
                    threshold=threshold,
                )
            else:
                match = self.match_text(
                    scene, word,
                    search_region=search_region,
                    threshold=threshold,
                    color=color,
                )
            if match:
                results.append(match)
        return results

    def match_char(self,
                   scene: np.ndarray,
                   char: str,
                   search_region=None,
                   threshold=DEFAULT_THRESHOLD,
                   multi_color=True) -> Optional[Dict]:
        """第二层：用单字库匹配（OCR 回退）。

        Args:
            char: 单个中文字符
            multi_color: 是否尝试多颜色变体

        Returns:
            dict 或 None
        """
        if len(char) != 1:
            raise ValueError(f"match_char 只接受单字符, 收到: {char}")
        if multi_color:
            return self.match_text_multi_color(
                scene, char,
                search_region=search_region,
                threshold=threshold,
            )
        return self.match_text(
            scene, char,
            search_region=search_region,
            threshold=threshold,
        )

    def match_full_corpus(self,
                          scene: np.ndarray,
                          search_region=None,
                          threshold=DEFAULT_THRESHOLD,
                          color=(0, 0, 0),
                          filter_func: Optional[Callable[[str], bool]] = None,
                          multi_color=False) -> List[Dict]:
        """第三层：用完整词库匹配。

        Args:
            filter_func: 过滤函数，决定哪些词需要匹配（用于场景过滤）
            multi_color: 是否尝试多颜色变体

        Returns:
            list[dict]: 所有匹配到的词
        """
        results = []
        for word in self.full_corpus:
            if filter_func and not filter_func(word):
                continue
            if multi_color:
                match = self.match_text_multi_color(
                    scene, word,
                    search_region=search_region,
                    threshold=threshold,
                )
            else:
                match = self.match_text(
                    scene, word,
                    search_region=search_region,
                    threshold=threshold,
                    color=color,
                )
            if match:
                results.append(match)
        return results

    # ============ 场景化匹配 ============

    def find_in_chat_header(self, scene: np.ndarray, text: str,
                            threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """在聊天标题区域查找文字（顶部偏左）。"""
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, text,
            search_region=(int(w * 0.2), 20, int(w * 0.7), 100),
            threshold=threshold,
        )

    def find_in_search_bar(self, scene: np.ndarray, text: str = '搜索',
                           threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """在搜索栏区域查找文字（左上角）。"""
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, text,
            search_region=(0, 0, min(400, int(w * 0.3)), 100),
            threshold=threshold,
        )

    def find_in_nav_rail(self, scene: np.ndarray, text: str,
                         threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """在左侧导航栏区域查找文字。"""
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, text,
            search_region=(0, 0, 80, h),
            threshold=threshold,
        )

    def find_in_session_list(self, scene: np.ndarray, text: str,
                             threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """在会话列表区域查找文字。"""
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, text,
            search_region=(80, 0, min(320, int(w * 0.3)), h),
            threshold=threshold,
        )

    def find_in_chat_area(self, scene: np.ndarray, text: str,
                          threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """在聊天区域查找文字（右侧主体区域）。"""
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, text,
            search_region=(min(320, int(w * 0.3)), 0, w, h),
            threshold=threshold,
        )

    # ============ 工具方法 ============

    def verify_ui_state(self, scene: np.ndarray,
                        expected_words: List[str],
                        threshold=DEFAULT_THRESHOLD) -> Dict[str, bool]:
        """验证 UI 状态：检查一组预期文字是否存在于场景中。

        Args:
            expected_words: 预期出现的文字列表

        Returns:
            dict: {word: bool} 每个词是否被找到
        """
        result = {}
        for word in expected_words:
            match = self.match_text_multi_color(scene, word, threshold=threshold)
            result[word] = match is not None
        return result

    def find_send_button(self, scene: np.ndarray,
                         threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """查找"发送"按钮（右下角，白色文字在绿色背景上）。

        使用 multi_color 自动尝试多种颜色变体，避免硬编码颜色与实际不符。
        """
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, '发送',
            search_region=(int(w * 0.7), int(h * 0.7), w, h),
            threshold=threshold,
            colors=[
                (255, 255, 255),  # 白色（绿色背景上的发送按钮）
                (0, 0, 0),        # 黑色（浅色背景上的发送按钮）
                (51, 51, 51),     # 深灰
            ],
        )

    def find_search_bar(self, scene: np.ndarray,
                        threshold=DEFAULT_THRESHOLD) -> Optional[Dict]:
        """查找搜索栏（左上角，灰色文字）。

        使用 multi_color 自动尝试多种灰色变体。
        """
        h, w = scene.shape[:2]
        return self.match_text_multi_color(
            scene, '搜索',
            search_region=(0, 0, min(400, int(w * 0.3)), 100),
            threshold=threshold,
            colors=[
                (128, 128, 128),  # 灰色（搜索栏占位符）
                (96, 96, 96),     # 中灰
                (153, 153, 153),  # 浅灰
                (0, 0, 0),        # 黑色
            ],
        )


# imread_unicode 已抽取到 image_utils.py（公共模块）
# 避免与 template_matcher.py 重复实现


def draw_match_result(scene: np.ndarray, match: Dict,
                      output_path: Optional[str] = None) -> np.ndarray:
    """在场景图上绘制匹配结果。"""
    if match is None:
        return scene
    x1, y1, x2, y2 = match['bbox']
    cv2.rectangle(scene, (x1, y1), (x2, y2), (0, 255, 0), 2)
    label = f"{match['text']} {match['confidence']:.3f} ({match['font_size']}px)"
    cv2.putText(scene, label, (x1, y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    if output_path:
        cv2.imwrite(output_path, scene)
    return scene


# ============ 模块级单例 ============
# FontMatcher 初始化会加载 1245 词库 + 拆分单字库，是重量级操作。
# 通过单例避免重复加载，节省 1-3 秒/次。
_singleton_matcher: Optional["FontMatcher"] = None


def get_font_matcher() -> "FontMatcher":
    """获取 FontMatcher 模块级单例（线程不安全，适用于单线程 E2E 流程）。

    首次调用会初始化并加载字库，后续调用直接返回缓存实例。
    """
    global _singleton_matcher
    if _singleton_matcher is None:
        _singleton_matcher = FontMatcher()
    return _singleton_matcher


def reset_font_matcher() -> None:
    """重置单例（仅用于测试或字库变更场景）。"""
    global _singleton_matcher
    _singleton_matcher = None
