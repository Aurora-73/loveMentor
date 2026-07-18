"""
端到端微信自动化流程：搜索联系人 → 点击头像 → 验证 → 输入发送消息。

整合阶段一/二/三：
- 阶段一：搜索栏点击+输入+搜索候选框匹配+点击头像+绿色环验证（含重试）
  来源：click_avatar_in_search_window.run_one_attempt
- 阶段二：根据聊天窗口数判定（精确统计，排除搜索候选框）
  - 1 个窗口 → 联系人聊天界面，直接进入阶段三
  - 2 个窗口 → 历史聊天界面（"搜索聊天记录"窗口），需在新弹出的窗口
              上再次匹配头像+双击，然后关闭该窗口，进入阶段三
- 阶段三：输入消息+找绿色发送按钮+点击发送
  来源：send_message_run.run_send_message

用法：
    python E:\\Code\\MaaFramework\\examples\\wechat_auto\\wechat_e2e_run.py "<消息内容>"
"""
import os
import sys
import time

import ctypes
import ctypes.wintypes as wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from click_avatar_in_search_window import (  # noqa: E402
    run_one_attempt,
    scroll_in_main_middle_column,
    find_template_multiscale,
    MAX_ATTEMPTS,
    MAX_RETRIES,
)
from send_message_run import run_send_message  # noqa: E402
from test_current_wechat import screencap_window  # noqa: E402
from wechat_window_utils import count_chat_windows, find_history_chat_window  # noqa: E402  统一窗口枚举
from click_search_and_input import client_to_screen, physical_click, safe_set_foreground_window, get_client_offset  # noqa: E402

user32 = ctypes.windll.user32

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
# 头像模板目录：data/avatars/（项目级共享）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES_DIR = os.path.join(_PROJECT_ROOT, "data", "avatars")

# 截图清理配置：保留最近 N 个文件
MAX_OUTPUT_FILES = 50
MAX_SCREENSHOT_FILES = 30


def cleanup_old_screenshots():
    """清理旧的截图文件，只保留最近的 N 个。

    清理两个目录：
    - outputs/：保留最近 MAX_OUTPUT_FILES 个
    - screenshots/：保留最近 MAX_SCREENSHOT_FILES 个
    """
    import glob

    for dir_path, max_files in [(OUTPUT_DIR, MAX_OUTPUT_FILES),
                                 (SCREENSHOTS_DIR, MAX_SCREENSHOT_FILES)]:
        if not os.path.exists(dir_path):
            continue
        files = glob.glob(os.path.join(dir_path, "*.png"))
        if len(files) <= max_files:
            continue
        # 按修改时间排序，删除最旧的
        files.sort(key=lambda f: os.path.getmtime(f))
        to_delete = files[:-max_files] if max_files > 0 else files
        for f in to_delete:
            try:
                os.remove(f)
            except Exception:
                pass
        if to_delete:
            logger.info(f"    [清理] 删除 {len(to_delete)} 个旧截图（{dir_path}）")

# 修复 P1-1/P1-3：从 config.py 导入统一配置，删除重复定义
from config import MATCH_THRESHOLD, TEMPLATE_SCALES, NMS_MIN_DIST

from logger import get_logger  # noqa: E402
logger = get_logger(__name__)

# 鼠标事件常量
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def close_window(hwnd):
    """关闭窗口（发送 WM_CLOSE）"""
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def physical_double_click(screen_x, screen_y):
    """物理双击屏幕坐标。

    已委托给 human_sim.human_physical_double_click，默认带 3px 随机抖动和随机间隔，
    模拟人类双击行为，降低被封号风险。
    """
    from human_sim import human_physical_double_click
    human_physical_double_click(screen_x, screen_y, jitter_radius=3)


