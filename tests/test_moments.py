"""engine/agent/moments.py 单元测试。

覆盖：
- _query_moments_data（朋友圈数据查询）
- _format_moments_section（格式化朋友圈 section）
- moments_stats（朋友圈统计主函数）
- sync_moments_to_archive（同步朋友圈到档案）
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.agent.moments import (
    _query_moments_data,
    _format_moments_section,
    moments_stats,
    sync_moments_to_archive,
)
from engine.config import Config, ROOT_DIR
from engine.identity import IdentityPerson, IdentityAccount


# ═══════════════════════════════════════════════════════════════════
# _query_moments_data
# ═══════════════════════════════════════════════════════════════════

class TestQueryMomentsData:
    """_query_moments_data 查询朋友圈数据。"""

    def test_empty_db_returns_empty_structure(self, tmp_db):
        """空 DB → 3 个空列表。"""
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert result == {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }

    def test_her_posts_queried(self, tmp_db, now_ts):
        """她的朋友圈动态被查询。"""
        # 她发的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, like_count, comment_count, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, 5, 2, now_ts),
        )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert len(result["her_posts"]) == 1
        assert result["her_posts"][0]["content"] == "她的动态"
        assert result["her_posts"][0]["likes"] == 5
        assert result["her_posts"][0]["comments"] == 2

    def test_my_interactions_on_her_posts(self, tmp_db, now_ts):
        """我在她朋友圈的互动被查询。"""
        # 需要先在 contacts 表注册 wxid_me 的 display_name
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            ("wxid_me", "我的名字", now_ts),
        )
        # 她发的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        # 我在她朋友圈评论
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_me", "我的名字", "我的评论", now_ts, now_ts),
        )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert len(result["my_interactions_on_her_posts"]) == 1
        assert result["my_interactions_on_her_posts"][0]["type"] == "comment"
        assert result["my_interactions_on_her_posts"][0]["content"] == "我的评论"
        assert result["my_interactions_on_her_posts"][0]["her_post"] == "她的动态"

    def test_her_interactions_on_my_posts(self, tmp_db, now_ts):
        """她在我朋友圈的互动被查询（display_name 过滤）。"""
        # 我发的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的动态", now_ts, now_ts),
        )
        # 她在我朋友圈点赞
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "like", "wxid_her", "Alice", "", now_ts, now_ts),
        )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert len(result["her_interactions_on_my_posts"]) == 1
        assert result["her_interactions_on_my_posts"][0]["type"] == "like"
        assert result["her_interactions_on_my_posts"][0]["my_post"] == "我的动态"

    def test_no_my_name_no_my_interactions(self, tmp_db, now_ts):
        """contacts 表无 wxid_me 记录 → my_interactions 为空。"""
        # 不创建 contacts 记录
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_me", "我的名字", "评论", now_ts, now_ts),
        )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        # my_interactions 应为空（my_name 为空）
        assert result["my_interactions_on_her_posts"] == []

    def test_no_display_name_no_her_interactions(self, tmp_db, now_ts):
        """display_name 为空 → her_interactions 为空。"""
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的动态", now_ts, now_ts),
        )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "")
        assert result["her_interactions_on_my_posts"] == []

    def test_her_posts_limited_to_20(self, tmp_db, now_ts):
        """her_posts 最多 20 条（LIMIT 20）。"""
        for i in range(25):
            tmp_db.execute(
                "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"mo{i}", "wxid_her", "Alice", f"动态{i}", now_ts + i, now_ts),
            )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        assert len(result["her_posts"]) == 20

    def test_her_posts_ordered_by_timestamp_desc(self, tmp_db, now_ts):
        """her_posts 按 timestamp 降序。"""
        for i in range(5):
            tmp_db.execute(
                "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"mo{i}", "wxid_her", "Alice", f"动态{i}", now_ts + i * 100, now_ts),
            )
        tmp_db.commit()
        result = _query_moments_data(tmp_db, "wxid_her", "wxid_me", "Alice")
        # 第一条应是 timestamp 最大的（动态4）
        assert result["her_posts"][0]["content"] == "动态4"

    def test_empty_my_wxid_loads_config(self, tmp_db, monkeypatch):
        """my_wxid 为空 → 调用 load_config()。"""
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_from_config"
        monkeypatch.setattr("engine.agent.moments.load_config", lambda: mock_config)
        # 不应崩溃
        result = _query_moments_data(tmp_db, "wxid_her", "", "Alice")
        assert result["her_posts"] == []


# ═══════════════════════════════════════════════════════════════════
# _format_moments_section
# ═══════════════════════════════════════════════════════════════════

class TestFormatMomentsSection:
    """_format_moments_section 格式化朋友圈 section。"""

    def test_empty_moments_returns_empty(self):
        """3 个列表都空 → 空字符串。"""
        moments = {
            "her_posts": [], "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        assert _format_moments_section(moments) == ""

    def test_her_interactions_on_my_posts(self):
        """她在你朋友圈的互动 → '### 她在你的朋友圈互动'。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [
                {"type": "comment", "content": "她的评论", "timestamp": ts, "my_post": "我的动态"},
            ],
        }
        result = _format_moments_section(moments)
        assert "### 她在你的朋友圈互动" in result
        assert "[07-24]" in result
        assert "评论" in result
        assert "她的评论" in result
        assert "我的动态" in result

    def test_my_interactions_on_her_posts(self):
        """你在她朋友圈的互动 → '### 你在她的朋友圈互动'。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [
                {"type": "like", "content": "", "timestamp": ts, "her_post": "她的动态"},
            ],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        assert "### 你在她的朋友圈互动" in result
        assert "点赞" in result

    def test_her_posts(self):
        """她的朋友圈动态 → '### 她的朋友圈动态'。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [
                {"content": "今天的分享", "timestamp": ts, "likes": 3, "comments": 1},
            ],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        assert "### 她的朋友圈动态" in result
        assert "今天的分享" in result
        assert "3赞" in result
        assert "1评" in result

    def test_her_post_empty_content(self):
        """her_post content 为空 → 显示 (图片/视频)。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [
                {"content": "", "timestamp": ts, "likes": 0, "comments": 0},
            ],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        assert "(图片/视频)" in result

    def test_her_post_no_likes_no_comments(self):
        """her_post 无赞无评 → 不显示统计后缀。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [
                {"content": "内容", "timestamp": ts, "likes": 0, "comments": 0},
            ],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        assert "赞" not in result
        assert "评" not in result

    def test_interaction_comment_with_content(self):
        """评论互动 → 显示评论内容。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [
                {"type": "comment", "content": "评论内容", "timestamp": ts, "my_post": "原贴"},
            ],
        }
        result = _format_moments_section(moments)
        assert ': "评论内容"' in result

    def test_interaction_like_without_content(self):
        """点赞互动 → 不显示评论内容。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [
                {"type": "like", "content": "", "timestamp": ts, "my_post": "原贴"},
            ],
        }
        result = _format_moments_section(moments)
        # 点赞不应有评论内容
        assert ': "' not in result

    def test_her_posts_truncated_to_60_chars(self):
        """her_post content 截取前 60 字符。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        long_content = "a" * 100
        moments = {
            "her_posts": [
                {"content": long_content, "timestamp": ts, "likes": 0, "comments": 0},
            ],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        # 截取的 content 部分 ≤ 60 字符
        # 格式 "- [07-24] content"
        line = [l for l in result.split("\n") if "a" * 10 in l][0]
        content_part = line.split("] ", 1)[1] if "] " in line else line
        assert len(content_part) <= 60

    def test_post_preview_truncated_to_30_chars(self):
        """互动中的 post preview 截取前 30 字符。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        long_post = "b" * 100
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [
                {"type": "like", "content": "", "timestamp": ts, "my_post": long_post},
            ],
        }
        result = _format_moments_section(moments)
        # 「post_preview」截取前 30 字符
        assert "b" * 30 in result
        assert "b" * 100 not in result

    def test_comment_content_truncated_to_40_chars(self):
        """评论内容截取前 40 字符。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        long_comment = "c" * 100
        moments = {
            "her_posts": [],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [
                {"type": "comment", "content": long_comment, "timestamp": ts, "my_post": "post"},
            ],
        }
        result = _format_moments_section(moments)
        # 评论内容截取前 40 字符
        assert "c" * 40 in result
        assert "c" * 100 not in result

    def test_max_10_items_per_section(self):
        """每个 section 最多显示 10 条。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [
                {"content": f"动态{i}", "timestamp": ts, "likes": 0, "comments": 0}
                for i in range(15)
            ],
            "my_interactions_on_her_posts": [],
            "her_interactions_on_my_posts": [],
        }
        result = _format_moments_section(moments)
        # 应只显示前 10 条
        for i in range(10):
            assert f"动态{i}" in result
        assert "动态10" not in result
        assert "动态14" not in result

    def test_section_order(self):
        """section 顺序：她的互动 → 你的互动 → 她的动态。"""
        ts = int(datetime(2024, 7, 24).timestamp())
        moments = {
            "her_posts": [{"content": "她的动态", "timestamp": ts, "likes": 0, "comments": 0}],
            "my_interactions_on_her_posts": [
                {"type": "like", "content": "", "timestamp": ts, "her_post": "她的贴"},
            ],
            "her_interactions_on_my_posts": [
                {"type": "like", "content": "", "timestamp": ts, "my_post": "我的贴"},
            ],
        }
        result = _format_moments_section(moments)
        idx_her = result.find("### 她在你的朋友圈互动")
        idx_my = result.find("### 你在她的朋友圈互动")
        idx_posts = result.find("### 她的朋友圈动态")
        assert idx_her < idx_my < idx_posts


