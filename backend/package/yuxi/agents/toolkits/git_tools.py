"""由运行时授权注入的 Project Git 工具。"""

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.services.project_git_service import (
    list_project_git_repositories_for_run,
    prepare_project_git_worktree_for_run,
    push_project_git_branch,
)


def _authorized_identity(runtime: ToolRuntime) -> tuple[str, str]:
    """从运行时提取服务层重新授权所需的最小身份。"""
    context = runtime.context
    run_id = str(getattr(context, "run_id", "") or "").strip()
    uid = str(getattr(context, "uid", "") or "").strip()
    if not run_id or not uid:
        raise PermissionError("Project Git requires an authorized AgentRun")
    return run_id, uid


@tool
async def git_list_project_repositories(runtime: ToolRuntime) -> dict:
    """列出当前 Root AgentRun 所属 Project 的可用仓库、用途、基线策略与任务分配状态。"""
    run_id, uid = _authorized_identity(runtime)
    return await list_project_git_repositories_for_run(run_id=run_id, uid=uid)


@tool
async def git_prepare_worktree(
    repository_alias: str,
    base_branch: str,
    branch_kind: str,
    branch_slug: str,
    task_purpose: str,
    runtime: ToolRuntime,
) -> dict:
    """经人工批准后，为当前根任务申请并准备一个 Project 仓库 worktree。

    branch_kind 仅支持 feature/fix/docs/refactor/chore/test；branch_slug 必须是
    ASCII kebab-case（仅小写字母、数字、连字符，例如 project-git-extend），
    最长 48 字符。
    """
    run_id, uid = _authorized_identity(runtime)
    return await prepare_project_git_worktree_for_run(
        run_id=run_id,
        uid=uid,
        repository_alias=repository_alias,
        base_branch=base_branch,
        branch_kind=branch_kind,
        branch_slug=branch_slug,
        task_purpose=task_purpose,
    )


@tool
async def git_push_branch(repository_alias: str, expected_head_sha: str, runtime: ToolRuntime) -> dict:
    """经人工批准后，把当前根任务的精确 clean HEAD 推送到其专属远端分支。"""
    run_id, uid = _authorized_identity(runtime)
    return await push_project_git_branch(
        run_id=run_id,
        uid=uid,
        repository_alias=repository_alias,
        expected_head_sha=expected_head_sha,
    )