def handle_stage_2_history_window(attempt_idx, template_path):
    """阶段二：处理历史聊天界面（2 个窗口的情况）。

    流程：
    1. 找到"搜索聊天记录"窗口
    2. 在该窗口内截图 + 多尺度匹配头像
    3. 双击头像（会跳转到该联系人聊天界面）
    4. 关闭"搜索聊天记录"窗口

    Args:
        attempt_idx: 尝试编号（用于输出文件命名）
        template_path: 联系人头像模板路径
    """
    logger.info("\n[阶段二] 处理历史聊天界面（2 个窗口）")

    history_win = find_history_chat_window()
    if not history_win:
        logger.error("    ❌ 未找到'搜索聊天记录'窗口")
        return False

    hwnd_history = history_win["hwnd"]
    logger.info(f"    历史聊天窗口: hwnd={hwnd_history} "
          f"size={history_win['width']}x{history_win['height']} "
          f"rect=({history_win['left']},{history_win['top']},{history_win['right']},{history_win['bottom']})")

    # 截图
    img = screencap_window(hwnd_history)
    if img is None:
        logger.error("    ❌ 历史聊天窗口截图失败")
        return False

    img_path = os.path.join(OUTPUT_DIR, f"stage_2_history_window_{attempt_idx}.png")
    cv2.imwrite(img_path, img)
    logger.info(f"    历史窗口截图: {img_path} ({img.shape[1]}x{img.shape[0]})")

    # 多尺度匹配头像
    points, best_score = find_template_multiscale(
        img, template_path, TEMPLATE_SCALES, MATCH_THRESHOLD, NMS_MIN_DIST
    )
    if not points:
        logger.error(f"    ❌ 历史聊天窗口内未匹配到头像 (最高置信度={best_score:.3f})")
        return False

    logger.info(f"    匹配到 {len(points)} 个头像:")
    for i, (x, y, s, sc) in enumerate(points):
        logger.info(f"      #{i}: ({x}, {y}) conf={s:.3f} scale={sc}px")

    # 修复 P1-5：阶段二选点逻辑与阶段一统一，先过滤低置信度点
    high_conf_points = [p for p in points if p[2] >= MATCH_THRESHOLD]
    if high_conf_points:
        target = max(high_conf_points, key=lambda p: p[2])
        logger.info(f"    选中(置信度最高, >= {MATCH_THRESHOLD}): ({target[0]}, {target[1]}) "
              f"conf={target[2]:.3f} scale={target[3]}px")
    else:
        logger.warning(f"    ⚠️ 所有匹配点置信度 < {MATCH_THRESHOLD}，回退到最高置信度")
        target = max(points, key=lambda p: p[2])
        logger.info(f"    选中(回退-置信度最高): ({target[0]}, {target[1]}) "
              f"conf={target[2]:.3f} scale={target[3]}px")

    # 画匹配结果图
    out = img.copy()
    half = target[3] // 2
    cv2.rectangle(out, (target[0] - half, target[1] - half),
                  (target[0] + half, target[1] + half), (0, 0, 255), 3)
    cv2.putText(out, f"DBLCLICK ({target[0]},{target[1]})",
                (target[0] + 30, target[1] + 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    match_path = os.path.join(OUTPUT_DIR, f"stage_2_match_{attempt_idx}.png")
    cv2.imwrite(match_path, out)
    logger.info(f"    匹配结果图: {match_path}")

    # 双击头像（屏幕坐标）— 修复 P0-4：减去客户区偏移
    offset_x, offset_y = get_client_offset(hwnd_history)
    screen_x, screen_y = client_to_screen(hwnd_history, target[0] - offset_x, target[1] - offset_y)
    logger.info(f"    双击屏幕坐标: ({screen_x}, {screen_y})")
    if not safe_set_foreground_window(hwnd_history):
        logger.warning(f"    ⚠️ 无法将历史聊天窗口设为前台，继续尝试双击")
    time.sleep(0.5)
    physical_double_click(screen_x, screen_y)
    time.sleep(1.0)

    # 关闭历史聊天窗口
    logger.info(f"    关闭历史聊天窗口 hwnd={hwnd_history}")
    close_window(hwnd_history)
    time.sleep(0.8)

    # 验证：再次统计聊天窗口数（应该只剩主窗口=1）
    chat_count, chat_wins = count_chat_windows()
    logger.info(f"    关闭后聊天窗口数: {chat_count}")
    for w in chat_wins:
        logger.info(f"    - hwnd={w['hwnd']} title={w['title']!r}")

    if chat_count == 1:
        logger.info("    ✅ 阶段二完成：已进入联系人聊天界面")
        return True
    else:
        logger.warning(f"    ⚠️ 关闭后窗口数={chat_count}（预期 1），但继续尝试阶段三")
        return True


def rollback_wechat_state():
    """回滚微信状态，清除残留输入和搜索栏。

    在流程失败时调用，确保下次重试不受残留状态影响：
    1. 按 Esc 关闭搜索候选框
    2. 按 Esc 清除搜索栏文字
    3. 点击聊天输入框区域清除焦点
    """
    logger.info("\n[回滚] 清理微信残留状态...")
    KEYEVENTF_KEYUP = 0x0002
    VK_ESCAPE = 0x1B

    # 连按3次 Esc，关闭搜索候选框和清除搜索栏
    for i in range(3):
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
    logger.info("    [回滚] 已按 Esc 清理搜索栏/候选框")
    time.sleep(0.3)


def _file_hash(file_path):
    """计算文件内容的 MD5 哈希（用于比较新旧头像是否相同）。"""
    import hashlib
    try:
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _refresh_avatar_and_maybe_retry(contact_name, template_path, message):
    """阶段一全部失败后，更新头像并检测变化，决定是否自动重试。

    用户需求：
    - 不要每次发消息都更新头像
    - 连续重试失败后，返回失败消息前更新头像
    - 检测新旧头像是否一样：
      - 一样 → 不重试（头像不是问题），返回 False
      - 不一样 → 自动重试发送流程，不通知 agent

    Args:
        contact_name: 联系人标识符（用于查询头像）
        template_path: 原头像模板路径
        message: 要发送的消息（重试时用）

    Returns:
        tuple (success: bool, new_template_path: str)
        - success=True: 头像更新后重试成功
        - success=False, new_template_path=template_path: 头像未变或重试仍失败
    """
    logger.info("\n[头像更新] 阶段一失败，尝试更新头像后重试...")

    # 1. 记录旧头像 hash
    old_hash = _file_hash(template_path) if os.path.exists(template_path) else ""
    logger.info(f"   旧头像: {template_path} hash={old_hash[:8] if old_hash else 'N/A'}")

    # 2. 强制更新头像
    # 注意：contact_name 可能是搜索名（微信号/alias），avatar_fetcher 查不到时
    # 回退用 template_path 的文件名（通常是 display_name）查询
    try:
        from engine.wechat_data.avatar_fetcher import get_avatar
        new_path = get_avatar(contact_name, force_refresh=True)
        if not new_path or not os.path.exists(new_path):
            # 回退：用 template_path 的文件名（stem）作为标识符
            fallback_name = os.path.splitext(os.path.basename(template_path))[0]
            logger.info(f"   用搜索名 '{contact_name}' 查询失败，回退用 '{fallback_name}' 查询")
            new_path = get_avatar(fallback_name, force_refresh=True)
        if not new_path or not os.path.exists(new_path):
            logger.warning(f"   ⚠️ 头像更新失败：未获取到 {contact_name} 的新头像")
            return False, template_path
        logger.info(f"   新头像: {new_path}")
    except Exception as e:
        logger.warning(f"   ⚠️ 头像更新异常: {e}")
        return False, template_path

    # 3. 比较新旧头像
    new_hash = _file_hash(new_path)
    logger.info(f"   新头像 hash={new_hash[:8] if new_hash else 'N/A'}")

    if old_hash and old_hash == new_hash:
        logger.info(f"   ℹ️ 新旧头像相同（hash 一致），头像未变化，无需重试")
        return False, template_path

    logger.info(f"   🔄 检测到头像已变化（hash 不同），自动重试发送流程...")

    # 4. 头像变了，用新头像重新执行端到端流程
    # 注意：不通知 agent，静默重试
    # 先回滚微信状态
    rollback_wechat_state()
    time.sleep(1.0)

    # 重新执行阶段一（只重试一次，避免无限循环）
    logger.info("\n" + "#" * 60)
    logger.info("#  [头像更新后重试] 阶段一：搜索+点击头像+绿色环验证")
    logger.info("#" * 60)

    retry_success = False
    retry_target = None
    retry_count_after = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # 每次尝试前确保微信窗口存在
        from wechat_window_utils import find_wechat_window as _find_wx
        if not _find_wx():
            logger.info(f"\n[头像更新后-窗口唤醒] 微信窗口不存在，尝试唤醒...")
            try:
                from open_wechat_window import open_wechat_window_robust
                if open_wechat_window_robust(timeout=10.0):
                    logger.info(f"   ✅ 微信窗口已唤醒")
                    time.sleep(0.5)
            except Exception as e:
                logger.warning(f"   ⚠️ 窗口唤醒异常: {e}")

        if attempt > 1:
            logger.info("\n[重试预备] 清理搜索栏残留状态 + 滚动+点击...")
            KEYEVENTF_KEYUP = 0x0002
            for _ in range(2):
                user32.keybd_event(0x1B, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(0x1B, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
            time.sleep(0.3)
            scroll_in_main_middle_column()
            time.sleep(0.5)

        success, target, count_after = run_one_attempt(
            attempt, MAX_ATTEMPTS, do_click=True,
            contact_name=contact_name, template_path=new_path,
        )

        if success:
            retry_success = True
            retry_target = target
            retry_count_after = count_after
            break
        else:
            logger.error(f"\n❌ [头像更新后] 第 {attempt} 次尝试失败")
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.5)

    if not retry_success:
        logger.error(f"\n❌ [头像更新后] 阶段一仍然失败（{MAX_ATTEMPTS} 次尝试）")
        rollback_wechat_state()
        return False, new_path

    logger.info(f"\n✅ [头像更新后] 阶段一成功（第 {attempt} 次尝试）")

    # 阶段二
    chat_count, chat_wins = count_chat_windows()
    logger.info(f"   聊天窗口数: {chat_count}")
    if chat_count == 2:
        stage2_ok = handle_stage_2_history_window(attempt, new_path)
        if not stage2_ok:
            logger.error("   ❌ [头像更新后] 阶段二失败")
            rollback_wechat_state()
            return False, new_path

    # 阶段三
    stage3_ok = run_send_message(message, do_send=True)
    if not stage3_ok:
        logger.error("   ❌ [头像更新后] 阶段三失败")
        rollback_wechat_state()
        return False, new_path

    logger.info("\n  ✅ [头像更新后] 端到端流程全部成功")
    return True, new_path


def run_e2e(message, contact_name, template_path):
    """端到端流程：阶段一 → 阶段二 → 阶段三

    Args:
        message: 要发送的消息内容
        contact_name: 联系人昵称（用于搜索栏输入）
        template_path: 联系人头像模板路径
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 清理旧截图，避免文件无限增长
    cleanup_old_screenshots()

    logger.info("=" * 60)
    logger.info("  端到端微信自动化流程")
    logger.info(f"  联系人: {contact_name!r}")
    logger.info(f"  模板: {template_path}")
    logger.info(f"  消息: {message!r}")
    logger.info(f"  最多尝试次数: {MAX_ATTEMPTS}（初次 + {MAX_RETRIES} 次重试）")
    logger.info("=" * 60)

    # ========== 阶段一：搜索+点击头像+绿色环验证（含重试） ==========
    logger.info("\n" + "#" * 60)
    logger.info("#  阶段一：搜索+点击头像+绿色环验证（含重试）")
    logger.info("#" * 60)

    stage1_success = False
    final_count_after = 0
    final_target = None
    attempt_idx = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_idx = attempt

        # 每次尝试前确保微信窗口存在，不存在则通过托盘图标唤醒
        from wechat_window_utils import find_wechat_window
        if not find_wechat_window():
            logger.info(f"\n[窗口唤醒] 微信窗口不存在，尝试通过托盘图标唤醒...")
            try:
                from open_wechat_window import open_wechat_window_robust
                if open_wechat_window_robust(timeout=10.0):
                    logger.info(f"   ✅ 微信窗口已唤醒")
                    time.sleep(0.5)
                else:
                    logger.warning(f"   ⚠️ 微信窗口唤醒失败，继续尝试（可能 PrintWindow 仍能工作）")
            except Exception as e:
                logger.warning(f"   ⚠️ 微信窗口唤醒异常: {e}")

        if attempt > 1:
            logger.info("\n[重试预备] 清理搜索栏残留状态 + 滚动+点击...")
            # 先按 Esc 关闭可能残留的搜索候选框和搜索栏
            # VK_ESCAPE = 0x1B，连按两次确保关闭搜索栏
            KEYEVENTF_KEYUP = 0x0002
            for _ in range(2):
                user32.keybd_event(0x1B, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(0x1B, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.1)
            time.sleep(0.3)
            scroll_in_main_middle_column()
            time.sleep(0.5)

        success, target, count_after = run_one_attempt(
            attempt, MAX_ATTEMPTS, do_click=True,
            contact_name=contact_name, template_path=template_path,
        )

        if not success:
            logger.error(f"\n❌ 第 {attempt} 次尝试失败")
            if attempt < MAX_ATTEMPTS:
                logger.info(f"   0.5 秒后将进行第 {attempt + 1} 次尝试...")
                time.sleep(0.5)
            continue

        # 绿色环验证成功
        stage1_success = True
        final_count_after = count_after
        final_target = target
        break

    if not stage1_success:
        logger.error(f"\n❌ 阶段一失败：{MAX_ATTEMPTS} 次尝试全部失败")
        # 用户需求：连续重试失败后，更新头像并检测变化，决定是否自动重试
        # - 头像未变 → 不重试（头像不是问题），直接返回失败
        # - 头像变了 → 自动重试发送流程，不通知 agent
        retry_success, new_template = _refresh_avatar_and_maybe_retry(
            contact_name, template_path, message
        )
        if retry_success:
            return True
        # 头像未变或重试仍失败，返回失败
        return False

    logger.info(f"\n✅ 阶段一成功（第 {attempt_idx} 次尝试）")
    if final_target:
        logger.info(f"   匹配点: ({final_target[0]}, {final_target[1]}) "
              f"conf={final_target[2]:.3f}")

    # ========== 阶段二：根据聊天窗口数判定 ==========
    logger.info("\n" + "#" * 60)
    logger.info("#  阶段二：窗口数判定")
    logger.info("#" * 60)

    # 用精确的 count_chat_windows 重新统计（排除搜索候选框）
    chat_count, chat_wins = count_chat_windows()
    logger.info(f"   聊天窗口数（排除搜索候选框）: {chat_count}")
    for w in chat_wins:
        logger.info(f"   - hwnd={w['hwnd']} title={w['title']!r} "
              f"class={w['class']!r}")

    if chat_count == 1:
        logger.info("   分支: 1 个窗口 → 联系人聊天界面，直接进入阶段三")
    elif chat_count == 2:
        logger.info("   分支: 2 个窗口 → 历史聊天界面，需再次匹配+双击")
        stage2_ok = handle_stage_2_history_window(attempt_idx, template_path)
        if not stage2_ok:
            logger.error("   ❌ 阶段二失败")
            rollback_wechat_state()
            return False
        logger.info("   ✅ 阶段二成功")
    else:
        logger.warning(f"   ⚠️ 未预期的窗口数: {chat_count}，尝试继续进入阶段三")

    # ========== 阶段三：输入+发送消息 ==========
    logger.info("\n" + "#" * 60)
    logger.info("#  阶段三：输入+发送消息")
    logger.info("#" * 60)

    stage3_ok = run_send_message(message, do_send=True)
    if not stage3_ok:
        logger.error("   ❌ 阶段三失败")
        rollback_wechat_state()
        return False

    logger.info("\n" + "=" * 60)
    logger.info("  ✅ 端到端流程全部成功")
    logger.info("=" * 60)
    return True


def main():
    if len(sys.argv) < 3:
        logger.info("用法: python E:\\Code\\loveMentor\\send_message\\wechat_e2e_run.py <联系人名> \"<消息内容>\"")
        logger.info("示例: python E:\\Code\\loveMentor\\send_message\\wechat_e2e_run.py [REDACTED] \"你好\"")
        logger.info(f"模板目录: {TEMPLATES_DIR}（模板文件名应为 <联系人名>.jpg）")
        sys.exit(1)
    contact_name = sys.argv[1]
    message = sys.argv[2]
    template_path = os.path.join(TEMPLATES_DIR, f"{contact_name}.jpg")
    if not os.path.exists(template_path):
        logger.error(f"❌ 模板文件不存在: {template_path}")
        logger.info(f"   请将联系人头像模板放在 {TEMPLATES_DIR} 目录，命名为 {contact_name}.jpg")
        sys.exit(1)
    success = run_e2e(message, contact_name, template_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

