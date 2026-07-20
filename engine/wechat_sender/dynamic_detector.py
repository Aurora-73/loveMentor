"""
基于方差和饱和度的微信界面布局动态检测算法。
在 screenshots/raw_screenshot.png 上标出边界，保存结果供用户审核。
"""
import cv2
import numpy as np


from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

class WeChatLayoutDetector:
    def __init__(self):
        self.nav_bar_right = 0
        self.session_list_right = 0

    def detect(self, image, debug: bool = False, output_path: str = None):
        """检测微信界面布局（导航栏/会话列表/聊天区域边界）。

        Args:
            image: BGR 图像（numpy 数组）
            debug: True 则保存标注图（默认 False，避免文件写入副作用）
            output_path: 自定义标注图保存路径（仅 debug=True 时生效），
                         默认 "screenshots/layout_analysis.png"
        Returns:
            tuple (nav_right, session_right)
        """
        h, w = image.shape[:2]
        logger.info(f"图片尺寸: {w}x{h}")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # 计算每列的统计信息
        column_variance = np.array([np.var(gray[:, x]) for x in range(w)])
        column_saturation = np.array([np.mean(hsv[:, x, 1]) for x in range(w)])
        column_brightness = np.array([np.mean(gray[:, x]) for x in range(w)])

        # 检测导航栏右边界：方差突增 + 饱和度升高
        nav_right = self._find_nav_boundary(column_variance, column_saturation, w)

        # 检测会话列表右边界：饱和度降零 + 亮度升高
        session_right = self._find_session_boundary(column_saturation, column_brightness, w, nav_right)

        self.nav_bar_right = nav_right
        self.session_list_right = session_right

        logger.info(f"\n检测结果:")
        logger.info(f"  导航栏右边界: {nav_right}px")
        logger.info(f"  会话列表右边界: {session_right}px")
        logger.info(f"  导航栏: 0-{nav_right} ({nav_right}px)")
        logger.info(f"  会话列表: {nav_right}-{session_right} ({session_right-nav_right}px)")
        logger.info(f"  聊天区域: {session_right}-{w} ({w-session_right}px)")

        # 标注边界（仅在 debug 模式下保存，避免生产环境的文件写入副作用）
        if debug:
            debug_image = image.copy()
            cv2.line(debug_image, (nav_right, 0), (nav_right, h), (0, 255, 0), 3)
            cv2.line(debug_image, (session_right, 0), (session_right, h), (0, 0, 255), 3)

            cv2.putText(debug_image, f"Nav: {nav_right}px", (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            cv2.putText(debug_image, f"Session: {session_right}px", (10, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

            save_path = output_path or "screenshots/layout_analysis.png"
            cv2.imwrite(save_path, debug_image)
            logger.info(f"\n标注图已保存: {save_path}")

        return nav_right, session_right

    def _find_nav_boundary(self, variance, saturation, w):
        """检测导航栏右边界：方差突增 + 饱和度升高"""
        search_start = 20
        search_end = min(200, w // 4)

        # 使用滑动窗口平滑
        window = 5

        for x in range(search_start, search_end - window):
            left_var = np.mean(variance[max(0, x-window):x])
            right_var = np.mean(variance[x:x+window])
            left_sat = np.mean(saturation[max(0, x-window):x])
            right_sat = np.mean(saturation[x:x+window])

            # 条件1：方差突增（从低到高，倍数>5）
            var_jump = (left_var < 100 and right_var > 300 and right_var > left_var * 3)

            # 条件2：饱和度升高（从0到>10）
            sat_increase = (left_sat < 5 and right_sat > 10)

            if var_jump and sat_increase:
                logger.info(f"  导航栏边界检测: x={x}, 方差 {left_var:.0f}→{right_var:.0f}, 饱和度 {left_sat:.1f}→{right_sat:.1f}")
                return x

        # 回退：找方差变化最大的位置
        best_x = 76
        best_ratio = 0
        for x in range(search_start, search_end - window):
            left_var = np.mean(variance[max(0, x-window):x])
            right_var = np.mean(variance[x:x+window])
            if left_var > 5:
                ratio = right_var / left_var
                if ratio > best_ratio and right_var > 200:
                    best_ratio = ratio
                    best_x = x

        logger.info(f"  导航栏边界检测(回退): x={best_x}, 方差比={best_ratio:.1f}")
        return best_x

    def _find_session_boundary(self, saturation, brightness, w, nav_right):
        """检测会话列表右边界：饱和度降零 + 亮度升高"""
        search_start = nav_right + 100
        search_end = min(int(w * 0.5), nav_right + 500)

        window = 5

        for x in range(search_start, search_end - window):
            left_sat = np.mean(saturation[max(0, x-window):x])
            right_sat = np.mean(saturation[x:x+window])
            left_brt = np.mean(brightness[max(0, x-window):x])
            right_brt = np.mean(brightness[x:x+window])

            # 条件1：饱和度从高降到低
            sat_drop = (left_sat > 10 and right_sat < 5)

            # 条件2：亮度升高
            brt_increase = (right_brt > left_brt + 10)

            if sat_drop and brt_increase:
                logger.info(f"  会话列表边界检测: x={x}, 饱和度 {left_sat:.1f}→{right_sat:.1f}, 亮度 {left_brt:.1f}→{right_brt:.1f}")
                return x

        # 回退：找饱和度下降最大的位置
        best_x = nav_right + 260
        best_drop = 0
        for x in range(search_start, search_end - window):
            left_sat = np.mean(saturation[max(0, x-window):x])
            right_sat = np.mean(saturation[x:x+window])
            drop = left_sat - right_sat
            if drop > best_drop and left_sat > 10:
                best_drop = drop
                best_x = x

        logger.info(f"  会话列表边界检测(回退): x={best_x}, 饱和度下降={best_drop:.1f}")
        return best_x


def main():
    logger.info("=" * 60)
    logger.info("  微信界面布局动态检测（方差+饱和度算法）")
    logger.info("=" * 60)

    image_path = "screenshots/raw_screenshot.png"
    image = cv2.imread(image_path)
    if image is None:
        logger.error(f"❌ 无法读取图片: {image_path}")
        return

    detector = WeChatLayoutDetector()
    detector.detect(image, debug=True)

    logger.info("\n✅ 完成，请查看 screenshots/layout_analysis.png")


if __name__ == "__main__":
    main()
