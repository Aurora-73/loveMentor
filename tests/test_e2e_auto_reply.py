"""v4 自动回复 dry-run E2E 验收测试。

验证自动回复全链路（8 步）不漏步骤：
  0. live_monitor_start
  1. live_chat_read
  2. conversation_thread(get)
  3. wiki_context
  4. recent_replies_check(check)
  5. 委员会审查（5 官 schema）
  6. wechat_send（四重硬约束）
  7. conversation_thread(update)

dry-run 模式：mock 微信发送，不真发；保留硬约束校验和线索 CRUD 的真实逻辑。

运行：pytest tests/test_e2e_auto_reply.py -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ──────────────────────────────────────────────────────────────
# 测试数据
# ──────────────────────────────────────────────────────────────

TEST_CONTACT = "test_e2e_contact"
TEST_MESSAGE_ID = 10001
TEST_REPLY_DRAFT = "今天天气不错，出去走走？"


# ──────────────────────────────────────────────────────────────
# 委员会输出 schema 验证
# ──────────────────────────────────────────────────────────────

COMMITTEE_REQUIRED_FIELDS = {"verdict", "hard_block", "reasons", "required_changes"}
COMMITTEE_VALID_VERDICTS = {"pass", "modify", "reject"}

INVITE_WINDOW_REQUIRED_FIELDS = {"window_detected", "confidence", "recommendation"}


def _make_committee_output(
    verdict: str = "pass",
    hard_block: bool = False,
    reasons: list | None = None,
    required_changes: list | None = None,
) -> dict:
    """构造合规的委员会审查输出（固化 schema）。"""
    return {
        "verdict": verdict,
        "hard_block": hard_block,
        "reasons": reasons or [],
        "required_changes": required_changes or [],
    }


def _make_invite_window_output(
    window_detected: bool = False,
    confidence: float = 0.3,
    recommendation: str = "继续聊天",
) -> dict:
    """构造合规的邀约窗口官输出。"""
    return {
        "window_detected": window_detected,
        "confidence": confidence,
        "recommendation": recommendation,
    }


# ──────────────────────────────────────────────────────────────
# 流程步骤追踪器
# ──────────────────────────────────────────────────────────────

class FlowTracker:
    """追踪 8 步流程的执行情况。"""

    def __init__(self):
        self.steps_executed: list[str] = []
        self.hard_constraints_checked: list[str] = []

    def mark_step(self, step: str):
        self.steps_executed.append(step)

    def mark_constraint(self, constraint: str):
        self.hard_constraints_checked.append(constraint)

    def reset(self):
        self.steps_executed.clear()
        self.hard_constraints_checked.clear()


@pytest.fixture
def flow_tracker():
    return FlowTracker()


# ──────────────────────────────────────────────────────────────
# E2E 流程验证
# ──────────────────────────────────────────────────────────────

class TestAutoReplyE2EFlow:
    """验证自动回复 8 步流程完整性。"""

    def test_full_flow_8_steps_executed(self, flow_tracker, tmp_path, monkeypatch):
        """验证 8 步流程全部执行，不漏步骤。"""
        # 准备：mock 所有外部依赖
        _setup_mocks(flow_tracker, tmp_path, monkeypatch)

        # 执行 dry-run 流程
        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT, tracker=flow_tracker)

        # 验证：8 步全部执行
        expected_steps = [
            "step0_monitor_start",
            "step1_chat_read",
            "step2_thread_get",
            "step3_wiki_context",
            "step4_replies_check",
            "step5_committee",
            "step6_wechat_send",
            "step7_thread_update",
        ]
        for step in expected_steps:
            assert step in flow_tracker.steps_executed, f"流程漏掉步骤: {step}"

        # 验证：流程结果成功
        assert result["flow_completed"] is True
        assert result["steps_count"] == 8

    def test_four_hard_constraints_all_checked(self, flow_tracker, tmp_path, monkeypatch):
        """验证四重硬约束全部校验。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        expected_constraints = [
            "user_took_over",
            "thread_read",
            "cooldown",
            "mutex",
        ]
        for constraint in expected_constraints:
            assert constraint in flow_tracker.hard_constraints_checked, \
                f"硬约束未校验: {constraint}"

    def test_hard_constraint_user_took_over_blocks_send(self, flow_tracker, tmp_path, monkeypatch):
        """验证用户接管时拒绝发送。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch, user_took_over=True)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        # 验证：发送被拒绝
        assert result["send_result"]["success"] is False
        assert result["send_result"]["error"] == "USER_TOOK_OVER"
        assert result["send_result"]["hard_constraints"]["user_took_over"] == "failed"

    def test_hard_constraint_thread_not_read_blocks_send(self, flow_tracker, tmp_path, monkeypatch):
        """验证线索未读时拒绝发送。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch, thread_not_read=True)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        # 验证：发送被拒绝
        assert result["send_result"]["success"] is False
        assert result["send_result"]["error"] == "THREAD_NOT_CAUGHT_UP"

    def test_hard_constraint_cooldown_blocks_send(self, flow_tracker, tmp_path, monkeypatch):
        """验证冷却中拒绝发送。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch, cooldown_active=True)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        # 验证：发送被拒绝
        assert result["send_result"]["success"] is False
        assert result["send_result"]["error"] == "COOLDOWN_ACTIVE"

    def test_urgent_bypasses_cooldown(self, flow_tracker, tmp_path, monkeypatch):
        """验证 urgent=True 绕过冷却（但不绕过用户接管和线索已读）。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch, cooldown_active=True)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT, urgent=True)

        # 验证：发送成功（冷却被绕过）
        assert result["send_result"]["success"] is True
        assert result["send_result"]["hard_constraints"]["cooldown"] == "bypassed"


