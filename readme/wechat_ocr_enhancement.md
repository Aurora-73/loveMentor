# 微信 OCR 增强方案（实现说明）

> **状态**：已实现（2026-07-23）— 图标模板匹配 + 字体匹配 + OCR 验证均已落地
> **关联**：[微信自动化流程](wechat_auto_flow.md) | [v4 自动回复架构](auto_reply_architecture.md)

---

## 一、方案概述

微信自动化发送消息时，需要精确定位 UI 元素（搜索栏、发送按钮、聊天标题等）。原方案依赖固定比例和绿色按钮检测，准确度不足。v3 方案采用**多层识别机制**，按优先级依次尝试：

1. **图标模板匹配**（首选）— 预制作图标模板，cv2.matchTemplate 匹配
2. **字体匹配**（display_name 专用）— 渲染指定字体与截图匹配
3. **OCR 验证**（兜底）— PaddleOCR/RapidOCR 识别未知文字
4. **几何约束**（辅助）— 布局检测和区域定位

---

## 二、图标模板匹配

### 原理

使用 OpenCV `cv2.matchTemplate` + `TM_CCOEFF_NORMED` 方法，在指定搜索区域中匹配预制作的图标模板。

### 模板资源

模板存放在 `engine/wechat_sender/wx_icon/` 目录：
- 搜索栏图标、发送按钮图标（绿色/灰色两种状态）
- 微信导航栏图标（16x16 ~ 64x64 不同尺寸）
- `send_green_full.png` (100x60) 和 `send_green_compact.png` (60x30) — 发送按钮绿色状态

### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 匹配方法 | `TM_CCOEFF_NORMED` | 归一化相关系数 |
| 置信度阈值 | 0.70+ | 低于此值视为未匹配 |
| 多尺度 | scales=20-80px | 支持不同 DPI 缩放 |
| NMS 去重 | 是 | 避免重复检测 |

### 验证结果

- v5/v6 验证：71% → **100% 通过率**
- 多数 conf=1.0000（旧模板 0.6464）
- 速度比 OCR 快 100 倍

### 实现位置

- `engine/wechat_sender/template_matcher.py` — 模板匹配核心
- `engine/wechat_sender/image_utils.py` — `imread_unicode` 公共函数（支持中文路径 + ico 格式）

---

## 三、字体匹配（display_name 专用）

### 原理

渲染指定字体（`msyh.ttc` 微软雅黑）生成文字图像，与截图进行模板匹配。适用于 display_name 等固定文字场景（每个联系人名字不同，无法预制作图标模板）。

### 关键特性

- **多字号扫描**：支持不同字号渲染匹配
- **多颜色扫描**：适配不同主题（深色/浅色模式）
- **场景化阈值**：
  - `chat_title`: 0.85（聊天标题验证）
  - `search_bar`: 0.90（搜索栏验证）
- **字体缓存**：避免重复加载 1245 词库 + 657 单字

### 单例优化

`FontMatcher` 采用模块级单例（`get_font_matcher()` / `reset_font_matcher()`），避免每次验证都加载词库，节省 1-3 秒/次。

### 实现位置

- `engine/wechat_sender/font_matcher.py` — 字体匹配核心
- 验证函数：`_verify_chat_header_display_name`（`wechat_e2e_run.py`）

---

## 四、OCR 验证（兜底）

### 原理

仅在未知文字（聊天消息内容验证）时启用 PaddleOCR 或 RapidOCR，用于验证消息是否出现在聊天记录中。

### 使用场景

- 发送消息后验证：OCR 识别聊天区域，确认消息已出现
- 搜索候选框验证：OCR 识别候选框内容，确认包含联系人名

### 实现位置

- `engine/importers/ocr_engine.py` — RapidOCR 封装（ONNX Runtime，带 MD5 缓存）
- `engine/wechat_sender/send_message_run.py` — `verify_message_sent` 函数

### 性能优化

- OCR 实例单例化（`get_ocr_engine()`）：首次 3.58s → 后续 1.58s
- 内存字节流替代临时文件：避免 Windows 文件锁定风险

---

## 五、几何约束

### 布局检测

`WeChatLayoutDetector` 检测微信窗口的三栏布局分界线：
- 状态栏（左侧）
- 聊天会话栏（中间）
- 聊天区域（右侧）

### 区域定位

基于布局分界线计算各功能区域的位置：
- 搜索栏：左上区域
- 发送按钮：右下区域
- 聊天标题：右侧顶部
- 好友选择框：中间栏 (74,485) to (312,564)

### 动态行高

基于 y 坐标预测行高，结合头像候选与几何评分判断候选合理性。

### 实现位置

- `engine/wechat_sender/dynamic_detector.py` — 布局检测（`detect(debug=False)` 避免生产环境写文件）
- `engine/wechat_sender/wechat_e2e_run.py` — 区域定位和坐标计算

---

## 六、综合定位策略

各功能点的定位策略（按优先级）：

| 功能点 | 首选方案 | 备选方案 | 兜底方案 |
|--------|----------|----------|----------|
| 搜索栏 | 图标模板匹配 | OCR 识别"搜索"文字 | 布局检测 + 固定比例 |
| 发送按钮 | 图标模板匹配（绿色）| OCR 识别"发送"文字 | 绿色按钮颜色检测 |
| 聊天标题 | 字体匹配 display_name | OCR 识别显示名 | — |
| 消息验证 | OCR 识别聊天内容 | — | — |
| 搜索候选框 | OCR 验证候选内容 | 头像模板匹配 | — |

### 头像匹配位置优先

先按置信度筛选（≥0.7），再综合评分选择：
- 评分 = confidence × 0.6 + position_score × 0.4
- position_score：距离归一化 + 搜索框下方加分 0.2
- 低置信度回退到选最近

---

## 七、相关文档

- [微信自动化流程](wechat_auto_flow.md) — 端到端发送流程图（v3.0）
- [微信窗口状态](wechat_window_states.md) — 窗口状态管理
- [v4 自动回复架构](auto_reply_architecture.md) — 自动回复整体架构
