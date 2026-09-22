"""Phase 0 Pre-check: 最小可行验证。

验证"规则检测文本可观测行为"这条路走不走得通。
选 3 个最容易用规则检测的标签：question_asking / flirt / perfunctory
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


# ============================================================
#  3 个简单规则检测函数
# ============================================================

_QUESTION_PATTERNS = [
    r"[？?]",
    r"吗[呀呢吧嘛]?",
    r"呢[呀嘛]?",
    r"吧[嘛]?",
    r"什么",
    r"怎么",
    r"为什么|为啥",
    r"哪里|哪个|哪些",
    r"谁|哪位",
    r"什么时候|几点|多久",
    r"是不是|对不对|行不行|好不好",
    r"你呢|那你",
]

_QUESTION_REGEX = re.compile("|".join(_QUESTION_PATTERNS))


def detect_question_asking(text: str) -> bool:
    """检测是否有提问/追问。"""
    if not text or len(text.strip()) < 2:
        return False
    return bool(_QUESTION_REGEX.search(text))


_FLIRT_KEYWORDS = [
    "想你", "想我", "喜欢你", "爱你", "宝贝", "亲爱的", "么么哒",
    "亲亲", "抱抱", "笨蛋", "傻瓜", "坏蛋", "讨厌", "你猜",
    "才不", "哼", "不理你了", "逗你", "欺负我", "讨厌鬼",
    "小坏蛋", "乖", "听话", "摸摸头", "捏脸", "戳你",
    "嘻嘻", "嘿嘿", "哈哈", "😘", "🥰", "😍", "😜", "😝",
    "心动", "小鹿乱撞", "脸红", "害羞",
]


def detect_flirt(text: str) -> bool:
    """检测是否有暧昧/调侃表达。"""
    if not text or len(text.strip()) < 2:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _FLIRT_KEYWORDS)


_PERFUNCTORY_WORDS = [
    "嗯", "哦", "噢", "喔", "额", "呃", "哎",
    "好", "行", "可以", "ok", "OK", "Ok",
    "哈哈", "呵呵", "嘿嘿", "嘻嘻", "666",
    "👌", "👍", "😊", "🙂", "😄", "😅",
    "。。。", "...", "。。",
]


def detect_perfunctory(text: str, *, min_chars: int = 5) -> bool:
    """检测是否为敷衍回应。

    规则：文本很短（< min_chars 字）且包含敷衍词，或全是敷衍词。
    """
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) == 0:
        return True

    # 超短句 + 敷衍词
    if len(stripped) <= min_chars:
        for w in _PERFUNCTORY_WORDS:
            if w in stripped:
                return True
        # 全是标点/表情也算敷衍
        if re.fullmatch(r"[\s\W_]+", stripped):
            return True

    # 全是敷衍词的组合（如"嗯好的"、"哦行"）
    remaining = stripped
    for w in sorted(_PERFUNCTORY_WORDS, key=len, reverse=True):
        remaining = remaining.replace(w, "")
    if len(remaining.strip()) == 0 and len(stripped) > 0:
        return True

    return False


# ============================================================
#  窗口级检测：聚合窗口内所有消息的检测结果
# ============================================================

def detect_window(messages: list[dict], target_role: str = "her") -> dict:
    """对一个窗口内 target_role 的所有消息做检测。

    返回每个标签的 binary 结果（窗口内出现 ≥1 次就算 True）。
    """
    her_messages = [m for m in messages if m.get("role") == target_role]
    texts = [m.get("text", "") for m in her_messages]
    joined = "\n".join(texts)

    return {
        "question_asking": any(detect_question_asking(t) for t in texts),
        "flirt": any(detect_flirt(t) for t in texts),
        "perfunctory": any(detect_perfunctory(t) for t in texts),
        "_her_msg_count": len(her_messages),
        "_her_total_chars": sum(len(t) for t in texts),
    }


# ============================================================
#  从数据库抽窗口
# ============================================================

def _get_conversations(db_path: Path) -> list[tuple[str, str, int]]:
    """获取所有私聊会话及其消息数。返回 [(wxid, name, msg_count), ...]"""
    conn = sqlite3.connect(db_path)
    try:
        # type=10000 是单聊；先查一下有哪些 type 值
        type_rows = conn.execute(
            "SELECT type, COUNT(*) FROM conversations GROUP BY type"
        ).fetchall()
        print(f"  conversation types: {type_rows}")

        rows = conn.execute("""
            SELECT c.id AS wxid,
                   COALESCE(co.remark, co.nickname, c.display_name, c.id) AS name,
                   COUNT(m.id) AS msg_count
            FROM conversations c
            LEFT JOIN contacts co ON co.id = c.contact_id
            JOIN messages m ON m.conversation_id = c.id
            WHERE c.type = 'private'
              AND m.type = 1
              AND m.content IS NOT NULL
              AND length(m.content) > 0
            GROUP BY c.id
            HAVING msg_count >= 50
            ORDER BY msg_count DESC
        """).fetchall()
        return rows
    finally:
        conn.close()


def _load_messages(db_path: Path, wxid: str) -> list[dict]:
    """加载某个会话的所有文本消息，按时间排序。"""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT id, sender_id, timestamp, content
            FROM messages
            WHERE conversation_id = ?
              AND type = 1
              AND content IS NOT NULL
              AND length(content) > 0
            ORDER BY timestamp ASC
        """, (wxid,)).fetchall()

        messages = []
        my_ids = _get_my_ids(conn)
        for row in rows:
            msg_id, sender_id, ts, content = row
            role = "me" if sender_id in my_ids else "her"
            # 清洗消息内容
            content = _clean_content(content)
            if content:
                messages.append({
                    "id": str(msg_id),
                    "sender_id": sender_id,
                    "role": role,
                    "timestamp": ts,
                    "text": content,
                })
        return messages
    finally:
        conn.close()