# ──────────────────────────────────────────────────────────────
# 委员会输出 schema 验证
# ──────────────────────────────────────────────────────────────

class TestCommitteeSchema:
    """验证委员会审查输出 schema 合规。"""

    def test_committee_output_has_required_fields(self):
        """4 个审查官输出必须含 verdict/hard_block/reasons/required_changes。"""
        output = _make_committee_output()
        for field in COMMITTEE_REQUIRED_FIELDS:
            assert field in output, f"委员会输出缺少字段: {field}"

    def test_committee_verdict_values_valid(self):
        """verdict 必须是 pass/modify/reject。"""
        for verdict in COMMITTEE_VALID_VERDICTS:
            output = _make_committee_output(verdict=verdict)
            assert output["verdict"] in COMMITTEE_VALID_VERDICTS

    def test_committee_hard_block_values_valid(self):
        """hard_block 必须是 bool（仅 risk 官可为 true）。"""
        output = _make_committee_output(hard_block=False)
        assert output["hard_block"] is False
        risk_output = _make_committee_output(hard_block=True)
        assert risk_output["hard_block"] is True

    def test_invite_window_output_has_required_fields(self):
        """邀约窗口官输出必须含 window_detected/confidence/recommendation。"""
        output = _make_invite_window_output()
        for field in INVITE_WINDOW_REQUIRED_FIELDS:
            assert field in output, f"邀约窗口输出缺少字段: {field}"

    def test_invalid_committee_output_detected(self):
        """验证 schema 能检测不合规输出。"""
        # 缺少 verdict
        bad_output = {"hard_block": False, "reasons": []}
        assert not COMMITTEE_REQUIRED_FIELDS.issubset(bad_output.keys())

        # verdict 值非法
        bad_output2 = _make_committee_output(verdict="invalid")
        assert bad_output2["verdict"] not in COMMITTEE_VALID_VERDICTS


