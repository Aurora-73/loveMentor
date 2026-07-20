# -*- coding: utf-8 -*-
"""
联系人特征数据结构（ContactProfile）。

将 _resolve_contact 查到的信息打包为统一的数据结构，
传递到 run_e2e 及下游所有阶段，让各阶段能用精确特征集做验证，
不再"盲找"。

来源：ocr建议.md 改进A（数据层：contact_profile 传递）

典型使用：
    profile = ContactProfile(
        wxid="[REDACTED]",
        alias="[REDACTED]",
        display_name="茶",
        remark="备注名",
        nickname="昵称",
        avatar_path="data/avatars/wxid_xxx.jpg",
    )
    run_e2e(message, profile.alias, profile.avatar_path, contact_profile=profile)
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContactProfile:
    """联系人特征集合。

    把 _resolve_contact 查到的所有字段打包成统一结构，
    传递到下游各阶段使用。

    字段说明：
    - wxid: 微信内部唯一标识（不可改），用于头像模板命名
    - alias: 微信号（用户可改），用于搜索栏输入
    - display_name: 微信显示名（聊天界面顶部标题），用于字体匹配验证
    - remark: 备注名（用户自定义），可能为空
    - nickname: 昵称（用户设置），可能为空
    - avatar_path: 本地头像模板路径
    - avatar_url: 头像网络 URL（可能为空）
    """

    wxid: str                                   # 微信ID（如 [REDACTED]）
    alias: str                                  # 微信号（如 [REDACTED]，可能为空字符串）
    display_name: str                           # 微信显示名（如"茶"）
    remark: Optional[str] = None                # 备注名
    nickname: Optional[str] = None              # 昵称
    avatar_path: Optional[str] = None           # 本地头像路径
    avatar_url: Optional[str] = None            # 头像URL

    # 搜索词（用于搜索栏输入，优先 alias，回退 display_name）
    search_term: str = ""

    # 原始解析结果（用于调试和错误处理）
    raw_resolution: Optional[dict] = field(default=None, repr=False)

    def __post_init__(self):
        """后处理：自动填充 search_term。"""
        if not self.search_term:
            # 优先用 alias（微信号唯一），回退到 display_name
            self.search_term = self.alias if self.alias else self.display_name

    @classmethod
    def from_resolution(cls, resolution: dict,
                        avatar_path: Optional[str] = None) -> "ContactProfile":
        """从 _resolve_contact 的返回值构建 ContactProfile。

        Args:
            resolution: _resolve_contact 返回的 dict
            avatar_path: 头像模板路径（由 _wechat_send_impl 解析后传入）

        Returns:
            ContactProfile 实例
        """
        return cls(
            wxid=resolution.get("id", ""),
            alias=resolution.get("alias") or "",
            display_name=resolution.get("display_name") or resolution.get("search_term", ""),
            remark=resolution.get("remark"),
            nickname=resolution.get("nickname"),
            avatar_path=avatar_path,
            avatar_url=resolution.get("avatar_url"),
            search_term=resolution.get("search_term", ""),
            raw_resolution=resolution,
        )

    def to_dict(self) -> dict:
        """转换为 dict（用于日志和序列化）。"""
        return {
            "wxid": self.wxid,
            "alias": self.alias,
            "display_name": self.display_name,
            "remark": self.remark,
            "nickname": self.nickname,
            "avatar_path": self.avatar_path,
            "avatar_url": self.avatar_url,
            "search_term": self.search_term,
        }

    def __repr__(self) -> str:
        """简洁的可读表示（不暴露完整 wxid）。"""
        wxid_short = self.wxid[:12] + "..." if len(self.wxid) > 12 else self.wxid
        return (
            f"ContactProfile(display_name={self.display_name!r}, "
            f"alias={self.alias!r}, wxid={wxid_short!r})"
        )


# ── 联系人解析（从 mcp_server/tools_wechat.py 迁移）──────────────

import os
import logging

logger = logging.getLogger(__name__)

# 项目根目录（contact_profile.py 在 engine/wechat_sender/ 下，上三级是项目根）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_contact(name: str) -> dict:
    """解析联系人标识符，返回唯一的微信号（alias）用于搜索。

    微信号的唯一性保证搜索结果准确，避免按昵称搜索时出现重名（如 'h'、'Y' 等）。

    查找顺序（逐步精确匹配，非模糊搜索）：
    1. 精确匹配 alias（微信号）—— 微信号唯一，直接使用
    2. 精确匹配 id（wxid）—— wxid 唯一，取该记录的 alias
    3. 精确匹配 display_name / nickname / remark —— 可能重名

    匹配规则：
    - 若第 1/2 步命中：直接返回（唯一）
    - 若第 3 步命中且仅 1 条：返回该记录
    - 若第 3 步命中多条：拒绝发送，返回所有匹配项供 Agent 决策
    - 若全部未命中：返回 CONTACT_NOT_FOUND

    Args:
        name: 联系人标识符（微信号 / wxid / 昵称 / 备注名 均可）

    Returns:
        dict: {
            "success": bool,
            "search_term": str,       # 用于微信搜索的关键词（优先 alias）
            "display_name": str,      # 用于头像模板查找的名称
            "alias": str|None,        # 微信号（可能为空）
            "id": str,                # wxid
            "matches": list[dict],    # 匹配的联系人列表（多匹配时用于错误信息）
            "match_count": int,       # 匹配数量
            "error": str|None,        # 错误类型
            "message": str,           # 描述信息
        }
    """
    import sqlite3

    DB_PATH = os.path.join(_PROJECT_ROOT, "data", "raw", "core.db")
    if not os.path.exists(DB_PATH):
        return {
            "success": False,
            "search_term": name,
            "display_name": name,
            "alias": None,
            "id": "",
            "matches": [],
            "match_count": 0,
            "error": "DATABASE_NOT_FOUND",
            "message": f"联系人数据库不存在: {DB_PATH}",
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # 步骤 1: 精确匹配 alias（微信号）
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE alias = ?",
            (name,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            return {
                "success": True,
                "search_term": alias,  # 用微信号搜索
                "display_name": display_name,
                "alias": alias,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": f"通过微信号匹配到联系人: {display_name}",
            }
        if len(rows) > 1:
            # 微信号重复（极罕见），也拒绝
            matches = [
                {"id": r["id"], "display_name": r["display_name"],
                 "alias": r["alias"], "nickname": r["nickname"]}
                for r in rows
            ]
            return {
                "success": False,
                "search_term": name,
                "display_name": name,
                "alias": None,
                "id": "",
                "matches": matches,
                "match_count": len(matches),
                "error": "MULTIPLE_MATCHES",
                "message": f"微信号 {name!r} 匹配到 {len(matches)} 个联系人（微信号重复），拒绝发送",
            }

        # 步骤 2: 精确匹配 id（wxid）
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE id = ?",
            (name,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            # 如果有微信号，用微信号搜索；否则用 display_name
            search_term = alias if alias else display_name
            return {
                "success": True,
                "search_term": search_term,
                "display_name": display_name,
                "alias": alias if alias else None,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": (
                    f"通过 wxid 匹配到联系人: {display_name}"
                    + (f"（使用微信号 {alias} 搜索）" if alias else "（无微信号，使用昵称搜索）")
                ),
            }

        # 步骤 3: 精确匹配 display_name / nickname / remark
        cur.execute(
            "SELECT id, nickname, remark, alias, display_name FROM contacts "
            "WHERE display_name = ? OR nickname = ? OR remark = ?",
            (name, name, name),
        )
        rows = cur.fetchall()
        if len(rows) == 0:
            return {
                "success": False,
                "search_term": name,
                "display_name": name,
                "alias": None,
                "id": "",
                "matches": [],
                "match_count": 0,
                "error": "CONTACT_NOT_FOUND",
                "message": f"在数据库中未找到匹配 {name!r} 的联系人",
            }
        if len(rows) == 1:
            row = rows[0]
            alias = row["alias"]
            display_name = row["display_name"] or row["nickname"] or name
            search_term = alias if alias else display_name
            return {
                "success": True,
                "search_term": search_term,
                "display_name": display_name,
                "alias": alias if alias else None,
                "id": row["id"],
                "matches": [],
                "match_count": 1,
                "error": None,
                "message": (
                    f"通过昵称匹配到联系人: {display_name}"
                    + (f"（使用微信号 {alias} 搜索）" if alias else "（无微信号，使用昵称搜索）")
                ),
            }

        # 多匹配，拒绝发送
        matches = [
            {"id": r["id"], "display_name": r["display_name"],
             "alias": r["alias"], "nickname": r["nickname"]}
            for r in rows
        ]
        return {
            "success": False,
            "search_term": name,
            "display_name": name,
            "alias": None,
            "id": "",
            "matches": matches,
            "match_count": len(matches),
            "error": "MULTIPLE_MATCHES",
            "message": (
                f"按昵称 {name!r} 匹配到 {len(matches)} 个联系人（重名），拒绝发送。"
                f"请用微信号（alias）或 wxid 重新调用"
            ),
        }
    finally:
        conn.close()
