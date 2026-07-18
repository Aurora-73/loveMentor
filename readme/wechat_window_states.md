# 微信窗口状态检测值记录

> 用途：校对窗口检测逻辑，用户把微信调到不同状态，运行 `check_wechat_state.py` 记录检测值。
> 规则：测试期间不改代码，所有状态测完后一次性修改。
> 测试顺序：按 ABC 大类 123 顺序

## 状态分类（笛卡尔积）

```
程序退出
├─ A: 进程未运行
│   └─ A1: 进程未运行（程序退出）

{未登录, 已登录} × ({有窗口} × {在前台, 在后台} ∪ {无窗口在任务栏图标})
├─ B: 未登录
│   ├─ B1: 未登录 + 有窗口 + 在前台
│   ├─ B2: 未登录 + 有窗口 + 在后台
│   └─ B3: 未登录 + 无窗口在任务栏图标（用户验证不存在，跳过）
├─ C: 已登录
│   ├─ C1: 已登录 + 有窗口 + 在前台
│   ├─ C2: 已登录 + 有窗口 + 在后台（最小化到任务栏/关闭回到任务栏）
│   └─ C3: 已登录 + 无窗口在任务栏图标（关闭到托盘）

特殊状态
├─ D: 特殊小窗口（搜索窗口等）
└─ E: 多开未登录（多个未登录窗口，不同进程）
```

## 任务栏结构（用户补充知识）

```
┌──────────────────────────────────────────────┐
│ 开始菜单 │ 应用窗口/固定图标区域 │ 系统托盘区域 │
└──────────────────────────────────────────────┘
```

- 微信后台图标在**系统托盘区域**
- 用户**不会固定微信到任务栏**
- 所以"应用窗口/固定图标区域"有微信图标 = 微信窗口存在（在前台或后台）
- "系统托盘区域"有微信图标 = 微信进程在运行（窗口可能可见/不可见）

## 微信图标匹配方式（用户要求）

- ❌ 不用 HSV 颜色匹配（可能误判其他绿色软件）
- ✅ 用 icon 模板匹配
- icon 路径：`<project_root>\engine\wechat_sender\wx_icon\`
- icon 文件：1.ico ~ 6.ico（6 个不同状态/尺寸的图标）

## 检测值记录

### A1: 进程未运行（程序退出）

**用户操作**：完全退出微信程序

**测试时间**：01:55:02

**检测结果**：

```
[状态判定] 进程未运行（程序退出）  ✅ 正确

[1] 进程状态:
    运行中: False
[2] 微信窗口（枚举所有，含不可见）: 0 个
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN' class='Chrome_WidgetWin_1'
[4] 托盘微信图标:
    找到: False
    扫描区域: (1338,1012) 573x60
```

**结论**：✅ 通过。进程未运行时所有检测值都正确（进程=False、窗口=0、托盘图标=False）。

---

### B1: 未登录 + 有窗口 + 在前台

**用户操作**：启动微信但未登录，窗口在前台

**用户补充特征**：未登录时左侧系统通知图标栏没有微信图标（后续需加入检测）

**测试时间**：01:57:11

**检测结果**：

```
[状态判定] 窗口正常显示并前台  ✅ 正确（但无法区分未登录/已登录）

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 4
    所有 PID: [35796, 29412, 24068, 2268]
[2] 微信窗口（枚举所有，含不可见）: 1 个
    #1: hwnd=2296990 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=35796
[3] 当前前台窗口:
    hwnd=2296990 title='微信' class='Qt51514QWindowIcon'
[4] 托盘微信图标:
    找到: False
    扫描区域: (1338,1012) 573x60
