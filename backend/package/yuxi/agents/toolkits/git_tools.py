"""由运行时授权注入的 Project Git 工具。"""

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.services.project_git_service import push_project_git_branch


@tool
async def git_push_branch(repository_alias: str, expected_head_sha: str, runtime: ToolRuntime) -> dict:
    """经人工批准后，把当前根任务的精确 clean HEAD 推送到其专属远端分支。"""
    context = runtime.context
    run_id = str(getattr(context, "run_id", "") or "").strip()
    uid = str(getattr(context, "uid", "") or "").strip()
    if not run_id or not uid:
        raise PermissionError("Git push requires an authorized AgentRun")
    return await push_project_git_branch(
        run_id=run_id,
        uid=uid,
        repository_alias=repository_alias,
        expected_head_sha=expected_head_sha,
    )
