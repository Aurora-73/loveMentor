"""engine/agent/identity_ops.py 单元测试。

覆盖：
- _format_person_md（纯函数，IdentityPerson → Markdown）
- agent_contact（init/search/show/alias/remove_alias/link/merge/audit 8 个 action）
- agent_sticker（scan/list/label 3 个 action）
- agent_exclude（list/add/remove 3 个 action）
- agent_failure（add/list 2 个 action）
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.agent.identity_ops import (
    _format_person_md,
    agent_contact,
    agent_sticker,
    agent_exclude,
    agent_failure,
)
from engine.identity import IdentityPerson, IdentityAccount
from engine.models.failure import FailureCase


# ═══════════════════════════════════════════════════════════════════
# _format_person_md
# ═══════════════════════════════════════════════════════════════════

class TestFormatPersonMd:
    """_format_person_md 把 IdentityPerson 格式化为 Markdown。"""

    def test_minimal_person_only_id_and_name(self):
        """只有 id 和 display_name → 输出最简结构。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        md = _format_person_md(person)
        assert "# Alice" in md
        assert "- person_id: p1" in md
        assert "## 账号" in md
        assert "## 别名" in md

    def test_with_real_name_and_note(self):
        """有 real_name 和 note → 显示对应行。"""
        person = IdentityPerson(id="p1", display_name="Alice",
                                real_name="张三", note="高中同学")
        md = _format_person_md(person)
        assert "- 真实姓名: 张三" in md
        assert "- 备注: 高中同学" in md

    def test_without_real_name_and_note(self):
        """无 real_name/note → 不显示对应行。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        md = _format_person_md(person)
        assert "真实姓名" not in md
        assert "备注:" not in md  # 注意 "## 账号" 含"账号"不含"备注:"

    def test_with_accounts(self):
        """有账号 → 列出每个账号。"""
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_a",
                                conversation_id="wxid_a", display_name="Alice",
                                remark="备注1", nickname="昵称1"),
                IdentityAccount(id="a2", person_id="p1", wxid="wxid_b",
                                conversation_id="wxid_b", display_name="Alice2"),
            ],
        )
        md = _format_person_md(person)
        assert "wxid_a | 备注=备注1 | 昵称=昵称1" in md
        assert "wxid_b" in md

    def test_account_without_remark_nickname(self):
        """账号无 remark/nickname → 只显示 wxid。"""
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_a",
                                conversation_id="wxid_a", display_name="Alice"),
            ],
        )
        md = _format_person_md(person)
        assert "- wxid_a" in md
        assert "备注=" not in md
        assert "昵称=" not in md

    def test_account_with_wxid_fallback_to_id(self):
        """账号 wxid 为空 → 用 id 作 fallback。"""
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[
                IdentityAccount(id="fallback_id", person_id="p1", wxid="",
                                conversation_id="c1", display_name="Alice"),
            ],
        )
        md = _format_person_md(person)
        assert "- fallback_id" in md

    def test_with_aliases(self):
        """有别名列出每个别名。"""
        person = IdentityPerson(
            id="p1", display_name="Alice",
            aliases=[
                {"type": "nickname", "value": "小爱"},
                {"type": "remark", "value": "Alice同学"},
            ],
        )
        md = _format_person_md(person)
        assert "- nickname: 小爱" in md
        assert "- remark: Alice同学" in md

    def test_no_accounts_no_aliases(self):
        """空账号 + 空别名 → section 标题存在但无内容。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        md = _format_person_md(person)
        # "## 账号" 后直接是 "## 别名"
        assert "## 账号\n\n## 别名" in md

    def test_display_name_with_special_chars(self):
        """display_name 含特殊字符 → 原样显示在 # 标题。"""
        person = IdentityPerson(id="p1", display_name="A/B:C")
        md = _format_person_md(person)
        assert "# A/B:C" in md
        assert "- person_id: p1" in md


# ═══════════════════════════════════════════════════════════════════
# agent_contact
# ═══════════════════════════════════════════════════════════════════

