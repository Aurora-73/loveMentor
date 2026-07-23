# 微信发消息流程识别增强改造方案（v3）

> **状态：已实现**（2026-07-23）— 图标模板匹配 + 字体匹配 + OCR 验证均已落地，微信发送功能端到端测试通过。
>
> **版本说明**：本方案基于 PoC 验证结果、两份建议（`ocr建议.md` 数据库特征利用 + `ocr建议2.md` 字体匹配）和 v1-v6 多轮验证迭代整合修订。原 v1 方案以"OCR 引擎替换"为主攻点，现降级为备选；**图标模板匹配（UI 元素）+ 字体匹配（display_name）+ 数据库特征 + 几何约束**成为主线。
>
> **v2.1 更新**：合并 `ocr建议.md` 第二轮审核 15 条建议（问题1-15），标注 3 大核心风险，增加前置验证步骤。
>
> **v3.0 更新（重要）**：基于 v1-v6 验证迭代结果，对架构做出重大调整：
> - **图标模板匹配**（v5/v6 验证 71%→100% 通过率，多数 conf=1.0000，速度快 100 倍）**提升为 UI 元素定位首选**
> - **字体匹配**（v4 验证 41% 通过率）**降级为 display_name 专用方案**（每个联系人名字不同，无法预制作模板）
> - **OCR** 仅用于未知文字（聊天消息内容验证）
> - **纠正 R3 方向错误**：微信 PC 导航栏**只有图标没有文字标签**，删除导航栏文字测试用例
> - **新增 v6 新模板**：`send_green_full.png` (100x60) 和 `send_green_compact.png` (60x30)，发送-绿色按钮 conf=1.0000（旧模板 0.6464）
> - **标注 1-5.ico**：都是微信图标的不同尺寸（16x16~64x64），6.ico 是 128x128
> - **PoC-9（灰色发送按钮）和 PoC-10（标题栏文字）已验证通过**

## 0. ⚠️ 实施前必须验证（前置验证）

> **来源**：`ocr建议.md` 第二轮审核核心风险总结。
> **状态**：🔴 R1/R2 仍未验证 — 实施前必须完成 V1/V2 验证。R3 已通过 v4 验证纠正方向（改用图标模板匹配）。

### 0.1 三大核心风险

| 风险编号 | 风险描述 | 影响阶段 | 严重性 | 当前状态 |
|----------|----------|----------|--------|----------|
| **R1** | core.db 表结构未验证，display_name 字段可能不存在或名字不同 | 阶段2（contact_profile） | 🔴 极高 | 未验证 |
| **R2** | 行高 80px 来自 Web 模拟（`SessionListPanel.vue`），真实微信 PC 行高可能不同 | 阶段6（几何评分） | 🔴 高 | 未验证 |
| **R3** | ~~标题栏检测失败无容错~~ → **方向纠正**：微信 PC 导航栏只有图标没有文字标签 | 阶段6（候选框选择） | 🟡 已纠正 | v4 验证发现，改用图标模板匹配（1-5.ico 已验证 conf=0.85-0.89） |

### 0.2 前置验证步骤（实施前必须完成）

| 步骤 | 验证内容 | 方法 | 预计耗时 | 通过标准 |
|------|----------|------|----------|----------|
| **V1** | core.db 表结构 | `PRAGMA table_info(contacts);` 查询字段名 | 5 分钟 | 确认 display_name 字段存在（或找到等效字段） |
| **V2** | 真实行高测量 | 用现有截图测相邻候选项 y 坐标差 | 5 分钟 | 确认行高是否为 80px（或记录真实值） |
| **V3** | PoC 补充测试 | 长文本"微信号:[REDACTED]" + 多候选场景 + 不同 DPR | 15 分钟 | 长文本置信度 ≥ 0.75，多候选可区分 |

### 0.3 其他潜在风险（实施过程中需关注）

| 风险编号 | 风险描述 | 缓解措施 |
|----------|----------|----------|
| **R4** | 字体版本差异（Win10/Win11 的 msyh.ttc 渲染细节可能不同） | 初始化时记录字体文件版本和 hash |
| **R5** | ClearType 设置变化（用户关闭 ClearType 后字体渲染不同） | 初始化时检测 ClearType 状态并记录 |
| **R6** | DPI 缩放兼容性（125%/150% 缩放下字号映射表失效） | 字号映射表增加 DPR 修正系数 |
| **R7** | 微信 UI 更新（标题栏文字变化） | `discover_section_headers` 增加 OCR 兜底扫描 |

## 1. 背景与问题

### 1.1 当前实现

微信发消息流程（`wechat_send` MCP 工具）调用链：
```
wechat_send → _wechat_send_impl → _resolve_contact (查 core.db)
  → avatar_fetcher (获取头像) → run_e2e (三阶段流程)
    ├─ 阶段一：搜索 + 点击头像 + 绿色环验证
    ├─ 阶段二：窗口数判定（1/2 窗口）
    └─ 阶段三：输入消息 + 找发送按钮 + 点击发送 + OCR 验证
```

现有识别方式：
- **搜索栏定位**：OCR 找"搜索"文字 + 布局检测（白色判定）
- **搜索候选框选择**：多尺度头像模板匹配（`[REDACTED].jpg`）+ 重试4次 + CDP刷新
- **发送按钮定位**：OCR 找"发送"文字 + 绿色像素连通组件分析
- **聊天界面验证**：绿色环颜色检测（单一验证）

### 1.2 已发现的问题

基于 12 张截图的 OCR 分析（`outputs/annotated/`）：

| 问题 | 现象 | 根因 |
|------|------|------|
| 搜索栏 OCR 不稳 | 识别为 `Q搜索` 而非 `搜索` | 放大镜图标被并入文字 |
| 微信号 OCR 错误 | `[REDACTED]` → `1wmight239` | T→1, l→1, i→无点 |
| 发送按钮置信度低 | `发送` conf=0.66 | 字体细，识别不稳 |
| 聊天标题识别失败 | (351,67) 的"茶"字识别不到 | RapidOCR 对 UI 字体识别能力差 |
| 候选框误点风险 | 可能点"搜索网络结果" | 无标题栏范围限定 |
| 数据库信息浪费 | `_resolve_contact` 查到的 display_name/alias 未传递到下游 | 仅 alias 用于搜索栏输入 |

### 1.3 RapidOCR 根因分析

对 `茶.png`（58x50 像素，单字"茶"）进行多种增强测试（原图、放大2/4/8倍、灰度+直方图均衡、Otsu二值化、反色+Otsu、自适应阈值），**所有变体识别到 0 条文字**。

根因（来自 `ocr建议2.md`）：
1. **训练数据不匹配**：RapidOCR 训练于印刷体/文档，不包含 UI 字体（Microsoft YaHei UI）的渲染特征
2. **ClearType 子像素抗 aliasing**：Windows 启用 ClearType 后，小字（58x50px）产生亚像素细节，与 OCR 训练数据分布严重不匹配
3. **字体 hinting 变形**：微软雅黑在小尺寸下有专门的 hinting 优化，笔画形态与训练数据不同

**结论**：通用 OCR 模型本质上不适合识别 UI 字体文字。

## 2. PoC 验证结果

### 2.1 字体匹配 PoC

脚本：`engine/wechat_sender/_poc_font_matcher.py`

核心思路：用微软雅黑（`C:/Windows/Fonts/msyh.ttc`）渲染已知文字，与微信截图做模板匹配（`cv2.matchTemplate` + `TM_CCOEFF_NORMED`）。

### 2.2 PoC 测试结果（全部通过）

| 测试 | 文字 | 场景图 | 位置 | 置信度 | 字号 | 对比 RapidOCR |
|------|------|--------|------|--------|------|---------------|
| 1 | 茶 | stage_f_after_click_1.png | (351, 68) | **0.8879** | 18px | OCR 失败 (0 条) |
| 2 | 茶（直接对比） | 茶.png | - | **0.8383** | 40px | OCR 失败 (0 条) |
| 3 | 搜索 | stage_f_after_click_1.png | (149, 71) | **0.9483** | 15px | OCR "Q搜索" 误识 |
| 4 | 发送 | stage_f_after_click_1.png | (515, 411) | **1.0000** | 12px | OCR conf=0.66 |
| 5 | 茶字变体 | - | - | 0.8880（深灰最佳） | 18px | - |

### 2.3 关键发现

1. **茶字 0.8879** — 远超 0.8 阈值，位置 (351, 68) 与用户指出的完全一致
2. **搜索 0.9483** — 彻底解决"Q搜索"误识别问题
3. **发送 1.0000** — 完美匹配，远超 OCR 的 0.66
4. **字号 18px** 是聊天标题标准字号
5. **深灰-YaHei 0.8880** 略优于纯黑，说明微信标题用深灰色而非纯黑
6. **Bold 字重 0.6969** 较低，说明微信标题用常规字重

### 2.4 PoC 结论

**字体匹配方案完全可行**，在所有核心场景中置信度远超阈值。weachat_send 流程中全是已知字符（display_name 来自数据库，"搜索"/"发送"是固定文字，微信号来自数据库），根本不需要"识别"，只需要"定位"。

### 2.5 v1-v6 多轮验证迭代结果（v3.0 新增）

> **背景**：PoC 验证后，为确认方案在更广泛场景下的可行性，进行了 v1-v6 共 6 轮迭代验证。
> **核心结论**：**图标模板匹配远优于字体匹配**（UI 元素定位场景），字体匹配应**降级为 display_name 专用方案**。

#### 2.5.1 验证版本演进

| 版本 | 方法 | 通过率 | 核心发现 |
|------|------|--------|----------|
| v1 | TM_CCOEFF_NORMED 单颜色 | 23% (8/34) | 测试了不存在的文字 |
| v2 | TM_CCOEFF_NORMED 多颜色+背景 | 33% (4/12) | 纯色模板 bug + 背景色敏感 |
| v3 | TM_SQDIFF_NORMED + mask | 0% | 方向错误，全面退化（"茶"从 0.8881 降到 0.5145） |
| v4 | v2 + 方差检查 + 自动对比背景色 | 41% (5/12) | 核心场景不退化，发送不可发送态新通过（0.6455→0.8928） |
| **v5** | **图标模板匹配**（`wx_icon/` 现成模板） | **71% (5/7)** | **多数 conf=1.0000，速度快 10-100 倍** |
| **v6** | **新模板 + ico 测试** | **100%** | **send_green_full.png 1.0000，ico 0.85-0.89** |

