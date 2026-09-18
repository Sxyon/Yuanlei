"""Project Git 工具的业务异常收敛。"""

from fastapi import HTTPException
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

# 仅这三个工具的业务失败允许收敛给模型；审批中断与其他异常保持原样传播。
GIT_RUNTIME_TOOL_NAMES = frozenset(
    {
        "git_list_project_repositories",
        "git_prepare_worktree",
        "git_push_branch",
    }
)

# 422 恒为模型输入校验失败，文案与 ToolNode 默认错误 ToolMessage 保持一致。
_FIXABLE_TEMPLATE = "Error: {error}\n Please fix your mistakes."
# PermissionError 混有模型可修正（alias 失效、误选保护分支）与基础设施故障
# （凭据/审计 Owner 不可用）两类，不给"修正你的错误"的误导性提示。
_NEUTRAL_TEMPLATE = "Error: {error}"


class GitToolErrorMiddleware(AgentMiddleware):
    """把 Git 工具的可预期业务失败收敛为 error ToolMessage。

    langgraph 默认只将 ToolInvocationError 转为失败 ToolMessage，工具体抛出的
    HTTPException/PermissionError（如 branch_slug 校验失败、仓库别名未授权）
    会直接 panic 整个 Run。这里仅对 Git 工具捕获这两类预期业务异常，让模型
    看到错误原因后自行修正或向用户报告阻塞；GraphInterrupt 等审批中断不在
    捕获范围内，ValueError 等其他异常视为编程/基础设施错误继续向上传播。
    """

    async def awrap_tool_call(self, request, handler):
        """仅拦截 Git 工具调用，业务异常转为 status=error 的 ToolMessage。"""
        tool_call = request.tool_call
        if tool_call["name"] not in GIT_RUNTIME_TOOL_NAMES:
            return await handler(request)
        try:
            return await handler(request)
        except HTTPException as exc:
            return _error_message(tool_call, _FIXABLE_TEMPLATE.format(error=exc.detail))
        except PermissionError as exc:
            return _error_message(tool_call, _NEUTRAL_TEMPLATE.format(error=exc))


def _error_message(tool_call: dict, content: str) -> ToolMessage:
    """构造与工具审计语义一致的失败 ToolMessage。"""
    return ToolMessage(
        content=content,
        name=tool_call["name"],
        tool_call_id=tool_call["id"],
        status="error",
    )