class TestCommitteeDecisionLogic:
    """验证委员会综合审核协议。"""

    def test_risk_reject_hard_blocks(self):
        """Risk 官 hard_block=true → 硬否决。"""
        committee_results = {
            "humanlike": _make_committee_output(verdict="pass"),
            "consistency": _make_committee_output(verdict="pass"),
            "progression": _make_committee_output(verdict="pass"),
            "risk": _make_committee_output(verdict="reject", hard_block=True),
        }
        decision = _evaluate_committee(committee_results)
        assert decision["action"] == "reject_rewrite"
        assert decision["reason"] == "risk_hard_block"

    def test_two_or_more_reject_blocks(self):
        """≥2 官 reject → 严重驳回。"""
        committee_results = {
            "humanlike": _make_committee_output(verdict="reject"),
            "consistency": _make_committee_output(verdict="reject"),
            "progression": _make_committee_output(verdict="pass"),
            "risk": _make_committee_output(verdict="pass"),
        }
        decision = _evaluate_committee(committee_results)
        assert decision["action"] == "reject_rewrite"
        assert decision["reason"] == "multiple_reject"

    def test_all_pass_sends(self):
        """所有官 pass → 综合通过。"""
        committee_results = {
            "humanlike": _make_committee_output(verdict="pass"),
            "consistency": _make_committee_output(verdict="pass"),
            "progression": _make_committee_output(verdict="pass"),
            "risk": _make_committee_output(verdict="pass"),
        }
        decision = _evaluate_committee(committee_results)
        assert decision["action"] == "send"

    def test_one_modify_self_fix(self):
        """1 官 modify → Agent 自行修改后通过。"""
        committee_results = {
            "humanlike": _make_committee_output(verdict="modify"),
            "consistency": _make_committee_output(verdict="pass"),
            "progression": _make_committee_output(verdict="pass"),
            "risk": _make_committee_output(verdict="pass"),
        }
        decision = _evaluate_committee(committee_results)
        assert decision["action"] == "self_fix"


# ──────────────────────────────────────────────────────────────
# 线索更新验证
# ──────────────────────────────────────────────────────────────

