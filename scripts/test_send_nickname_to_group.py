"""测试：给全部"群友"标签的联系人发送对方的昵称。

验证 P1-1（logger 替换）和 P1-2（统一窗口枚举）优化后的发送功能。

流程：
1. 查询 data/raw/core.db 获取"群友"标签的联系人列表
2. 检查每个联系人的头像模板是否存在
3. 对每个联系人，调用 run_e2e 发送其 display_name
4. 记录测试结果

用法：
    python -X utf8 scripts/test_send_nickname_to_group.py
    python -X utf8 scripts/test_send_nickname_to_group.py --dry-run  # 只查询不发送
"""
import os
import sys
import sqlite3
import argparse

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 微信发送模块路径
WECHAT_SENDER_DIR = os.path.join(PROJECT_ROOT, "engine", "wechat_sender")
if WECHAT_SENDER_DIR not in sys.path:
    sys.path.insert(0, WECHAT_SENDER_DIR)

# 数据库路径
DB_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "core.db")
# 头像模板目录
AVATARS_DIR = os.path.join(PROJECT_ROOT, "data", "avatars")


def parse_labels(labels_str):
    """解析 labels 字段（逗号分隔或 JSON 格式）。"""
    if not labels_str:
        return []
    # 尝试 JSON 解析
    import json
    try:
        result = json.loads(labels_str)
        if isinstance(result, list):
            return [str(x) for x in result]
        if isinstance(result, str):
            return [result]
    except (json.JSONDecodeError, TypeError):
        pass
    # 回退到逗号分隔
    return [x.strip() for x in labels_str.split(",") if x.strip()]