```

**关键观察**：
- 进程名识别正确（Weixin.exe，pid=35796）
- Snipaste 误判已排除（窗口列表只有 1 个微信窗口，没有被 Snipaste 污染）
- 托盘图标 = False（符合未登录状态：未登录时托盘没有微信图标）
- **未登录 vs 已登录的区分**：当前脚本无法区分，两者都是"窗口正常显示并前台"
  - 用户补充：未登录时"左侧系统通知图标栏"没有微信图标
  - 需要后续加入此特征检测

**结论**：✅ 窗口/进程检测通过。⚠️ 未登录/已登录区分需要补充"左侧系统通知图标栏"特征检测。

---

### B2: 未登录 + 有窗口 + 在后台

**用户操作**：启动微信但未登录，把窗口切到后台（点击其他窗口）

**测试时间**：01:58:20

**检测结果**：

```
[状态判定] 窗口正常显示但在后台  ✅ 正确

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 4
    所有 PID: [35796, 29412, 24068, 2268]
[2] 微信窗口（枚举所有，含不可见）: 1 个
    #1: hwnd=2296990 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=35796
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN' class='Chrome_WidgetWin_1'
[4] 托盘微信图标:
    找到: False
    扫描区域: (1338,1012) 573x60
```

**关键观察**：
- 状态判定正确：is_visible=True, is_iconic=False, 前台不是微信 → 后台
- 与 B1 唯一区别：前台窗口不同（B1=微信，B2=Trae）

**结论**：✅ 通过。前台/后台判定基于 GetForegroundWindow 准确有效。

---

### B3: 未登录 + 无窗口在任务栏图标

**用户验证**：此状态不存在（未登录状态下不能关闭到托盘），跳过

---

### C1: 已登录 + 有窗口 + 在前台

**用户操作**：登录微信，窗口在前台

**测试时间**：01:59:11

**检测结果**：

```
[状态判定] 窗口正常显示并前台  ✅ 正确

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 14
    所有 PID: [35796, 29412, 24068, 2268, 9140, 23208, 3616, 31644, 14588, 24136, 27840, 31640, 25416, 34084]
[2] 微信窗口（枚举所有，含不可见）: 2 个
    #1: hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(436,110,1612,855) size=1176x745 pid=35796
    #2: hwnd=6554052 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=35796
[3] 当前前台窗口:
    hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
    扫描区域: (1338,1012) 573x60
```

**关键观察（与 B1 对比）**：
- 进程数：4 → 14（登录后子进程大量增加）
- 窗口数：1 → 2（多了一个隐藏的 'Weixin' 窗口，size=218x247）
- 主窗口尺寸：368x484 → 1176x745（登录界面 vs 主界面）
- 托盘图标：False → True（登录后托盘出现微信图标）
- 主窗口 PID 不变（35796），说明是同一个进程

**未登录 vs 已登录区分特征**：
1. 托盘是否有微信图标（True=已登录，False=未登录）
2. 进程数（≥10=已登录，≤5=未登录）
3. 窗口数（2=已登录，1=未登录）
4. 主窗口尺寸（>1000 宽=已登录，<500 宽=未登录）
5. 隐藏窗口 'Weixin' 是否存在（已登录才有）
6. 用户补充：左侧系统通知图标栏是否有微信图标

**结论**：✅ 通过。已登录/未登录可通过托盘图标+窗口数+进程数+窗口尺寸多维度区分，托盘图标是最可靠的单一特征。

---

### C2: 已登录 + 有窗口 + 在后台（最小化到任务栏）

**用户操作**：登录微信，点击最小化按钮最小化到任务栏（或点击关闭回到任务栏）

**用户补充特征**：未登录窗口无法调解大小，长宽比固定（约 368:484 = 0.76），但可能被缩放

**第一次测试**（用户操作：点击关闭/最小化，状态意外）：

**测试时间**：02:02:04

**检测结果**：

```
[状态判定] 窗口不可见（关闭到托盘）  ⚠️ 与预期不符（用户准备的是 C2 后台）

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 2 个
    #1: hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False  ⚠️ 不可见且非最小化
        rect=(436,110,1612,855) size=1176x745 pid=35796
    #2: hwnd=6554052 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=35796
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN'
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- is_visible=False, is_iconic=False（窗口被隐藏，但不是 iconic 最小化状态）
- 这实际上是 C3 状态（关闭到托盘），不是 C2
- 可能原因：用户点击的是"关闭"按钮（关闭到托盘），或微信的"最小化"行为是隐藏窗口而非 iconic

