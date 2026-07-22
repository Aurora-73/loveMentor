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
    capture_initial_main_window_layout,
    MAX_ATTEMPTS,
    MAX_RETRIES,
)
from send_message_run import run_send_message  # noqa: E402
from window_capture import screencap_window  # noqa: E402
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

    # v3.0 改进：历史聊天窗口头像匹配失败 → 刷新头像并重新匹配
    # 场景：能进入阶段二说明阶段一已成功（点击了正确的联系人），所以联系人是对的
    #       阶段一用的可能是旧头像模板，历史聊天窗口里的头像是最新的 → 刷新头像
    # 用户需求："OCR 认为匹配到了，但头像匹配认为没匹配到，应该都更新头像"
    # 阶段二虽然没有独立 OCR 验证，但阶段一的 OCR 验证已确认联系人
    if not points:
        logger.info(
            f"    🔄 [v3.0-Stage2] 历史聊天窗口头像匹配失败 (best={best_score:.3f})，"
            f"刷新头像并重新匹配..."
        )
        try:
            import os as _os
            avatar_filename = _os.path.basename(template_path)
            wxid_guess = _os.path.splitext(avatar_filename)[0]
            from engine.wechat_data.avatar_fetcher import get_avatar
            new_avatar_path = get_avatar(wxid_guess, force_refresh=True)
            if new_avatar_path and _os.path.exists(new_avatar_path):
                logger.info(f"    ✅ 头像已刷新: {new_avatar_path}")
                # 用新模板重新匹配
                points, best_score = find_template_multiscale(
                    img, new_avatar_path, TEMPLATE_SCALES,
                    MATCH_THRESHOLD, NMS_MIN_DIST
                )
                if points:
                    logger.info(
                        f"    ✅ [v3.0-Stage2] 刷新后历史聊天窗口匹配成功 "
                        f"(best={best_score:.3f})"
                    )
                    # 更新 template_path 指向新头像
                    template_path = new_avatar_path
                else:
                    logger.warning(
                        f"    ⚠️ [v3.0-Stage2] 刷新后历史聊天窗口仍匹配失败 "
                        f"(best={best_score:.3f})"
                    )
            else:
                logger.warning(f"    ⚠️ [v3.0-Stage2] 头像刷新失败")
        except Exception as e:
            logger.warning(f"    ⚠️ [v3.0-Stage2] 刷新头像异常: {e}")

    if not points:
        logger.error(f"    ❌ 历史聊天窗口内未匹配到头像 (最高置信度={best_score:.3f})")
        return False

    logger.info(f"    匹配到 {len(points)} 个头像:")
    for i, (x, y, s, sc) in enumerate(points):
        logger.info(f"      #{i}: ({x}, {y}) conf={s:.3f} scale={sc}px")

    # 修复 P1-5：阶段二选点逻辑与阶段一统一，先过滤低置信度点
    # 严格阈值：低于 MATCH_THRESHOLD(0.7) 一律不点击，直接判失败触发上层重试
    # （与 click_avatar_in_search_window.py 阶段一逻辑保持一致，避免点错位置触发意外窗口）
    high_conf_points = [p for p in points if p[2] >= MATCH_THRESHOLD]
    if not high_conf_points:
        logger.error(
            f"    ❌ 所有匹配点置信度 < {MATCH_THRESHOLD}，"
            f"严格判定阶段二失败（不点击，避免点错位置触发意外窗口）"
        )
        return False

    target = max(high_conf_points, key=lambda p: p[2])
    logger.info(f"    选中(置信度最高, >= {MATCH_THRESHOLD}): ({target[0]}, {target[1]}) "
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
    """回滚微信状态，清除残留输入、搜索栏、意外窗口。

    用户反馈：失败重试时直接累加操作到搜索框，导致错误。
    正确做法：失败后先回滚状态（清理所有残留），再进行下一次重试。

    步骤：
    1. 关闭意外窗口（"搜索网络结果"窗口、Chrome_WidgetWin_0 内嵌浏览器窗口）
    2. 关闭搜索候选框（避免重试时累加操作到搜索框）
    3. 主窗口置顶（确保下次操作的是主窗口）

    ⚠️ 不按 Esc 键：微信"关闭主面板"快捷键默认是 Esc，按 Esc 会关闭主窗口
       导致下次重试时 find_wechat_window 找不到窗口，全部 attempt 失败。

    ⚠️ 不点击中间栏：测试发现点击中间栏中心会触发微信 mini 模式
       （nav_right 从 149 变成 41），导致 verify_main_window_layout 判失败。
       搜索栏残留文本由下次 attempt 的 search bar 点击逻辑负责清空。
    """
    logger.info("\n[回滚] 清理微信残留状态（关闭意外窗口+搜索候选框+主窗口置顶）...")

    # 步骤 1：关闭意外窗口
    try:
        from wechat_window_utils import close_unexpected_wechat_windows
        closed_count, closed_wins = close_unexpected_wechat_windows()
        if closed_count > 0:
            logger.info(f"    [回滚] 关闭 {closed_count} 个意外窗口:")
            for cw in closed_wins:
                logger.info(
                    f"      - hwnd={cw['hwnd']} title={cw['title']!r} class={cw['class']!r}"
                )
            time.sleep(0.3)
    except Exception as e:
        logger.warning(f"    [回滚] 关闭意外窗口异常: {e}")

    # 步骤 2：关闭搜索候选框
    try:
        from wechat_window_utils import find_search_candidate_windows
        search_candidates = find_search_candidate_windows()
        if search_candidates:
            logger.info(f"    [回滚] 关闭 {len(search_candidates)} 个搜索候选框")
            WM_CLOSE = 0x0010
            for sc in search_candidates:
                user32.PostMessageW(sc["hwnd"], WM_CLOSE, 0, 0)
            time.sleep(0.5)
    except Exception as e:
        logger.warning(f"    [回滚] 关闭搜索候选框异常: {e}")

    # 步骤 3：主窗口置顶
    try:
        from window_capture import find_wechat_window
        from click_search_and_input import safe_set_foreground_window
        main_win = find_wechat_window()
        if main_win:
            if safe_set_foreground_window(main_win["hwnd"]):
                logger.info(f"    [回滚] 主窗口已置顶 (hwnd={main_win['hwnd']})")
                time.sleep(0.3)
    except Exception as e:
        logger.warning(f"    [回滚] 主窗口置顶异常: {e}")


def _file_hash(file_path):
    """计算文件内容的 MD5 哈希（用于比较新旧头像是否相同）。"""
    import hashlib
    try:
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _refresh_avatar_and_maybe_retry(contact_name, template_path, message,
                                   contact_profile=None):
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
        contact_profile: ContactProfile 实例（可选，v3.0 新增）
            - 传给 run_one_attempt 用于阶段 F 的 OCR display_name 回退验证

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
    # 注意：template_path 现在是 <wxid>.jpg（统一用 wxid 命名）
    # 从 template_path 反推 wxid 作为查询标识符
    # avatar_fetcher.get_avatar(force_refresh=True) 内部会调用
    # mcp_server.weflow_cdp.refresh_contact_avatar(wxid)，通过 CDP 强制刷新
    # WeFlow 的 L1/L2 头像缓存，从 wcdb 数据库读取最新 avatarUrl。
    # 不再调用 CDP clearAvatarCache（旧方案），因为那会清空 contacts.json 导致 API 找不到联系人。
    try:
        from engine.wechat_data.avatar_fetcher import get_avatar
        # 从 template_path 反推 wxid（stem 就是 wxid）
        wxid = os.path.splitext(os.path.basename(template_path))[0]
        logger.info(f"   从 template_path 反推 wxid: {wxid}")
        # 优先用 wxid 查询，回退到 contact_name（兼容旧模板）
        fetch_identifier = wxid if wxid else contact_name
        new_path = get_avatar(fetch_identifier, force_refresh=True)
        if not new_path or not os.path.exists(new_path):
            # 回退：用 contact_name 查询
            if contact_name and contact_name != fetch_identifier:
                logger.info(f"   用 wxid '{wxid}' 查询失败，回退用 '{contact_name}' 查询")
                new_path = get_avatar(contact_name, force_refresh=True)
        if not new_path or not os.path.exists(new_path):
            logger.warning(f"   ⚠️ 头像更新失败：未获取到 {fetch_identifier} 的新头像")
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
        # 每次尝试前确保微信主窗口可见（>= 500x400）
        # 修复 bug：原来用 find_wechat_window() 判断，但它在小窗口存在时回退返回非 None
        from wechat_window_utils import (
            find_wechat_window as _find_wx, restore_wechat_windows, count_wechat_windows
        )
        _big_wx_count, _ = count_wechat_windows()
        if _big_wx_count == 0:
            logger.info(f"\n[头像更新后-窗口唤醒] 微信主窗口不可见，尝试唤醒...")
            try:
                from open_wechat_window import open_wechat_window_robust
                if open_wechat_window_robust(timeout=10.0):
                    logger.info(f"   ✅ 微信窗口已唤醒")
                    # 唤醒后立即保持窗口前台和可见，避免被系统自动隐藏
                    wx_win = _find_wx()
                    if wx_win:
                        from click_search_and_input import safe_set_foreground_window
                        restore_wechat_windows()
                        safe_set_foreground_window(wx_win["hwnd"])
                        logger.info(f"   ✅ 微信窗口已设为前台 (hwnd={wx_win['hwnd']})")
                    time.sleep(0.5)
            except Exception as e:
                logger.warning(f"   ⚠️ 窗口唤醒异常: {e}")

        if attempt > 1:
            # 用户反馈：失败重试时必须先回滚状态（与 run_e2e 主循环保持一致）
            # 注意：回滚只在重试前调用一次，不在失败后立即调用（避免重复回滚触发 mini 模式）
            logger.info("\n[头像更新后-重试预备] 回滚微信状态...")
            rollback_wechat_state()
            time.sleep(0.5)

        success, target, count_after = run_one_attempt(
            attempt, MAX_ATTEMPTS, do_click=True,
            contact_name=contact_name, template_path=new_path,
            contact_profile=contact_profile,
        )

        if success:
            retry_success = True
            retry_target = target
            retry_count_after = count_after
            break
        else:
            logger.error(f"\n❌ [头像更新后] 第 {attempt} 次尝试失败")
            # 不在此处回滚，留到下次重试前统一回滚（避免重复回滚）

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


def _verify_chat_header_display_name(contact_profile, image=None):
    """用 font_matcher 验证聊天界面顶部的 display_name（v3.0 新增）。

    在阶段二完成后调用，截图当前聊天界面，用字体匹配验证顶部 display_name。
    失败只记录警告，不阻断流程（增强验证，提升可信度）。

    Args:
        contact_profile: ContactProfile 实例（必须包含 display_name）
        image: 可选，已有的聊天界面截图（BGR numpy 数组）。
               None 时自动截图。传入可避免重复截图。

    Returns:
        bool: True=验证通过，False=验证失败（不阻断主流程）
    """
    display_name = contact_profile.display_name
    if not display_name:
        return False

    logger.info(f"\n[阶段 2.5] display_name 验证: {display_name!r}")

    # 截图当前聊天界面（或使用传入的截图）
    if image is not None:
        img = image
        logger.info("   使用传入的截图（避免重复截图）")
    else:
        from window_capture import find_wechat_window, screencap_window
        window = find_wechat_window()
        if window is None:
            logger.warning("   ⚠️ 未找到微信窗口，跳过 display_name 验证")
            return False

        img = screencap_window(window["hwnd"])
        if img is None:
            logger.warning("   ⚠️ 截图失败，跳过 display_name 验证")
            return False

    # 保存截图供调试
    debug_path = os.path.join(OUTPUT_DIR, "stage_2_5_chat_header.png")
    cv2.imwrite(debug_path, img)
    logger.info(f"   截图: {debug_path}")

    # 用 font_matcher 在聊天标题区域匹配 display_name
    try:
        from font_matcher import get_font_matcher
        matcher = get_font_matcher()  # 单例，避免重复加载字库
        match = matcher.find_in_chat_header(img, display_name, threshold=0.75)
        if match:
            conf = match.get("confidence", 0)
            cx = match.get("center_x", 0)
            cy = match.get("center_y", 0)
            logger.info(
                f"   ✅ display_name 验证通过: {display_name!r} "
                f"conf={conf:.4f} pos=({cx}, {cy})"
            )
            return True
        else:
            logger.warning(
                f"   ⚠️ display_name 验证失败: 未在聊天标题区域匹配到 {display_name!r}"
            )
            logger.info("   （可能原因：display_name 含特殊字符、字号不匹配、"
                        "窗口未完全切换到聊天界面）")
            return False
    except ImportError:
        logger.warning("   ⚠️ font_matcher 模块不可用，跳过 display_name 验证")
        return False


def run_e2e(message, contact_name, template_path, contact_profile=None,
            stage3_func=None):
    """端到端流程：阶段一 → 阶段二 → 阶段三

    Args:
        message: 要发送的消息内容（表情包模式下为表情搜索关键词）
        contact_name: 联系人昵称（用于搜索栏输入）
        template_path: 联系人头像模板路径
        contact_profile: ContactProfile 实例（可选，v3.0 新增）
            - 包含 display_name/alias/wxid 等精确特征
            - 用于 font_matcher 验证聊天标题、template_matcher 验证 UI 元素
            - None 时回退到原有行为（仅靠 contact_name + template_path）
        stage3_func: 阶段三执行函数（可选，默认 run_send_message）
            - 签名：func(message, do_send=True) -> bool
            - 发送文字消息时用 run_send_message（默认）
            - 发送表情包时用 run_send_emoji（来自 send_emoji_run.py）
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 清理旧截图，避免文件无限增长
    cleanup_old_screenshots()

    logger.info("=" * 60)
    logger.info("  端到端微信自动化流程")
    logger.info(f"  联系人: {contact_name!r}")
    logger.info(f"  模板: {template_path}")
    logger.info(f"  消息: {message!r}")
    if contact_profile is not None:
        logger.info(f"  联系人特征: {contact_profile}")
    logger.info(f"  最多尝试次数: {MAX_ATTEMPTS}（初次 + {MAX_RETRIES} 次重试）")
    logger.info("=" * 60)

    # ========== 阶段一：搜索+点击头像+绿色环验证（含重试） ==========
    logger.info("\n" + "#" * 60)
    logger.info("#  阶段一：搜索+点击头像+绿色环验证（含重试）")
    logger.info("#" * 60)

    # 确保微信窗口宽度足够大（用户反馈：窗口化 658px 宽度时只有两栏，无法走三栏流程）
    # 通过 SetWindowPos 增大窗口宽度恢复三栏布局（等同于用户拖动右边界向右放大）
    # 必须在 capture_initial_main_window_layout 之前调用，否则捕获的初始布局仍是两栏
    from wechat_window_utils import ensure_wechat_window_width
    width_result = ensure_wechat_window_width(min_width=1000)
    logger.info(
        f"[窗口宽度] hwnd={width_result['hwnd']} "
        f"old={width_result['old_width']}px new={width_result['new_width']}px "
        f"resized={width_result['was_resized']} success={width_result['success']} "
        f"| {width_result['reason']}"
    )
    if not width_result["success"]:
        logger.warning(
            f"   ⚠️ 微信窗口宽度调整失败，可能继续以两栏模式运行，"
            f"阶段一搜索栏定位可能失败"
        )
    time.sleep(0.3)  # 等待窗口稳定

    # 捕获主窗口初始布局（用户反馈：不要用硬编码范围判断，要和初始布局对比）
    # 在操作开始时捕获一次，后续 verify_main_window_layout 会自动和它对比
    capture_initial_main_window_layout()

    stage1_success = False
    final_count_after = 0
    final_target = None
    attempt_idx = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_idx = attempt

        # 每次尝试前确保微信主窗口可见（>= 500x400），不可见则通过托盘图标唤醒
        # 修复 bug：原来用 find_wechat_window() 判断，但它在小窗口存在时回退返回非 None，
        # 导致微信主窗口最小化时不会触发唤醒，run_one_attempt [A] 阶段报"窗口数=0"
        from wechat_window_utils import (
            find_wechat_window, restore_wechat_windows, count_wechat_windows
        )
        _big_wx_count, _ = count_wechat_windows()
        if _big_wx_count == 0:
            logger.info(f"\n[窗口唤醒] 微信主窗口不可见（大窗口数=0），尝试通过托盘图标唤醒...")
            try:
                from open_wechat_window import open_wechat_window_robust
                if open_wechat_window_robust(timeout=10.0):
                    logger.info(f"   ✅ 微信窗口已唤醒")
                    # 唤醒后立即保持窗口前台和可见，避免被系统自动隐藏
                    from wechat_window_utils import find_wechat_window as _fw
                    wx_win = _fw()
                    if wx_win:
                        from click_search_and_input import safe_set_foreground_window
                        restore_wechat_windows()  # 恢复最小化的窗口
                        safe_set_foreground_window(wx_win["hwnd"])  # 设为前台
                        logger.info(f"   ✅ 微信窗口已设为前台 (hwnd={wx_win['hwnd']})")
                    time.sleep(0.5)
                    # 唤醒后再次验证大窗口确实存在
                    _big_wx_count2, _ = count_wechat_windows()
                    if _big_wx_count2 == 0:
                        logger.warning(f"   ⚠️ 唤醒后大窗口数仍为 0，可能窗口被立即隐藏")
                else:
                    logger.warning(f"   ⚠️ 微信窗口唤醒失败，继续尝试（可能 PrintWindow 仍能工作）")
            except Exception as e:
                logger.warning(f"   ⚠️ 窗口唤醒异常: {e}")

        if attempt > 1:
            # 用户反馈：失败重试时不能直接累加操作，必须先回滚状态
            # - 关闭意外窗口（搜索网络结果等）
            # - 关闭搜索候选框（避免重试时累加操作到搜索框）
            # - 主窗口置顶
            # 注意：回滚只在重试前调用一次，不在失败后立即调用（避免重复回滚触发 mini 模式）
            logger.info("\n[重试预备] 回滚微信状态（关闭意外窗口+搜索候选框+主窗口置顶）...")
            rollback_wechat_state()
            time.sleep(0.5)

        success, target, count_after = run_one_attempt(
            attempt, MAX_ATTEMPTS, do_click=True,
            contact_name=contact_name, template_path=template_path,
            contact_profile=contact_profile,
        )

        if not success:
            logger.error(f"\n❌ 第 {attempt} 次尝试失败")
            # 不在此处回滚，留到下次重试前统一回滚（避免重复回滚）
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
            contact_name, template_path, message,
            contact_profile=contact_profile,
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

    # ========== 阶段 2.5：display_name 验证（v3.0 新增，非阻断） ==========
    # 用 font_matcher 在聊天界面顶部验证 display_name
    # 失败只记录警告，不阻断流程（增强验证，不是必须）
    if contact_profile is not None and contact_profile.display_name:
        try:
            _verify_chat_header_display_name(contact_profile)
        except Exception as e:
            logger.warning(f"   ⚠️ display_name 验证异常: {e}（不阻断流程）")

    # ========== 阶段三：输入+发送消息（或表情包） ==========
    logger.info("\n" + "#" * 60)
    if stage3_func is None:
        logger.info("#  阶段三：输入+发送消息")
    else:
        logger.info("#  阶段三：发送表情包（使用自定义 stage3_func）")
    logger.info("#" * 60)

    # 默认用 run_send_message（发送文字），可传入 stage3_func 切换为表情包发送
    actual_stage3_func = stage3_func if stage3_func is not None else run_send_message
    stage3_ok = actual_stage3_func(message, do_send=True)
    if not stage3_ok:
        logger.error("   ❌ 阶段三失败")
        rollback_wechat_state()
        return False

    logger.info("\n" + "=" * 60)
    logger.info("  ✅ 端到端流程全部成功")
    logger.info("=" * 60)
    return True


# ── 业务编排：发送消息（从 mcp_server/tools_wechat.py 迁移）──────────────

def send_message_with_retry(name: str, message: str,
                             stage3_func=None) -> dict:
    """发送消息完整业务编排（不含录屏，由 MCP 工具层包装）。

    流程：
    1. 解析联系人（resolve_contact）→ 获取微信号/wxid/display_name
    2. 同步最新 display_name（WeFlow API + 数据库更新）
    3. 定位头像模板（本地 → avatar_fetcher 自动获取）
    4. 确保微信窗口可见（ensure_wechat_window）
    5. 构建 ContactProfile + 调用 run_e2e
    6. 返回标准化的结果 dict

    头像自动获取逻辑：
    - 本地有头像 → 直接用
    - 本地无头像 → 立即调用 avatar_fetcher 获取并保存

    Args:
        name: 联系人标识符（微信号/wxid/昵称/备注名 均可）
        message: 要发送的消息内容（表情包模式下为表情搜索关键词）
        stage3_func: 阶段三执行函数（可选，默认 run_send_message）
            - 发送文字消息时用 None（默认 run_send_message）
            - 发送表情包时用 run_send_emoji（来自 send_emoji_run.py）

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "contact": str,
            "search_term": str,
            "template": str,
            "attempts": int,
            "error": str|None,
            "window_restored": bool,
            "matches": list|None,
        }
    """
    import traceback
    from engine.wechat_sender.contact_profile import resolve_contact, ContactProfile
    from engine.wechat_sender.ensure_window import ensure_wechat_window

    # ── 步骤 1: 解析联系人，获取微信号 ──
    resolution = resolve_contact(name)
    if not resolution["success"]:
        # 匹配失败（未找到 / 多匹配），拒绝发送
        return {
            "success": False,
            "message": resolution["message"],
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "error": resolution["error"],
            "window_restored": False,
            "matches": resolution["matches"] if resolution["match_count"] > 1 else None,
        }

    search_term = resolution["search_term"]   # 微信号（用于搜索）
    display_name = resolution["display_name"]  # 显示名（OCR 文字识别用）
    alias = resolution["alias"]                # 微信号（内部唯一标识）
    wxid = resolution["id"]                    # wxid（唯一，用于头像模板命名）

    # ── 步骤 1.5: 同步最新 display_name（v3.0 新增） ──
    # 用户决策：OCR display_name 验证作为主要验证方式，必须保证 display_name 是最新的
    # WeFlow API 查询很轻量（~0.05s），每次发送前都同步
    # 如果 WeFlow API 不可用或查询失败，静默回退到数据库中的 display_name（不阻断流程）
    if wxid:
        try:
            from engine.config import load_config
            from engine.importers.weflow_client import WeFlowClient
            from engine.importers.wcd_client import WCDClient
            config = load_config()
            # 根据 backend 选择客户端（WCD 后端用 source=decrypted 绕过 WeChat 运行时锁）
            if config.weflow.backend == "wcd":
                client = WCDClient(
                    base_url=config.weflow.base_url,
                    token=config.weflow.token,
                    timeout=min(config.weflow.timeout, 5),  # 限制 5s，避免卡住
                    decrypted_db_dir=config.weflow.decrypted_db_dir or None,
                )
                contacts = client.list_contacts(keyword=wxid, limit=5, source="decrypted")
            else:
                client = WeFlowClient(
                    base_url=config.weflow.base_url,
                    token=config.weflow.token,
                    timeout=min(config.weflow.timeout, 5),  # 限制 5s，避免卡住
                )
                contacts = client.list_contacts(keyword=wxid, limit=5)
            # 精确匹配 wxid（避免 keyword 模糊匹配到其他联系人）
            matched = [c for c in contacts if c.get("username") == wxid]
            if matched:
                latest_info = matched[0]
                latest_display_name = latest_info.get("displayName") or latest_info.get("nickname")
                if latest_display_name and latest_display_name != display_name:
                    logger.info(
                        f"[display_name 同步] 数据库={display_name!r} → WeFlow 最新={latest_display_name!r}，已更新"
                    )
                    # 更新数据库
                    import sqlite3
                    DB_PATH = os.path.join(_PROJECT_ROOT, "data", "raw", "core.db")
                    conn = sqlite3.connect(DB_PATH)
                    try:
                        conn.execute(
                            "UPDATE contacts SET display_name = ?, nickname = ?, updated_at = strftime('%s','now') WHERE id = ?",
                            (latest_display_name, latest_info.get("nickname"), wxid),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    # 更新 resolution 和本地变量
                    display_name = latest_display_name
                    resolution["display_name"] = latest_display_name
                elif latest_display_name:
                    logger.info(f"[display_name 同步] 数据库已是最新: {display_name!r}")
            else:
                logger.warning(f"[display_name 同步] WeFlow 未找到 wxid={wxid}，使用数据库 display_name={display_name!r}")
        except Exception as e:
            logger.warning(
                f"[display_name 同步] 查询 WeFlow 失败: {e}，使用数据库 display_name={display_name!r}"
            )

    # ── 步骤 2: 定位头像模板（统一用 wxid 查找，唯一不会冲突）──
    # 重要：
    # - 不能用 display_name 作为文件名，因为同名联系人会互相覆盖
    # - 不再用 alias 副本，统一用 wxid 命名（avatar_fetcher 不再创建 alias 副本）
    # - wxid 是微信内部唯一标识，比微信号（alias）更稳定（alias 可改，wxid 不可改）
    avatars_dir = os.path.join(_PROJECT_ROOT, "data", "avatars")
    template_path = os.path.join(avatars_dir, f"{wxid}.jpg") if wxid else ""

    # 如果头像模板不存在，先尝试用 avatar_fetcher 获取头像（用 wxid 查询）
    if not template_path or not os.path.exists(template_path):
        try:
            from engine.wechat_data.avatar_fetcher import get_avatar
            # 用 wxid 查询（wxid 唯一，不会冲突）
            # 重要：force_refresh=True 会触发 avatar_fetcher 内部调用
            # mcp_server.weflow_cdp.refresh_contact_avatar(wxid)，
            # 通过 CDP 强制刷新 WeFlow 的 L1/L2 头像缓存，从 wcdb 数据库
            # 读取最新 avatarUrl。不需要在这里显式调 CDP。
            fetch_identifier = wxid if wxid else (alias if alias else display_name)
            fetched_path = get_avatar(fetch_identifier, force_refresh=True)
            if fetched_path and os.path.exists(fetched_path):
                template_path = fetched_path
            else:
                id_hint = f"（wxid: {wxid}）" if wxid else ""
                return {
                    "success": False,
                    "message": (
                        f"头像模板不存在且自动获取失败: data/avatars/{wxid}.jpg{id_hint}。"
                        f"请手动将联系人头像保存为 data/avatars/<wxid>.jpg"
                    ),
                    "contact": display_name,
                    "search_term": search_term,
                    "template": template_path or "",
                    "attempts": 0,
                    "error": "TEMPLATE_NOT_FOUND",
                    "window_restored": False,
                    "matches": None,
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"头像模板不存在且获取异常: {e}",
                "contact": display_name,
                "search_term": search_term,
                "template": template_path or "",
                "attempts": 0,
                "error": "TEMPLATE_FETCH_ERROR",
                "window_restored": False,
                "matches": None,
            }

    # 设置 DPI 感知
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    # 确保微信窗口可见（修复：后台运行无窗口时打开窗口）
    window_result = ensure_wechat_window()
    window_restored = window_result.get("action") == "restored"

    if not window_result["success"]:
        return {
            "success": False,
            "message": f"微信窗口不可用: {window_result['message']}",
            "contact": display_name,
            "search_term": search_term,
            "template": template_path,
            "attempts": 0,
            "error": "WINDOW_NOT_AVAILABLE",
            "window_restored": window_restored,
            "matches": None,
        }

    # 构建 ContactProfile（v3.0 新增：把 resolve_contact 的结果打包传递给下游）
    # 让各阶段能用 display_name 做字体匹配、用 alias 做微信号验证
    contact_profile = ContactProfile.from_resolution(resolution, avatar_path=template_path)

    # 执行端到端发送（用微信号 search_term 搜索，用 template_path 匹配头像）
    # stage3_func=None 时用默认的 run_send_message（发送文字），
    # 传入 run_send_emoji 时切换为表情包发送流程
    try:
        success = run_e2e(message, search_term, template_path,
                          contact_profile=contact_profile,
                          stage3_func=stage3_func)
    except ImportError as e:
        return {
            "success": False,
            "message": f"依赖模块导入失败: {e}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "error": "IMPORT_ERROR",
            "window_restored": False,
            "matches": None,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行异常: {e}",
            "contact": name,
            "search_term": name,
            "template": "",
            "attempts": 0,
            "error": f"RUNTIME_ERROR: {traceback.format_exc()}",
            "window_restored": False,
            "matches": None,
        }

    if success:
        msg = f"消息已成功发送给 {display_name}"
        if alias:
            msg += f"（微信号: {alias}）"
        if window_restored:
            msg += "（已自动恢复微信窗口）"
        return {
            "success": True,
            "message": msg,
            "contact": display_name,
            "search_term": search_term,
            "template": template_path,
            "attempts": 1,
            "error": None,
            "window_restored": window_restored,
            "matches": None,
        }
    else:
        return {
            "success": False,
            "message": f"发送失败（端到端流程未成功，详见日志）",
            "contact": display_name,
            "search_term": search_term,
            "template": template_path,
            "attempts": 4,
            "error": "E2E_FLOW_FAILED",
            "window_restored": window_restored,
            "matches": None,
        }


def send_emoji_with_retry(name: str, emoji_keyword: str) -> dict:
    """发送表情包完整业务编排（不含录屏，由 MCP 工具层包装）。

    复用 send_message_with_retry 的全部业务逻辑（联系人解析、头像获取、
    窗口检查等），仅通过 stage3_func 参数切换阶段三为表情包发送流程。

    与 send_message_with_retry 的区别：
    - 阶段三用 run_send_emoji 替代 run_send_message
    - 流程：点击表情按钮 → 打开表情面板（独立窗口）→ 点击搜索键 →
      输入关键词 → 匹配"全部表情"标题 → 点击下方第一个表情（直接发送）

    Args:
        name: 联系人标识符（微信号/wxid/昵称/备注名 均可）
        emoji_keyword: 表情搜索关键词（如 "猫猫"、"感谢"、"开心"）

    Returns:
        dict: 与 send_message_with_retry 相同的结构
    """
    # 延迟导入，避免模块加载时循环依赖
    from send_emoji_run import run_send_emoji
    return send_message_with_retry(name, emoji_keyword,
                                    stage3_func=run_send_emoji)


def send_image_with_retry(name: str, image_path: str) -> dict:
    """发送图片完整业务编排（v4 第十六章多媒体发送能力）。

    复用 send_message_with_retry 的全部业务逻辑（联系人解析、头像获取、
    窗口检查等），仅通过 stage3_func 参数切换阶段三为图片发送流程。

    技术方案（v4 16.2 节）：复用文本发送的剪贴板机制，把剪贴板内容从文字换成图片。
    流程：点击输入框 → 剪贴板放图片 → Ctrl+V → 微信显示预览 → 点击发送

    Args:
        name: 联系人标识符（微信号/wxid/昵称/备注名 均可）
        image_path: 图片文件路径（支持 jpg/jpeg/png/bmp/gif/webp/tiff）

    Returns:
        dict: 与 send_message_with_retry 相同的结构
    """
    # 延迟导入，避免模块加载时循环依赖
    from send_image_run import run_send_image
    return send_message_with_retry(name, image_path,
                                    stage3_func=run_send_image)


def send_message_batch(name: str, messages: list) -> dict:
    """连续发送多条消息的业务编排（v4 连续发送能力）。

    第一条消息走完整流程（搜索+点击头像+发送），
    后续消息跳过搜索，直接在当前聊天界面发送，
    每次发送前校验聊天框左上角显示名。
    校验失败则回退到完整流程（重新搜索联系人）。

    适用场景：分段发送长文本、连续发送多条独立消息。

    Args:
        name: 联系人标识符（微信号/wxid/昵称/备注名 均可）
        messages: 要发送的消息列表（每条独立发送）

    Returns:
        dict: {
            "success": bool,       # 全部成功=True，任一失败=False
            "total": int,          # 总消息数
            "succeeded": int,      # 成功数
            "failed": int,         # 失败数
            "results": list[dict], # 每条消息的结果
            "contact": str,
            "error": str|None,
        }
    """
    import time
    from engine.wechat_sender.contact_profile import (
        resolve_contact, ContactProfile
    )

    if not messages:
        return {
            "success": False,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
            "contact": name,
            "error": "消息列表为空",
        }

    logger.info("=" * 60)
    logger.info(f"  连续发送多条消息: {name!r}，共 {len(messages)} 条")
    logger.info("=" * 60)

    results = []
    succeeded = 0
    failed = 0
    contact_display_name = name

    # ── 预解析联系人，用于后续 display_name 校验 ──
    # 第一条消息会走 send_message_with_retry（内部也会解析），这里预解析是为了
    # 后续消息能构建 ContactProfile 做校验
    pre_resolution = None
    try:
        pre_resolution = resolve_contact(name)
        if pre_resolution.get("success"):
            contact_display_name = pre_resolution.get("display_name") or name
    except Exception as e:
        logger.warning(f"预解析联系人失败: {e}，后续消息校验可能回退到完整流程")

    # ── 发送第一条消息（走完整流程） ──
    logger.info(f"\n[1/{len(messages)}] 第一条消息（完整流程）: {messages[0]!r}")
    first_result = send_message_with_retry(name, messages[0])
    results.append({
        "index": 0,
        "message": messages[0],
        "success": first_result.get("success", False),
        "error": first_result.get("error"),
        "mode": "full_flow",
    })
    if first_result.get("success"):
        succeeded += 1
        logger.info(f"   ✅ 第一条消息发送成功")
    else:
        failed += 1
        logger.warning(f"   ❌ 第一条消息发送失败: {first_result.get('error')}")
        # 第一条失败，后续消息仍尝试发送（可能第一条是网络问题，后续能成功）

    # ── 发送后续消息（跳过搜索，校验后直接发送） ──
    for i in range(1, len(messages)):
        msg = messages[i]
        logger.info(f"\n[{i+1}/{len(messages)}] 后续消息: {msg!r}")

        # 消息间间隔（模拟人工操作，避免发送过快）
        time.sleep(2.0)

        # 校验聊天框左上角显示名
        verify_passed = False
        if pre_resolution and pre_resolution.get("success"):
            try:
                # 构建 ContactProfile 用于校验
                avatars_dir = os.path.join(_PROJECT_ROOT, "data", "avatars")
                wxid = pre_resolution.get("id", "")
                template_path = os.path.join(avatars_dir, f"{wxid}.jpg") if wxid else ""
                contact_profile = ContactProfile.from_resolution(
                    pre_resolution, avatar_path=template_path
                )

                logger.info(f"   [校验] 检查聊天框显示名: {contact_profile.display_name!r}")
                verify_passed = _verify_chat_header_display_name(contact_profile)
                if not verify_passed:
                    logger.warning(f"   ⚠️ 显示名校验失败，回退到完整流程")
            except Exception as e:
                logger.warning(f"   ⚠️ 显示名校验异常: {e}，回退到完整流程")
        else:
            logger.info(f"   [校验] 无预解析数据，回退到完整流程")

        if verify_passed:
            # 校验通过，直接调用 run_send_message（跳过阶段一/二）
            logger.info(f"   ✅ 校验通过，直接发送（跳过搜索）")
            try:
                stage3_ok = run_send_message(msg, do_send=True)
                if stage3_ok:
                    succeeded += 1
                    results.append({
                        "index": i,
                        "message": msg,
                        "success": True,
                        "error": None,
                        "mode": "direct_send",
                    })
                    logger.info(f"   ✅ 第 {i+1} 条消息发送成功（直接发送）")
                else:
                    failed += 1
                    results.append({
                        "index": i,
                        "message": msg,
                        "success": False,
                        "error": "STAGE3_FAILED",
                        "mode": "direct_send",
                    })
                    logger.warning(f"   ❌ 第 {i+1} 条消息发送失败（直接发送 stage3 失败）")
            except Exception as e:
                failed += 1
                results.append({
                    "index": i,
                    "message": msg,
                    "success": False,
                    "error": f"DIRECT_SEND_ERROR: {e}",
                    "mode": "direct_send",
                })
                logger.error(f"   ❌ 第 {i+1} 条消息发送异常: {e}")
        else:
            # 校验失败或无预解析数据，回退到完整流程
            logger.info(f"   [回退] 走完整流程重新发送")
            retry_result = send_message_with_retry(name, msg)
            results.append({
                "index": i,
                "message": msg,
                "success": retry_result.get("success", False),
                "error": retry_result.get("error"),
                "mode": "fallback_full_flow",
            })
            if retry_result.get("success"):
                succeeded += 1
                logger.info(f"   ✅ 第 {i+1} 条消息发送成功（完整流程回退）")
            else:
                failed += 1
                logger.warning(f"   ❌ 第 {i+1} 条消息发送失败: {retry_result.get('error')}")

    # ── 汇总结果 ──
    all_success = (failed == 0)
    summary = f"连续发送完成: {succeeded}/{len(messages)} 成功"
    if failed > 0:
        summary += f"，{failed} 失败"

    logger.info("\n" + "=" * 60)
    logger.info(f"  {summary}")
    logger.info("=" * 60)

    return {
        "success": all_success,
        "total": len(messages),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
        "contact": contact_display_name,
        "error": None if all_success else f"{failed} 条消息发送失败",
    }


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