#### 2.5.2 v5 图标模板匹配结果（推荐方案）

| 场景 | v4 字体匹配 | v5 图标模板 | 改进 | 状态 |
|------|-------------|-------------|------|------|
| 搜索栏 | 0.9483 | **1.0000** | +0.0517 | ✅ |
| 最常使用 | 0.9818 | **1.0000** | +0.0182 | ✅ |
| 群聊 | 0.9770 | **1.0000** | +0.0230 | ✅ |
| 发送-灰色 | 0.8928 | **1.0000** | +0.1072 | ✅ |
| 对话-已激活 | - | **1.0000** | 新发现（导航栏图标） | ✅ |
| 联系人(候选框) | 0.4904 | 0.4537 | - | 候选框没有"联系人"分类，失败是正确的 |
| 发送-绿色 | 0.5038 | 0.6464 | 旧模板尺寸不符 | v6 已修复 |

**关键发现**：
1. 图标模板匹配 conf=1.0000，**速度快 10-100 倍**（0.01-0.21s vs 字体匹配 0.5-3.5s）
2. 多数 UI 元素都能预制作模板，图标模板匹配是最佳选择
3. 字体匹配只适合无法预制作模板的场景（如 display_name）

#### 2.5.3 v6 新模板与 ico 测试结果

**发送-绿色按钮新模板**（解决 v5 失败）：

| 模板 | 尺寸 | 旧模板 conf | 新模板 conf | 改进 |
|------|------|-------------|-------------|------|
| send_green_full.png | 100x60 | 0.6464 | **1.0000** | +0.3536 |
| send_green_compact.png | 60x30 | - | **1.0000** | 新模板 |

**ico 导航栏图标测试**（1-5.ico 都是微信图标不同尺寸）：

| 图标 | 尺寸 | 置信度 | 匹配方法 | 位置 | 说明 |
|------|------|--------|----------|------|------|
| 1.ico | 16x16 | 0.8916 ✅ | TM_CCORR_NORMED | (47, 141) | 微信图标 16x16 |
| 2.ico | 24x24 | 0.8711 ✅ | TM_CCORR_NORMED | (54, 129) | 微信图标 24x24 |
| 3.ico | 32x32 | 0.8664 ✅ | TM_CCORR_NORMED | (55, 128) | 微信图标 32x32 |
| 4.ico | 48x48 | 0.8616 ✅ | TM_CCORR_NORMED | (56, 125) | 微信图标 48x48 |
| 5.ico | 64x64 | 0.8565 ✅ | TM_CCORR_NORMED | (32, 164) | 微信图标 64x64 |
| 6.ico | 128x128 | - | - | - | 模板太大，不适用 |

**用户澄清（重要）**：1-5.ico 都是微信图标的不同尺寸缩放，和 6.ico 一样，不是不同的导航栏功能图标。

#### 2.5.4 v4 字体匹配失败场景分析（纠正 R3 方向）

v4 验证发现的失败场景及其根因：

| 失败场景 | v4 conf | 根因分析 | v3.0 处理 |
|----------|---------|----------|-----------|
| 导航栏"聊天/朋友圈/我/联系人" | 0.40-0.62 | **微信 PC 导航栏只有图标，没有文字标签** | ❌ 删除该测试用例（R3 方向错误） |
| 表情按钮 | 0.4898 | 匹配到"昨天"文字（位置错误） | 🔄 改用图标模板匹配（`wx_icon/表情按钮.png`） |
| 发送按钮可发送态 | 0.5038 | 绿色背景 + 白色文字，深色背景模板不匹配 | ✅ v6 新模板 send_green_full.png 1.0000 |
| 微信号内容"[REDACTED]" | 0.3659 | 字母数字组合匹配困难 | 🔴 待 V3 验证（PoC-6 长文本分段匹配） |

#### 2.5.5 v3 失败根因分析（避免重复错误）

v3（TM_SQDIFF_NORMED + mask）全面退化的原因：
1. **SQDIFF 对像素差异过敏**：微信截图有 ClearType 子像素抗 aliasing，PIL 渲染是普通抗 aliasing，边缘像素差异大
2. **mask 膨胀过度**：3x3 膨胀让 mask 覆盖了抗 aliasing 过渡区（差异最大的区域）
3. **灰度匹配丢失颜色信息**：v2 用彩色匹配有额外区分度，v3 灰度后全部丢失
4. **总是选 Bold 字重**：Bold 的 mask 区域更大，在 SQDIFF 中"稀释"了差异，是数值假象而非真匹配

**结论**：TM_CCOEFF_NORMED（v2/v4）是正确选择，归一化后对亮度/对比度不敏感，更能抓住文字形状相似性。

#### 2.5.6 推荐的三层架构（v3.0 最终方案）

| 场景类型 | 推荐方法 | 置信度 | 速度 | 理由 |
|----------|----------|--------|------|------|
| **UI 元素定位**（搜索栏/发送按钮/群聊/最常使用/导航栏图标） | **图标模板匹配** | 1.0000 | 0.01-0.21s | 速度快 100 倍，conf 完美 |
| **聊天标题验证**（display_name 如"茶"） | **字体匹配** | 0.8880 | 0.5-3.5s | 每个联系人名字不同，无法预制作模板 |
| **未知文字**（聊天消息内容） | **OCR**（PaddleOCR-VL） | - | ~200ms | 字体匹配和图标模板都不适用 |

**验证报告**：
- `_corpus_match_report_v3.md` — v3 报告（0% 通过率）
- `_corpus_match_report_v4.md` — v4 报告（41% 通过率）
- `_corpus_match_report_v5.md` — v5 报告（71% 通过率）
- 可视化图片：`_v4_failure_*.png`、`_v5_icon_*.png`、`_v5_send_button_*.png`、`_v5_ico_*.png`

## 3. 最终架构

### 3.1 识别优先级（降序）

> **v3.0 调整**：基于 v5/v6 验证结果（图标模板匹配 conf=1.0000，速度快 100 倍），Layer 1 和 Layer 2 优先级互换。图标模板匹配成为 UI 元素定位首选，字体匹配降为 display_name 专用。

```
┌─────────────────────────────────────────────────────────┐
│  识别策略分层（v3.0 按优先级降序）                       │
├─────────────────────────────────────────────────────────┤
│  Layer 1: 图标模板匹配（UI 元素，v3.0 提升）             │
│    - 搜索栏.png（放大镜图标+文字）       conf=1.0000     │
│    - send_green_full.png / 发送-灰色.png conf=1.0000     │
│    - 最常使用.png / 群聊.png             conf=1.0000     │
│    - 对话-已激活.png / 1-5.ico           conf=0.85-1.00  │
│    - 表情按钮.png                                       │
├─────────────────────────────────────────────────────────┤
│  Layer 2: 字体匹配（display_name 专用，v3.0 降级）       │
│    - display_name（如"茶"）来自 core.db  conf=0.8880     │
│    - 微信号："微信号:" + alias（V3 待验证长文本分段）     │
│    - 适用场景：每个联系人名字不同，无法预制作模板         │
├─────────────────────────────────────────────────────────┤
│  Layer 3: OCR（未知内容）                                │
│    - 聊天消息内容验证（用户输入的任意文字）               │
│    - 备选：PaddleOCR-VL 0.9B 或 RapidOCR                │
├─────────────────────────────────────────────────────────┤
│  Layer 4: 颜色检测（兜底）                               │
│    - 绿色环（聊天界面验证）                               │
│    - 绿色像素（发送按钮）                                 │
├─────────────────────────────────────────────────────────┤
│  Layer 5: 几何约束（贯穿所有层）                         │
│    - 标题栏范围限定（两个标题栏之间）                     │
│    - 候选项 y 坐标预测（标题栏_y + 行高 × 索引）          │
│    - 三栏布局（nav_right, session_right）                │
└─────────────────────────────────────────────────────────┘
```

**v3.0 架构调整说明**：

| 调整点 | v2.1 方案 | v3.0 方案 | 调整理由 |
|--------|-----------|-----------|----------|
| Layer 1 | 字体匹配 | **图标模板匹配** | v5/v6 验证 conf=1.0000，速度快 100 倍 |
| Layer 2 | 模板匹配 | **字体匹配（display_name 专用）** | 每个联系人名字不同，无法预制作模板 |
| 导航栏检测 | 字体匹配"聊天/朋友圈/我" | **删除（无文字标签）** | v4 验证发现微信 PC 导航栏只有图标 |
| 发送按钮模板 | 发送-绿色.png (45x19) | **send_green_full.png (100x60)** | v6 验证旧模板 conf=0.6464，新模板 1.0000 |
| 标题栏图标 | 字体匹配"最常使用/联系人" | **图标模板匹配（最常使用.png 等）** | v5 验证字体匹配 0.98，图标模板 1.0000 |

### 3.2 数据层：contact_profile 传递

**核心改进（来自 `ocr建议.md` 改进A）**：把 `_resolve_contact` 查到的信息打包为 `contact_profile`，传递到 `run_e2e` 及下游所有阶段。

```python
# 新增数据结构
@dataclass
class ContactProfile:
    wxid: str                    # 微信ID（如 [REDACTED]）
    alias: str                   # 微信号（如 [REDACTED]）
    display_name: str            # 微信显示名（如"茶"）
    remark: str | None           # 备注名（如"CDP修复验证测试"）
    nickname: str | None         # 昵称
    avatar_url: str | None       # 头像URL
    avatar_path: str | None      # 本地头像路径
```

**传递路径**：
```
_resolve_contact (查 core.db)
  → 构建 ContactProfile
  → _wechat_send_impl (传递)
  → run_e2e (传递)
  → 阶段一/二/三 (各阶段可用 display_name/alias 做字体匹配验证)
```

**收益**：下游所有阶段都能用精确特征集做验证，不再"盲找"。

### 3.3 验证机制：证据融合评分

**来自 `ocr建议.md` 改进G**：候选项选择升级为加权证据评分。

| 证据 | 权重 | 来源 | 现状 |
|------|------|------|------|
| 头像相似度 | 0.40 | 模板匹配 | ✅ 已有 |
| 字体匹配（微信号） | 0.25 | 字体匹配 alias | ❌ 新增 |
| 字体匹配（display_name） | 0.20 | 字体匹配 display_name | ❌ 新增 |
| 几何位置合理 | 0.15 | y 坐标预测 | ❌ 新增 |

