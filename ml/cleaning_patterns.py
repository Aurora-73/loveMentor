"""清洗模式共享模块 — 水印/时间戳/OCR碎片/旁白/案例标签。
被 clean_rerun.py, clean_batch.py, clean_on_fly.py import。
"""
from __future__ import annotations

import re
import sys

# ── 水印行（整行删除） ──
WATERMARK_REGEX = [
    re.compile(r"瑞恩情感.*?(?:RYAN|PUA|微信)?"),
    re.compile(r"RYAN\s*PUA"),
    re.compile(r"^加PUA倪微信平台.*"),
    re.compile(r"^以上是打招呼的内容"),
    re.compile(r"Type\s*a\s*message", re.IGNORECASE),
    re.compile(r"^(?:May|Apr|Mar|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\d{4}.*"),
    re.compile(r"请加.*?微信.*?回复"),
    re.compile(r"获得.*?全程.*?聊天记录"),
    re.compile(r"^推广$"),
    re.compile(r"^广告$"),
    re.compile(r"puaxingnan", re.IGNORECASE),
    re.compile(r"PUANEY"),
    re.compile(r"NEY\d{3}"),
    re.compile(r"微信号[：:]?kaiyuanpua"),
    re.compile(r"关注微信平台[：:]?neyhow"),
    re.compile(r"开源pua"),
    re.compile(r"^C\.Y\.Hero"),
    re.compile(r"报名咨询[：:]?puaxingnan"),
    re.compile(r"报备咨询\s*puaxingnan"),
    re.compile(r"^扫一扫上面的二维码图案，加我微信"),
    re.compile(r"长按下图二维码.*?(?:艾克|微信|添加)"),
    re.compile(r"^或添加微信[：:].*"),
    re.compile(r"倪[·.](?:恋爱教育|NEY|零教育)"),
    re.compile(r"艾克@私人号"),
    re.compile(r"puaney\d+"),
    re.compile(r"puateddy"),
    re.compile(r"^恋爱补习班"),
    re.compile(r"^Cicada婵"),
    re.compile(r"to\.get\.her"),
]

