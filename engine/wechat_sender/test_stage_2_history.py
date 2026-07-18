"""
阶段二 2 窗口分支测试脚本（历史聊天界面）。

假设：当前微信已处于 2 窗口状态——主窗口 + "搜索聊天记录"窗口。
（由用户手动操作触发：在微信搜索栏输入联系人名后，点击搜索结果中的
  "搜索聊天记录"或类似选项，弹出独立的"搜索聊天记录"窗口）

流程：
1. 统计当前聊天窗口数（应 = 2）
2. 找"搜索聊天记录"窗口
3. PrintWindow 截图 + 多尺度匹配联系人头像
4. 双击头像（主窗口会跳转到该联系人聊天界面）
5. 关闭"搜索聊天记录"窗口
6. 验证窗口数变为 1

用法：
    python E:\\Code\\MaaFramework\\examples\\wechat_auto\\test_stage_2_history.py [联系人名]

    联系人名默认 [REDACTED]，模板路径为 E:\\Code\\MaaFramework\\templates\\<联系人名>.jpg
"""
import os
import sys

import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wechat_e2e_run import (  # noqa: E402
    count_chat_windows,
    handle_stage_2_history_window,
    TEMPLATES_DIR,
)


def main():
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(output_dir, exist_ok=True)

    # 联系人名（命令行参数，默认 [REDACTED]）
    contact_name = sys.argv[1] if len(sys.argv) > 1 else "[REDACTED]"
    template_path = os.path.join(TEMPLATES_DIR, f"{contact_name}.jpg")

    print("=" * 60)
    print("  阶段二 2 窗口分支测试（历史聊天界面）")
    print(f"  联系人: {contact_name!r}")
    print(f"  模板: {template_path}")
    print("=" * 60)

    if not os.path.exists(template_path):
        print(f"\n❌ 模板文件不存在: {template_path}")
        print(f"   请将联系人头像模板放在 {TEMPLATES_DIR} 目录，命名为 {contact_name}.jpg")
        return False

    # 1. 检查当前窗口数
    chat_count, chat_wins = count_chat_windows()
    print(f"\n[1] 当前聊天窗口数（排除搜索候选框）: {chat_count}")
    for w in chat_wins:
        print(f"    - hwnd={w['hwnd']} title={w['title']!r} "
              f"class={w['class']!r}")

    if chat_count != 2:
        print(f"\n⚠️ 预期 2 个窗口，实际 {chat_count} 个")
        print("   请手动操作微信进入 2 窗口状态：")
        print(f"   1. 在微信主窗口搜索栏输入联系人名（如 {contact_name}）")
        print("   2. 在搜索候选框中点击'搜索聊天记录'或类似选项")
        print("      （会弹出独立的'搜索聊天记录'窗口）")
        print("   3. 确认'搜索聊天记录'窗口可见且包含对方头像")
        print("   4. 重新运行本脚本：")
        print(f"      python E:\\Code\\loveMentor\\send_message\\test_stage_2_history.py {contact_name}")
        return False

    print("\n✅ 已是 2 窗口状态，开始执行阶段二逻辑")

    # 2. 执行阶段二
    ok = handle_stage_2_history_window(attempt_idx=99, template_path=template_path)
    if not ok:
        print("\n❌ 阶段二失败")
        return False

    # 3. 验证窗口数变为 1
    chat_count_after, chat_wins_after = count_chat_windows()
    print(f"\n[验证] 执行后聊天窗口数: {chat_count_after}")
    for w in chat_wins_after:
        print(f"    - hwnd={w['hwnd']} title={w['title']!r} "
              f"class={w['class']!r}")

    if chat_count_after == 1:
        print("\n✅ 阶段二测试成功：已从 2 窗口变为 1 窗口")
        print("   主窗口应已跳转到联系人聊天界面，可进入阶段三发送消息")
        return True
    else:
        print(f"\n⚠️ 预期 1 窗口，实际 {chat_count_after} 窗口")
        print("   但阶段二逻辑已执行，请检查微信当前状态")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
