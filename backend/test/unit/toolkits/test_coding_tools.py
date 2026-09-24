from types import SimpleNamespace

from yuxi.agents.toolkits.buildin.coding_tools import _await_blocked_by_current_run


def test_await_defers_turn_enqueued_by_later_current_run():
    """续轮由后续 Run 入队时，await 也必须立即返回，不能等待自身租约。"""
    session = SimpleNamespace(
        parent_run_id="run-created-session",
        policy_json={"pending_turn": {"id": "turn-2", "enqueueing_run_id": "run-later"}},
    )
    latest = SimpleNamespace(id="turn-2", status="pending")

    assert _await_blocked_by_current_run(session, latest, "run-later")
    assert not _await_blocked_by_current_run(session, latest, "run-other")


def test_await_uses_session_parent_for_legacy_pending_marker():
    """旧 marker 没有 enqueueing Run 时仍兼容会话创建 Run。"""
    session = SimpleNamespace(
        parent_run_id="run-created-session",
        policy_json={"pending_turn": {"id": "turn-1"}},
    )
    latest = SimpleNamespace(id="turn-1", status="running")

    assert _await_blocked_by_current_run(session, latest, "run-created-session")