**结论**：⚠️ 实际是 C3 状态。需要用户重新准备 C2（确保窗口仍可见 is_visible=True，只是失去焦点到后台）。

**第二次测试**（用户从托盘恢复窗口后点击其他窗口切到后台）：

**测试时间**：02:03:05

**检测结果**：

```
[状态判定] 窗口正常显示但在后台  ✅ 正确

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 2 个
    #1: hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False  ✅ 可见且非最小化
        rect=(436,110,1612,855) size=1176x745 pid=35796
    #2: hwnd=6554052 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=35796
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN'
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- is_visible=True, is_iconic=False（可见但失去焦点到后台）
- 与 C1 唯一区别：前台窗口不同（C1=微信，C2=Trae）
- 与 C3 唯一区别：is_visible（C2=True, C3=False）

**结论**：✅ 通过。C1/C2/C3 三态判定基于 is_visible + 前台窗口：
- C1：is_visible=True + 前台=微信
- C2：is_visible=True + 前台≠微信
- C3：is_visible=False

注意：微信的"最小化"按钮行为待测试（是否会触发 is_iconic=True），但目前测试的"关闭到托盘"是 is_visible=False 而非 is_iconic=True。

---

### C3: 已登录 + 无窗口在任务栏图标（关闭到托盘）

**用户操作**：登录微信，点击关闭按钮关闭到托盘（窗口不可见）

**测试时间**：02:02:04（与 C2 第一次测试同一次操作，实际是 C3 状态）

**检测结果**：

```
[状态判定] 窗口不可见（关闭到托盘）  ✅ 正确

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 2 个
    #1: hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False  ⚠️ 不可见且非最小化
        rect=(436,110,1612,855) size=1176x745 pid=35796
    #2: hwnd=6554052 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=35796
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN'
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- 关闭到托盘时 is_visible=False, is_iconic=False（不是最小化状态，是直接隐藏）
- 窗口仍存在于 EnumWindows 枚举中，只是不可见
- 窗口位置/尺寸保持关闭前的值（436,110,1612,855 size=1176x745）
- 托盘图标 = True

**结论**：✅ 通过。关闭到托盘的判定基于 is_visible=False（不是 is_iconic=True）。这是微信特有的行为——关闭按钮是隐藏窗口而非最小化。

---

### D: 特殊小窗口（搜索窗口等）

**用户操作**：打开微信搜索窗口（点击搜索栏或 Ctrl+F）

**测试时间**：02:04:06

**检测结果**：

```
[状态判定] 窗口正常显示并前台  ✅ 正确（主窗口在前台）

[1] 进程状态:
    运行中: True
    主 PID: 35796
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 3 个  ⚠️ 比平时多 1 个
    #1: hwnd=25038260 title='Weixin' class='Qt51514QWindowToolSaveBits'  ⚠️ 搜索窗口特征
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(505,189,965,694) size=460x505 pid=35796
    #2: hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(436,110,1612,855) size=1176x745 pid=35796
    #3: hwnd=6554052 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=35796
[3] 当前前台窗口:
    hwnd=4919102 title='微信' class='Qt51514QWindowIcon'
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- **搜索窗口特征**：
  - class = `Qt51514QWindowToolSaveBits`（含 `ToolSaveBits`，与主窗口的 `WindowIcon` 不同）
  - title = 'Weixin'（与主窗口的 '微信' 不同）
  - size = 460x505（比主窗口小，比隐藏窗口大）
  - is_visible = True（可见）
- 状态判定仍为"窗口正常显示并前台"——因为脚本优先选 title='微信' 的主窗口作为 main_win
- 搜索窗口不影响主窗口状态判定，但可通过 class 含 'ToolSaveBits' 单独识别

**结论**：✅ 通过。搜索窗口可通过 class 含 'ToolSaveBits' 识别，不影响主窗口状态判定。
**改进建议**：可在 detect_state 中额外识别搜索窗口（class 含 'ToolSaveBits'），用于区分"主窗口在前台 + 搜索窗口打开"的状态。

---

### D2: 历史聊天界面窗口（搜索聊天记录）

**用户操作**：在某个聊天中点击右上角菜单 → 查找聊天记录，打开"搜索聊天记录"独立窗口

**测试时间**：02:09:29

**检测结果**：

```
[状态判定] 窗口正常显示但在后台  ⚠️ 误判（前台实际是历史聊天界面）