# ═══════════════════════════════════════════════════════════════════
# moments_stats
# ═══════════════════════════════════════════════════════════════════

class TestMomentsStats:
    """moments_stats 朋友圈统计主函数。

    注：moments_stats 函数内部 `from engine.agent.core import _get_conn, _resolve_person`，
    所以必须 patch `engine.agent.core._get_conn` 和 `engine.agent.core._resolve_person`。
    """

    def test_person_not_found(self, monkeypatch):
        """未找到联系人 → 错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: None)
        result = moments_stats("Alice")
        assert "未找到联系人" in result
        assert "Alice" in result

    def test_person_no_accounts(self, monkeypatch):
        """联系人无 accounts → 错误字符串。"""
        mock_conn = MagicMock()
        mock_config = MagicMock()
        mock_config.my_wxid = "wxid_me"
        person = IdentityPerson(id="p1", display_name="Alice")
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (mock_conn, mock_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert "未找到联系人" in result

    def test_no_interactions(self, monkeypatch, tmp_db, test_config):
        """无朋友圈互动 → summary='无朋友圈互动'。"""
        # 插入联系人记录
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", 1),
        )
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        assert result["engagement_summary"] == "无朋友圈互动"
        assert result["her_posts"] == 0
        assert result["my_likes_on_her"] == 0

    def test_one_sided_my_interactions(self, monkeypatch, tmp_db, test_config, now_ts):
        """只有我互动 → summary='单向投入'。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 她的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        # 我点赞
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "like", "wxid_me", "我的名字", "", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        assert "单向投入" in result["engagement_summary"]
        assert result["my_likes_on_her"] == 1
        assert result["her_likes_on_my"] == 0

    def test_one_sided_her_interactions(self, monkeypatch, tmp_db, test_config, now_ts):
        """只有她互动 → summary='她主动'。"""
        test_config.my_wxid = "wxid_me"  # 与 SQL 数据中的 "wxid_me" 保持一致
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 我的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", "我的动态", now_ts, now_ts),
        )
        # 她评论
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "评论内容", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        assert "她主动" in result["engagement_summary"]
        assert result["her_comments_on_my"] == 1

    def test_my_over_investment(self, monkeypatch, tmp_db, test_config, now_ts):
        """我互动 > 她的 2 倍 → summary='你投入过多'。"""
        test_config.my_wxid = "wxid_me"  # 与 SQL 数据中的 "wxid_me" 保持一致
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 她的朋友圈（我多次互动）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        # 我 3 次点赞
        for i in range(3):
            tmp_db.execute(
                "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"mi{i}", "mo1", "like", "wxid_me", "我的名字", "", now_ts + i, now_ts),
            )
        # 我的朋友圈（她 1 次点赞）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo2", "wxid_me", "我的名字", "我的动态", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi3", "mo2", "like", "wxid_her", "Alice", "", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        # total_my=3, total_her=1, 3 > 1*2 → 你投入过多
        assert "你投入过多" in result["engagement_summary"]

    def test_balanced_interactions(self, monkeypatch, tmp_db, test_config, now_ts):
        """互动均衡 → summary='互动均衡'。"""
        test_config.my_wxid = "wxid_me"  # 与 SQL 数据中的 "wxid_me" 保持一致
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 她的朋友圈（我 1 次点赞）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "like", "wxid_me", "我的名字", "", now_ts, now_ts),
        )
        # 我的朋友圈（她 1 次点赞）
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo2", "wxid_me", "我的名字", "我的动态", now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi2", "mo2", "like", "wxid_her", "Alice", "", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        assert "互动均衡" in result["engagement_summary"]

    def test_her_like_ratio(self, monkeypatch, tmp_db, test_config, now_ts):
        """her_like_ratio = her_likes / my_posts_count。"""
        test_config.my_wxid = "wxid_me"  # 与 SQL 数据中的 "wxid_me" 保持一致
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 我发 2 条朋友圈
        for i in range(2):
            tmp_db.execute(
                "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"mo{i}", "wxid_me", "我的名字", f"动态{i}", now_ts + i, now_ts),
            )
        # 她 1 次点赞
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo0", "like", "wxid_her", "Alice", "", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        # her_like_ratio = 1 / 2 = 0.5
        assert result["her_like_ratio"] == 0.5
        assert result["my_posts_total"] == 2

    def test_no_my_posts_her_like_ratio_zero(self, monkeypatch, tmp_db, test_config):
        """无我的朋友圈 → her_like_ratio = 0.0。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", 1),
        )
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert result["her_like_ratio"] == 0.0

    def test_comments_detail_truncated_to_40_chars(self, monkeypatch, tmp_db, test_config, now_ts):
        """comments_detail 中 post 截取前 40 字符。"""
        test_config.my_wxid = "wxid_me"  # 与 SQL 数据中的 "wxid_me" 保持一致
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        long_post = "b" * 100
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_me", "我的名字", long_post, now_ts, now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moment_interactions (id, moment_id, type, user_id, user_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("mi1", "mo1", "comment", "wxid_her", "Alice", "评论", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert isinstance(result, dict)
        # her_comments_detail[0]["post"] 应为前 40 字符
        assert result["her_comments_detail"][0]["post"] == "b" * 40

    def test_result_includes_person_info(self, monkeypatch, tmp_db, test_config):
        """结果含 person 和 person_id。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", 1),
        )
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        monkeypatch.setattr("engine.agent.core._get_conn", lambda: (tmp_db, test_config))
        monkeypatch.setattr("engine.agent.core._resolve_person", lambda conn, name: person)
        result = moments_stats("Alice")
        assert result["person"] == "Alice"
        assert result["person_id"] == "p1"


