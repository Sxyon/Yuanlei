"""任务 Git 作用域、持续资源占用与派发门禁。"""

import uuid
import asyncio

from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.storage.postgres.models_business import ProjectGitOccupancy
from yuxi.utils.datetime_utils import utc_now_naive


async def git_scope_for_thread(*, db, uid: str, project_id: str, thread_id: str) -> str:
    """同一任务跨智能体复用作用域，子任务默认继承父任务。"""
    store = ProjectGitRepositoryStore(db)
    task = await store.task_for_thread(thread_id, project_id, uid)
    if task is None:
        return thread_id
    return await git_scope_for_task(db=db, task=task, project_id=project_id)


async def git_scope_for_task(*, db, task, project_id: str) -> str:
    """解析父任务共享链，隔离子任务保持自己的稳定工作区。"""
    store = ProjectGitRepositoryStore(db)
    seen = set()
    while task.parent_id and (task.git_workspace_mode or "inherit") == "inherit":
        if task.id in seen:
            raise ValueError("任务父级关系循环")
        seen.add(task.id)
        parent = await store.task_for_project(task.parent_id, project_id)
        if parent is None:
            raise ValueError("Git 工作区父任务不存在")
        task = parent
    return f"task:{task.id}"


async def git_scope_for_run(*, db, uid: str, project_id: str, run) -> str:
    """子智能体沿创建者关系复用根运行的 Git 作用域。"""
    store = ProjectGitRepositoryStore(db)
    seen = set()
    while run.run_type == "subagent":
        if run.id in seen or not run.created_by_run_id:
            raise ValueError("Git 根运行关系非法")
        seen.add(run.id)
        run = await store.run_for_user(run.created_by_run_id, uid)
        if run is None:
            raise ValueError("Git 根运行不存在")
    return await git_scope_for_thread(db=db, uid=uid, project_id=project_id, thread_id=run.conversation_thread_id)


async def revoke_git_owner_runtime(*, db, uid: str, project_id: str, run_id: str | None):
    """先撤销旧容器 generation，后台进程不能把写权限带给下一 owner。"""
    if not run_id:
        return
    from yuxi.agents.backends.sandbox import SandboxScope, get_sandbox_provider
    from yuxi.repositories.project_repository import ProjectRepository
    from yuxi.services.run_scope_service import resolve_run_scope_key

    run = await ProjectGitRepositoryStore(db).run_for_user(run_id, uid)
    if run is None:
        raise RuntimeError("持久占用的根运行不存在，不能确认旧写权限已撤销")
    scope = SandboxScope.from_runtime_scope(uid=uid, runtime_scope_id=await resolve_run_scope_key(db, run))
    project = await ProjectRepository(db).get_for_user(project_id, uid)
    if project is None:
        raise RuntimeError("资源占用项目不存在")
    provider = get_sandbox_provider()
    # 只撤销实际 generation；生命周期 Owner 在下次发现/巡检中记录 suspended。
    # 此处已持有用户锁，不能反向等待 ensure_ready 持有的 AgentSandbox 行锁。
    await asyncio.to_thread(provider.release_scope, scope, workdir_path=project.workdir_path)


async def refresh_git_owner_runtime(*, db, uid: str, run, workdir_path: str):
    """动态分配生效后，由原沙盒 Owner 更新实际挂载与凭据环境。"""
    from yuxi.agents.backends.sandbox import SandboxScope, get_sandbox_provider
    from yuxi.services.coding_thread_sandbox_service import CodingThreadSandboxService
    from yuxi.services.run_scope_service import resolve_run_scope_key

    scope = SandboxScope.from_runtime_scope(uid=uid, runtime_scope_id=await resolve_run_scope_key(db, run))
    if scope.kind == "agent_project":
        await CodingThreadSandboxService(db).ensure_runtime(uid=uid, thread_id=run.conversation_thread_id)
    else:
        await asyncio.to_thread(get_sandbox_provider().release_scope, scope, workdir_path=workdir_path)


async def reserve_git_resources_for_dispatch(
    *, db, uid: str, project_id: str, thread_id: str, run_id: str, requested_at
):
    """在创建 AgentRun 前确认所有资源可用；等待保持原 Request 为 queued。"""
    store = ProjectGitRepositoryStore(db)
    scope = await git_scope_for_thread(db=db, uid=uid, project_id=project_id, thread_id=thread_id)
    await store.acquire_user_runtime_lock(uid)
    allocations = await store.list_scope_worktrees(scope, uid)
    reservations = []
    for allocation in sorted(allocations, key=lambda item: item.repository_id):
        binding = await store.get_binding(allocation.repository_id, uid, lock=True)
        if binding is None or binding.project_id != project_id:
            raise PermissionError("Git 资源归属不一致")
        slot = await store.occupancy(binding.id, scope, uid)
        if slot is None:
            slot = ProjectGitOccupancy(
                id=str(uuid.uuid4()),
                repository_id=binding.id,
                project_id=project_id,
                uid=uid,
                scope_key=scope,
                status="queued",
                requested_at=requested_at,
            )
            db.add(slot)
            await db.flush()
        elif slot.status == "released":
            slot.status = "queued"
            slot.requested_at = requested_at
            slot.released_at = None
        reservations.append((binding, slot, allocation))
    available = True
    for binding, slot, allocation in reservations:
        if slot.active_run_id != run_id and await store.active_root_run(slot.active_run_id, uid):
            available = False
        if allocation.usage_mode == "in_place":
            queue = await store.checkout_occupancies(binding.id, uid)
            owners = [item for item in queue if item.status == "owned"]
            if owners and any(item.scope_key != scope for item in owners):
                available = False
            elif not owners and queue and queue[0].scope_key != scope:
                available = False
    if not available:
        return False
    for _, slot, _ in reservations:
        if slot.active_run_id and slot.active_run_id != run_id:
            await revoke_git_owner_runtime(db=db, uid=uid, project_id=project_id, run_id=slot.active_run_id)
        slot.status = "owned"
        slot.active_run_id = run_id
    await db.flush()
    return True


