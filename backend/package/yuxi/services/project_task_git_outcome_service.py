"""任务完成前的 Git 成果检查，只回读事实，不自动处理成果。"""

import httpx
from fastapi import HTTPException

from yuxi.git.executor import GitExecutionError
from yuxi.git.worktree_executor import GitWorktreeExecutor
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.services.project_git_execution_service import git_scope_for_task
from yuxi.services.project_git_resource_service import get_resource_provider
from yuxi.workspace.git_paths import resolve_project_git_host_paths
from yuxi.workspace.git_resource_paths import open_resource_checkout, resource_metadata_path


async def inspect_task_git_outcomes(*, db, uid: str, project_id: str, task_id: str):
    """检查任务共享作用域的内容、远端同步、合并与占用情况。"""
    store = ProjectGitRepositoryStore(db)
    await store.acquire_user_runtime_lock(uid)
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, uid)
    task = await ProjectWorkRepository(db, project_id=project_id, uid=uid).get_task(task_id)
    if project is None or task is None:
        raise HTTPException(status_code=404, detail="项目或任务不存在")
    scope = await git_scope_for_task(db=db, task=task, project_id=project_id)
    values = []
    for allocation in await store.list_scope_worktrees(scope, uid):
        binding = await store.get_binding(allocation.repository_id, uid)
        if binding is None or binding.project_id != project_id:
            raise HTTPException(status_code=409, detail="任务 Git 资源归属不一致")
        slot = await store.occupancy(binding.id, scope, uid)
        row = {
            "repository_id": binding.id,
            "alias": binding.alias,
            "worktree_id": allocation.id,
            "branch": allocation.branch_name,
            "usage_mode": allocation.usage_mode,
            "allocation_status": allocation.status,
            "occupancy": slot.status if slot else None,
            "dirty": None,
            "unpushed": None,
            "merged": None,
            "issues": [],
            "errors": [],
        }
        if slot and slot.status != "released":
            row["issues"].append("unreleased")
        if allocation.usage_mode == "worktree":
            row["issues"].append("unarchived")
        if allocation.status != "ready":
            row["issues"].append("not_ready")
            values.append(row)
            continue
        try:
            if allocation.usage_mode == "in_place":
                with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
                    local = await executor.review(
                        metadata=resource_metadata_path(binding.id), checkout=path, branch=allocation.branch_name
                    )
                head, row["dirty"] = local["head_sha"], local["dirty"]
            else:
                bare, path = resolve_project_git_host_paths(
                    uid, project.workdir_path, binding.directory_name, allocation.task_key
                )
                state = await GitWorktreeExecutor().operate(
                    bare=bare,
                    checkout=path,
                    branch=allocation.branch_name,
                    task_key=allocation.task_key,
                    private_root=resource_metadata_path(binding.id).parent,
                )
                head, row["dirty"] = state["head_sha"], state["dirty"]
            if row["dirty"]:
                row["issues"].append("uncommitted")
        except (GitExecutionError, OSError, ValueError):
            row["errors"].append("无法读取本地成果，请在项目资源管理中检查目录与工作树")
            values.append(row)
            continue
        try:
            provider, _ = await get_resource_provider(binding, store)
            try:
                remote = await provider.get_branch(
                    binding.repository_owner, binding.repository_name, allocation.branch_name
                )
                row["unpushed"] = remote.commit_sha != head
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                row["unpushed"] = True
            if row["unpushed"]:
                row["issues"].append("unpushed")
            if allocation.usage_mode == "worktree":
                targets = {binding.configured_base_branch} | {
                    value.branch_name
                    for value in await store.list_project_worktrees(project_id, uid)
                    if value.repository_id == binding.id and value.branch_name != allocation.branch_name
                }
                pulls = await provider.list_pull_requests(binding.repository_owner, binding.repository_name)
                row["merged"] = any(
                    pull["merged"]
                    and pull["head_sha"] == head
                    and pull["head_branch"] == allocation.branch_name
                    and pull["base_branch"] in targets
                    and pull["head_repository_id"] == binding.remote_repository_id
                    and pull["base_repository_id"] == binding.remote_repository_id
                    for pull in pulls
                )
                if not row["merged"]:
                    row["issues"].append("unmerged")
        except (httpx.HTTPError, ValueError, HTTPException):
            row["errors"].append("无法确认 Gitea 同步与合并状态，请检查连接后刷新")
        values.append(row)
    await db.commit()
    return {
        "scope_key": scope,
        "resources": values,
        "requires_attention": any(row["issues"] or row["errors"] for row in values),
    }