**决策规则**：
- 综合置信度 ≥ 0.7 → 点击
- 综合置信度 < 0.4 → 拒绝
- 0.4 ~ 0.7 → 重试

### 3.4 失败恢复：分层降级链

**来自 `ocr建议.md` 改进F**：5 级降级链。

```
Level 0: 完整流程（字体匹配 + 模板匹配 + 数据库特征融合）
  ↓ 失败
Level 1: 简化搜索词（如只搜 display_name 而非全 alias）
  ↓ 失败
Level 2: 切换识别方式（字体匹配 → OCR → 纯模板匹配 → 颜色检测）
  ↓ 失败
Level 3: CDP 刷新头像（已有）+ 重试
  ↓ 失败
Level 4: 报错 + AskUserQuestion 请求用户介入（替代当前静默返回失败）
```

## 4. 实施阶段（重排优先级）

### 4.1 阶段优先级

> **v3.0 调整**：基于 v5/v6 验证结果，`template_matcher.py`（阶段7）从 P2 提升为 **P0**，与 `font_matcher.py` 并列最优先实施。

| 优先级 | 阶段 | 收益 | 成本 | 依赖 | v3.0 说明 |
|--------|------|------|------|------|-----------|
| **P0** | 阶段7: template_matcher.py 模板匹配工具 | 极高 | 低 | 无 | **v3.0 提升**（v5/v6 验证 conf=1.0000，速度快 100 倍） |
| **P0** | 阶段1: font_matcher.py 字体匹配工具 | 高 | 低 | 无 | display_name 专用（v4 验证 41% 通过率） |
| **P0** | 阶段2: contact_profile 数据传递 | 极高 | 低 | 无 | 数据基础 |
| **P1** | 阶段3: 聊天界面验证增强（字体匹配 display_name） | 高 | 低 | 阶段1+2 | display_name 验证（字体匹配唯一主战场） |
| **P1** | 阶段4: 搜索栏定位改造（图标模板匹配"搜索栏.png"） | 高 | 低 | 阶段7 | **v3.0 改为图标模板**（v5 验证 1.0000） |
| **P1** | 阶段5: 发送按钮定位改造（图标模板匹配 send_green_full.png） | 高 | 低 | 阶段7 | **v3.0 改为图标模板**（v6 验证 1.0000） |
| **P2** | 阶段6: 候选框选择增强（标题栏范围 + 证据融合） | 中高 | 中 | 阶段1+2+7 | 标题栏用图标模板匹配 |
| **P3** | 阶段8: PaddleOCR-VL 引入（仅聊天消息验证） | 低 | 中 | 无 | 可选 |
| **P3** | 阶段9: 分层失败恢复机制 | 中 | 低 | 阶段1-7 | 贯穿所有阶段 |
| **P3** | 阶段10: 多账号搜索栏宽度自适应 | 低 | 低 | 阶段4 | 扩展 |

### 4.2 阶段流程图

```
阶段7 (template_matcher) ─┬─→ 阶段4 (搜索栏图标定位)
                           ├─→ 阶段5 (发送按钮图标定位)
                           ├─→ 阶段6 (标题栏图标定位)
                           └─→ 阶段3 (导航栏图标验证，可选)

阶段1 (font_matcher) ─┬─→ 阶段3 (聊天界面 display_name 验证)
                      └─→ 阶段6 (候选框微信号验证)

阶段2 (contact_profile) ─→ 阶段3, 阶段6

阶段8 (PaddleOCR-VL) ─→ 仅用于聊天消息内容验证（阶段3发送后验证）

阶段9 (分层降级) ─→ 贯穿所有阶段

阶段10 (多账号自适应) ─→ 阶段4 的扩展
```

**v3.0 流程图说明**：
- 阶段7（图标模板匹配）从依赖项变为被依赖项，优先实施
- 阶段1（字体匹配）保留用于 display_name 和微信号验证
- 阶段4/5/6 的主要识别方式从字体匹配改为图标模板匹配
- 字体匹配仅在 display_name 验证（阶段3）和微信号验证（阶段6）中作为主战方法

## 5. 各阶段详细设计

### 5.1 阶段1：font_matcher.py 字体匹配工具（P0）

**目标**：创建字体匹配工具模块，作为最优先的识别手段。

**新增文件**：`engine/wechat_sender/font_matcher.py`

**接口设计**：
```python
@dataclass
class FontMatch:
    text: str                    # 匹配的文字
    center_x: int                # 中心x坐标
    center_y: int                # 中心y坐标
    confidence: float            # 置信度
    font_size: int               # 匹配的字号
    color: tuple[int, int, int]  # 匹配的颜色（RGB）
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)

# 场景化字号映射表（建议1：减少 60% 匹配次数）
SCENE_FONT_SIZES = {
    "chat_title": [16, 17, 18, 19, 20],       # 聊天标题（PoC: 18px 最佳）
    "search_bar": [14, 15, 16, 17],           # 搜索栏（PoC: 15px 最佳）
    "send_button": [11, 12, 13, 14],          # 发送按钮（PoC: 12px 最佳）
    "section_header": [12, 13, 14, 15],       # 标题栏
    "wxid_label": [11, 12, 13, 14],           # 微信号标签
    "default": [12, 13, 14, 15, 16, 18, 20, 22, 24, 28, 32],  # 兜底全扫描
}

# 场景化阈值（建议4：阈值 = PoC 最佳置信度 - 0.05）
SCENE_THRESHOLDS = {
    "chat_title": 0.85,       # PoC 0.8879 - 0.05
    "search_bar": 0.90,       # PoC 0.9483 - 0.05
    "send_button": 0.95,      # PoC 1.0000 - 0.05
    "wxid_label": 0.75,       # 保守，多字符更易错
    "default": 0.80,
}

# 颜色常量（建议2：深灰优先 + 白色例外）
COLOR_DARK_GRAY = (51, 51, 51)    # 默认：覆盖聊天标题、搜索栏、标题栏
COLOR_WHITE = (255, 255, 255)     # 例外：发送按钮（绿色背景上）

# 字体模板缓存（建议3：避免重复渲染）
_template_cache: dict[tuple, np.ndarray] = {}

# 环境信息（初始化时检测，R4/R5 风险缓解）
_env_info: dict = {}

def init_font_matcher(font_path: str = "C:/Windows/Fonts/msyh.ttc") -> dict:
    """初始化字体匹配器，记录环境信息（R4 字体版本 + R5 ClearType 状态）。

    在 font_matcher 模块首次导入时自动调用，也可手动调用重新检测。

    Returns:
        dict: 环境信息
            - font_path: 字体文件路径
            - font_hash: 字体文件 MD5（用于版本识别）
            - font_size_bytes: 字体文件大小
            - cleartype_enabled: ClearType 是否启用（Windows）
            - dpi_scale: 当前 DPI 缩放比例
    """
    import hashlib
    import os
    import sys

    info = {"font_path": font_path}

    # R4: 字体版本记录（文件 hash）
    if os.path.exists(font_path):
        info["font_size_bytes"] = os.path.getsize(font_path)
        with open(font_path, "rb") as f:
            info["font_hash"] = hashlib.md5(f.read()).hexdigest()
    else:
        info["font_hash"] = None
        info["font_size_bytes"] = None

    # R5: ClearType 检测（仅 Windows）
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Desktop",
                0,
                winreg.KEY_READ,
            )
            value, _ = winreg.QueryValueEx(key, "FontSmoothing")
            info["cleartype_enabled"] = (value == "2")
            # 进一步检查 ClearType 类型
            try:
                smooth_type, _ = winreg.QueryValueEx(key, "FontSmoothingType")
                info["cleartype_type"] = int(smooth_type)  # 2=ClearType
            except FileNotFoundError:
                info["cleartype_type"] = None
        except Exception:
            info["cleartype_enabled"] = None
    else:
        info["cleartype_enabled"] = None

    # R6: DPI 缩放
    try:
        import ctypes
        user32 = ctypes.windll.user32
        info["dpi_scale"] = user32.GetDpiForSystem() / 96.0
    except Exception:
        info["dpi_scale"] = 1.0

    _env_info.update(info)
    return info

def get_env_info() -> dict:
    """获取已检测的环境信息。"""
    return _env_info.copy()

# 模块导入时自动初始化
init_font_matcher()

def match_text(
    scene: np.ndarray,
    text: str,
    search_region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.80,
    font_sizes: list[int] | None = None,
    color: tuple[int, int, int] = COLOR_DARK_GRAY,  # 默认深灰
    font_path: str = "C:/Windows/Fonts/msyh.ttc",
    font_index: int = 0,  # 0=YaHei, 1=YaHei UI
    scene_type: str = "default",  # 场景类型，用于自动选择字号和阈值
) -> FontMatch | None:
    """在场景图中查找指定文字（多字号尝试）。

    Args:
        scene: BGR 图像
        text: 要查找的文字（已知字符）
        search_region: (x1, y1, x2, y2) 搜索区域，None 表示全图
        threshold: 匹配阈值（默认 0.80，可被 scene_type 覆盖）
        font_sizes: 尝试的字号列表（None 时用 scene_type 对应的字号）
        color: 文字颜色（RGB，默认深灰）
        font_path: 字体文件路径
        font_index: ttc 字体索引
        scene_type: 场景类型，自动选择字号和阈值

    Returns:
        FontMatch 或 None（未匹配到）

    优化：
        - 场景化字号映射（建议1）：减少 60% 匹配次数
        - 深灰优先（建议2）：避免多颜色扫描浪费
        - 模板缓存（建议3）：首次匹配后耗时降低 80%
        - 量化阈值（建议4）：基于 PoC 结果设定
    """
    # 场景化字号和阈值
    if font_sizes is None:
        font_sizes = SCENE_FONT_SIZES.get(scene_type, SCENE_FONT_SIZES["default"])
    if scene_type in SCENE_THRESHOLDS:
        threshold = SCENE_THRESHOLDS[scene_type]

    # ... 匹配逻辑（参考 PoC 脚本）

def match_text_all(
    scene: np.ndarray,
    text: str,
    search_region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.80,
    font_sizes: list[int] | None = None,
    color: tuple[int, int, int] = COLOR_DARK_GRAY,
    font_path: str = "C:/Windows/Fonts/msyh.ttc",
    font_index: int = 0,
    scene_type: str = "default",
    max_results: int = 10,
) -> list[FontMatch]:
    """在场景图中查找指定文字的所有匹配位置（问题1：多候选场景必需）。

    Args:
        同 match_text，增加：
        max_results: 最大返回结果数（避免误匹配爆炸）

    Returns:
        list[FontMatch]：所有匹配位置（按置信度降序）

    使用场景：
        - 阶段6 候选框中验证多个候选项的微信号
        - 同名联系人区分（多个"茶"字定位）
    """
    # 实现：cv2.matchTemplate 后用 NMS（非极大值抑制）去重
    # ... 匹配逻辑 + NMS
```

