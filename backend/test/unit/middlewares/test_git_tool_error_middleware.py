"""GitToolErrorMiddleware 单元测试。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from yuxi.agents.middlewares.git_tool_error import GitToolErrorMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _request(tool_name: str, tool_call_id: str = "call-1"):
    return SimpleNamespace(tool_call={"name": tool_name, "args": {}, "id": tool_call_id})


async def test_git_tool_http_exception_becomes_error_tool_message():
    """branch_slug 校验失败等 422 收敛为 error ToolMessage，不再 panic Run。"""

    async def handler(_request):
        raise HTTPException(status_code=422, detail="branch_slug must be ASCII kebab-case")

    result = await GitToolErrorMiddleware().awrap_tool_call(_request("git_prepare_worktree"), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call-1"
    assert result.name == "git_prepare_worktree"
    assert "branch_slug must be ASCII kebab-case" in result.content
    assert "fix your mistakes" in result.content


async def test_git_tool_permission_error_becomes_neutral_error_tool_message():
    """权限类失败收敛为中性文案，不暗示模型一定是自己的输入错误。"""

    async def handler(_request):
        raise PermissionError("Repository alias is not active for this Project")

    result = await GitToolErrorMiddleware().awrap_tool_call(_request("git_push_branch"), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "Repository alias is not active" in result.content
    assert "fix your mistakes" not in result.content


async def test_git_tool_value_error_still_raises():
    """ValueError 不来自模型输入校验（service 已统一包成 422），视为编程错误继续传播。"""

    async def handler(_request):
        raise ValueError("unexpected internal state")

    with pytest.raises(ValueError, match="unexpected internal state"):
        await GitToolErrorMiddleware().awrap_tool_call(_request("git_prepare_worktree"), handler)


async def test_git_tool_unexpected_error_still_raises():
    """未知异常不属于可自愈业务失败，必须继续向上传播。"""

    async def handler(_request):
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await GitToolErrorMiddleware().awrap_tool_call(_request("git_prepare_worktree"), handler)


async def test_git_tool_interrupt_is_not_swallowed():
    """审批产生的 GraphInterrupt 必须原样传播，不能被收敛成工具失败。"""

    async def handler(_request):
        raise GraphInterrupt()

    with pytest.raises(GraphInterrupt):
        await GitToolErrorMiddleware().awrap_tool_call(_request("git_prepare_worktree"), handler)


async def test_non_git_tool_errors_pass_through():
    """非 Git 工具的同类异常不在本中间件职责内，原样传播。"""

    async def handler(_request):
        raise HTTPException(status_code=422, detail="other")

    with pytest.raises(HTTPException):
        await GitToolErrorMiddleware().awrap_tool_call(_request("execute"), handler)


async def test_successful_git_tool_result_is_unchanged():
    """正常执行结果原样返回。"""

    async def handler(_request):
        return {"status": "ready"}

    result = await GitToolErrorMiddleware().awrap_tool_call(_request("git_list_project_repositories"), handler)

    assert result == {"status": "ready"}
