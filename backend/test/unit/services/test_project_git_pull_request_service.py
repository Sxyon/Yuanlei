"""合并审批回读当前目标分支，拒绝过期确认和外部仓库。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from yuxi.services import project_git_pull_request_service as service


@pytest.fixture
def pull_context(monkeypatch):
    """固定授权资源边界，仅替换远端协议。"""
    binding = SimpleNamespace(
        repository_owner="owner", repository_name="repo", remote_repository_id="7", configured_base_branch="main"
    )
    value = {
        "number": 1,
        "head_branch": "agent/task",
        "base_branch": "main",
        "head_sha": "source",
        "base_sha": "old-merge-base",
        "head_repository_id": "7",
        "base_repository_id": "7",
        "merged": False,
        "state": "open",
        "mergeable": True,
    }
    provider = SimpleNamespace(
        get_pull_request=AsyncMock(return_value=value),
        get_branch=AsyncMock(return_value=SimpleNamespace(commit_sha="current-target")),
        merge_pull_request=AsyncMock(return_value={**value, "merged": True}),
        list_pull_requests=AsyncMock(return_value=[value]),
    )
    context = AsyncMock(return_value=(None, binding, {"agent/task": SimpleNamespace()}, provider))
    monkeypatch.setattr(service, "resource_pull_request_context", context)
    return provider, value


@pytest.mark.asyncio
async def test_merge_requires_current_target_head(pull_context):
    """PR 记录的旧基准不是当前目标 HEAD，旧确认不能触发副作用。"""
    provider, _ = pull_context
    with pytest.raises(HTTPException) as failure:
        await service.merge_resource_pull_request(
            uid="user",
            project_id="project",
            repository_id="resource",
            number=1,
            expected_head="source",
            expected_base="old-merge-base",
            db=None,
        )
    assert failure.value.status_code == 409
    provider.merge_pull_request.assert_not_awaited()
    result = await service.merge_resource_pull_request(
        uid="user",
        project_id="project",
        repository_id="resource",
        number=1,
        expected_head="source",
        expected_base="current-target",
        db=None,
    )
    assert result["merged"] is True
    provider.merge_pull_request.assert_awaited_once_with("owner", "repo", 1, head_sha="source")


@pytest.mark.asyncio
async def test_list_projects_live_target_and_ignores_external_fork(pull_context):
    """只展示当前资源请求，开放请求的确认目标来自真实分支。"""
    provider, value = pull_context
    provider.list_pull_requests.return_value = [value, {**value, "number": 2, "head_repository_id": "foreign"}]
    result = await service.list_resource_pull_requests(
        uid="user", project_id="project", repository_id="resource", db=None
    )
    assert len(result) == 1
    assert result[0]["base_sha"] == "current-target"
    assert value["base_sha"] == "old-merge-base"


@pytest.mark.asyncio
async def test_external_fork_cannot_be_merged(pull_context):
    """即使请求号与任务分支名称相同，外部 fork 仍不能执行合并。"""
    provider, value = pull_context
    provider.get_pull_request.return_value = {**value, "head_repository_id": "foreign"}
    with pytest.raises(HTTPException) as failure:
        await service.merge_resource_pull_request(
            uid="user",
            project_id="project",
            repository_id="resource",
            number=1,
            expected_head="source",
            expected_base="current-target",
            db=None,
        )
    assert failure.value.status_code == 409
    provider.merge_pull_request.assert_not_awaited()
    provider.get_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_created_pull_uses_live_target_projection(pull_context):
    """新建请求立即使用当前目标确认，不要求用户刷新才能合并。"""
    provider, value = pull_context
    provider.create_pull_request = AsyncMock(return_value=value)
    provider.get_branch.side_effect = [
        SimpleNamespace(commit_sha="source"),
        SimpleNamespace(commit_sha="current-target"),
    ]
    context = service.resource_pull_request_context.return_value
    context[2]["agent/task"].last_pushed_sha = "source"
    result = await service.create_resource_pull_request(
        uid="user",
        project_id="project",
        repository_id="resource",
        head_branch="agent/task",
        base_branch="main",
        title="人工请求",
        body="",
        db=None,
    )
    assert result["base_sha"] == "current-target"
    assert value["base_sha"] == "old-merge-base"