# ── 行内替换（仅 sub，不删整行） ──
SUB_WATERMARK = [
    re.compile(r"更多内容加微信平台[：:]?\s*neyhow"),
    re.compile(r"加PUA倪微信平台[：:]?\s*neyhow"),
    re.compile(r"关注微信平台[：:]?\s*neyhow"),
    re.compile(r"或关注微信公众平台\w*"),
    re.compile(r"关注微信公众平台[：:]?\s*\w+"),
    re.compile(r"加微信puateddy"),
    re.compile(r"更多干货加微信\w+"),
    re.compile(r"微信公众号[：:]\s*\w+"),
    re.compile(r"或添加微信[：:].*?艾克"),
    re.compile(r"扫描?(?:下方)?二维码"),
    re.compile(r"倪·恋爱"),
    re.compile(r"·恋爱教育"),
    re.compile(r"neyhow\s*并\s*回复"),
    re.compile(r"谢谢neyhow"),
    re.compile(r"[：:]?\s*neyhow\s*获得"),
    re.compile(r"关注微信平會[：:]?\s*neyhow"),
    re.compile(r"平會[：:]?\s*neyhow"),
    re.compile(r"加PUA倪微信平台"),
    re.compile(r"获得从街搭到邀约再到TD"),
    re.compile(r"neyhow"),
    re.compile(r"\"[A-Za-z]+\s*武汉\"撤回了一条消息"),
    re.compile(r"\"[A-Za-z]+武汉\"撤回了一条消息"),
    re.compile(r"撤回了一条消息"),
    re.compile(r"<\d+T武汉[^>]*>?"),
    re.compile(r"<\d+\s*T武汉[^>]*>?"),
    re.compile(r"\d+T武汉"),
    re.compile(r"微信收藏"),
    re.compile(r"<93速约被拒反转"),
    re.compile(r"速约被拒反转"),
    re.compile(r"积目\s*10句话外卖上门"),
    re.compile(r"10句话外卖上门\s*积目"),
    re.compile(r"积目"),
    re.compile(r"10句话外卖上门"),
    re.compile(r"Chris工作号"),
    re.compile(r"<99\d{2}街"),
    re.compile(r"99\d{2}街"),
    re.compile(r"<99\d{2}"),
    re.compile(r"99\d{2}"),
    re.compile(r"成都182白富美"),
    re.compile(r"HDR"),
    re.compile(r"获赞\d+粉丝\d+关注"),
    re.compile(r"抖音号.*?·.*?"),
    re.compile(r"成都搭汕\d+酒吧女模仙女圈"),
    re.compile(r"成都搭讪\d+酒吧女模仙女圈"),
    re.compile(r"成都搭灿\d+酒吧女模仙女圈"),
    re.compile(r"成都搭训\d+酒吧女模仙女圈"),
    re.compile(r"成都搭仙\d+酒吧女模仙女圈"),
    re.compile(r"成都搭山\d+酒吧女模仙女圈"),
    re.compile(r"戈都搭汕\d+酒吧女模仙女圈"),
    re.compile(r"KU70ZBR"),
    re.compile(r"Y400NCL"),
    re.compile(r"Y400MCL"),
    re.compile(r"KU70ZB"),
    re.compile(r"KU70ZBA"),
    re.compile(r"广州170性感辣妹"),
    re.compile(r"美团外卖.*?"),
    re.compile(r"支付成功"),
    re.compile(r"^M$"),
    re.compile(r"林宇晨"),
    re.compile(r"三□"),
    re.compile(r"三0"),
    re.compile(r"小程房"),
    re.compile(r"pala"),
    re.compile(r"广州170性感辣妹案例"),
    re.compile(r"^资过$"),
    re.compile(r"^IMS$"),
    re.compile(r"^十能规戈$"),
    re.compile(r"^回田$"),
    re.compile(r"^鱼好嘛$"),
    re.compile(r"^选妃$"),
    re.compile(r"成都肖肖TD"),
    re.compile(r"^O$"),
    re.compile(r"^4\"\($"),
    re.compile(r"^L$"),
    re.compile(r"^の$"),
    re.compile(r"^三の$"),
    re.compile(r"成都Rosine学生妹T"),
    re.compile(r"成都 Rosine学生妹T"),
    re.compile(r"^\d+\"?$"),
    re.compile(r"^()$"),
    re.compile(r"^\.》$"),
    re.compile(r"^三C$"),
    re.compile(r"^三》D$"),
    re.compile(r"^@④$"),
    re.compile(r"^@SEN$"),
    re.compile(r"职明白"),
    re.compile(r"邀过"),
    re.compile(r"^三D$"),
    re.compile(r"^三>0$"),
    re.compile(r"^厂$"),
    re.compile(r"^CC$"),
    re.compile(r"^a$"),
    re.compile(r"^好室息$"),
    re.compile(r"geinis"),
    re.compile(r"女玉玉"),
    re.compile(r"广州刘天天"),
    re.compile(r"^V$"),
    re.compile(r"^\+$"),
    re.compile(r"^三！$"),
    re.compile(r"^三》$"),
    re.compile(r"^\?\?$"),
    re.compile(r"^\?\?\?$"),
    re.compile(r"^\?$"),
    re.compile(r"^D$"),
    re.compile(r"^\)P十$"),
    re.compile(r"^三口$"),
    re.compile(r"^\)6\"$"),
    re.compile(r"^\)8\"$"),
    re.compile(r"^\)11\"$"),
    re.compile(r"^\)4\"$"),
    re.compile(r"^\)13\"$"),
    re.compile(r"^\)17\"$"),
    re.compile(r"^3\"$"),
    re.compile(r"^4\"$"),
    re.compile(r"^5\"$"),
    re.compile(r"^13\"\"$"),
    re.compile(r"广州sticky黄珊珊"),
    re.compile(r"查无此人"),
    re.compile(r"全部>"),
    re.compile(r"礼物墙"),
    re.compile(r"^三O$"),
    re.compile(r"^4\" \($"),
    re.compile(r"^7\(0$"),
    re.compile(r"^3\" \($"),
    re.compile(r"^\)7\($"),
    re.compile(r"^の\+$"),
    re.compile(r"^三》□$"),
    re.compile(r"成都170高分案例"),
    re.compile(r"^ian$"),
    re.compile(r"^三印$"),
    re.compile(r"生期四下十"),
    re.compile(r"^tiang$"),
    re.compile(r"青峨山居"),
    re.compile(r"成都339"),
    re.compile(r"^赋你$"),
    re.compile(r"^包色$"),
    re.compile(r"^回田$"),
    re.compile(r"成都假脸妹"),
    re.compile(r"^he tui$"),
    re.compile(r"^百能$"),
    re.compile(r"^胚$"),
    re.compile(r"^naha$"),
    re.compile(r"^来3$"),
    re.compile(r"人站你验代"),
    re.compile(r"青城3"),
    re.compile(r"^>D$"),
    re.compile(r"^三>D$"),
    re.compile(r"^王昆明$"),
    re.compile(r"^月天$"),
    re.compile(r"^起多好玩$"),
    re.compile(r"^田$"),
    re.compile(r"^3\($"),
    re.compile(r"^7\" \($"),
    re.compile(r"^6\" \(6$"),
    re.compile(r"^免上$"),
    re.compile(r"^3\"\($"),
    re.compile(r"^3:57 4$"),
    re.compile(r"^3:57 4三$"),
    re.compile(r"^3:57 4=$"),
    re.compile(r"星期四下"),
    re.compile(r"成都大胸妹"),
    re.compile(r"^7:57 4$"),
    re.compile(r"^三> □$"),
    re.compile(r"昆明faith TD"),
    re.compile(r"昆明faithTD"),
    re.compile(r"月期工"),
    re.compile(r"社交牛杂证"),
    re.compile(r"乐巢K·PARTY"),
    re.compile(r"T绅士派嘉诺"),
    re.compile(r"嘉诺微信xdwh010"),
    re.compile(r"绅±派嘉诺"),
    re.compile(r"绅士派嘉诺"),
    re.compile(r"T嘉诺"),
    re.compile(r"嘉诺"),
    re.compile(r"间隔两天后.*?但往往"),
    re.compile(r"不断的像我展示.*?高价值"),
    re.compile(r"转换完成"),
    re.compile(r"按住说话"),
    re.compile(r"流表\d+:\w+"),
    re.compile(r"HDa<"),
    re.compile(r"HD<"),
    re.compile(r"xdwh010"),
    re.compile(r"信xdwh"),
    re.compile(r"信xdwho"),
    re.compile(r"嘉诺微"),
    re.compile(r"嘉诺微信dwho"),
    re.compile(r"v27"),
    re.compile(r"96p"),
    re.compile(r"外卖专家"),
    re.compile(r"聊天达人"),
    re.compile(r"配的上你的野心"),
    re.compile(r"让你的魅力"),
    re.compile(r"PoweredbyZine"),
    re.compile(r"快速兑现拒绝口嗨"),
    re.compile(r"170大长腿的火热邂逅"),
    re.compile(r"假脸邻居"),
]