async def cancel_git_waiter_if_unused(*, db, uid: str, project_id: str, thread_id: str):
    """取消最后一个等待请求时移除 FIFO 等待者，保留已持有的任务占用。"""
    store = ProjectGitRepositoryStore(db)
    scope = await git_scope_for_thread(db=db, uid=uid, project_id=project_id, thread_id=thread_id)
    pending_scopes = {
        await git_scope_for_thread(db=db, uid=uid, project_id=project_id, thread_id=thread)
        for thread in await store.queued_project_threads(project_id, uid)
    }
    if scope in pending_scopes:
        return
    slots = await store.project_occupancies(project_id, uid)
    for candidate in sorted(slots, key=lambda item: item.repository_id):
        if candidate.scope_key != scope or candidate.status != "queued":
            continue
        await store.get_binding(candidate.repository_id, uid, lock=True)
        slot = await store.occupancy(candidate.repository_id, scope, uid)
        if slot.status == "queued" and not await store.active_root_run(slot.active_run_id, uid):
            slot.status = "released"
            slot.active_run_id = None
            slot.released_at = utc_now_naive()
    await db.flush()


async def list_git_occupancies(*, db, uid: str, project_id: str):
    """投影持久占用与真实根运行状态，不猜测崩溃结局。"""
    from fastapi import HTTPException
    from yuxi.repositories.project_repository import ProjectRepository

    if await ProjectRepository(db).get_active_selectable_for_user(project_id, uid) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    store = ProjectGitRepositoryStore(db)
    values = []
    queue_positions = {}
    for slot in await store.project_occupancies(project_id, uid):
        binding = await store.get_binding(slot.repository_id, uid)
        allocation = await store.get_worktree(slot.repository_id, slot.scope_key, uid)
        if binding is None:
            continue
        if slot.repository_id not in queue_positions:
            queue = await store.checkout_occupancies(slot.repository_id, uid)
            queue_positions[slot.repository_id] = {
                item.id: index + 1 for index, item in enumerate(item for item in queue if item.status == "queued")
            }
        run = await store.run_for_user(slot.active_run_id, uid) if slot.active_run_id else None
        active = await store.active_root_run(slot.active_run_id, uid)
        task = (
            await store.task_for_project(slot.scope_key[5:], project_id) if slot.scope_key.startswith("task:") else None
        )
        values.append(
            {
                "id": slot.id,
                "repository_id": slot.repository_id,
                "repository_alias": binding.alias,
                "scope_key": slot.scope_key,
                "scope_label": f"{task.number} · {task.title}" if task else "项目对话",
                "task_id": task.id if task else None,
                "status": slot.status,
                "run_id": slot.active_run_id,
                "run_status": run.status if run else None,
                "active_execution": active is not None,
                "active_agent": active.agent_slug if active else None,
                "heartbeat_at": active.heartbeat_at.isoformat() + "Z" if active and active.heartbeat_at else None,
                "lease_expires_at": active.lease_expires_at.isoformat() + "Z"
                if active and active.lease_expires_at
                else None,
                "lease_expired": bool(
                    active and active.lease_expires_at and active.lease_expires_at <= utc_now_naive()
                ),
                "usage_mode": allocation.usage_mode if allocation else binding.usage_mode,
                "workspace_path": allocation.relative_path if allocation else binding.checkout_path,
                "branch": allocation.branch_name if allocation else binding.configured_base_branch,
                "worktree_status": allocation.status if allocation else None,
                "queue_position": queue_positions[slot.repository_id].get(slot.id),
                "requested_at": slot.requested_at.isoformat() + "Z",
            }
        )
    return values


async def release_git_occupancy(*, db, uid: str, project_id: str, repository_id: str, scope_key: str):
    """在无活跃根运行且成果已处理后，由用户释放持久占用。"""
    from fastapi import HTTPException
    from yuxi.services.project_git_resource_service import (
        get_resource_context,
        open_resource_checkout,
        resource_metadata_path,
    )
    from yuxi.git.worktree_executor import GitWorktreeExecutor
    from yuxi.workspace.git_paths import resolve_project_git_host_paths

    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    slot = await store.occupancy(binding.id, scope_key, uid)
    if slot is None or slot.status == "released":
        raise HTTPException(status_code=404, detail="资源占用不存在")
    if await store.active_root_run(slot.active_run_id, uid):
        raise HTTPException(status_code=409, detail="根运行仍在执行，不能释放资源")
    allocation = await store.get_worktree(binding.id, scope_key, uid, lock=True)
    if slot.status == "owned" and allocation is not None and allocation.status == "ready":
        if allocation.usage_mode == "in_place":
            with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
                state = await executor.review(
                    metadata=resource_metadata_path(binding.id), checkout=path, branch=binding.configured_base_branch
                )
            if state["dirty"]:
                raise HTTPException(status_code=409, detail="资源存在未提交内容，请先提交或明确清理")
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
            if state["dirty"]:
                raise HTTPException(status_code=409, detail="工作树存在未提交内容，请先提交或明确清理")
    if slot.status == "owned":
        await revoke_git_owner_runtime(db=db, uid=uid, project_id=project_id, run_id=slot.active_run_id)
    slot.status = "released"
    slot.active_run_id = None
    slot.released_at = utc_now_naive()
    await db.commit()
    return {"status": "released", "scope_key": scope_key}