class TestAgentContact:
    """agent_contact 的 8 个 action 路由 + 错误处理。"""

    def test_unknown_action(self, monkeypatch):
        """未知 action → 返回错误信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        result = agent_contact("Alice", action="invalid_action")
        assert "未知" in result
        assert "invalid_action" in result
        mock_conn.close.assert_called_once()

    def test_init_action(self, monkeypatch):
        """init action → 调用 bootstrap_identity 并返回统计。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        # mock 依赖
        def fake_ensure(conn, my_wxid):
            return None
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", fake_ensure)
        stats = {"people": 5, "accounts": 10, "aliases": 3, "merges": 1}
        monkeypatch.setattr("engine.identity.bootstrap_identity", lambda conn: stats)
        result = agent_contact("", action="init")
        assert "身份目录初始化完成" in result
        assert "新增 5 人" in result
        assert "10 账号" in result
        assert "合并 1 组" in result

    def test_search_found(self, monkeypatch):
        """search action 找到 person → 返回 _format_person_md 输出。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock()
        mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        result = agent_contact("Alice", action="search")
        assert "# Alice" in result
        assert "- person_id: p1" in result

    def test_search_not_found(self, monkeypatch):
        """search action 未找到 person → 返回未找到信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        mock_result = MagicMock()
        mock_result.person = None
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        result = agent_contact("Unknown", action="search")
        assert "未找到联系人: Unknown" in result

    def test_show_with_set_name(self, monkeypatch):
        """show action + set_name kwarg → 调用 set_display_name + rename_person_archive。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        old_person = IdentityPerson(id="p1", display_name="OldName")
        new_person = IdentityPerson(id="p1", display_name="NewName")
        mock_result1 = MagicMock(); mock_result1.person = old_person
        mock_result2 = MagicMock(); mock_result2.person = new_person
        # resolve_contact 第一次返回 old，第二次返回 new
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result1 if q == "OldName" else mock_result2)
        set_name_called = []
        monkeypatch.setattr("engine.identity.set_display_name",
                            lambda conn, pid, name: set_name_called.append((pid, name)))
        rename_called = []
        monkeypatch.setattr("engine.facts.rename_person_archive",
                            lambda old, new, my_wxid: rename_called.append((old, new, my_wxid)))
        result = agent_contact("OldName", action="show", set_name="NewName")
        assert "# NewName" in result
        assert set_name_called == [("p1", "NewName")]
        assert len(rename_called) == 1

    def test_alias_action_success(self, monkeypatch):
        """alias action + 成功添加 → 返回"已添加别名"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.add_alias",
                            lambda conn, pid, t, v, sensitivity: True)
        result = agent_contact("Alice", action="alias", type="nickname", value="小爱")
        assert "已添加别名" in result

    def test_alias_action_failure(self, monkeypatch):
        """alias action + 添加失败 → 返回"别名已存在或添加失败"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.add_alias",
                            lambda conn, pid, t, v, sensitivity: False)
        result = agent_contact("Alice", action="alias", type="nickname", value="小爱")
        assert "已存在或添加失败" in result

    def test_remove_alias_action_deleted(self, monkeypatch):
        """remove_alias action + 删除 N 条 → 返回删除数量。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.remove_alias",
                            lambda conn, pid, t, value: 3)
        result = agent_contact("Alice", action="remove_alias", type="nickname", value="小爱")
        assert "已删除 3 条别名" in result
        assert "type=nickname" in result

    def test_remove_alias_action_no_match(self, monkeypatch):
        """remove_alias action + 未匹配 → 返回"未找到匹配的别名"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.remove_alias",
                            lambda conn, pid, t, value: 0)
        result = agent_contact("Alice", action="remove_alias", type="nickname", value="小爱")
        assert "未找到匹配的别名" in result

    def test_link_action_success(self, monkeypatch):
        """link action + 绑定成功 → "已绑定账号"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.link_account",
                            lambda conn, pid, wxid: True)
        result = agent_contact("Alice", action="link", wxid="wxid_new")
        assert "已绑定账号" in result

    def test_link_action_failure(self, monkeypatch):
        """link action + 绑定失败 → "绑定失败"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        person = IdentityPerson(id="p1", display_name="Alice")
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact", lambda conn, q: mock_result)
        monkeypatch.setattr("engine.identity.link_account",
                            lambda conn, pid, wxid: False)
        result = agent_contact("Alice", action="link", wxid="wxid_new")
        assert "绑定失败" in result

    def test_merge_action_success(self, monkeypatch):
        """merge action + 合并成功 → 返回合并方向信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        p1 = IdentityPerson(id="p1", display_name="Alice")
        p2 = IdentityPerson(id="p2", display_name="Bob")
        r1 = MagicMock(); r1.person = p1
        r2 = MagicMock(); r2.person = p2
        # 第一次调用返回 p1（query），第二次返回 p2（merged）
        call_count = [0]
        def fake_resolve(conn, q):
            call_count[0] += 1
            return r1 if call_count[0] == 1 else r2
        monkeypatch.setattr("engine.identity.resolve_contact", fake_resolve)
        monkeypatch.setattr("engine.identity.merge_people",
                            lambda conn, pid1, pid2: True)
        result = agent_contact("Alice", action="merge", merged="Bob")
        assert "已合并" in result
        assert "Bob -> Alice" in result

    def test_merge_action_first_not_found(self, monkeypatch):
        """merge action + 第一个联系人不存在 → 返回"未找到"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        r1 = MagicMock(); r1.person = None
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: r1)
        result = agent_contact("Unknown", action="merge", merged="Bob")
        assert "未找到: Unknown" in result

    def test_merge_action_second_not_found(self, monkeypatch):
        """merge action + 第二个联系人不存在 → 返回"未找到"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        p1 = IdentityPerson(id="p1", display_name="Alice")
        r1 = MagicMock(); r1.person = p1
        r2 = MagicMock(); r2.person = None
        call_count = [0]
        def fake_resolve(conn, q):
            call_count[0] += 1
            return r1 if call_count[0] == 1 else r2
        monkeypatch.setattr("engine.identity.resolve_contact", fake_resolve)
        result = agent_contact("Alice", action="merge", merged="Unknown")
        assert "未找到: Unknown" in result

    def test_audit_action(self, monkeypatch):
        """audit action → 返回审计报告。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.facts.ensure_people_archives_migrated", lambda c, w: None)
        audit_data = {
            "multi_account": [
                {"display_name": "Alice", "person_id": "p1", "accounts": 3},
            ],
            "duplicate_aliases": [
                {"value": "小爱", "people": ["p1", "p2"]},
            ],
        }
        monkeypatch.setattr("engine.identity.audit_identity", lambda conn: audit_data)
        result = agent_contact("", action="audit")
        assert "# 身份审计" in result
        assert "## 多账号联系人" in result
        assert "Alice (p1): 3 个账号" in result
        assert "## 疑似重复" in result
        assert "小爱 -> p1, p2" in result


# ═══════════════════════════════════════════════════════════════════
# agent_sticker
# ═══════════════════════════════════════════════════════════════════

class TestAgentSticker:
    """agent_sticker 的 3 个 action 路由。"""

    def test_unknown_action(self, monkeypatch):
        """未知 action → 错误信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        result = agent_sticker(action="invalid")
        assert "未知" in result
        mock_conn.close.assert_called_once()

    def test_scan_action(self, monkeypatch):
        """scan action → 返回扫描统计。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        scan_result = {"total": 10, "new": 5, "updated": 3, "total_messages": 25}
        monkeypatch.setattr("engine.stickers.scan_stickers",
                            lambda conn, private_only: scan_result)
        result = agent_sticker(action="scan", private_only=True)
        assert "扫描完成 (私聊)" in result
        assert "10 种贴纸" in result
        assert "新增 5" in result
        assert "总贴纸消息: 25 条" in result

    def test_scan_action_all_scope(self, monkeypatch):
        """scan action + private_only=False → 显示"全部"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        scan_result = {"total": 20, "new": 0, "updated": 0, "total_messages": 100}
        monkeypatch.setattr("engine.stickers.scan_stickers",
                            lambda conn, private_only: scan_result)
        result = agent_sticker(action="scan", private_only=False)
        assert "扫描完成 (全部)" in result

    def test_list_action_empty(self, monkeypatch):
        """list action + 无贴纸 → "无贴纸数据"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit, unlabeled_only, min_frequency: [])
        result = agent_sticker(action="list")
        assert "无贴纸数据" in result
        assert "先运行 sticker scan" in result

    def test_list_action_with_data(self, monkeypatch):
        """list action + 有贴纸 → 返回格式化列表。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        mock_sticker = MagicMock()
        mock_stickers = [mock_sticker, mock_sticker]
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit, unlabeled_only, min_frequency: mock_stickers)
        monkeypatch.setattr("engine.stickers.format_sticker_list",
                            lambda stickers: "贴纸1\n贴纸2")
        result = agent_sticker(action="list", limit=30)
        assert "贴纸词典 (Top 30)" in result
        assert "贴纸1" in result

    def test_list_action_unlabeled(self, monkeypatch):
        """list action + unlabeled=True → 标题为"未标注贴纸"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        mock_sticker = MagicMock()
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit, unlabeled_only, min_frequency: [mock_sticker])
        monkeypatch.setattr("engine.stickers.format_sticker_list",
                            lambda stickers: "未标注1")
        result = agent_sticker(action="list", unlabeled=True)
        assert "未标注贴纸" in result

    def test_label_action_found_by_exact_md5(self, monkeypatch):
        """label action + 精确 md5 匹配 → 调用 label_sticker。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        mock_sticker = MagicMock()
        mock_sticker.md5 = "abcdef1234567890"
        monkeypatch.setattr("engine.stickers.get_sticker",
                            lambda conn, md5: mock_sticker)
        monkeypatch.setattr("engine.stickers.label_sticker",
                            lambda conn, md5, label, emotion, content_type: True)
        result = agent_sticker(action="label", md5="abcdef1234567890",
                               label="微笑", emotion="开心", content_type="face")
        assert "已标注" in result
        assert "abcdef123456" in result  # md5 前 12 字符

    def test_label_action_not_found(self, monkeypatch):
        """label action + md5 不存在且无前缀匹配 → "未找到"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.stickers.get_sticker",
                            lambda conn, md5: None)
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit: [])  # 无前缀匹配
        result = agent_sticker(action="label", md5="nonexistent")
        assert "未找到" in result
        assert "nonexistent" in result

    def test_label_action_multiple_prefix_matches(self, monkeypatch):
        """label action + 多个前缀匹配 → "匹配到 N 个贴纸"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.stickers.get_sticker",
                            lambda conn, md5: None)
        s1 = MagicMock(); s1.md5 = "abc1234567890"
        s2 = MagicMock(); s2.md5 = "abc9876543210"
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit: [s1, s2])
        result = agent_sticker(action="label", md5="abc")
        assert "匹配到 2 个贴纸" in result

    def test_label_action_single_prefix_match(self, monkeypatch):
        """label action + 唯一前缀匹配 → 自动选中并标注。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.stickers.get_sticker",
                            lambda conn, md5: None)
        s1 = MagicMock(); s1.md5 = "abc1234567890"
        monkeypatch.setattr("engine.stickers.list_stickers",
                            lambda conn, limit: [s1])
        monkeypatch.setattr("engine.stickers.label_sticker",
                            lambda conn, md5, label, emotion, content_type: True)
        result = agent_sticker(action="label", md5="abc", label="微笑")
        assert "已标注" in result


# ═══════════════════════════════════════════════════════════════════
# agent_exclude
# ═══════════════════════════════════════════════════════════════════

class TestAgentExclude:
    """agent_exclude 的 3 个 action 路由。"""

    def test_unknown_action(self, monkeypatch):
        """未知 action → 错误信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        result = agent_exclude(action="invalid")
        assert "未知" in result
        mock_conn.close.assert_called_once()

    def test_list_action_empty(self, monkeypatch):
        """list action + 无排除项 → 显示空列表 + 参与排名统计。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        mock_config.ranking.exclude.name_keywords = []
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.analyzers.exclude.get_manual_excludes",
                            lambda conn: {})
        monkeypatch.setattr("engine.analyzers.metrics.get_all_contacts_with_messages",
                            lambda conn, min_messages: [])
        monkeypatch.setattr("engine.analyzers.exclude.filter_contacts",
                            lambda contacts, conn, my_wxid, name_keywords: ([], []))
        result = agent_exclude(action="list")
        assert "# 排除列表" in result
        assert "## 硬排除" in result
        assert "## 标签排除 (0)" in result
        assert "## 手动排除 (0)" in result
        assert "参与排名: 0 / 0" in result

    def test_add_action_person_not_found(self, monkeypatch):
        """add action + 联系人不存在 → "未找到"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        mock_result = MagicMock(); mock_result.person = None
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        result = agent_exclude(action="add", name="Unknown")
        assert "未找到: Unknown" in result

    def test_add_action_no_accounts(self, monkeypatch):
        """add action + person 无账号 → "无关联账号"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(id="p1", display_name="Alice", accounts=[])
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        result = agent_exclude(action="add", name="Alice")
        assert "Alice 无关联账号" in result

    def test_add_action_success(self, monkeypatch):
        """add action + 成功排除 → 返回成功信息。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_a",
                                       conversation_id="wxid_a", display_name="Alice")],
        )
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        added = []
        monkeypatch.setattr("engine.analyzers.exclude.add_manual_exclude",
                            lambda conn, wxid, reason: added.append((wxid, reason)))
        result = agent_exclude(action="add", name="Alice", reason="测试排除")
        assert "已排除: Alice" in result
        assert "原因: 测试排除" in result
        assert added == [("wxid_a", "测试排除")]

    def test_remove_action_person_not_found(self, monkeypatch):
        """remove action + 联系人不存在 → "未找到"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        mock_result = MagicMock(); mock_result.person = None
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        result = agent_exclude(action="remove", name="Unknown")
        assert "未找到: Unknown" in result

    def test_remove_action_success(self, monkeypatch):
        """remove action + 取消排除 → 返回取消数量。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[
                IdentityAccount(id="a1", person_id="p1", wxid="wxid_a",
                                conversation_id="wxid_a", display_name="Alice"),
                IdentityAccount(id="a2", person_id="p1", wxid="wxid_b",
                                conversation_id="wxid_b", display_name="Alice2"),
            ],
        )
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        monkeypatch.setattr("engine.analyzers.exclude.remove_manual_exclude",
                            lambda conn, wxid: True)
        result = agent_exclude(action="remove", name="Alice")
        assert "已取消排除: Alice" in result
        assert "2 个账号" in result

    def test_remove_action_not_excluded(self, monkeypatch):
        """remove action + 联系人不在排除列表 → "不在排除列表中"。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        monkeypatch.setattr("engine.agent.identity_ops._get_conn", lambda: (mock_conn, mock_config))
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_a",
                                       conversation_id="wxid_a", display_name="Alice")],
        )
        mock_result = MagicMock(); mock_result.person = person
        monkeypatch.setattr("engine.identity.resolve_contact",
                            lambda conn, q: mock_result)
        monkeypatch.setattr("engine.analyzers.exclude.remove_manual_exclude",
                            lambda conn, wxid: False)
        result = agent_exclude(action="remove", name="Alice")
        assert "不在排除列表中" in result


# ═══════════════════════════════════════════════════════════════════
# agent_failure
# ═══════════════════════════════════════════════════════════════════

class TestAgentFailure:
    """agent_failure 的 add/list 2 个 action。"""

    def test_unknown_action(self):
        """未知 action → 错误信息。"""
        result = agent_failure(action="invalid")
        assert "未知" in result
        assert "invalid" in result

    def test_add_action(self, monkeypatch):
        """add action → 构造 FailureCase + 调用 save_failure。"""
        saved_cases = []
        def fake_save(case):
            saved_cases.append(case)
            return Path("/tmp/test_failure.md")
        monkeypatch.setattr("engine.facts.failure_archive.save_failure", fake_save)
        result = agent_failure(action="add", person="Alice", stage="stage_2",
                               cause="需求感过强", lesson="控制节奏",
                               signals="太秒回, 过度热情", outcome="对方冷淡")
        assert "已保存失败案例" in result
        assert "/tmp/test_failure.md" in result or "test_failure.md" in result
        # 验证 FailureCase 构造正确
        assert len(saved_cases) == 1
        case = saved_cases[0]
        assert case.person == "Alice"
        assert case.stage == "stage_2"
        assert case.cause == "需求感过强"
        assert case.lesson == "控制节奏"
        assert case.signals == ["太秒回", "过度热情"]
        assert case.outcome == "对方冷淡"
        # created_at 应是今天日期格式 YYYY-MM-DD
        assert datetime.strptime(case.created_at, "%Y-%m-%d") is not None

    def test_add_action_with_empty_signals(self, monkeypatch):
        """add action + signals 为空 → signals=[]。"""
        saved_cases = []
        def fake_save(case):
            saved_cases.append(case)
            return Path("/tmp/test.md")
        monkeypatch.setattr("engine.facts.failure_archive.save_failure", fake_save)
        result = agent_failure(action="add", person="Alice", signals="")
        assert "已保存失败案例" in result
        assert saved_cases[0].signals == []

    def test_add_action_with_signals_whitespace(self, monkeypatch):
        """add action + signals 含空白项 → 过滤空白。"""
        saved_cases = []
        def fake_save(case):
            saved_cases.append(case)
            return Path("/tmp/test.md")
        monkeypatch.setattr("engine.facts.failure_archive.save_failure", fake_save)
        # 含空字符串和空白字符的 signals
        agent_failure(action="add", person="Alice", signals=" a , , b ")
        assert saved_cases[0].signals == ["a", "b"]

    def test_list_action(self, monkeypatch):
        """list action → 调用 load_all_failures + format_failures。"""
        cases = [MagicMock(spec=FailureCase), MagicMock(spec=FailureCase)]
        monkeypatch.setattr("engine.facts.failure_archive.load_all_failures",
                            lambda: cases)
        monkeypatch.setattr("engine.facts.failure_archive.format_failures",
                            lambda cs: "案例1\n案例2" if len(cs) == 2 else "")
        result = agent_failure(action="list")
        assert "案例1" in result
        assert "案例2" in result

    def test_list_action_empty(self, monkeypatch):
        """list action + 无案例 → format_failures 返回空。"""
        monkeypatch.setattr("engine.facts.failure_archive.load_all_failures",
                            lambda: [])
        monkeypatch.setattr("engine.facts.failure_archive.format_failures",
                            lambda cs: "暂无失败案例" if not cs else "")
        result = agent_failure(action="list")
        assert "暂无失败案例" in result