# ── 时间戳行 ──
TIMESTAMP_REGEX = [
    re.compile(r"^\d{1,2}:\d{2}\s*(?:AM|PM)"),
    re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日.*"),
    re.compile(r"^星期[一二三四五六日日].*\d{1,2}:\d{2}"),
    re.compile(r"^\d{1,2}月\d{1,2}日.*"),
    re.compile(r"^(?:今天|昨天|前天).*\d{1,2}:\d{2}"),
    re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"),
    re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"),
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^星期[一二三四五六日]\s*(?:上午|下午|晚上)\d{1,2}:\d{2}"),
    re.compile(r"^星期[一二三四五六日]\s*(?:上午|下午|晚上)$"),
    re.compile(r"^星期[一二三四五六日]\d{1,2}:\d{2}$"),
]

# ── OCR 碎片行 ──
OCR_REGEX = [
    re.compile(r"^@\d*□?$"),
    re.compile(r"^<\d+.*"),
    re.compile(r"^[lI]+[a-z]?$"),
    re.compile(r"^[A-Za-z]{1,2}$"),
    re.compile(r"^[^一-鿿\w]{1,3}$"),
    re.compile(r"^\d+km\)?$"),
    re.compile(r"^按住说话$"),
    re.compile(r"^转换完成$"),
    re.compile(r"微信\(\d+\)"),
    re.compile(r"^4G$"),
    re.compile(r"^国联通4G"),
    re.compile(r"^<详情"),
    re.compile(r"^<微"),
    re.compile(r"^\d{1,2}:\d{2}\s*[。，,.]"),
    re.compile(r"^\d{1,2}:\d{2}\s+l?\s*4G"),
    re.compile(r"^微信收藏$"),
    re.compile(r"^\d+:\d+\d+$"),
]