**接口说明（问题1：match_text vs match_text_all）**：
- `match_text` — 返回单个最佳匹配，用于单目标定位（聊天标题、搜索栏、发送按钮）
- `match_text_all` — 返回所有匹配位置（NMS 去重），用于多候选场景（候选框微信号验证、同名联系人区分）

**长文本分段匹配策略（问题2）**：
```python
def match_long_text(
    scene: np.ndarray,
    prefix: str,           # 固定前缀，如"微信号:"
    content: str,          # 可变内容，如"[REDACTED]"
    search_region: tuple[int, int, int, int] | None = None,
    prefix_threshold: float = 0.85,   # 前缀高阈值
    content_threshold: float = 0.70,  # 内容较低阈值（字母数字更易错）
    **kwargs,
) -> FontMatch | None:
    """长文本分段匹配（问题2：避免整段渲染降置信度）。

    策略：
    1. 先匹配 prefix（如"微信号:"），高阈值 0.85
    2. 在 prefix 右侧匹配 content（如"[REDACTED]"），较低阈值 0.70
    3. 两者都匹配 → 验证通过，返回 content 的匹配位置

    Returns:
        FontMatch 或 None（任一段未匹配则返回 None）
    """
```

**长文本未验证风险（问题14）**：
- PoC 只验证了单字/短词（"茶"/"搜索"/"发送"）
- 长文本"微信号:[REDACTED]"未验证
- **必须在 V3 前置验证中测试**

**验证标准**（基于 PoC，建议4量化）：
| 场景 | 文字 | PoC 置信度 | 建议阈值 |
|------|------|-----------|----------|
| 聊天标题 | 茶 | 0.8879 | 0.85 |
| 搜索栏 | 搜索 | 0.9483 | 0.90 |
| 发送按钮 | 发送 | 1.0000 | 0.95 |
| 微信号 | [REDACTED] | 未测 | 0.75（保守） |

**参考实现**：`engine/wechat_sender/_poc_font_matcher.py`（PoC 脚本，已验证通过）

### 5.2 阶段2：contact_profile 数据传递（P0）

**目标**：把 `_resolve_contact` 查到的信息打包传递到下游。

**修改文件**：
- `mcp_server/tools_wechat.py` — `_resolve_contact` 返回 ContactProfile
- `engine/wechat_sender/wechat_e2e_run.py` — `run_e2e` 接收 ContactProfile 参数
- `engine/wechat_sender/click_avatar_in_search_window.py` — 阶段一接收 ContactProfile
- `engine/wechat_sender/send_message_run.py` — 阶段三接收 ContactProfile

**新增数据结构**：`engine/wechat_sender/contact_profile.py`
```python
@dataclass
class ContactProfile:
    wxid: str
    alias: str
    display_name: str
    remark: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    avatar_path: str | None = None
```

**修改 `_resolve_contact`**：
```python
# 现状：只返回 alias 用于搜索栏输入
alias = _resolve_contact(wxid)

# 改造后：返回 ContactProfile
profile = _resolve_contact(wxid)  # 返回 ContactProfile
# profile.alias 用于搜索栏输入
# profile.display_name 用于聊天界面字体匹配验证
# profile.avatar_path 用于头像模板匹配
```

**⚠️ 问题3：core.db 表结构前置验证（V1 必做）**

实施前必须验证 core.db 的 contacts 表结构，确认 display_name 字段存在：

```python
# 前置验证脚本（V1）
import sqlite3
conn = sqlite3.connect("path/to/core.db")
cursor = conn.execute("PRAGMA table_info(contacts)")
fields = {row[1]: row[2] for row in cursor.fetchall()}  # {字段名: 类型}
print(fields)

# 期望字段映射表（根据实际表结构修正 ContactProfile）
EXPECTED_FIELDS = {
    "wxid": ["wxid", "id", "wxid_str"],
    "alias": ["alias", "wechat_id", "wxid_alias"],
    "display_name": ["display_name", "displayName", "displayname", "nickname"],
    "remark": ["remark", "remark_name", "conRemark"],
    "nickname": ["nickname", "nick_name"],
}
# 若字段名不匹配，在 _resolve_contact 中做字段名映射
```

**字段映射表（实施前需填充）**：

| ContactProfile 字段 | core.db 实际字段名 | 验证状态 |
|---------------------|-------------------|----------|
| wxid | ? | 🔴 未验证 |
| alias | ? | 🔴 未验证 |
| display_name | ? | 🔴 未验证 |
| remark | ? | 🔴 未验证 |
| nickname | ? | 🔴 未验证 |

**回退策略（建议7：contact_profile 缺失时的具体处理）**：
| 字段缺失 | 回退方案 | 影响阶段 |
|----------|----------|----------|
| `display_name` 缺失（问题4） | 回退链：`display_name` → `nickname` → `remark` 首字符 → 仅用绿色环+搜索栏消失 | 阶段3（聊天界面验证） |
| `display_name` + `nickname` + `remark` 全缺失 | 聊天界面验证只用"绿色环 + 区域特征对比"双特征（问题9改进） | 阶段3 |
| `alias` 缺失 | 搜索栏输入 `display_name` 或 `nickname` | 阶段4（搜索栏输入） |
| `avatar_path` 为 None（问题5） | 回退链：`avatar_path` → `wx_icon/[REDACTED].jpg`（默认模板）→ 跳过头像匹配，仅用字体匹配（微信号+display_name） | 阶段6（候选框选择） |
| 整个 `ContactProfile` 查询失败 | 回退到纯 alias 搜索（现有逻辑） | 全流程 |

**display_name 为空字符串的判断（问题4补充）**：

```python
def get_display_name_for_match(profile: ContactProfile) -> str | None:
    """获取用于字体匹配的 display_name，处理空值回退。"""
    # 1. display_name 非空
    if profile.display_name and profile.display_name.strip():
        return profile.display_name.strip()
    # 2. nickname 非空（取首字符作为候选）
    if profile.nickname and profile.nickname.strip():
        return profile.nickname.strip()[0]  # 首字符
    # 3. remark 非空（取首字符作为候选）
    if profile.remark and profile.remark.strip():
        return profile.remark.strip()[0]
    # 4. 全部缺失
    return None  # 调用方需处理 None，跳过字体匹配验证
```

**验证标准**：
- `_resolve_contact` 返回 ContactProfile
- `run_e2e` 接收并传递到各阶段
- 各阶段可用 `profile.display_name` 做字体匹配
- 各字段缺失时有明确回退（见上表）

### 5.3 阶段3：聊天界面验证增强（P1）

**目标**：用字体匹配 display_name 替代单一绿色环验证。

**修改文件**：`engine/wechat_sender/click_avatar_in_search_window.py`

**新验证逻辑**：
```
1. 主特征：绿色环颜色检测（现有）
2. 辅特征1：字体匹配 display_name
   - 搜索区域：右侧栏左上角 (280, 30) ~ (600, 120)（相对坐标，见问题7）
   - 期望文字：get_display_name_for_match(profile)（问题4回退）
   - 阈值：0.85（场景化阈值，chat_title）
3. 正向特征：右侧聊天界面特征对比（问题9改进，替代"搜索栏消失"判定）
   - 检测右侧栏是否出现聊天界面特征：
     a. 聊天标题栏（display_name 字体匹配）
     b. 消息区域背景色（白色/浅灰）
     c. 输入框区域（底部白色矩形）
   - 至少 2 个特征匹配 → 确认进入聊天界面
```

**问题9 改进说明**：

原方案"搜索栏消失"判定有误判风险（字体匹配失败被误判为"消失"）。改为**正向区域特征对比**：

```python
def verify_chat_interface(image: np.ndarray, profile: ContactProfile) -> bool:
    """验证是否进入聊天界面（问题9：区域特征对比，不依赖"消失"判定）。"""
    features_matched = 0

    # 特征1：绿色环颜色检测（主特征）
    if detect_green_ring(image):
        features_matched += 1

    # 特征2：字体匹配 display_name
    display_name = get_display_name_for_match(profile)
    if display_name:
        match = match_text(image, display_name,
                          search_region=get_relative_region("chat_title"),
                          scene_type="chat_title")
        if match:
            features_matched += 1

    # 特征3：右侧消息区域背景特征（白色/浅灰为主）
    if detect_message_area_background(image):
        features_matched += 1

    # 特征4：底部输入框区域（白色矩形）
    if detect_input_box_region(image):
        features_matched += 1

    # 决策：至少 2 个特征匹配 → 通过
    return features_matched >= 2
```

**决策规则**：
- 绿色环 + display_name 匹配 → 通过
- 绿色环 + 消息区域/输入框特征 → 通过
- 仅绿色环（其他特征未匹配） → 可疑，记录 WARNING 但通过
- 无绿色环 → 失败

### 5.4 阶段4：搜索栏定位改造（P1，v3.0 改为图标模板匹配）

> **v3.0 调整**：原方案用字体匹配"搜索"，现改为**图标模板匹配 `wx_icon/搜索栏.png`**（v5 验证 conf=1.0000，速度快 100 倍）。

**目标**：用图标模板匹配替代 OCR 找搜索栏。

**修改文件**：`engine/wechat_sender/click_avatar_in_search_window.py` — `find_search_bar_in_image`

**新逻辑（v3.0）**：
```
1. 主要：图标模板匹配 wx_icon/搜索栏.png（v5 验证 conf=1.0000）
   - 搜索区域：相对坐标（问题7），基于窗口尺寸 w, h
     - x: [0, int(w * 0.35)]    # 主窗口左上角 35% 宽度
     - y: [0, int(h * 0.15)]    # 顶部 15% 高度
   - 阈值：0.85（图标模板匹配）
   - 速度：0.01-0.05s
2. 回退1：字体匹配"搜索"（阶段1实施后，v4 验证 0.9483）
   - 颜色：灰色 (128, 128, 128)
   - 字号：15px
   - 阈值：0.90
3. 回退2：布局检测（白色判定）+ 固定比例（现有逻辑）
```