def get_group_friends():
    """查询"群友"标签的联系人列表。"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, nickname, remark, alias, display_name, labels FROM contacts"
    ).fetchall()
    conn.close()

    group_friends = []
    for row in rows:
        labels = parse_labels(row["labels"])
        if "群友" in labels:
            # 优先用 display_name，其次 remark，最后 nickname
            display_name = row["display_name"] or row["remark"] or row["nickname"] or row["id"]
            # 搜索用的名字：优先 alias（微信号唯一），其次 display_name
            search_name = row["alias"] or display_name
            group_friends.append({
                "wxid": row["id"],
                "nickname": row["nickname"],
                "remark": row["remark"],
                "alias": row["alias"],
                "display_name": display_name,
                "search_name": search_name,
                "labels": labels,
            })

    return group_friends


def check_avatar_template(display_name):
    """检查头像模板是否存在。"""
    # 尝试多种文件名格式
    candidates = [
        f"{display_name}.jpg",
        f"{display_name}.png",
    ]
    for name in candidates:
        path = os.path.join(AVATARS_DIR, name)
        if os.path.exists(path):
            return path
    return None


def parse_messages(message_arg, num_contacts):
    """解析消息参数，支持单条消息或 JSON 列表。

    Args:
        message_arg: --message 参数值
        num_contacts: 联系人数量

    Returns:
        list[str]: 每个联系人对应的消息列表
    """
    import json
    # 尝试 JSON 列表解析
    try:
        msgs = json.loads(message_arg)
        if isinstance(msgs, list):
            if len(msgs) < num_contacts:
                print(f"⚠️ 消息列表长度 {len(msgs)} < 联系人数量 {num_contacts}，不足部分用最后一条填充")
                last = msgs[-1] if msgs else ""
                msgs = msgs + [last] * (num_contacts - len(msgs))
            return [str(m) for m in msgs[:num_contacts]]
    except (json.JSONDecodeError, TypeError):
        pass
    # 单条消息：所有联系人发相同内容
    return [message_arg] * num_contacts


def main():
    parser = argparse.ArgumentParser(description="给群友群发消息测试")
    parser.add_argument("--dry-run", action="store_true", help="只查询不发送")
    parser.add_argument("--only", type=str, help="只发送给指定联系人")
    parser.add_argument("--message", type=str, default="晚上好",
                        help="发送的消息内容（默认：晚上好）。支持 JSON 列表格式为不同联系人发不同消息，"
                             '如 --message \'["在吗", "最近咋样", "今天忙不"]\'')
    parser.add_argument("--messages-file", type=str,
                        help="从 JSON 文件读取消息列表（每条消息一行，JSON 数组格式）。"
                             "优先级高于 --message。避免 PowerShell 引号转义问题。")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  测试：给群友群发消息")
    print(f"  数据库: {DB_PATH}")
    print(f"  头像目录: {AVATARS_DIR}")
    print("=" * 60)

    # 1. 查询群友列表
    friends = get_group_friends()
    print(f"\n[1] 找到 {len(friends)} 个'群友'标签联系人:")

    # 检查头像模板
    send_list = []
    skip_list = []
    for f in friends:
        avatar = check_avatar_template(f["display_name"])
        if avatar:
            f["avatar_path"] = avatar
            send_list.append(f)
            print(f"  ✅ {f['display_name']} (search={f['search_name']!r}, alias={f['alias']!r}) -> {avatar}")
        else:
            skip_list.append(f)
            print(f"  ❌ {f['display_name']} (search={f['search_name']!r}) -> 无头像模板")

    if skip_list:
        print(f"\n  ⚠️ {len(skip_list)} 个联系人因无头像模板跳过")

    if args.dry_run:
        print("\n[dry-run] 仅查询模式，不发送消息")
        return

    if not send_list:
        print("\n❌ 没有可发送的联系人（全部缺少头像模板）")
        return

    # 过滤 --only
    if args.only:
        send_list = [f for f in send_list if args.only in f["display_name"]]
        print(f"\n[--only {args.only!r}] 过滤后 {len(send_list)} 个联系人")

    if not send_list:
        print("❌ 过滤后无可发送联系人")
        return

    # 解析消息列表
    if args.messages_file:
        # 从 JSON 文件读取
        import json
        with open(args.messages_file, "r", encoding="utf-8") as fp:
            msgs = json.load(fp)
        if not isinstance(msgs, list):
            print(f"❌ {args.messages_file} 内容不是 JSON 数组")
            return
        if len(msgs) < len(send_list):
            print(f"⚠️ 消息列表长度 {len(msgs)} < 联系人数量 {len(send_list)}，不足部分用最后一条填充")
            last = msgs[-1] if msgs else ""
            msgs = msgs + [last] * (len(send_list) - len(msgs))
        messages = [str(m) for m in msgs[:len(send_list)]]
        print(f"\n[消息来源] 从文件读取: {args.messages_file}")
    else:
        # 从命令行参数解析
        messages = parse_messages(args.message, len(send_list))

    # 2. 逐个发送
    print(f"\n[2] 开始发送（共 {len(send_list)} 个联系人）")
    print(f"\n消息分配:")
    for i, (f, msg) in enumerate(zip(send_list, messages), 1):
        print(f"  {i}. {f['display_name']}: {msg!r}")

    # 导入发送模块
    try:
        from wechat_e2e_run import run_e2e
        from logger import get_logger
        logger = get_logger(__name__)
    except ImportError as e:
        print(f"❌ 导入发送模块失败: {e}")
        return

    success_count = 0
    fail_count = 0
    results = []

    for i, (f, message) in enumerate(zip(send_list, messages), 1):
        contact_name = f["search_name"]  # 用于搜索的名字
        template_path = f["avatar_path"]

        print(f"\n{'='*60}")
        print(f"  [{i}/{len(send_list)}] 发送给: {f['display_name']}")
        print(f"  搜索名: {contact_name!r}")
        print(f"  消息内容: {message!r}")
        print(f"  头像模板: {template_path}")
        print(f"{'='*60}")

        try:
            result = run_e2e(message, contact_name, template_path)
            if result:
                success_count += 1
                results.append({"name": f["display_name"], "success": True, "message": message})
                print(f"  ✅ 发送成功")
            else:
                fail_count += 1
                results.append({"name": f["display_name"], "success": False, "message": message})
                print(f"  ❌ 发送失败")
        except Exception as e:
            fail_count += 1
            results.append({"name": f["display_name"], "success": False, "message": message, "error": str(e)})
            print(f"  ❌ 发送异常: {e}")

        # 发送间隔（随机 3-6 秒，避免机械化节奏）
        if i < len(send_list):
            import time
            import random
            gap = random.uniform(3, 6)
            print(f"  等待 {gap:.1f} 秒后发送下一个...")
            time.sleep(gap)

    # 3. 汇总
    print(f"\n{'='*60}")
    print(f"  测试完成")
    print(f"  成功: {success_count}/{len(send_list)}")
    print(f"  失败: {fail_count}/{len(send_list)}")
    print(f"{'='*60}")

    if fail_count > 0:
        print("\n失败列表:")
        for r in results:
            if not r["success"]:
                error = r.get("error", "未知原因")
                print(f"  ❌ {r['name']}: {error}")

    # 成功列表（显示发送的消息）
    if success_count > 0:
        print("\n成功列表:")
        for r in results:
            if r["success"]:
                print(f"  ✅ {r['name']}: {r['message']!r}")


if __name__ == "__main__":
    main()