[1] 进程状态:
    运行中: True
    主 PID: 20984
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 3 个
    #1: hwnd=3346170 title='搜索聊天记录' class='Qt51514QWindowIcon'  ⚠️ 历史聊天界面
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(496,105,1414,914) size=918x809 pid=20984
    #2: hwnd=1445714 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(436,110,1612,855) size=1176x745 pid=20984
    #3: hwnd=1508338 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=20984
[3] 当前前台窗口:
    hwnd=3346170 title='搜索聊天记录' class='Qt51514QWindowIcon'  ⚠️ 前台是历史聊天界面
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- **历史聊天界面特征**：
  - title = '搜索聊天记录'（与主窗口 '微信' 不同）
  - class = `Qt51514QWindowIcon`（与主窗口相同，**不是 ToolSaveBits**）
  - size = 918x809（比主窗口小）
  - is_visible = True（可见）
- **行为说明**：脚本选 title='微信' 的主窗口作为 main_win，主窗口不在前台 → 判为"后台"
  - 这是合理的判定（用户确认：主窗口确实在后台，前台是历史聊天界面）
  - 但需要额外返回"哪个微信窗口在前台"的信息，便于自动化脚本决策

**结论**：✅ 通过（用户确认主窗口确实在后台）。状态判定关注主窗口状态，符合预期。
**改进建议**：在状态返回信息中额外标注"前台窗口是否是微信相关窗口"（基于 PID 匹配）。

---

### D3: 私聊独立窗口（联系人聊天窗口被单独打开）

**用户操作**：从主窗口拖出某个联系人的聊天，或双击聊天打开独立小窗口

**测试时间**：02:13:27

**检测结果**：

```
[状态判定] 窗口正常显示但在后台  ✅ 正确（主窗口在后台）

[1] 进程状态:
    运行中: True
    主 PID: 20984
    进程数: 14
[2] 微信窗口（枚举所有，含不可见）: 3 个
    #1: hwnd=4456532 title='[REDACTED]' class='Qt51514QWindowIcon'  ⚠️ 私聊独立窗口
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(626,130,1387,892) size=761x762 pid=20984
    #2: hwnd=1445714 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(436,110,1612,855) size=1176x745 pid=20984
    #3: hwnd=1508338 title='Weixin' class='Qt51514QWindowIcon'
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=20984
[3] 当前前台窗口:
    hwnd=4456532 title='[REDACTED]' class='Qt51514QWindowIcon'  ⚠️ 前台是私聊独立窗口
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- **私聊独立窗口特征**：
  - title = 联系人名（'[REDACTED]'，与主窗口 '微信' 不同）
  - class = `Qt51514QWindowIcon`（与主窗口相同）
  - size = 761x762（比主窗口小，比历史聊天界面小）
  - is_visible = True（可见）
  - pid 与主窗口相同（同一进程的子窗口）
- 主窗口在后台，私聊独立窗口在前台

**结论**：✅ 通过。状态判定关注主窗口状态（后台），符合预期。
**与 D2 的区别**：
- D2 历史聊天界面 title='搜索聊天记录'（固定）
- D3 私聊独立窗口 title=联系人名（动态）
- 两者 class 都是 'Qt51514QWindowIcon'，无法通过 class 区分
- 都需要通过 PID 匹配判断是否是微信相关窗口

---

### E: 多开未登录

**用户操作**：启动多个微信实例，都未登录

**用户补充**：还有混合状态（一个已登录 + 多个未登录），以及多个已登录（需用户自己保证，不常见）

**测试时间**：02:06:17

**检测结果**：

```
[状态判定] 窗口正常显示但在后台  ⚠️ 未识别多开（只判定为后台）