def _get_my_ids(conn: sqlite3.Connection) -> set[str]:
    """获取本机账号的 wxid。

    策略：取发送消息最多的 sender_id 作为自己（通常比其他人多一个数量级）。
    这在个人聊天数据集中非常可靠——自己发的消息总是最多的。
    """
    rows = conn.execute("""
        SELECT sender_id, COUNT(*) as cnt
        FROM messages
        WHERE type = 1 AND content IS NOT NULL AND length(content) > 0
        GROUP BY sender_id
        ORDER BY cnt DESC
        LIMIT 3
    """).fetchall()
    if not rows:
        return set()
    # 取发送最多的那个
    return {rows[0][0]}


def _clean_content(text: str) -> str:
    """清洗微信消息内容，移除 XML 包装等。"""
    if not text:
        return ""
    # 去掉可能的 XML 标签（表情引用等）
    text = re.sub(r"<[^>]+>", "", text)
    # 去掉常见的系统消息前缀
    text = text.strip()
    if len(text) > 500:
        text = text[:500]
    return text


def build_windows(messages: list[dict], window_turns: int = 20, slide_turns: int = 10) -> list[list[dict]]:
    """构建 20 轮滑动窗口。

    轮次（turn）定义：连续同人消息合并为一轮，交替计数。
    """
    if not messages:
        return []

    # 第一步：合并连续同人为一轮
    turns: list[list[dict]] = []
    current_turn: list[dict] = []
    current_role: str | None = None

    for msg in messages:
        role = msg["role"]
        if role != current_role and current_turn:
            turns.append(current_turn)
            current_turn = []
        current_turn.append(msg)
        current_role = role
    if current_turn:
        turns.append(current_turn)

    # 第二步：滑动窗口
    windows = []
    for start in range(0, max(1, len(turns) - window_turns + 1), slide_turns):
        end = min(start + window_turns, len(turns))
        window_msgs = []
        for t in range(start, end):
            window_msgs.extend(turns[t])
        # 过滤掉消息太少的窗口
        if len(window_msgs) >= 10:
            windows.append(window_msgs)

    return windows


# ============================================================
#  分层抽样：确保每个标签至少 10-15 个正例
# ============================================================