**相对坐标辅助函数（问题7）**：

```python
def get_relative_region(region_name: str, window_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """获取相对坐标区域（问题7：避免固定坐标在窗口缩放时失效）。

    Args:
        region_name: 区域名称
        window_size: (width, height) 微信窗口尺寸

    Returns:
        (x1, y1, x2, y2) 绝对坐标
    """
    w, h = window_size
    REGIONS = {
        "chat_title": (int(w * 0.20), int(h * 0.04), int(w * 0.50), int(h * 0.12)),  # 聊天标题
        "search_bar": (0, 0, int(w * 0.35), int(h * 0.15)),                          # 搜索栏
        "send_button": (int(w * 0.50), int(h * 0.60), w, h),                         # 发送按钮
        "session_list": (int(w * 0.05), int(h * 0.15), int(w * 0.30), h),            # 会话列表
        "message_area": (int(w * 0.30), int(h * 0.15), w, int(h * 0.85)),            # 消息区域
        "input_box": (int(w * 0.30), int(h * 0.85), w, h),                           # 输入框
    }
    return REGIONS.get(region_name, (0, 0, w, h))
```

### 5.5 阶段5：发送按钮定位改造（P1，v3.0 改为图标模板匹配）

> **v3.0 调整**：原方案用字体匹配"发送"，现改为**图标模板匹配**（v5/v6 验证 conf=1.0000）。v6 新模板 `send_green_full.png` (100x60) 解决了 v5 旧模板 0.6464 的失败。

**目标**：用图标模板匹配替代 OCR + 颜色检测。

**修改文件**：`engine/wechat_sender/send_message_run.py`

**新逻辑（v3.0，双状态匹配）**：
```
1. 主要：图标模板匹配（v5/v6 验证 conf=1.0000）
   - 搜索区域：相对坐标（问题7）(int(w*0.50), int(h*0.60), w, h)
   - 状态1：可发送 → 模板 wx_icon/send_green_full.png (100x60)
     - v6 验证 conf=1.0000（旧模板 0.6464）
     - 优先匹配
   - 状态2：不可发送 → 模板 wx_icon/发送-灰色.png
     - v5 验证 conf=1.0000
     - 失败时匹配，提示需要聚焦输入框
   - 速度：0.01-0.05s
2. 回退1：字体匹配"发送"（阶段1实施后，v4 验证 0.8928）
   - 状态1：白色文字 + 绿色背景，字号 12px，阈值 0.95
   - 状态2：灰色文字 + 灰色背景，字号 12px，阈值 0.90
3. 兜底：绿色像素连通组件（现有，仅匹配可发送状态）
```

**v3.0 模板资源说明**：

| 模板 | 尺寸 | 验证 conf | 用途 | 说明 |
|------|------|-----------|------|------|
| `send_green_full.png` | 100x60 | 1.0000 | 可发送态（推荐） | v6 新模板，从 stage_3_send_button.png 截取 |
| `send_green_compact.png` | 60x30 | 1.0000 | 可发送态（紧凑） | v6 新模板，适用于小窗口 |
| `发送-灰色.png` | - | 1.0000 | 不可发送态 | v5 验证通过 |
| ~~`发送-绿色.png`~~ | 45x19 | 0.6464 | ~~已弃用~~ | v5 验证失败，尺寸不符 |

**决策规则**：
- 状态1（绿色）匹配 → 直接点击
- 状态2（灰色）匹配 → 先点击输入框聚焦，等待按钮变绿，再点击
- 都未匹配 → 回退到颜色检测（绿色像素连通组件）

### 5.6 阶段6：候选框选择增强（P2）

**目标**：标题栏范围限定 + 证据融合评分。

**修改文件**：`engine/wechat_sender/click_avatar_in_search_window.py`

**新增函数**：
```python
# 标题栏文字清单（建议5：完整分类）
CLICKABLE_HEADERS = ["最常使用", "联系人"]  # 可点击标题栏
NON_CLICKABLE_HEADERS = [  # 不可点击标题栏
    "群聊", "聊天记录", "聊天文件", "收藏",
    "搜索网络结果", "最近使用过的小程序",
]

def discover_section_headers(image: np.ndarray, search_region: tuple[int, int, int, int]) -> list[dict]:
    """扫描搜索候选框，发现所有标题栏位置（建议12：前置步骤）。

    策略：
    1. 用预定义文字列表（CLICKABLE_HEADERS + NON_CLICKABLE_HEADERS）字体匹配
    2. 对未匹配的区域，用 OCR 扫描发现新标题（兜底）
    3. 返回所有标题栏的 [{y, text, is_clickable}] 列表
    """
    headers = []
    # 1. 字体匹配预定义标题栏
    for name in CLICKABLE_HEADERS + NON_CLICKABLE_HEADERS:
        match = match_text(image, name, search_region=search_region,
                          scene_type="section_header")
        if match:
            headers.append({
                "y": match.center_y,
                "text": name,
                "is_clickable": name in CLICKABLE_HEADERS,
            })
    # 2. OCR 扫描发现新标题（兜底，处理微信新版本标题）
    # ... 仅在字体匹配未覆盖的区域扫描
    # 3. 按 y 坐标排序
    headers.sort(key=lambda h: h["y"])
    return headers

def find_section_headers(image: np.ndarray, profile: ContactProfile) -> dict:
    """检测搜索候选框中的所有标题栏位置。

    Returns:
        {
            "clickable": [(y, name), ...],  # 可点击标题栏（最常使用、联系人）
            "non_clickable": [(y, name), ...],  # 不可点击（群聊、聊天记录等）
        }
    """

def compute_clickable_regions(headers: dict) -> list[tuple[int, int]]:
    """计算可点击区域（两个标题栏之间的y范围）。

    Returns:
        [(y_start, y_end), ...]  # 可点击的y范围列表
    """

def detect_row_height(candidates_y: list[int]) -> int | None:
    """动态行高检测（问题6：替代固定 80px）。

    Args:
        candidates_y: 已检测到的候选项 y 坐标列表

    Returns:
        int: 检测到的行高（相邻 y 坐标差的中位数），或 None（少于 2 个候选）

    说明：
        - 原 80px 来自 Web 模拟 SessionListPanel.vue，真实微信 PC 可能不同
        - 检测到至少 2 个候选项后，用 y 坐标差作为行高
        - 前置验证 V2 需用实际截图测量
    """
    if len(candidates_y) < 2:
        return None
    sorted_y = sorted(candidates_y)
    diffs = [sorted_y[i+1] - sorted_y[i] for i in range(len(sorted_y)-1)]
    diffs = [d for d in diffs if 50 <= d <= 120]  # 过滤异常值
    if not diffs:
        return None
    return int(np.median(diffs))

def compute_geometry_score(candidate_y: int, clickable_regions: list,
                           header_y: int | None = None,
                           row_height: int | None = None) -> float:
    """计算几何位置合理性评分（建议6：具体定义 + 问题6：动态行高）。

    评分逻辑：
    - 候选项 y 坐标应在某个可点击区域内
    - 候选项 y 坐标应满足 y = 标题栏_y + 行高 × 索引 + 偏移
    - 行高用动态检测（detect_row_height），而非固定 80px

    Returns:
        float: 0.0 ~ 1.0 的几何合理性评分
    """
    # 1. 检查 y 是否在可点击区域内
    in_region = any(y_start <= candidate_y <= y_end for y_start, y_end in clickable_regions)
    if not in_region:
        return 0.0
    # 2. 检查 y 是否满足行高规律（动态行高）
    if header_y is not None and row_height is not None:
        # y_pred = header_y + row_height * index + offset
        # 反推 index = (candidate_y - header_y) / row_height
        index_approx = (candidate_y - header_y) / row_height
        index_round = round(index_approx)
        y_pred = header_y + row_height * index_round
        diff = abs(candidate_y - y_pred)
        if diff < 10:
            return 1.0
        elif diff < 30:
            return 0.5
    # 3. 仅在可点击区域内，无行高信息
    return 0.7  # 默认分数

def verify_wxid_by_font_match(image: np.ndarray, alias: str,
                               candidate_region: tuple[int, int, int, int] | None = None) -> bool:
    """字体匹配"微信号:" + alias 验证候选项（问题2：长文本分段匹配）。

    使用 match_long_text 分段匹配：
    1. 先匹配"微信号:"（前缀，高阈值 0.85）
    2. 再匹配 alias 部分（内容，较低阈值 0.70）
    3. 两者都匹配 → 验证通过
    """
    from .font_matcher import match_long_text
    match = match_long_text(
        image,
        prefix="微信号:",
        content=alias,
        search_region=candidate_region,
        prefix_threshold=0.85,
        content_threshold=0.70,
    )
    return match is not None

**标题栏检测策略**（建议5：完整分类）：
- **可点击**（必须检测）：`最常使用`、`联系人`
- **不可点击**（必须检测）：`群聊`、`聊天记录`、`聊天文件`、`收藏`
- **不可点击**（可选检测）：`搜索网络结果`、`最近使用过的小程序`
- **兜底**（建议12）：字体匹配未覆盖的区域用 OCR 扫描发现新标题

**候选项选择逻辑（问题12 改进：先匹配头像，再用标题栏验证）**：

原流程有依赖陷阱：标题栏检测失败 → 后续全部失败。改为"先全区域匹配头像，再用标题栏验证候选"：

```
1. 全区域匹配头像（find_template_multiscale，现有逻辑）
   → 得到所有头像候选位置 list[candidate]
2. 对每个头像候选，用标题栏验证：
   a. discover_section_headers() — 发现所有标题栏（建议12前置步骤）
   b. 若标题栏检测成功：
      - compute_clickable_regions() — 计算可点击区域
      - 用 compute_geometry_score() 评分
   c. 若标题栏检测失败（问题10容错）：
      - 记录 WARNING 日志：标题栏检测失败，回退到全区域匹配
      - 几何评分设为默认值 0.5（不阻断流程）
3. 对每个头像候选，计算证据融合评分：
   - 头像相似度 0.40
   - 字体匹配（微信号）0.25  ← match_long_text 分段匹配（问题2）
   - 字体匹配（display_name）0.20
   - 几何位置合理 0.15  ← 动态行高（问题6）