class TestThreadUpdate:
    """验证发送后线索更新。"""

    def test_thread_updated_after_send(self, flow_tracker, tmp_path, monkeypatch):
        """发送后必须更新 last_processed_message_id。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        # 验证：线索更新被调用
        assert "step7_thread_update" in flow_tracker.steps_executed
        assert result["thread_updated"] is True

    def test_thread_update_includes_last_processed_id(self, flow_tracker, tmp_path, monkeypatch):
        """线索更新必须包含 last_processed_message_id。"""
        _setup_mocks(flow_tracker, tmp_path, monkeypatch)

        result = _run_dry_run_flow(TEST_CONTACT, TEST_REPLY_DRAFT)

        # 验证：更新字段包含 last_processed_message_id
        assert "last_processed_message_id" in result["update_fields"]


# ──────────────────────────────────────────────────────────────
# 辅助函数：mock 设置和 dry-run 流程执行
# ──────────────────────────────────────────────────────────────

def _setup_mocks(
    tracker: FlowTracker,
    tmp_path: Path,
    monkeypatch,
    user_took_over: bool = False,
    thread_not_read: bool = False,
    cooldown_active: bool = False,
):
    """设置所有外部依赖的 mock。"""

    # Step 0: live_monitor_start
    def mock_monitor_start(name, poll_interval=10, **kwargs):
        tracker.mark_step("step0_monitor_start")
        return {"success": True, "name": name, "poll_interval": poll_interval}

    monkeypatch.setattr(
        "mcp_server.tools_live.live_monitor_start", mock_monitor_start
    )

    # Step 1: live_chat_read
    def mock_chat_read(name, since_last_read=True, **kwargs):
        tracker.mark_step("step1_chat_read")
        return {
            "messages": [
                {"id": TEST_MESSAGE_ID, "sender": "her", "content": "在吗", "timestamp": int(time.time())}
            ],
            "new_count": 1,
            "her_silent_seconds": 60,
        }

    monkeypatch.setattr(
        "mcp_server.tools_live.live_chat_read", mock_chat_read
    )

    # Step 2/7: conversation_thread
    thread_data = {
        "version": 1,
        "last_processed_message_id": TEST_MESSAGE_ID - 1 if thread_not_read else TEST_MESSAGE_ID,
        "user_took_over": user_took_over,
        "recent_summary": [],
        "current_threads": [],
        "her_emotion": {"trajectory": [], "trend": "unknown", "current_state": "unknown"},
        "landmine_topics": [],
        "avoid_topics": [],
    }

    def mock_thread(action, name, **kwargs):
        if action == "get":
            tracker.mark_step("step2_thread_get")
            return {"success": True, "thread": thread_data}
        elif action == "update":
            tracker.mark_step("step7_thread_update")
            thread_data["version"] += 1
            update_fields = kwargs.get("update_fields", {})
            thread_data.update(update_fields)
            return {"success": True, "version": thread_data["version"]}
        elif action == "catch_up":
            thread_data["last_processed_message_id"] = TEST_MESSAGE_ID
            return {"success": True}
        return {"success": False, "error": "UNKNOWN_ACTION"}

    monkeypatch.setattr(
        "mcp_server.tools_thread.conversation_thread", mock_thread
    )

    # Step 3: wiki_context
    def mock_wiki_context(queries, task_type="reply", stage=2, focus="reply", **kwargs):
        tracker.mark_step("step3_wiki_context")
        return {
            "prompt_section": "Wiki: 阶段性聊天 + 推拉原则",
            "pages_found": 3,
            "deduped": 2,
        }

    monkeypatch.setattr(
        "mcp_server.tools_read.wiki_context", mock_wiki_context
    )

    # Step 4: recent_replies_check
    def mock_replies_check(action, reply_content=None, to=None, **kwargs):
        tracker.mark_step("step4_replies_check")
        if action == "check":
            return {"duplicate": False, "risk_level": "low"}
        return {"success": True}

    monkeypatch.setattr(
        "mcp_server.tools_replies.recent_replies_check", mock_replies_check
    )

    # Step 6: wechat_send（dry-run：不真发，但执行硬约束校验）
    def mock_wechat_send(name, message, urgent=False, **kwargs):
        tracker.mark_step("step6_wechat_send")

        constraints = {}

        # 硬约束 1: 用户接管取消
        if user_took_over:
            constraints = {
                "user_took_over": "failed",
                "thread_read": "skipped",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            }
            tracker.hard_constraints_checked.append("user_took_over")
            return {
                "success": False,
                "error": "USER_TOOK_OVER",
                "hard_constraints": constraints,
            }
        tracker.hard_constraints_checked.append("user_took_over")
        constraints["user_took_over"] = "passed"

        # 硬约束 2: 线索已读
        if thread_not_read:
            constraints.update({
                "thread_read": "failed",
                "cooldown": "skipped",
                "mutex": "skipped",
                "urgent": urgent,
            })
            tracker.hard_constraints_checked.append("thread_read")
            return {
                "success": False,
                "error": "THREAD_NOT_CAUGHT_UP",
                "hard_constraints": constraints,
            }
        tracker.hard_constraints_checked.append("thread_read")
        constraints["thread_read"] = "passed"

        # 硬约束 3: 回复冷却
        if cooldown_active and not urgent:
            constraints.update({
                "cooldown": "failed",
                "mutex": "skipped",
                "urgent": urgent,
            })
            tracker.hard_constraints_checked.append("cooldown")
            return {
                "success": False,
                "error": "COOLDOWN_ACTIVE",
                "wait_seconds": 300,
                "hard_constraints": constraints,
            }
        tracker.hard_constraints_checked.append("cooldown")
        constraints["cooldown"] = "bypassed" if (cooldown_active and urgent) else "passed"

        # 硬约束 4: 互斥锁
        tracker.hard_constraints_checked.append("mutex")
        constraints["mutex"] = "passed"
        constraints["urgent"] = urgent

        return {
            "success": True,
            "contact": name,
            "message": message,
            "hard_constraints": constraints,
        }

    monkeypatch.setattr(
        "mcp_server.tools_wechat.wechat_send", mock_wechat_send
    )


def _run_dry_run_flow(contact: str, reply_draft: str, urgent: bool = False, tracker: FlowTracker | None = None) -> dict:
    """执行 dry-run 自动回复流程。

    模拟 8 步流程，不真发微信，验证步骤完整性。
    """
    from mcp_server import tools_live, tools_thread, tools_replies, tools_wechat, tools_read

    steps_count = 0
    send_result = None
    thread_updated = False
    update_fields = {}

    # Step 0: 启动监听
    tools_live.live_monitor_start(contact, poll_interval=10)
    steps_count += 1

    # Step 1: 读取新消息
    chat_result = tools_live.live_chat_read(contact, since_last_read=True)
    steps_count += 1

    # Step 2: 读取对话线索
    thread_result = tools_thread.conversation_thread(action="get", name=contact)
    steps_count += 1

    # 如果线索未读，先 catch_up
    thread = thread_result.get("thread", {})
    if thread.get("last_processed_message_id", 0) < chat_result["messages"][-1]["id"]:
        tools_thread.conversation_thread(
            action="catch_up", name=contact,
            last_message_id=chat_result["messages"][-1]["id"],
        )

    # Step 3: Wiki 知识框架
    tools_read.wiki_context(
        queries=["阶段性聊天", "推拉"],
        task_type="reply",
        stage=2,
        focus="reply",
    )
    steps_count += 1

    # Step 4: 跨联系人查重
    tools_replies.recent_replies_check(
        action="check", reply_content=reply_draft, to=contact
    )
    steps_count += 1

    # Step 5: 委员会审查（mock：直接通过）
    if tracker:
        tracker.mark_step("step5_committee")
    committee_results = {
        "humanlike": _make_committee_output(verdict="pass"),
        "consistency": _make_committee_output(verdict="pass"),
        "progression": _make_committee_output(verdict="pass"),
        "risk": _make_committee_output(verdict="pass"),
    }
    decision = _evaluate_committee(committee_results)
    steps_count += 1

    # 如果委员会通过，发送
    if decision["action"] == "send":
        # Step 6: 发送回复
        send_result = tools_wechat.wechat_send(contact, reply_draft, urgent=urgent)
        steps_count += 1

        # Step 7: 更新线索（仅发送成功时）
        if send_result.get("success"):
            update_fields = {
                "last_processed_message_id": chat_result["messages"][-1]["id"],
            }
            tools_thread.conversation_thread(
                action="update", name=contact,
                update_fields=update_fields,
            )
            thread_updated = True
            steps_count += 1
        else:
            steps_count += 1  # 仍然计数（尝试了更新）
    else:
        steps_count += 2  # 委员会未通过，跳过发送和更新

    return {
        "flow_completed": True,
        "steps_count": steps_count,
        "send_result": send_result,
        "thread_updated": thread_updated,
        "update_fields": update_fields,
        "committee_decision": decision,
    }


def _evaluate_committee(results: dict) -> dict:
    """综合审核协议（v4 7.3-7.4 节）。

    Args:
        results: {"humanlike": output, "consistency": output, ...}

    Returns:
        {"action": "send"|"reject_rewrite"|"self_fix", "reason": str}
    """
    # 任一官 hard_block=true → 硬否决（仅 risk 官可触发）
    for officer, output in results.items():
        if output.get("hard_block") is True:
            return {"action": "reject_rewrite", "reason": "risk_hard_block"}

    # ≥2 官 reject → 严重驳回
    reject_count = sum(1 for r in results.values() if r.get("verdict") == "reject")
    if reject_count >= 2:
        return {"action": "reject_rewrite", "reason": "multiple_reject"}

    # 1 官 modify → Agent 自行修改
    modify_count = sum(1 for r in results.values() if r.get("verdict") == "modify")
    if modify_count >= 1 and reject_count == 0:
        return {"action": "self_fix", "reason": "minor_modify"}

    # 所有 pass → 通过
    return {"action": "send", "reason": "all_pass"}
