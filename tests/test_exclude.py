"""exclude.py 单元测试。

覆盖 HARDCODED_WXIDS/PREFIXES/SUFFIXES/EXCLUDE_LABELS/PRIORITY_LABEL 常量、
parse_labels、is_hard_excluded、get_manual_excludes、add_manual_exclude、
remove_manual_exclude、filter_contacts、get_contact_labels、search_contacts、
账号合并相关函数。
"""
from __future__ import annotations

import json
import time

import pytest

from engine.analyzers.exclude import (
    EXCLUDE_LABELS,
    HARDCODED_PREFIXES,
    HARDCODED_SUFFIXES,
    HARDCODED_WXIDS,
    PRIORITY_LABEL,
    ExcludeInfo,
    add_manual_exclude,
    add_merge,
    filter_contacts,
    get_all_merges,
    get_contact_labels,
    get_merge_for_wxid,
    get_manual_excludes,
    is_hard_excluded,
    parse_labels,
    remove_manual_exclude,
    remove_merge,
    search_contacts,
)


# ── 常量 ─────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_hardcoded_wxids_contains_filehelper(self):
        assert "filehelper" in HARDCODED_WXIDS

    def test_hardcoded_wxids_contains_exmail_tool(self):
        assert "exmail_tool" in HARDCODED_WXIDS

    def test_hardcoded_prefixes_contains_ww(self):
        assert "ww_" in HARDCODED_PREFIXES

    def test_hardcoded_prefixes_contains_qq(self):
        assert "qq" in HARDCODED_PREFIXES

    def test_hardcoded_suffixes_contains_openim(self):
        assert "@openim" in HARDCODED_SUFFIXES

    def test_exclude_labels_contains_non_target(self):
        assert "非攻略对象" in EXCLUDE_LABELS
        assert "放弃" in EXCLUDE_LABELS
        assert "群友" in EXCLUDE_LABELS

    def test_priority_label(self):
        assert PRIORITY_LABEL == "置顶攻略对象"


# ── parse_labels ─────────────────────────────────────────────────────────────

