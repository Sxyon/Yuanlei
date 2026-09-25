"""沙盒编码执行器适配器的单元测试：能力、句柄绑定与只回收被委派那一轮。"""

from __future__ import annotations

import pytest

from yuxi.delegation.contracts import DelegationError, DelegationHandle, DelegationRequest
from yuxi.delegation.sandbox import SandboxCodingExecutor


class _Turn:
    def __init__(self, *, status: str, summary: str = "done", error_code: str | None = None):
        self.status = status
        self.result_summary = summary
        self.usage_json = {"tokens": 1}
        self.error_code = error_code


class _FakeRepo:
    turns: dict[str, _Turn] = {}

    def __init__(self, _db):
        pass

    async def get_turn(self, turn_id: str):
        return self.turns.get(turn_id)


def _executor() -> SandboxCodingExecutor:
    return SandboxCodingExecutor(object(), executor_key="opencode")


def test_capabilities_and_executor_key_validation() -> None:
    executor = _executor()
    assert executor.key == "opencode"
    assert executor.capabilities() == {"multi_turn": True, "remote_artifacts": False}
    with pytest.raises(DelegationError) as exc:
        SandboxCodingExecutor(object(), executor_key="multica")
    assert exc.value.error_code == "invalid_executor"


@pytest.mark.asyncio
async def test_dispatch_requires_sandbox_scope() -> None:
    with pytest.raises(DelegationError) as exc:
        await _executor().dispatch(DelegationRequest(operation_id="op-1", project_id="p", task="t", metadata={}))
    assert exc.value.error_code == "sandbox_scope_missing"


@pytest.mark.asyncio
async def test_status_and_collect_read_only_the_delegated_turn(monkeypatch) -> None:
    import yuxi.repositories.coding_session_repository as repo_module

    _FakeRepo.turns = {"turn-1": _Turn(status="completed", summary="被委派那一轮")}
    monkeypatch.setattr(repo_module, "CodingSessionRepository", _FakeRepo)

    executor = _executor()
    handle = DelegationHandle(operation_id="op-1", executor_key="opencode", session_id="s1", turn_id="turn-1")
    assert await executor.status(handle) == "completed"
    result = await executor.collect(handle)
    assert result.summary == "被委派那一轮"
    assert result.usage == {"tokens": 1}

    missing = DelegationHandle(operation_id="op-1", executor_key="opencode", session_id="s1", turn_id="turn-9")
    assert await executor.status(missing) is None


@pytest.mark.asyncio
async def test_collect_rejects_unsettled_turn(monkeypatch) -> None:
    import yuxi.repositories.coding_session_repository as repo_module

    _FakeRepo.turns = {"turn-2": _Turn(status="running")}
    monkeypatch.setattr(repo_module, "CodingSessionRepository", _FakeRepo)

    handle = DelegationHandle(operation_id="op-1", executor_key="opencode", session_id="s1", turn_id="turn-2")
    with pytest.raises(DelegationError) as exc:
        await _executor().collect(handle)
    assert exc.value.error_code == "delegation_not_ready"