4. 综合置信度 ≥ 0.7 → 点击
5. 若所有候选都 < 0.7 → 进入分层降级链（阶段9）
```

**问题10 容错说明**：

```python
def select_candidate_with_headers(image, profile, avatar_candidates):
    """问题12 改进流程：先匹配头像，再用标题栏验证。"""
    # 1. 标题栏检测（可能失败）
    headers = discover_section_headers(image, search_region)
    clickable_regions = compute_clickable_regions(headers) if headers else []

    # 2. 动态行高检测（问题6）
    candidates_y = [c.center_y for c in avatar_candidates]
    row_height = detect_row_height(candidates_y)

    # 3. 对每个候选项评分
    scored_candidates = []
    for candidate in avatar_candidates:
        # 几何评分（问题10容错）
        if clickable_regions:
            header_y = headers[0]["y"] if headers else None
            geometry_score = compute_geometry_score(
                candidate.center_y, clickable_regions, header_y, row_height
            )
        else:
            # 标题栏检测失败，几何评分用默认值（不阻断）
            logger.warning("标题栏检测失败，几何评分用默认值 0.5")
            geometry_score = 0.5

        # 证据融合评分
        total_score = (
            candidate.confidence * 0.40 +  # 头像相似度
            (1.0 if verify_wxid_by_font_match(image, profile.alias) else 0.0) * 0.25 +
            (1.0 if verify_display_name(image, profile) else 0.0) * 0.20 +
            geometry_score * 0.15
        )
        scored_candidates.append((candidate, total_score))

    # 4. 选择最高分候选
    scored_candidates.sort(key=lambda x: -x[1])
    return scored_candidates[0] if scored_candidates else None
```

**问题10 标题栏检测失败容错规则**：
- 至少匹配到 1 个可点击标题栏 → 正常流程
- 全部未匹配 → 回退到"全区域头像匹配 + 证据融合"（不用标题栏范围限定）
- 记录 WARNING 日志，提示"标题栏检测失败，回退到全区域匹配"

### 5.7 阶段7：template_matcher.py 模板匹配工具（P0，v3.0 提升）

> **v3.0 重要调整**：基于 v5/v6 验证结果（图标模板匹配 conf=1.0000，速度快 100 倍），本阶段从 P2 提升为 **P0**，作为最优先实施的工具模块。

**目标**：创建统一的图标模板匹配工具，作为 UI 元素定位的首选方法。

**新增文件**：`engine/wechat_sender/template_matcher.py`

**接口设计**：
```python
@dataclass
class TemplateMatch:
    center_x: int
    center_y: int
    confidence: float
    scale: float  # 匹配时模板的实际尺寸（像素）
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    template_size: tuple[int, int]  # (width, height)

def match_template(
    scene: np.ndarray,
    template_path: str,
    threshold: float = 0.8,
    search_region: tuple[int, int, int, int] | None = None,
    method: int = cv2.TM_CCOEFF_NORMED,  # 默认方法（v5 验证最佳）
) -> list[TemplateMatch]:
    """图标模板匹配，返回所有匹配位置。

    v5 验证结论：
    - TM_CCOEFF_NORMED 是最佳匹配方法（归一化后对亮度/对比度不敏感）
    - 图标模板不需要多尺度（模板尺寸固定，直接匹配）
    - 搜索区域限定可大幅提升速度（0.01-0.21s）
    """

def match_template_best(
    scene: np.ndarray,
    template_path: str,
    threshold: float = 0.8,
    **kwargs,
) -> TemplateMatch | None:
    """返回最佳匹配（conf 最高的一个）。"""

def imread_unicode(path: str) -> np.ndarray | None:
    """读取图片（支持中文路径和 ico 格式）。

    v6 验证发现：
    - cv2.imread 不支持中文路径
    - cv2.imdecode 不支持 ico 文件
    - 解决方案：用 PIL.Image.open 解码，再转 cv2 格式
    """
    from PIL import Image
    pil_img = Image.open(path)
    if pil_img.mode != 'RGB':
        pil_img = pil_img.convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

def imwrite_unicode(path: str, img: np.ndarray) -> bool:
    """保存图片（支持中文路径）。

    v6 验证发现：cv2.imwrite 不支持中文路径，需用 imencode + tofile。
    """
    ext = os.path.splitext(path)[1]
    result, encoded = cv2.imencode(ext, img)
    if result:
        encoded.tofile(path)
        return True
    return False