class TestParseLabels:
    def test_none_returns_empty(self):
        assert parse_labels(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_labels("") == []

    def test_valid_json_list(self):
        assert parse_labels('["a", "b"]') == ["a", "b"]

    def test_valid_json_empty_list(self):
        assert parse_labels('[]') == []

    def test_json_not_list_returns_empty(self):
        """JSON 解析为非 list（如 dict/str）时返回空。"""
        assert parse_labels('{"key": "value"}') == []
        assert parse_labels('"single string"') == []

    def test_invalid_json_returns_empty(self):
        assert parse_labels('not json') == []

    def test_chinese_labels(self):
        labels = '["非攻略对象", "置顶攻略对象"]'
        assert parse_labels(labels) == ["非攻略对象", "置顶攻略对象"]


# ── is_hard_excluded ─────────────────────────────────────────────────────────

class TestIsHardExcluded:
    def test_my_wxid_exact_match(self):
        assert is_hard_excluded("wxid_me", "wxid_me") == "用户自己"

    def test_my_wxid_prefix_match(self):
        """wxid 以 my_wxid 开头也视为用户自己。"""
        assert is_hard_excluded("wxid_me_suffix", "wxid_me") == "用户自己"

    def test_filehelper(self):
        assert is_hard_excluded("filehelper", "wxid_me") == "系统账号"

    def test_exmail_tool(self):
        assert is_hard_excluded("exmail_tool", "wxid_me") == "系统账号"

    def test_shhtinns(self):
        assert is_hard_excluded("shhtinns", "wxid_me") == "系统账号"

    def test_opencustomerservicemsg(self):
        assert is_hard_excluded("@opencustomerservicemsg", "wxid_me") == "系统账号"

    def test_ww_prefix(self):
        result = is_hard_excluded("ww_corp123", "wxid_me")
        assert result is not None
        assert "ww_" in result

    def test_qq_prefix(self):
        result = is_hard_excluded("qq123456", "wxid_me")
        assert result is not None
        assert "qq" in result

    def test_openim_suffix(self):
        result = is_hard_excluded("wxid_test@openim", "wxid_me")
        assert result is not None
        assert "@openim" in result

    def test_qy_u_suffix(self):
        result = is_hard_excluded("wxid_test@qy_u", "wxid_me")
        assert result is not None
        assert "@qy_u" in result

    def test_normal_wxid_not_excluded(self):
        assert is_hard_excluded("wxid_normal123", "wxid_me") is None

    def test_empty_my_wxid_matches_everything(self):
        """边界情况：my_wxid="" 时任何 wxid 都 startswith("") → 视为用户自己。

        这是代码的已知行为（实际使用中 my_wxid 不会为空），测试固化。
        """
        assert is_hard_excluded("wxid_x", "") == "用户自己"


# ── manual_excludes ──────────────────────────────────────────────────────────

class TestManualExcludes:
    def test_get_empty_when_no_table_data(self, tmp_db):
        """contact_excludes 表存在但无数据时返回空 dict。"""
        assert get_manual_excludes(tmp_db) == {}

    def test_add_and_get(self, tmp_db):
        add_manual_exclude(tmp_db, "wxid_block1", "测试屏蔽")
        result = get_manual_excludes(tmp_db)
        assert "wxid_block1" in result
        assert result["wxid_block1"] == "测试屏蔽"

    def test_add_default_reason(self, tmp_db):
        add_manual_exclude(tmp_db, "wxid_block2")
        result = get_manual_excludes(tmp_db)
        assert result["wxid_block2"] == "手动排除"

    def test_add_duplicate_updates_reason(self, tmp_db):
        """重复添加同一 wxid 应更新 reason。"""
        add_manual_exclude(tmp_db, "wxid_dup", "原因1")
        add_manual_exclude(tmp_db, "wxid_dup", "原因2")
        result = get_manual_excludes(tmp_db)
        assert result["wxid_dup"] == "原因2"

    def test_remove_existing(self, tmp_db):
        add_manual_exclude(tmp_db, "wxid_rm")
        assert remove_manual_exclude(tmp_db, "wxid_rm") is True
        assert get_manual_excludes(tmp_db) == {}

    def test_remove_nonexistent_returns_false(self, tmp_db):
        assert remove_manual_exclude(tmp_db, "not_exist") is False


# ── filter_contacts ──────────────────────────────────────────────────────────

class TestFilterContacts:
    def _make_contact(self, wxid: str, display_name: str = "",
                      message_count: int = 100) -> dict:
        return {
            "wxid": wxid,
            "display_name": display_name,
            "message_count": message_count,
        }

    def test_empty_contacts(self, tmp_db):
        included, excluded = filter_contacts([], tmp_db, "wxid_me")
        assert included == []
        assert excluded == []

    def test_normal_contact_included(self, tmp_db, setup_contacts):
        setup_contacts("wxid_alice", "Alice", display_name="Alice")
        c = self._make_contact("wxid_alice", "Alice")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert len(included) == 1
        assert included[0]["wxid"] == "wxid_alice"
        assert excluded == []

    def test_my_wxid_excluded(self, tmp_db):
        c = self._make_contact("wxid_me", "Me")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert len(excluded) == 1
        assert excluded[0].reason == "用户自己"

    def test_filehelper_excluded(self, tmp_db):
        c = self._make_contact("filehelper", "文件助手")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert excluded[0].reason == "系统账号"

    def test_ww_prefix_excluded(self, tmp_db):
        c = self._make_contact("ww_corp123", "企业号")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert "非个人账号" in excluded[0].reason

    def test_exclude_label_excluded(self, tmp_db, setup_contacts):
        """标签含 '非攻略对象' 被排除。"""
        setup_contacts("wxid_lbl", "Lbl", display_name="Lbl")
        # 更新 labels
        tmp_db.execute(
            "UPDATE contacts SET labels = ? WHERE id = ?",
            (json.dumps(["非攻略对象"], ensure_ascii=False), "wxid_lbl"),
        )
        tmp_db.commit()
        c = self._make_contact("wxid_lbl", "Lbl")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert "标签" in excluded[0].reason
        assert "非攻略对象" in excluded[0].reason

    def test_priority_label_marks_top_target(self, tmp_db, setup_contacts):
        """标签含 '置顶攻略对象' 标记为 top_target。"""
        setup_contacts("wxid_top", "Top", display_name="Top")
        tmp_db.execute(
            "UPDATE contacts SET labels = ? WHERE id = ?",
            (json.dumps(["置顶攻略对象"], ensure_ascii=False), "wxid_top"),
        )
        tmp_db.commit()
        c = self._make_contact("wxid_top", "Top")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert len(included) == 1
        assert included[0].get("top_target") is True
        assert "置顶攻略对象" in included[0].get("labels", [])

    def test_former_friend_type_excluded(self, tmp_db, setup_contacts):
        """contacts.type = 'former_friend' 被排除。"""
        setup_contacts("wxid_ff", "FF", display_name="FF")
        tmp_db.execute(
            "UPDATE contacts SET type = 'former_friend' WHERE id = ?",
            ("wxid_ff",),
        )
        tmp_db.commit()
        c = self._make_contact("wxid_ff", "FF")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert excluded[0].reason == "已删除好友"

    def test_manual_exclude(self, tmp_db, setup_contacts):
        setup_contacts("wxid_man", "Man", display_name="Man")
        add_manual_exclude(tmp_db, "wxid_man", "不想聊")
        c = self._make_contact("wxid_man", "Man")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert excluded[0].reason == "不想聊"

    def test_name_keyword_exclude_by_display_name(self, tmp_db, setup_contacts):
        setup_contacts("wxid_kw", "测试 Bot", display_name="测试 Bot")
        c = self._make_contact("wxid_kw", "测试 Bot")
        included, excluded = filter_contacts(
            [c], tmp_db, "wxid_me", name_keywords=["Bot"]
        )
        assert included == []
        assert "Bot" in excluded[0].reason

    def test_name_keyword_exclude_by_remark(self, tmp_db, setup_contacts):
        setup_contacts("wxid_kw2", "原始", remark="备注Bot", display_name="原始")
        c = self._make_contact("wxid_kw2", "原始")
        included, excluded = filter_contacts(
            [c], tmp_db, "wxid_me", name_keywords=["Bot"]
        )
        assert included == []
        assert "Bot" in excluded[0].reason

    def test_name_keyword_exclude_by_nickname(self, tmp_db, setup_contacts):
        # setup_contacts 签名: (wxid, nickname, remark="", display_name="")
        setup_contacts("wxid_kw3", "nickBot", display_name="displayX")
        c = self._make_contact("wxid_kw3", "displayX")
        included, excluded = filter_contacts(
            [c], tmp_db, "wxid_me", name_keywords=["Bot"]
        )
        assert included == []
        assert "Bot" in excluded[0].reason

    def test_priority_over_excluded(self, tmp_db, setup_contacts):
        """标签同时含排除标签和优先标签时，排除标签优先。"""
        setup_contacts("wxid_both", "Both", display_name="Both")
        tmp_db.execute(
            "UPDATE contacts SET labels = ? WHERE id = ?",
            (json.dumps(["非攻略对象", "置顶攻略对象"], ensure_ascii=False), "wxid_both"),
        )
        tmp_db.commit()
        c = self._make_contact("wxid_both", "Both")
        included, excluded = filter_contacts([c], tmp_db, "wxid_me")
        assert included == []
        assert len(excluded) == 1

    def test_multiple_contacts_filter(self, tmp_db, setup_contacts):
        """多联系人混合过滤。"""
        setup_contacts("wxid_alice", "Alice", display_name="Alice")
        setup_contacts("wxid_filehelper", "FH", display_name="FH")
        setup_contacts("wxid_bob", "Bob", display_name="Bob")

        contacts = [
            self._make_contact("wxid_alice", "Alice"),
            self._make_contact("filehelper", "文件助手"),
            self._make_contact("wxid_bob", "Bob"),
        ]
        included, excluded = filter_contacts(contacts, tmp_db, "wxid_me")
        # alice + bob 通过，filehelper 被排除
        assert len(included) == 2
        assert len(excluded) == 1
        assert excluded[0].wxid == "filehelper"


# ── get_contact_labels ───────────────────────────────────────────────────────

class TestGetContactLabels:
    def test_no_contact_returns_empty(self, tmp_db):
        assert get_contact_labels(tmp_db, "not_exist") == []

    def test_returns_labels(self, tmp_db, setup_contacts):
        setup_contacts("wxid_lbl", "Lbl", display_name="Lbl")
        tmp_db.execute(
            "UPDATE contacts SET labels = ? WHERE id = ?",
            (json.dumps(["a", "b"], ensure_ascii=False), "wxid_lbl"),
        )
        tmp_db.commit()
        assert get_contact_labels(tmp_db, "wxid_lbl") == ["a", "b"]

    def test_empty_labels_returns_empty(self, tmp_db, setup_contacts):
        setup_contacts("wxid_emptylbl", "Empty", display_name="Empty")
        assert get_contact_labels(tmp_db, "wxid_emptylbl") == []


# ── search_contacts ──────────────────────────────────────────────────────────

class TestSearchContacts:
    def test_no_match_returns_empty(self, tmp_db, setup_contacts):
        setup_contacts("wxid_a", "Alice", display_name="Alice")
        assert search_contacts(tmp_db, "不存在的名字") == []

    def test_match_display_name(self, tmp_db, setup_contacts):
        setup_contacts("wxid_a", "Alice", display_name="Alice")
        result = search_contacts(tmp_db, "Alice")
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_a"
        assert result[0]["display_name"] == "Alice"

    def test_match_remark(self, tmp_db, setup_contacts):
        setup_contacts("wxid_b", "Bob", remark="备注B", display_name="displayB")
        result = search_contacts(tmp_db, "备注B")
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_b"
        assert result[0]["remark"] == "备注B"

    def test_match_nickname(self, tmp_db, setup_contacts):
        # setup_contacts 签名: (wxid, nickname, remark="", display_name="")
        setup_contacts("wxid_c", "nickC", display_name="dispC")
        result = search_contacts(tmp_db, "nickC")
        assert len(result) == 1
        assert result[0]["nickname"] == "nickC"

    def test_match_alias(self, tmp_db, setup_contacts):
        """alias 字段也可被搜索。"""
        setup_contacts("wxid_d", "Alias", display_name="Alias")
        tmp_db.execute(
            "UPDATE contacts SET alias = ? WHERE id = ?",
            ("alias_d", "wxid_d"),
        )
        tmp_db.commit()
        result = search_contacts(tmp_db, "alias_d")
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_d"

    def test_partial_match(self, tmp_db, setup_contacts):
        """LIKE 模糊匹配。"""
        setup_contacts("wxid_e", "Alice姐姐", display_name="Alice姐姐")
        result = search_contacts(tmp_db, "Alice")
        assert len(result) == 1

    def test_limit_20(self, tmp_db, setup_contacts):
        """搜索结果上限 20 条。"""
        for i in range(25):
            setup_contacts(f"wxid_u{i}", f"User{i}", display_name=f"User{i}")
        result = search_contacts(tmp_db, "User")
        assert len(result) == 20

    def test_returns_labels_field(self, tmp_db, setup_contacts):
        setup_contacts("wxid_lbl", "Lbl", display_name="Lbl")
        tmp_db.execute(
            "UPDATE contacts SET labels = ? WHERE id = ?",
            (json.dumps(["标签1"], ensure_ascii=False), "wxid_lbl"),
        )
        tmp_db.commit()
        result = search_contacts(tmp_db, "Lbl")
        assert result[0]["labels"] == ["标签1"]

    def test_only_private_conversations(self, tmp_db, setup_contacts):
        """只搜索 type='private' 的会话。"""
        setup_contacts("wxid_priv", "Priv", display_name="Priv")
        # 添加一个群聊会话（不会被搜到）
        tmp_db.execute(
            "INSERT OR IGNORE INTO conversations (id, type, display_name, contact_id, updated_at) "
            "VALUES (?, 'group', ?, ?, ?)",
            ("group_x", "群名", "group_x", int(time.time())),
        )
        tmp_db.commit()
        # 搜 "Priv" 应只返回私聊
        result = search_contacts(tmp_db, "Priv")
        assert len(result) == 1
        assert result[0]["wxid"] == "wxid_priv"


# ── 账号合并 ─────────────────────────────────────────────────────────────────

class TestContactMerges:
    def test_get_all_merges_empty(self, tmp_db):
        assert get_all_merges(tmp_db) == {}

    def test_add_and_get_merge(self, tmp_db):
        add_merge(tmp_db, "wxid_main", ["wxid_sub1", "wxid_sub2"], "主账号")
        result = get_all_merges(tmp_db)
        assert "wxid_main" in result
        assert "wxid_sub1" in result["wxid_main"]
        assert "wxid_sub2" in result["wxid_main"]

    def test_add_merge_updates_existing(self, tmp_db):
        """重复添加同一 canonical_wxid 应更新 merged_wxids。"""
        add_merge(tmp_db, "wxid_main", ["wxid_sub1"], "主账号")
        add_merge(tmp_db, "wxid_main", ["wxid_sub2", "wxid_sub3"], "主账号v2")
        result = get_all_merges(tmp_db)
        assert result["wxid_main"] == ["wxid_sub2", "wxid_sub3"]

    def test_get_merge_for_wxid_canonical(self, tmp_db):
        add_merge(tmp_db, "wxid_main", ["wxid_sub1", "wxid_sub2"])
        # 主账号本身也在合并组中
        result = get_merge_for_wxid(tmp_db, "wxid_main")
        assert result is not None
        assert "wxid_main" in result
        assert "wxid_sub1" in result
        assert "wxid_sub2" in result

    def test_get_merge_for_wxid_merged(self, tmp_db):
        add_merge(tmp_db, "wxid_main", ["wxid_sub1", "wxid_sub2"])
        # 子账号也属于合并组
        result = get_merge_for_wxid(tmp_db, "wxid_sub1")
        assert result is not None
        assert "wxid_main" in result
        assert "wxid_sub2" in result

    def test_get_merge_for_wxid_not_merged(self, tmp_db):
        assert get_merge_for_wxid(tmp_db, "wxid_alone") is None

    def test_remove_merge_existing(self, tmp_db):
        add_merge(tmp_db, "wxid_main", ["wxid_sub1"])
        assert remove_merge(tmp_db, "wxid_main") is True
        assert get_all_merges(tmp_db) == {}

    def test_remove_merge_nonexistent(self, tmp_db):
        assert remove_merge(tmp_db, "not_exist") is False

    def test_add_merge_with_display_name(self, tmp_db):
        add_merge(tmp_db, "wxid_main", ["wxid_sub1"], display_name="合并账号")
        # 验证 display_name 被存储
        row = tmp_db.execute(
            "SELECT display_name FROM contact_merges WHERE canonical_wxid = ?",
            ("wxid_main",),
        ).fetchone()
        assert row["display_name"] == "合并账号"


# ── ExcludeInfo dataclass ────────────────────────────────────────────────────

class TestExcludeInfo:
    def test_construction(self):
        info = ExcludeInfo(wxid="wxid_x", display_name="X", reason="测试")
        assert info.wxid == "wxid_x"
        assert info.display_name == "X"
        assert info.reason == "测试"

    def test_equality(self):
        """dataclass 默认生成 __eq__。"""
        a = ExcludeInfo("w", "n", "r")
        b = ExcludeInfo("w", "n", "r")
        assert a == b