def stratified_sample_50(db_path: Path, output_path: Path) -> list[dict]:
    """分层抽样 50 个窗口。

    策略：
    1. 遍历所有会话，构建窗口，用规则预标注
    2. 优先选稀有标签（flirt/perfunctory）的正例
    3. 补足随机窗口
    4. 保证每个标签至少 15 个正例、15 个负例（共 50 条）
    """
    convs = _get_conversations(db_path)
    print(f"找到 {len(convs)} 个消息数>=50的会话")

    # 收集所有窗口及其预标注结果
    all_windows: list[dict] = []
    for wxid, name, msg_count in convs[:80]:  # 前80个会话，确保覆盖足够多样本
        messages = _load_messages(db_path, wxid)
        windows = build_windows(messages)
        for i, win_msgs in enumerate(windows[:50]):  # 每会话最多50个窗口
            result = detect_window(win_msgs)
            all_windows.append({
                "sample_id": f"s_{len(all_windows)+1:04d}",
                "contact_wxid": wxid,
                "contact_name": name,
                "window_index": i,
                "start_ts": win_msgs[0]["timestamp"],
                "end_ts": win_msgs[-1]["timestamp"],
                "messages": [
                    {"role": m["role"], "text": m["text"], "ts": m["timestamp"]}
                    for m in win_msgs
                ],
                "rule_labels": {
                    "question_asking": result["question_asking"],
                    "flirt": result["flirt"],
                    "perfunctory": result["perfunctory"],
                },
            })

    print(f"总窗口数: {len(all_windows)}")

    # 分层抽样：每个标签尽量均衡（25正 / 25负），总样本 50
    selected: list[dict] = []
    selected_ids: set[str] = set()

    # 第一步：flirt 正例（最稀有，优先保证 15-20 个）
    flirt_pos = [w for w in all_windows if w["rule_labels"]["flirt"]]
    import random
    random.shuffle(flirt_pos)
    for w in flirt_pos[:20]:
        selected.append(w)
        selected_ids.add(w["sample_id"])
    print(f"  选了 {sum(1 for w in selected if w['rule_labels']['flirt'])} 个 flirt 正例")

    # 第二步：补足 question_asking 的负例（稀有负例）
    qa_neg = [w for w in all_windows
              if w["sample_id"] not in selected_ids
              and not w["rule_labels"]["question_asking"]]
    random.shuffle(qa_neg)
    target_qa_neg = 20
    for w in qa_neg[:target_qa_neg]:
        selected.append(w)
        selected_ids.add(w["sample_id"])
    print(f"  补足 question_asking 负例后: {len(selected)} 个")

    # 第三步：补足 perfunctory 的负例
    perf_neg = [w for w in all_windows
                if w["sample_id"] not in selected_ids
                and not w["rule_labels"]["perfunctory"]]
    random.shuffle(perf_neg)
    target_perf_neg = 20
    for w in perf_neg[:target_perf_neg]:
        selected.append(w)
        selected_ids.add(w["sample_id"])
    print(f"  补足 perfunctory 负例后: {len(selected)} 个")

    # 第四步：随机补足到 50 条
    remaining = [w for w in all_windows if w["sample_id"] not in selected_ids]
    random.shuffle(remaining)
    need = max(0, 50 - len(selected))
    for w in remaining[:need]:
        selected.append(w)
        selected_ids.add(w["sample_id"])

    print(f"最终选了 {len(selected)} 个窗口")

    # 统计标签分布
    for label in ["question_asking", "flirt", "perfunctory"]:
        pos = sum(1 for w in selected if w["rule_labels"][label])
        print(f"  {label}: pos={pos}, neg={len(selected)-pos}")

    # 保存
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        for w in selected:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")

    print(f"已保存到: {output_path}")
    return selected


def generate_annotation_template(samples_path: Path, output_path: Path):
    """生成人工标注模板（Markdown 表格格式）。"""
    import json
    samples = []
    with open(samples_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    lines = [
        "# Pre-check 人工标注模板",
        "",
        "## 标注说明",
        "",
        "对每个窗口，判断她的消息中是否出现了以下行为：",
        "- **question_asking**：有没有提问/追问？（是=1，否=0，不确定=?）",
        "- **flirt**：有没有暧昧/调侃/暗示？（是=1，否=0，不确定=?）",
        "- **perfunctory**：有没有敷衍回应？（是=1，否=0，不确定=?）",
        "",
        "只看**她**发的消息，不看你发的。",
        "",
        "---",
        "",
    ]

    for i, s in enumerate(samples, 1):
        her_msgs = [m for m in s["messages"] if m["role"] == "her"]
        preview = "\n".join([f"  她: {m['text'][:60]}" for m in her_msgs[:5]])
        if len(her_msgs) > 5:
            preview += f"\n  ... (共 {len(her_msgs)} 条她的消息)"

        lines.append(f"### {i}. {s['sample_id']} | {s['contact_name']}")
        lines.append("")
        lines.append("**她的消息预览：**")
        lines.append("")
        lines.append(preview)
        lines.append("")
        lines.append("**标注：**")
        lines.append("")
        lines.append(f"- question_asking: ___")
        lines.append(f"- flirt: ___")
        lines.append(f"- perfunctory: ___")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"标注模板已生成: {output_path}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    DB_PATH = project_root / "data" / "raw" / "core.db"
    OUT_DIR = project_root / "data" / "pre_check"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    samples_path = OUT_DIR / "precheck_samples_50.jsonl"
    template_path = OUT_DIR / "annotation_template.md"

    print("=" * 60)
    print("Phase 0 Pre-check: 分层抽样 50 个窗口")
    print("=" * 60)
    stratified_sample_50(DB_PATH, samples_path)

    print()
    print("生成人工标注模板...")
    generate_annotation_template(samples_path, template_path)
    print("\n完成！")