```

**应用点**（v5/v6 已验证）：

| 应用场景 | 模板文件 | 验证 conf | 速度 | 说明 |
|----------|----------|-----------|------|------|
| 搜索栏定位 | `wx_icon/搜索栏.png` | 1.0000 | 0.01-0.05s | 替代 OCR "搜索" |
| 发送-绿色按钮 | `wx_icon/send_green_full.png` | 1.0000 | 0.01-0.05s | v6 新模板（100x60） |
| 发送-绿色按钮（紧凑） | `wx_icon/send_green_compact.png` | 1.0000 | 0.01-0.05s | v6 新模板（60x30） |
| 发送-灰色按钮 | `wx_icon/发送-灰色.png` | 1.0000 | 0.01-0.05s | 不可发送态 |
| 最常使用标题栏 | `wx_icon/最常使用.png` | 1.0000 | 0.01-0.05s | 候选框标题栏 |
| 群聊标题栏 | `wx_icon/群聊.png` | 1.0000 | 0.01-0.05s | 候选框标题栏 |
| 对话-已激活 | `wx_icon/对话-已激活.png` | 1.0000 | 0.01-0.05s | 导航栏图标 |
| 微信图标 | `wx_icon/1-5.ico` | 0.85-0.89 | 0.01-0.05s | 1-5 都是微信图标不同尺寸 |
| 表情按钮 | `wx_icon/表情按钮.png` | 待验证 | - | 替代 v4 失败的字体匹配 |

**模板匹配 vs 字体匹配 性能对比**（v5 验证）：

| 指标 | 图标模板匹配 | 字体匹配（v4） | 提升 |
|------|-------------|---------------|------|
| 通过率 | 71%→100%（v6 修复后） | 41% | +30~59% |
| 平均置信度 | 1.0000 | 0.74 | +0.26 |
| 单次匹配耗时 | 0.01-0.21s | 0.5-3.5s | **快 10-100 倍** |
| 模板准备 | 需要预制作 | 字体渲染自动生成 | - |
| 适用场景 | 固定 UI 元素 | display_name 等可变文字 | 互补 |

**实施要点**：
1. **模板路径**：统一在 `engine/wechat_sender/wx_icon/` 目录
2. **中文路径**：必须用 `imread_unicode`（PIL 解码），不能用 `cv2.imread`
3. **匹配方法**：默认 `TM_CCOEFF_NORMED`（v5 验证最佳），ico 文件可用 `TM_CCORR_NORMED`
4. **搜索区域**：限定搜索区域可大幅提升速度（全图扫描 0.5s → 限定区域 0.01s）
5. **阈值**：默认 0.70（v5 验证可区分存在/不存在），关键场景 0.85+
6. **多尺度**：图标模板一般不需要多尺度（v5 直接匹配 conf=1.0000）

### 5.8 阶段8：PaddleOCR-VL 引入（P3，可选/非必须）

**目标**：仅用于聊天消息内容验证（未知字符场景）。

**说明**（建议11：标记为可选/非必须）：
- PoC 已证明字体匹配覆盖所有已知字符场景，PaddleOCR-VL 价值降低
- **本阶段标记为"可选"**，非主攻点
- **替代方案**：发送后验证改为"位置验证"（消息出现在聊天区域右侧）而非 OCR 内容验证
- 如果消息内容验证非必须，可完全移除阶段8

**位置验证方案**（建议11替代方案）：
```
发送后验证（不用 OCR）：
1. 截图聊天区域
2. 检测消息气泡位置（颜色检测 + 连通组件）
3. 验证消息出现在聊天区域右侧（isSent=true，x 坐标 > 聊天区域中心）
4. 验证消息时间戳为当前时间附近
5. 如果需要内容验证，才用 OCR（PaddleOCR-VL 或 RapidOCR）
```

**实施方式**（如果需要 OCR 内容验证）：
- 通过 `OCR_BACKEND` 环境变量切换（`rapidocr` / `paddleocr`）
- 默认用 RapidOCR（已有），PaddleOCR-VL 作为备选
- 仅在 `verify_message_sent`（发送后验证）中使用

**依赖**（如果实施）：
- `paddlepaddle==3.3.1`（已安装）
- `paddleocr==3.6.0`（已安装）
- `paddlex[ocr]`（已安装）
- PaddleOCR-VL 模型（已下载，1.79GB）

### 5.9 阶段9：分层失败恢复机制（P3）

**目标**：建立 5 级降级链，替代当前的"4 次相同重试"。

**修改文件**：`engine/wechat_sender/wechat_e2e_run.py` — `run_e2e` 重试逻辑

**新逻辑（问题11：明确每级触发条件）**：

| Level | 触发条件 | 执行动作 | 失败后 |
|-------|----------|----------|--------|
| **L0** | 初始尝试 | 完整流程（字体匹配 + 模板匹配 + 数据库特征融合） | 进入 L1 |
| **L1** | L0 失败：搜索栏无候选 / 所有候选综合置信度 < 0.4 | 简化搜索词（只搜 display_name 而非全 alias） | 进入 L2 |
| **L2** | L1 失败：简化搜索词仍无候选 / 置信度 < 0.4 | 切换识别方式：字体匹配 → OCR → 纯模板匹配 → 颜色检测 | 进入 L3 |
| **L3** | L2 失败：所有识别方式都未达阈值 | CDP 刷新头像（已有）+ 重试 L0-L2 | 进入 L4 |
| **L4** | L3 失败：CDP 刷新后仍无候选 / 重试次数耗尽 | 报错 + AskUserQuestion 请求用户介入 | 终止 |

**问题11 失败定义明确**：

| 阶段 | 失败判定 |
|------|----------|
| **搜索栏定位** | 字体匹配 conf < 阈值 且 模板匹配 conf < 0.8 且 布局检测失败 |
| **候选框选择** | 所有候选综合置信度 < 0.4（拒绝阈值） |
| **聊天界面验证** | 绿色环检测失败 且 display_name 字体匹配失败 且 区域特征 < 2 个 |
| **发送按钮定位** | 字体匹配（白色/灰色）conf < 阈值 且 颜色检测无绿色像素 |
| **发送后验证** | OCR 未识别到消息内容 且 位置验证未检测到消息气泡 |
| **整个阶段一超时** | 总耗时 > 30 秒（可配置） |

### 5.10 阶段10：多账号搜索栏宽度自适应（P3）

**目标**：处理多账号场景下搜索栏右侧的账号下拉框。

**修改文件**：`engine/wechat_sender/click_avatar_in_search_window.py`

**新逻辑**：
- 检测搜索栏右侧是否有下拉框（字体匹配"账号"或模板匹配下拉箭头）
- 若有，搜索区域 x 范围相应缩小

## 6. 风险与回退

### 6.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| ClearType 子像素差异 | 字体匹配置信度降低 | PoC 已验证 0.8879，可接受；多字号扫描找最佳 |
| 微信 UI 更新 | 字体/布局变化 | 字体匹配用系统字体，不受微信版本影响；模板匹配可更新 |
| 标题栏文字变化 | 范围限定失败 | 字体匹配 + OCR 双重检测 |
| contact_profile 查询失败 | 无 display_name | 回退到纯像素识别（现有逻辑） |
| PaddleOCR-VL 推理慢 | 发送延迟 | 仅用于发送后验证，非关键路径 |

### 6.2 回退方案

- **字体匹配失败**：回退到 OCR（RapidOCR）+ 模板匹配 + 颜色检测（现有逻辑）
- **contact_profile 查询失败**：回退到纯 alias 搜索（现有逻辑）
- **标题栏范围限定失败**：回退到全区域头像匹配（现有逻辑）
- **PaddleOCR-VL 不可用**：回退到 RapidOCR（现有）

## 7. 测试方案

### 7.1 单元测试

每个阶段独立测试，使用现有 12 张截图：

| 阶段 | 测试输入 | 期望输出 | 验证标准 |
|------|----------|----------|----------|
| 阶段1 | stage_f_after_click_1.png + "茶" | FontMatch(conf≥0.85) | PoC 已通过 |
| 阶段1 | stage_b_main_printwindow_1.png + "搜索" | FontMatch(conf≥0.90) | PoC 已通过 |
| 阶段1 | stage_3_before_send.png + "发送" | FontMatch(conf≥0.95) | PoC 已通过 |
| 阶段2 | [REDACTED] | ContactProfile(alias=[REDACTED], display_name=茶) | 数据库查询 |
| 阶段3 | stage_f_after_click_1.png + profile | 验证通过 | 绿色环 + 字体匹配 |
| 阶段4 | stage_b_main_printwindow_1.png | 搜索栏位置 | 字体匹配 conf≥0.85 |
| 阶段5 | stage_3_before_send.png | 发送按钮位置 | 字体匹配 conf≥0.90 |
| 阶段6 | stage_d_search_candidate_1.png + profile | 可点击区域 + 候选项 | 标题栏检测 |

### 7.2 集成测试

端到端测试，调用 `wechat_send` 发送测试消息：
1. 发送消息到 [REDACTED]（小号）
2. 收集所有阶段截图
3. 验证发送成功
4. 生成标注图（字体匹配 + 模板匹配 + OCR 三层结果）
5. 对比改造前后效果

### 7.3 对抗性测试（建议10）

| 测试场景 | 测试目的 | 期望行为 |
|----------|----------|----------|
| 同名联系人（多个"茶"） | 验证证据融合能区分 | 微信号+头像区分，点击正确的 |
| 头像相似联系人 | 验证微信号验证能区分 | 微信号字体匹配置信度区分 |
| core.db 查询失败 | 验证回退逻辑 | 回退到纯 alias 搜索（现有逻辑） |
| 搜索栏无候选 | 验证失败恢复 | 进入分层降级链，最终 AskUserQuestion |
| display_name 缺失 | 验证回退（建议7） | 用 nickname/remark 首字符，或只用绿色环+搜索栏消失 |
| 多账号场景 | 验证搜索栏宽度自适应（阶段10） | 检测账号下拉框，调整搜索区域 |
| 微信 UI 更新（新标题栏） | 验证 discover_section_headers（建议12） | OCR 兜底发现新标题 |

### 7.4 回归测试（问题15：增加基线数据）

**改造前基线数据（实施前必须收集）**：

| 指标 | 改造前数值 | 收集方法 |
|------|-----------|----------|
| 端到端发送成功率 | ?（待测） | 连续发送 20 次消息，统计成功率 |
| 平均重试次数 | ?（待测） | 日志统计 |
| 阶段一总耗时 | ?（待测） | 从搜索到点击的耗时 |
| 阶段三总耗时 | ?（待测） | 从输入到发送的耗时 |
| 单次 OCR 耗时 | ?（待测） | RapidOCR 单次识别耗时 |
| 误点率 | ?（待测） | 对抗性测试 |

**改造后回归测试**：
- 改造后连续发送 20 次消息，统计成功率
- 对比改造前的成功率（应 ≥ 改造前）
- 记录每次发送的识别置信度
- 生成对比报告（改造前 vs 改造后）

### 7.5 负面测试集（问题13：补充失败场景）

现有 12 张截图都是成功流程，缺少失败场景。需补充负面测试集：

| 测试场景 | 截图来源 | 期望行为 |
|----------|----------|----------|
| 搜索无结果（候选项为空） | 主动制造：搜索一个不存在的 wxid | 进入分层降级链 L1，简化搜索词 |
| 头像不匹配（目标联系人未在候选框） | 主动制造：输入错误的 alias | 综合置信度 < 0.4，进入降级链 |
| 同名联系人（多个"茶"） | 真实场景：添加同名测试联系人 | 证据融合区分，点击正确的 |
| 窗口被遮挡 | 主动制造：用其他窗口遮挡微信 | 检测到遮挡，请求用户前置微信窗口 |
| 搜索栏无候选 | 主动制造：搜索一个被删除的联系人 | 进入降级链 L4，AskUserQuestion 请求介入 |
| display_name 为空 | 主动制造：用未设置 display_name 的联系人 | 回退到 nickname 首字符，或只用绿色环+区域特征 |
| 发送按钮灰色（不可发送） | 主动制造：消息输入后立即点击输入框外 | 双状态匹配识别灰色按钮，先聚焦输入框再发送 |

### 7.6 PoC 补充测试（问题14：长文本和多候选场景）

**原 PoC 只验证了单字/短词，需补充以下测试**：

| 测试项 | 测试内容 | 通过标准 | 状态 |
|--------|----------|----------|------|
| **PoC-6 长文本** | "微信号:[REDACTED]" 分段匹配 | 前缀 conf ≥ 0.85, 内容 conf ≥ 0.70 | 🔴 未测（V3 必做） |
| **PoC-7 多候选场景** | 候选框中多个候选项的微信号区分 | match_text_all 返回多个匹配 | 🔴 未测（V3 必做） |
| **PoC-8 不同 DPR** | DPR 1.0 / 1.5 / 2.0 下字体匹配 | 各 DPR 下 conf ≥ 阈值 | 🔴 未测 |
| **PoC-9 灰色发送按钮** | 不可发送状态（灰色文字）匹配 | conf ≥ 0.90 | ✅ **已通过**（v4 验证 0.8928，v5 图标模板 1.0000） |
| **PoC-10 标题栏文字** | "最常使用"/"联系人"/"群聊"等匹配 | conf ≥ 0.85 | ✅ **已通过**（v4 字体匹配 0.98/0.98，v5 图标模板 1.0000） |

**前置验证 V3 要求**：PoC-6、PoC-7 必须在实施前完成。

**v3.0 更新**：PoC-9 和 PoC-10 已通过 v4/v5/v6 验证。其中：
- **PoC-9 灰色发送按钮**：v4 字体匹配 0.8928 ✅，v5 图标模板匹配 1.0000 ✅（推荐用图标模板）
- **PoC-10 标题栏文字**：v4 字体匹配"最常使用" 0.9818 ✅、"群聊" 0.9770 ✅，v5 图标模板匹配 1.0000 ✅（推荐用图标模板）
- **R3 方向纠正**：v4 验证发现微信 PC 导航栏**只有图标没有文字标签**，原"最常使用/联系人/聊天/朋友圈/我"文字测试是错误的，删除该测试用例

## 8. 日志和诊断规范（建议8）

### 8.1 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| `INFO` | 正常流程节点 | `[阶段1] 字体匹配"搜索" conf=0.9483 位置=(149,71)` |
| `WARNING` | 降级/回退触发 | `[阶段2] display_name 缺失，回退到 nickname 首字符` |
| `ERROR` | 识别失败 | `[阶段3] 字体匹配"茶" conf=0.72 < 阈值 0.85` |
| `DEBUG` | 详细诊断信息 | `[阶段6] 标题栏检测: 最常使用(y=30), 联系人(y=200), 群聊(y=350)` |

### 8.2 关键日志点

每个阶段必须记录：
1. **输入**：场景图尺寸、搜索区域、期望文字
2. **识别结果**：置信度、位置、字号
3. **决策**：通过/失败/重试/降级
4. **耗时**：单次匹配耗时

### 8.3 诊断模式

启用 `WECHAT_SEND_DEBUG=1` 环境变量时：
- 保存所有阶段的中间截图
- 生成标注图（字体匹配 + 模板匹配 + OCR 三层结果）
- 输出详细日志到 `outputs/diagnostics/` 目录

## 9. 性能指标（建议9）

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| 单次字体匹配耗时 | < 50ms | `time.time()` 包围 |
| 字体模板缓存命中率 | > 80% | 缓存统计 |
| 端到端发送成功率 | ≥ 95% | 连续 20 次测试 |
| 误点率（点错联系人） | < 1% | 对抗性测试 |
| 平均重试次数 | < 1.5 | 日志统计 |
| 阶段一总耗时 | < 3s | 从搜索到点击 |
| 阶段三总耗时 | < 2s | 从输入到发送 |

### 9.1 性能基线（改造前）

| 指标 | 改造前数值 | 来源 |
|------|-----------|------|
| 单次 OCR 耗时 | ~200ms | RapidOCR |
| 端到端发送成功率 | ~90% | 历史日志 |
| 平均重试次数 | ~1.8 | 历史日志 |
| 阶段一总耗时 | ~5s | 历史日志 |

### 9.2 性能目标（改造后）

字体匹配比 OCR 快 10x（PoC 验证），预期：
- 单次匹配耗时降低 75%（200ms → 50ms）
- 端到端成功率提升 5%（90% → 95%）
- 平均重试次数降低 17%（1.8 → 1.5）

## 8. 附录

### 8.1 现有截图清单

`engine/wechat_sender/outputs/` 目录下 12 张截图：
- `stage_b_main_printwindow_1.png` — 主窗口
- `stage_d_search_candidate_1.png` — 搜索候选框
- `stage_d_match_result_1.png` — 头像匹配结果
- `stage_e_pre_click_1.png` — 点击前
- `stage_f_after_click_1.png` — 点击后
- `stage_f_verify_green_ring_1.png` — 绿色环验证
- `stage_3_input_box.png` — 输入框
- `stage_3_before_send.png` — 发送前
- `stage_3_after_input.png` — 输入后
- `stage_3_send_button.png` — 发送按钮
- `stage_3_after_send.png` — 发送后
- `tray_capture_debug.png` — 托盘

### 8.2 模板资源清单（v3.0 更新）

`engine/wechat_sender/wx_icon/` 目录下：

**核心 UI 元素模板（v5/v6 已验证）**：

| 模板文件 | 尺寸 | 验证 conf | 用途 | v3.0 状态 |
|---------|------|-----------|------|-----------|
| `搜索栏.png` | - | 1.0000 | 搜索栏定位（替代 OCR "搜索"） | ✅ 推荐 |
| `send_green_full.png` | 100x60 | 1.0000 | 发送-绿色按钮（可发送态） | ✅ v6 新增，推荐 |
| `send_green_compact.png` | 60x30 | 1.0000 | 发送-绿色按钮（紧凑版） | ✅ v6 新增 |
| `发送-灰色.png` | - | 1.0000 | 发送-灰色按钮（不可发送态） | ✅ 推荐 |
| `最常使用.png` | - | 1.0000 | 候选框标题栏 | ✅ 推荐 |
| `群聊.png` | - | 1.0000 | 候选框标题栏 | ✅ 推荐 |
| `对话-已激活.png` | - | 1.0000 | 导航栏对话图标（激活态） | ✅ 推荐 |
| `对话-未激活.png` | - | 待验证 | 导航栏对话图标（未激活态） | 🔴 待验证 |
| `联系人.png` | - | 0.4537 | 候选框标题栏（搜索"茶"时不存在） | ⚠️ 场景依赖 |
| `表情按钮.png` | - | 待验证 | 输入框表情按钮 | 🔴 待验证 |
| `表情搜索键.png` | - | 待验证 | 表情搜索键 | 🔴 待验证 |
| `表情搜索后的"全部表情".png` | - | 待验证 | 表情面板标题（搜索表情后出现，可点击下方表情直接发送） | 🔴 待验证 |
| ~~`发送-绿色.png`~~ | 45x19 | 0.6464 | ~~旧绿色发送按钮模板~~ | ❌ v6 已弃用（尺寸不符） |

**ico 图标资源**（v6 验证，1-5 都是微信图标不同尺寸）：

| 文件 | 尺寸 | 验证 conf | 说明 |
|------|------|-----------|------|
| `1.ico` | 16x16 | 0.8916 | 微信图标 16x16 |
| `2.ico` | 24x24 | 0.8711 | 微信图标 24x24 |
| `3.ico` | 32x32 | 0.8664 | 微信图标 32x32 |
| `4.ico` | 48x48 | 0.8616 | 微信图标 48x48 |
| `5.ico` | 64x64 | 0.8565 | 微信图标 64x64 |
| `6.ico` | 128x128 | - | 模板太大，不适用 |

**用户澄清（v3.0）**：1-5.ico 都是微信图标的不同尺寸缩放，和 6.ico 一样，**不是不同的导航栏功能图标**。导航栏功能图标需另外提取（如"对话-已激活.png"、"对话-未激活.png"）。

### 8.3 字体资源

- `C:/Windows/Fonts/msyh.ttc` — 微软雅黑（index=0: YaHei, index=1: YaHei UI）
- `C:/Windows/Fonts/msyhbd.ttc` — 微软雅黑 Bold

### 8.4 关键代码位置

- 搜索栏定位：`click_avatar_in_search_window.py` L96-179 `find_search_bar_in_image`
- 头像模板匹配：`click_avatar_in_search_window.py` L365-389 `find_template_multiscale`
- 发送按钮 OCR：`send_message_run.py` L68-103 `find_send_button_by_ocr`
- 发送按钮颜色：`send_message_run.py` L106-170 `find_send_button_from_bottom_right`
- OCR 引擎：`engine/importers/ocr_engine.py` L142-192 `ocr_image_array`
- 联系人解析：`mcp_server/tools_wechat.py` `_resolve_contact`
- 端到端流程：`engine/wechat_sender/wechat_e2e_run.py` `run_e2e`

### 8.5 PoC 脚本

- `engine/wechat_sender/_poc_font_matcher.py` — 字体匹配 PoC（已验证通过）
- `scripts/_annotate_ocr_temp.py` — OCR 标注脚本（中文版）
- `scripts/_test_paddleocr_temp.py` — PaddleOCR-VL 测试脚本
- `scripts/_test_cha_paddle_temp.py` — 茶.png PaddleOCR 测试

## 9. 实施自检清单

### 9.1 字体匹配自检清单

- [ ] 字体文件路径跨平台兼容（Windows 用 `C:/Windows/Fonts/msyh.ttc`，Linux/Mac 需替代）
- [ ] 多字号扫描覆盖微信所有 UI 字号（12-32px）
- [ ] 多颜色变体覆盖（黑色、深灰、白色）
- [ ] 搜索区域限定正确（避免全图扫描误匹配）
- [ ] 阈值设置合理（0.8 为默认，关键场景 0.85+）
- [ ] PoC 验证通过（茶 0.8879, 搜索 0.9483, 发送 1.0000）

### 9.2 数据库特征传递自检清单

- [ ] ContactProfile 数据结构定义清晰
- [ ] `_resolve_contact` 返回 ContactProfile
- [ ] `run_e2e` 接收并传递到各阶段
- [ ] 各阶段可用 profile.display_name / profile.alias
- [ ] 查询失败时有回退（纯 alias 搜索）

### 9.3 证据融合评分自检清单

- [ ] 权重设置合理（头像0.40 + 微信号0.25 + display_name0.20 + 几何0.15）
- [ ] 决策规则清晰（≥0.7 点击, <0.4 拒绝, 中间重试）
- [ ] 各证据来源独立（不重复计算）
- [ ] 证据缺失时有降级（如无 display_name 则权重重新归一化）

### 9.4 失败恢复自检清单

- [ ] 5 级降级链完整
- [ ] 每级降级有明确触发条件
- [ ] 最终级（Level 4）有 AskUserQuestion 请求用户介入
- [ ] 降级过程有日志记录

## 10. 端到端工作流

### 10.1 改造后的 wechat_send 完整流程（v3.0）

```
1. wechat_send(wxid, message)
   ↓
