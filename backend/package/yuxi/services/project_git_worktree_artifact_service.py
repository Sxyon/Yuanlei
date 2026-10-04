"""用户查看、提交、推送与恢复任务工作树成果。"""

from fastapi import HTTPException

from yuxi.git.credentials import GitCredentialOwner
from yuxi.git.worktree_executor import GitWorktreeExecutor
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.services.project_git_execution_service import revoke_git_owner_runtime
from yuxi.services.project_git_resource_service import get_resource_context
from yuxi.services.project_git_service import is_allocated_task_branch
from yuxi.workspace.git_paths import resolve_project_git_host_paths
from yuxi.workspace.git_resource_paths import resource_metadata_path


async def operate_worktree_artifact(*, db, uid: str, project_id: str, worktree_id: str, action="review", **snapshot):
    """按项目所有权与执行树边界处理指定工作树，拒绝替换资源分支。"""
    store = ProjectGitRepositoryStore(db)
    allocation = await store.get_project_worktree(worktree_id, project_id, uid)
    if allocation is None:
        raise HTTPException(status_code=404, detail="任务工作树不存在")
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=allocation.repository_id, db=db, lock=True
    )
    allocation = await store.get_project_worktree(worktree_id, project_id, uid, lock=True)
    if allocation is None:
        raise HTTPException(status_code=404, detail="任务工作树不存在")
    if allocation.usage_mode != "worktree" or allocation.status != "ready":
        raise HTTPException(status_code=409, detail="此分配不是已就绪的隔离工作树，请在资源管理中处理")
    if not is_allocated_task_branch(allocation, uid) or allocation.branch_name == binding.configured_base_branch:
        raise HTTPException(status_code=409, detail="工作树分支与任务分配不一致")
    if action != "review":
        if await store.has_nonterminal_run(project_id, allocation.runtime_scope_id, uid):
            raise HTTPException(status_code=409, detail="任务仍有运行中的 AgentRun")
        slots = [slot for slot in await store.project_occupancies(project_id, uid) if slot.repository_id == binding.id]
        for slot in slots:
            if await store.active_root_run(slot.active_run_id, uid):
                raise HTTPException(status_code=409, detail="同仓库仍有根运行或子智能体执行，请停止后处理成果")
        for slot in slots:
            if slot.status == "owned":
                await revoke_git_owner_runtime(db=db, uid=uid, project_id=project_id, run_id=slot.active_run_id)
    remote = None
    if action == "push":
        connection = await store.get_connection(binding.connection_id, uid, active_only=True)
        credential = await store.get_credential(binding.deploy_private_credential_id, uid)
        if connection is None or credential is None or not binding.canonical_ssh_url:
            raise HTTPException(status_code=409, detail="Git 推送连接不可用")
        remote = {
            "remote_url": binding.canonical_ssh_url,
            "private_key": GitCredentialOwner().decrypt(credential),
            "known_hosts": connection.ssh_known_host_key,
        }
    bare, checkout = resolve_project_git_host_paths(
        uid, project.workdir_path, binding.directory_name, allocation.task_key
    )
    state = await GitWorktreeExecutor().operate(
        bare=bare,
        checkout=checkout,
        branch=allocation.branch_name,
        task_key=allocation.task_key,
        private_root=resource_metadata_path(binding.id).parent,
        action=action,
        review_base=allocation.last_pushed_sha or allocation.base_sha,
        remote=remote,
        **snapshot,
    )
    allocation.last_observed_head_sha = state["head_sha"]
    if "pushed_sha" in state:
        allocation.last_pushed_sha = state["pushed_sha"]
    result = {
        **state,
        "remote_tracking_sha": allocation.last_pushed_sha,
        "unpushed": state["head_sha"] != allocation.last_pushed_sha,
    }
    await db.commit()
    return result