[1] 进程状态:
    运行中: True
    主 PID: 5720
    进程数: 6
    所有 PID: [5720, 18604, 27856, 13052, 20984, 8904]
[2] 微信窗口（枚举所有，含不可见）: 3 个  ⚠️ 多开特征
    #1: hwnd=11340328 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=8904
    #2: hwnd=1836994 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=20984
    #3: hwnd=2492240 title='微信' class='Qt51514QWindowIcon'
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=5720
[3] 当前前台窗口:
    hwnd=28707440 title='wechat_state_records.md - loveMentor - Trae CN'
[4] 托盘微信图标:
    找到: False
```

**关键观察**：
- **多开特征**：3 个窗口都是 title='微信'，但 PID 不同（8904, 20984, 5720）
- 所有窗口位置完全相同（772,269,1140,753）——窗口重叠
- 所有窗口尺寸都是 368x484（未登录固定尺寸，符合用户补充的"长宽比固定"）
- 进程数 = 6（每个微信实例约 2 个进程）
- 托盘图标 = False（未登录时托盘没有图标）
- 当前脚本判定为"窗口正常显示但在后台"——没有识别多开

**多开识别方法**：
- 统计不同 PID 的微信主窗口数（title='微信'）
- ≥2 个不同 PID 的主窗口 = 多开
- 主进程 PID 选择策略待定（取第一个？还是按窗口顺序？）

**结论**：⚠️ 当前脚本未识别多开状态。需要改进：统计不同 PID 的微信主窗口数，≥2 个即为多开。

**未测试的混合状态**：
- 一个已登录 + 多个未登录（需用户手动准备）
- 多个已登录（需用户自己保证，不常见）

---

### F: 混合状态（一个已登录 + 多个未登录）

**用户操作**：启动一个微信并登录，同时启动多个微信实例但不登录

**测试时间**：02:16:46

**检测结果**：

```
[状态判定] 窗口正常显示并前台  ✅ 正确（已登录主窗口在前台）

[1] 进程状态:
    运行中: True
    主 PID: 20984
    进程数: 19  ⚠️ 比单独已登录（14）多 5
    所有 PID: [20984, 28140, 35260, 32088, 34964, 19044, 9540, 7764, 23688, 20772, 35252, 35904, 36648, 11752, 35776, 35540, 21400, 18480, 34640]
[2] 微信窗口（枚举所有，含不可见）: 4 个  ⚠️ 多开+混合
    #1: hwnd=1445714 title='微信' class='Qt51514QWindowIcon'  ✅ 已登录主窗口
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(436,110,1612,855) size=1176x745 pid=20984
    #2: hwnd=1708072 title='微信' class='Qt51514QWindowIcon'  ⚠️ 未登录窗口 1
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=34640
    #3: hwnd=6294506 title='微信' class='Qt51514QWindowIcon'  ⚠️ 未登录窗口 2
        is_window=True is_visible=True is_iconic=False is_zoomed=False
        rect=(772,269,1140,753) size=368x484 pid=35776
    #4: hwnd=1508338 title='Weixin' class='Qt51514QWindowIcon'  ✅ 已登录的隐藏子窗口
        is_window=True is_visible=False is_iconic=False is_zoomed=False
        rect=(847,368,1065,615) size=218x247 pid=20984
[3] 当前前台窗口:
    hwnd=1445714 title='微信' class='Qt51514QWindowIcon'  ✅ 已登录主窗口
[4] 托盘微信图标:
    找到: True
    位置: (1679, 1042)