2. _resolve_contact(wxid) → ContactProfile
   - 查 core.db 获取 alias, display_name, avatar_path
   ↓
3. avatar_fetcher.get_avatar(wxid) → avatar_path
   - 本地缓存 → core.db → WeFlow API → contacts.json
   ↓
4. run_e2e(message, search_term=profile.alias, template_path=avatar_path, profile=profile)
   ↓
5. 阶段一：搜索 + 点击头像 + 验证
   5.1 _ensure_wechat_window() — 托盘图标唤醒
   5.2 find_search_bar_by_template_match() — 图标模板匹配 wx_icon/搜索栏.png [阶段4，v3.0]
       - 回退1：字体匹配"搜索"
       - 回退2：布局检测（白色判定）
   5.3 输入 profile.alias（如 [REDACTED]）
   5.4 find_section_headers_by_template() — 标题栏图标模板匹配 [阶段6，v3.0]
       - 最常使用.png / 群聊.png / 联系人.png
   5.5 compute_clickable_regions() — 计算可点击区域
   5.6 find_template_multiscale() — 在可点击区域内匹配头像
   5.7 verify_wxid_by_font_match(profile.alias) — 字体匹配微信号 [阶段6，display_name 专用]
       - 使用 match_long_text 分段匹配（V3 待验证）
   5.8 证据融合评分 → 决定是否点击
   5.9 点击头像
   5.10 verify_chat_interface(profile.display_name) — 字体匹配 display_name [阶段3，display_name 专用]
       - 字体匹配 + 绿色环 + 区域特征对比
   ↓
6. 阶段二：窗口数判定（1/2 窗口）
   ↓
7. 阶段三：输入消息 + 发送 + 验证
   7.1 找输入框（现有逻辑）
   7.2 输入 message
   7.3 find_send_button_by_template_match() — 图标模板匹配 [阶段5，v3.0]
       - 主要：send_green_full.png（可发送态）
       - 备选：发送-灰色.png（不可发送态）
       - 回退1：字体匹配"发送"
       - 回退2：绿色像素连通组件
   7.4 点击发送
   7.5 verify_message_sent(message) — OCR 验证（RapidOCR 或 PaddleOCR-VL）
   ↓
8. 返回结果
```

**v3.0 工作流调整说明**：
- 步骤 5.2：从"字体匹配'搜索'"改为"图标模板匹配 `搜索栏.png`"
- 步骤 5.4：标题栏检测从"字体匹配文字"改为"图标模板匹配（最常使用.png 等）"
- 步骤 5.7：微信号验证保留字体匹配（display_name 专用，因为微信号是可变文字）
- 步骤 5.10：display_name 验证保留字体匹配（核心场景，"茶" 0.8880）
- 步骤 7.3：从"字体匹配'发送'"改为"图标模板匹配 `send_green_full.png`"

### 10.2 失败恢复流程

```
Level 0: 完整流程失败
  ↓ 记录日志，进入 Level 1
Level 1: 简化搜索词（只搜 display_name）
  ↓ 失败，进入 Level 2
Level 2: 切换识别方式
  - 字体匹配 → OCR
  - OCR → 纯模板匹配
  - 模板匹配 → 颜色检测
  ↓ 失败，进入 Level 3
Level 3: CDP 刷新头像 + 重试
  ↓ 失败，进入 Level 4
Level 4: AskUserQuestion 请求用户介入
  - 提供错误详情
  - 提供选项：重试 / 切换联系人 / 终止
```
