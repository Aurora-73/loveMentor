"""导出指定联系人的聊天记录到文件，供深度分析。

Usage:
    python tools/ops/export_chats.py [names...]
    python tools/ops/export_chats.py --all

如果未提供参数，默认导出配置文件中的联系人。
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from engine.config import load_config
from engine.importers.db_init import get_db
from engine.facts import ensure_people_archives_migrated
from engine.identity import resolve_contact
from engine.agent.chat import agent_chat

config = load_config()
conn = get_db(config.db_path)
ensure_people_archives_migrated(conn, config.my_wxid)

parser = argparse.ArgumentParser(description="导出聊天记录")
parser.add_argument("names", nargs="*", help="联系人姓名列表")
parser.add_argument("--all", action="store_true", help="导出所有联系人")
args = parser.parse_args()

if args.all:
    from engine.backtest.load_cases import load_cases
    cases = load_cases()
    targets = [c["name"] for c in cases]
elif args.names:
    targets = args.names
else:
    targets = []

if not targets:
    print("请提供联系人姓名或使用 --all 参数")
    print("示例: python tools/ops/export_chats.py [REDACTED] [REDACTED]")
    sys.exit(1)

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "outputs", "chat_analysis")
os.makedirs(out_dir, exist_ok=True)

for name in targets:
    result = resolve_contact(conn, name)
    person = result.person
    if not person:
        print(f"[SKIP] 找不到: {name}, candidates={result.candidates}")
        continue
    print(f"[START] {name} -> person_id={person.id}, display={person.display_name}, accounts={len(person.accounts)}")

    md = agent_chat(conn, config, person, recent=9999)

    safe_name = person.display_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    out_path = os.path.join(out_dir, f"{safe_name}_chat.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    msg_count = md.count("**[")
    print(f"[DONE] {name}: ~{msg_count} messages, {len(md)} chars -> {out_path}")

print("\n全部导出完成")