```

**关键观察**：
- **混合状态特征**：
  - 4 个微信窗口，3 个不同 PID（20984 已登录, 34640 未登录, 35776 未登录）
  - 已登录窗口尺寸 1176x745（pid=20984）
  - 未登录窗口尺寸 368x484（pid=34640, 35776）
  - 隐藏子窗口 'Weixin' 只在已登录进程下出现（pid=20984）
  - 进程数 19（已登录 14 + 未登录 5）
- **状态判定正确**：脚本选 title='微信' 中面积最大的窗口作为 main_win（1176x745 > 368x484），所以选了已登录主窗口
- **未识别多开**：当前脚本没有识别出多开状态

**混合状态识别方法**：
- 统计不同 PID 的 title='微信' 窗口数（≥2 个不同 PID = 多开）
- 对每个窗口单独判定登录状态：
  - 尺寸 > 1000 宽 → 已登录
  - 尺寸 < 500 宽 → 未登录
  - 同 PID 下有隐藏子窗口 'Weixin' → 已登录

**结论**：✅ 状态判定正确（已登录主窗口在前台）。⚠️ 未识别多开，需要改进。

---

## 测试总结

### 各状态检测结果

| 状态 | 描述 | 检测结果 | 备注 |
|------|------|----------|------|
| A1 | 进程未运行 | ✅ 通过 | 进程=False、窗口=0、托盘=False |
| B1 | 未登录+前台 | ✅ 通过 | 无法区分未登录/已登录 |
| B2 | 未登录+后台 | ✅ 通过 | 前台≠微信 |
| B3 | 未登录+无窗口 | 跳过 | 用户验证不存在 |
| C1 | 已登录+前台 | ✅ 通过 | 前台=微信 |
| C2 | 已登录+后台 | ✅ 通过（重测） | is_visible=True + 前台≠微信 |
| C3 | 已登录+关闭到托盘 | ✅ 通过 | is_visible=False |
| D  | 搜索窗口（ToolSaveBits） | ✅ 通过 | class 含 'ToolSaveBits' |
| D2 | 历史聊天界面 | ✅ 通过 | title='搜索聊天记录'，class='Qt51514QWindowIcon' |
| D3 | 私聊独立窗口 | ✅ 通过 | title=联系人名，class='Qt51514QWindowIcon' |
| E  | 多开未登录 | ⚠️ 未识别多开 | 需改进：统计不同 PID 的主窗口数 |
| F  | 混合状态（1 已登录 + 多个未登录） | ✅ 状态判定正确 | 已登录主窗口在前台，未识别多开 |

### 关键发现

1. **未登录 vs 已登录区分**（当前脚本未区分）：
   - 托盘图标（False=未登录，True=已登录）—— 最可靠
   - 进程数（≤6=未登录，≥10=已登录）
   - 窗口数（1=未登录，2=已登录，3=已登录+搜索窗口）
   - 主窗口尺寸（368x484=未登录，1176x745=已登录）
   - 隐藏窗口 'Weixin' 是否存在（已登录才有）
   - 未登录窗口长宽比固定（约 0.76），无法调整大小

2. **微信"关闭"按钮行为**：隐藏窗口（is_visible=False），不是最小化（is_iconic=False）
   - 微信没有真正的"最小化到任务栏"行为，关闭=隐藏到托盘

3. **微信子窗口类型识别**：
   - 搜索窗口（D）：class 含 'ToolSaveBits'，title='Weixin'
   - 历史聊天界面（D2）：title='搜索聊天记录'，class='Qt51514QWindowIcon'
   - 私聊独立窗口（D3）：title=联系人名（动态），class='Qt51514QWindowIcon'
   - 隐藏子窗口：title='Weixin'，class='Qt51514QWindowIcon'，is_visible=False

4. **多开特征**：多个 title='微信' 窗口但 PID 不同

5. **Snipaste 误判已修复**：通过进程名验证排除

6. **未测试的混合状态**：一个已登录 + 多个未登录（待用户手动准备）

7. **前台判定基于 title='微信' 的局限性**：
   - 当前台是微信子窗口（搜索聊天记录/私聊独立窗口等）时，主窗口在后台
   - 状态判定返回"后台"是正确的（主窗口确实在后台）
   - 但自动化脚本可能需要知道"哪个微信窗口在前台"，建议额外返回前台窗口的 PID 信息

## 代码改进计划

### 改进 1：托盘检测 HSV → icon 模板匹配

- **当前**：`check_tray_icon()` 用 HSV 颜色匹配（可能误判其他绿色软件）
- **改进**：用 `wx_icon/1.ico` ~ `6.ico` 模板匹配
- **影响文件**：`scripts/check_wechat_state.py`、`engine/wechat_sender/open_wechat_window.py`

### 改进 2：增加任务栏"应用窗口/固定图标区域"检测（⚠️ 优先级低，仅作 fallback）

- **目的**：检测微信窗口是否在任务栏（用户不会固定微信到任务栏，所以任务栏有图标=窗口存在）
- **方法**：截取任务栏"应用窗口/固定图标区域"，用 icon 模板匹配
- **用途**：作为窗口 API 的 fallback，不作为核心
- **⚠️ 优先级低的原因**（ChatGPT 反馈）：
  - Windows 任务栏状态不可靠：合并按钮、隐藏任务栏、DPI 缩放、主题变化、多显示器
  - 窗口 API（EnumWindows/IsWindowVisible/GetForegroundWindow）已完全覆盖检测需求
  - 任务栏检测只能作为 fallback，不作为核心

### 改进 3：增加未登录/已登录区分

- **方法**：基于托盘图标 + 窗口数 + 进程数 + 窗口尺寸 + 隐藏窗口 'Weixin' 综合判定
- **优先级**：托盘图标是最可靠的单一特征

### 改进 4：增加多开识别

- **方法**：统计不同 PID 的微信主窗口数（title='微信'），≥2 个即为多开
- **状态判定**：返回主窗口列表 + 各窗口的 PID/登录状态

### 改进 5：增加微信子窗口类型识别

- **方法**：基于 title 和 class 综合判定子窗口类型
  - 搜索窗口：class 含 'ToolSaveBits'
  - 历史聊天界面：title='搜索聊天记录'
  - 私聊独立窗口：title 不在已知列表中（联系人名）+ class='Qt51514QWindowIcon' + PID=微信主进程
  - 隐藏子窗口：title='Weixin' + is_visible=False
- **状态判定**：在状态返回信息中额外标注子窗口列表（类型+hwnd+title+pid）

### 改进 6：增加前台窗口 PID 匹配

- **目的**：辅助判断"哪个微信窗口在前台"
- **方法**：检测前台窗口的 PID 是否是微信进程的 PID
- **返回信息**：前台窗口是否是微信相关窗口（基于 PID 匹配）

### 改进 7：增加"左侧系统通知图标栏"特征检测（用户补充）

- **目的**：辅助区分未登录/已登录（未登录时左侧没有微信图标）
- **方法**：截取微信窗口左侧区域，检测是否有微信图标
- **备注**：此特征是用户补充的，需要进一步确认具体位置和检测方法

### 改进 8：状态判定逻辑优化

新状态判定逻辑：
```
1. 进程未运行 → A1
2. 进程运行 + 无可见窗口 + 托盘有图标 → C3（关闭到托盘）
3. 进程运行 + 可见窗口 + 前台=微信 → C1/B1（前台）
4. 进程运行 + 可见窗口 + 前台≠微信 → C2/B2（后台）
5. 多个不同 PID 的主窗口 → E（多开）
6. 子窗口识别：
   - class 含 'ToolSaveBits' → 搜索窗口（D）
   - title='搜索聊天记录' → 历史聊天界面（D2）
   - title 不在已知列表 → 私聊独立窗口（D3）

区分 B/C（未登录/已登录）：
- 托盘图标（True=已登录）
- 窗口数（2=已登录，1=未登录）
- 主窗口尺寸（>1000 宽=已登录）
```