# ═══════════════════════════════════════════════════════════════════
# sync_moments_to_archive
# ═══════════════════════════════════════════════════════════════════

class TestSyncMomentsToArchive:
    """sync_moments_to_archive 同步朋友圈到档案。"""

    def test_no_accounts_returns_empty(self, tmp_db, test_config):
        """person 无 accounts → 空字符串。"""
        person = IdentityPerson(id="p1", display_name="Alice")
        result = sync_moments_to_archive(tmp_db, test_config, person)
        assert result == ""

    def test_no_moments_returns_empty(self, tmp_db, test_config):
        """无朋友圈数据 → 空字符串。"""
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        result = sync_moments_to_archive(tmp_db, test_config, person)
        assert result == ""

    def test_moments_text_returned(self, tmp_db, test_config, now_ts):
        """有朋友圈数据 → 返回格式化文本。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        # 她的朋友圈
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        result = sync_moments_to_archive(tmp_db, test_config, person)
        assert "### 她的朋友圈动态" in result
        assert "她的动态" in result

    def test_archive_file_created(self, tmp_db, test_config, now_ts, tmp_path, monkeypatch):
        """档案文件不存在 → 创建新文件含 section。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "她的动态", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        # mock archive path
        archive_path = tmp_path / "Alice__p1.md"
        monkeypatch.setattr("engine.facts.people_archive.get_person_archive_path",
                            lambda p, my_wxid: archive_path)
        result = sync_moments_to_archive(tmp_db, test_config, person)
        # 文件应已创建
        assert archive_path.is_file()
        content = archive_path.read_text(encoding="utf-8")
        assert "## 朋友圈互动" in content
        assert "她的动态" in content

    def test_archive_file_updated(self, tmp_db, test_config, now_ts, tmp_path, monkeypatch):
        """档案文件已存在 → 替换 朋友圈互动 section。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "新动态", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        archive_path = tmp_path / "Alice__p1.md"
        # 预创建含旧 section 的档案
        archive_path.write_text(
            "# Alice\n\n## 当前状态\n旧内容\n\n## 朋友圈互动\n\n旧的朋友圈内容\n\n## Notes\n其他\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("engine.facts.people_archive.get_person_archive_path",
                            lambda p, my_wxid: archive_path)
        sync_moments_to_archive(tmp_db, test_config, person)
        content = archive_path.read_text(encoding="utf-8")
        # 应有新的 section 内容
        assert "## 朋友圈互动" in content
        assert "新动态" in content
        # 旧的朋友圈内容应被替换
        assert "旧的朋友圈内容" not in content
        # 其他 section 应保留
        assert "## 当前状态" in content
        assert "## Notes" in content
        assert "旧内容" in content

    def test_archive_file_no_existing_section_appended(self, tmp_db, test_config, now_ts, tmp_path, monkeypatch):
        """档案文件无 朋友圈互动 section → 追加到末尾。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "新动态", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        archive_path = tmp_path / "Alice__p1.md"
        archive_path.write_text("# Alice\n\n## 当前状态\n内容\n", encoding="utf-8")
        monkeypatch.setattr("engine.facts.people_archive.get_person_archive_path",
                            lambda p, my_wxid: archive_path)
        sync_moments_to_archive(tmp_db, test_config, person)
        content = archive_path.read_text(encoding="utf-8")
        # 应追加上新 section
        assert "## 朋友圈互动" in content
        assert "新动态" in content
        # 原 section 保留
        assert "## 当前状态" in content

    def test_archive_section_replaces_to_end(self, tmp_db, test_config, now_ts, tmp_path, monkeypatch):
        """朋友圈互动 section 是最后一个 → 替换至末尾。"""
        tmp_db.execute(
            "INSERT INTO contacts (id, display_name, type, updated_at) VALUES (?, ?, 'friend', ?)",
            (test_config.my_wxid, "我的名字", now_ts),
        )
        tmp_db.execute(
            "INSERT INTO moments (id, author_id, author_name, content, timestamp, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mo1", "wxid_her", "Alice", "新动态", now_ts, now_ts),
        )
        tmp_db.commit()
        person = IdentityPerson(
            id="p1", display_name="Alice",
            accounts=[IdentityAccount(id="a1", person_id="p1", wxid="wxid_her",
                                       conversation_id="wxid_her", display_name="Alice")],
        )
        archive_path = tmp_path / "Alice__p1.md"
        # 朋友圈互动是最后一个 section
        archive_path.write_text(
            "# Alice\n\n## 当前状态\n内容\n\n## 朋友圈互动\n\n旧内容\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("engine.facts.people_archive.get_person_archive_path",
                            lambda p, my_wxid: archive_path)
        sync_moments_to_archive(tmp_db, test_config, person)
        content = archive_path.read_text(encoding="utf-8")
        # 旧内容应被替换
        assert "旧内容" not in content
        assert "新动态" in content
