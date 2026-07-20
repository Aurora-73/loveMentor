"""微信自动化发消息模块的配置参数。

所有硬编码阈值集中在此文件，方便调优和维护。
"""

# ── 微信进程和窗口 ────────────────────────────────────────────

# 微信可执行文件路径
WEIXIN_EXE = r"D:\Weixin\Weixin.exe"

# 微信窗口最小尺寸（小于此尺寸视为托盘图标等小窗口，排除）
WECHAT_MIN_WIDTH = 500
WECHAT_MIN_HEIGHT = 400


# ── 搜索栏定位 ────────────────────────────────────────────────

# OCR 匹配"搜索"文字的最大长度（避免匹配到"搜索聊天记录"等长文字）
SEARCH_TEXT_MAX_LENGTH = 4

# 搜索栏位置合理性验证范围（窗口比例）
SEARCH_X_MAX_RATIO = 0.3   # x 应在窗口左侧 30% 以内
SEARCH_Y_MAX_RATIO = 0.15  # y 应在窗口顶部 15% 以内

# 固定比例回退的搜索栏位置（布局检测失败时用）
SEARCH_FALLBACK_X_RATIO = 0.075
SEARCH_FALLBACK_Y_RATIO = 0.05


# ── 头像模板匹配 ──────────────────────────────────────────────

# 模板匹配阈值（低于此值视为不匹配）
MATCH_THRESHOLD = 0.7

# 多尺度匹配的模板尺寸列表（像素）
TEMPLATE_SCALES = (20, 30, 40, 45, 50, 60, 70, 80)

# 非极大值抑制最小距离
NMS_MIN_DIST = 20

# 匹配点选择的最低置信度（低于此值回退到选最近）
MIN_CONFIDENCE_FOR_SELECTION = 0.7

# 模板有效性警告阈值（低于此值提示模板可能过期）
TEMPLATE_WARNING_THRESHOLD = 0.75

# 综合评分权重
CONFIDENCE_WEIGHT = 0.6
POSITION_WEIGHT = 0.4

# 在搜索框下方的加分
BELOW_SEARCH_BOX_BONUS = 0.2


# ── 绿色环验证 ────────────────────────────────────────────────

# 绿色环 BGR 颜色值
GREEN_RING_BGR = (112, 172, 21)

# 绿色环颜色容差
GREEN_RING_TOLERANCE = 30

# 绿色像素占比阈值（达到此值视为绿色环存在）
GREEN_RING_MIN_RATIO = 0.4

# 霍夫圆检测参数
HOUGH_CIRCLE_DP = 1
HOUGH_CIRCLE_PARAM1 = 50
HOUGH_CIRCLE_PARAM2 = 15
HOUGH_CIRCLE_CENTER_DIST_RATIO = 0.3  # 圆心距头像中心的最大距离比例


# ── 发送按钮 ──────────────────────────────────────────────────

# OCR 匹配"发送"文字的最大长度
SEND_TEXT_MAX_LENGTH = 4

# 微信发送按钮颜色（用户澄清：RGB(0, 195, 117) = BGR(117, 195, 0)）
SEND_BTN_BGR = (117, 195, 0)  # 用 tuple 避免 uint8 溢出

# 发送按钮颜色容差
SEND_BTN_TOLERANCE = 30

# 输入框位置：距底部 80px（输入框中心的大概位置）
INPUT_BOX_OFFSET_FROM_BOTTOM = 80


# ── 消息发送 ──────────────────────────────────────────────────

# 超长消息分段长度（超过此值分段发送）
MAX_MSG_LENGTH = 500


# ── 截图清理 ──────────────────────────────────────────────────

# outputs/ 目录保留的最大文件数
MAX_OUTPUT_FILES = 50

# screenshots/ 目录保留的最大文件数
MAX_SCREENSHOT_FILES = 30


# ── 重试和时序 ────────────────────────────────────────────────

# 最大尝试次数
MAX_ATTEMPTS = 4

# 各步骤等待时间（秒）
WAIT_AFTER_FOREGROUND = 0.3
WAIT_AFTER_CLICK_FOCUS = 0.3
WAIT_AFTER_CTRL_F = 0.8
WAIT_AFTER_INPUT = 1.0
WAIT_AFTER_SEND_CLICK = 1.0
WAIT_AFTER_MESSAGE_INPUT = 0.8
WAIT_RENDER_AFTER_RESTORE = 1.5
WAIT_ESC_BETWEEN = 0.1
WAIT_AFTER_ESC_CLEANUP = 0.3