# ── 通用旁白标记（特化短语用 clean_batch.py --prune 按需指定）──
NARRATIVE_MARKERS = [
    "顺势把车开去", "午夜2点", "表情缓和很多",
    "笑着调", "完全变成了", "身子却一点没有挪开",
    "被我书写", "我书写了",
    "回复动力就减弱", "把你在她心里印象无限放大",
    "续写的故事", "故事正在按照", "剧本上演",
    "回家之后的事情",
]

# ── 案例标签（如 <3621台湾超模案例 / 4596 街搭正妹有老公）──
CASE_TAG_REGEX = [
    re.compile(r"^<\s*\d+\s*\S+"),
    re.compile(r"^\d{3,5}\s+\S+"),
    re.compile(r"^\d{1,2}:\d{2}\s+.*?\d{3,5}\s+\S+"),
    re.compile(r"^[A-Za-z]\s*武汉\s*\d*"),
    re.compile(r"^[A-Za-z]武汉\s*\d*"),
    re.compile(r"^\d{2,3}\s+速约.*"),
    re.compile(r"速约被拒反转"),
    re.compile(r"<93速约被拒反转"),
    re.compile(r"积目.*10句话外卖上门"),
    re.compile(r"10句话外卖上门.*积目"),
]


def is_narrative(text: str) -> bool:
    if any(m in text for m in NARRATIVE_MARKERS):
        return True
    if len(text) > 40:
        has_dialogue = any(c in text for c in "？?！!你我他她")
        if not has_dialogue:
            return True
    return False


def clean_message(content: str, verbose: bool = False) -> str | None:
    """清洗单条消息。返回清洗后的文本，或 None（完全无效）。

    verbose=True 时将每行移除原因打印到 stderr（用于预览/调试）。
    """
    lines = content.split("\n")
    kept = []
    skipped = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 案例标签行
        if any(p.match(line) for p in CASE_TAG_REGEX):
            skipped.append(f"  [案例标签] {line[:80]}")
            continue
        # 水印行
        if any(p.fullmatch(line) or p.search(line) for p in WATERMARK_REGEX):
            skipped.append(f"  [水印] {line[:80]}")
            continue
        # 时间戳行
        if any(p.match(line) for p in TIMESTAMP_REGEX):
            skipped.append(f"  [时间戳] {line[:80]}")
            continue
        # OCR 碎片行
        if any(p.match(line) for p in OCR_REGEX):
            skipped.append(f"  [OCR碎片] {line[:80]}")
            continue
        # 旁白行
        if is_narrative(line):
            skipped.append(f"  [旁白] {line[:80]}")
            continue
        # 行内替换（WATERMARK_REGEX 已在前面的行级检查中匹配并跳过，不重复 sub）
        for p in SUB_WATERMARK:
            line = p.sub("", line)
        line = line.strip()
        if line and len(line) >= 2:
            kept.append(line)

    if verbose and skipped:
        print(f"  === 移除了 {len(skipped)} 行 ===", file=sys.stderr)
        for s in skipped:
            print(s, file=sys.stderr)

    if not kept:
        return None
    result = "\n".join(kept)
    return result if len(result.strip()) >= 3 else None
