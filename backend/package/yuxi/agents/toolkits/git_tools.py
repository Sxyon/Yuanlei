"""由运行时授权注入的 Project Git 工具。"""

import asyncio

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from typing import Literal
from yuxi.storage.postgres.manager import pg_manager

from yuxi.services.project_git_service import (
    ProjectGitBusyError,
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
    while True:
        try:
            return await prepare_project_git_worktree_for_run(
                run_id=run_id,
                uid=uid,
                repository_alias=repository_alias,
                base_branch=base_branch,
                branch_kind=branch_kind,
                branch_slug=branch_slug,
                task_purpose=task_purpose,
            )
        except ProjectGitBusyError:
            # 意图与 FIFO 占用已持久化；保留本次工具调用，避免模型误报任务完成。
            # 下一次尝试重新检查运行授权，取消或 lease 丢失不能继续申请写权限。
            await asyncio.sleep(5)


@tool
async def git_push_branch(repository_alias: str, expected_head_sha: str, runtime: ToolRuntime) -> dict:
    """申请推送精确 clean HEAD；受保护目标等待人工批准，自动批准与结果可追溯。"""
    run_id, uid = _authorized_identity(runtime)
    return await push_project_git_branch(
        run_id=run_id,
        uid=uid,
        repository_alias=repository_alias,
        expected_head_sha=expected_head_sha,
        request_id=runtime.tool_call_id,
    )


@tool
async def git_review_workspace(repository_alias: str, runtime: ToolRuntime) -> dict:
    """读取当前任务资源的可信 HEAD/tree、已提交差异与未提交差异，供申请批准。"""
    from yuxi.services.project_git_action_service import review_git_workspace_for_run

    run_id, uid = _authorized_identity(runtime)
    async with pg_manager.get_async_session_context() as db:
        return await review_git_workspace_for_run(db=db, uid=uid, run_id=run_id, repository_alias=repository_alias)


@tool
async def git_request_action(
    repository_alias: str,
    action: Literal["commit", "push", "merge"],
    expected_head: str,
    runtime: ToolRuntime,
    expected_tree: str | None = None,
    message: str = "",
    pull_number: int | None = None,
    expected_base: str | None = None,
) -> dict:
    """申请固定快照的提交、推送或合并；自动授权先记录规则，受保护目标等待项目所有者决定。

    commit/push 使用 git_review_workspace 的 HEAD/tree，commit 填写 message。
    merge 填写已有 Gitea 合并请求编号及源/目标 HEAD；只允许自身任务分支合入资源目标或持久父任务分支。
    返回批准及执行状态，pending/approved/running 都不代表 Git 操作已完成。
    """
    from yuxi.services.project_git_action_service import request_git_action_for_run

    run_id, uid = _authorized_identity(runtime)
    async with pg_manager.get_async_session_context() as db:
        return await request_git_action_for_run(
            db=db,
            uid=uid,
            run_id=run_id,
            repository_alias=repository_alias,
            request_id=runtime.tool_call_id,
            action=action,
            expected_head=expected_head,
            expected_tree=expected_tree,
            message=message,
            pull_number=pull_number,
            expected_base=expected_base,
        )


@tool
async def git_action_status(action_id: str, runtime: ToolRuntime) -> dict:
    """回读当前任务的批准与执行结果；失败后先审查实际成果，不自动重试原申请。"""
    from yuxi.services.project_git_action_service import get_git_action_for_run

    run_id, uid = _authorized_identity(runtime)
    async with pg_manager.get_async_session_context() as db:
        return await get_git_action_for_run(db=db, uid=uid, run_id=run_id, action_id=action_id)


@tool
async def git_list_pull_requests(repository_alias: str, runtime: ToolRuntime) -> dict:
    """查看自身任务分支的 Gitea 合并请求及合法目标，返回 merge 申请所需编号和源/目标 SHA。"""
    from yuxi.services.project_git_pull_request_service import pull_requests_for_run

    run_id, uid = _authorized_identity(runtime)
    async with pg_manager.get_async_session_context() as db:
        return await pull_requests_for_run(db=db, uid=uid, run_id=run_id, repository_alias=repository_alias)


@tool
async def git_create_pull_request(
    repository_alias: str, base_branch: str, title: str, runtime: ToolRuntime, body: str = ""
) -> dict:
    """将已推送任务分支向资源目标或父任务分支发起 Gitea 合并请求；实际合并继续申请 Git 审批。"""
    from yuxi.services.project_git_pull_request_service import pull_requests_for_run

    run_id, uid = _authorized_identity(runtime)
    async with pg_manager.get_async_session_context() as db:
        return await pull_requests_for_run(
            db=db,
            uid=uid,
            run_id=run_id,
            repository_alias=repository_alias,
            base_branch=base_branch,
            title=title,
            body=body,
        )
