"""Git 动态资源申请在占用释放前保持同一次工具调用。"""

from types import SimpleNamespace

import pytest

import yuxi.agents.toolkits.git_tools as tools


@pytest.mark.asyncio
async def test_busy_resource_waits_then_returns_prepared_workspace(monkeypatch):
    attempts = []

    async def prepare(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise tools.ProjectGitBusyError("资源排队")
        return {"status": "ready", "branch": "agent/test"}

    async def wait(_seconds):
        pass

    monkeypatch.setattr(tools, "prepare_project_git_worktree_for_run", prepare)
    monkeypatch.setattr(tools.asyncio, "sleep", wait)
    result = await tools.git_prepare_worktree.coroutine(
        repository_alias="api",
        base_branch="main",
        branch_kind="test",
        branch_slug="verify",
        task_purpose="验证",
        runtime=SimpleNamespace(context=SimpleNamespace(run_id="root-run", uid="user")),
    )
    assert result == {"status": "ready", "branch": "agent/test"}
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]


@pytest.mark.asyncio
async def test_waiter_stops_when_run_authorization_is_revoked(monkeypatch):
    calls = 0

    async def prepare(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise tools.ProjectGitBusyError("资源排队")
        raise PermissionError("运行已取消")

    async def wait(_seconds):
        pass

    monkeypatch.setattr(tools, "prepare_project_git_worktree_for_run", prepare)
    monkeypatch.setattr(tools.asyncio, "sleep", wait)
    with pytest.raises(PermissionError, match="运行已取消"):
        await tools.git_prepare_worktree.coroutine(
            repository_alias="api",
            base_branch="main",
            branch_kind="test",
            branch_slug="verify",
            task_purpose="验证",
            runtime=SimpleNamespace(context=SimpleNamespace(run_id="root-run", uid="user")),
        )
    assert calls == 2
