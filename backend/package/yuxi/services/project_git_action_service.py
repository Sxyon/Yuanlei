"""Git 批准事实、运行身份与可恢复执行意图。"""

import hashlib
import json
import uuid

from fastapi import HTTPException

from yuxi.git.worktree_executor import GitWorktreeExecutor
from yuxi.repositories.project_git_action_repository import ProjectGitActionRepository
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.project_git_execution_service import git_scope_for_run
from yuxi.services.project_git_resource_service import get_resource_context, get_resource_provider
from yuxi.services.task_service import tasker
from yuxi.storage.postgres.models_business import ProjectGitAction
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.git_paths import require_commit_sha, resolve_project_git_host_paths
from yuxi.workspace.git_resource_paths import open_resource_checkout, resource_metadata_path


async def require_git_action_run(*, db, uid, run_id, project_id=None):
    """仅当前 lease 的根运行可以申请或自动执行项目 Git 动作。"""
    value = await ProjectGitActionRepository(db).root_context(uid, run_id)
    if value is None:
        raise PermissionError("Git 操作运行不属于当前用户项目")
    run, project = value
    if (
        run.run_type == "subagent"
        or run.status != "running"
        or not run.worker_id
        or run.lease_expires_at is None
        or run.lease_expires_at <= utc_now_naive()
        or (project_id is not None and project.id != project_id)
    ):
        raise PermissionError("Git 操作需要拥有有效 lease 的根运行")
    return run, project


async def git_action_run_resource(*, db, uid, run_id, repository_alias):
    """根运行只能操作自己的持久资源分配与持续占用。"""
    run, project = await require_git_action_run(db=db, uid=uid, run_id=run_id)
    store = ProjectGitRepositoryStore(db)
    await store.acquire_user_runtime_lock(uid)
    binding = await store.get_active_binding_by_alias(project_id=project.id, uid=uid, alias=repository_alias, lock=True)
    if binding is None:
        raise PermissionError("项目 Git 资源不存在")
    scope = await git_scope_for_run(db=db, uid=uid, project_id=project.id, run=run)
    allocation = await store.get_worktree(binding.id, scope, uid, lock=True)
    slot = await store.occupancy(binding.id, scope, uid)
    if (
        allocation is None
        or allocation.status != "ready"
        or slot is None
        or slot.status != "owned"
        or slot.active_run_id != run.id
    ):
        raise PermissionError("根运行未持有此任务 Git 工作空间")
    return run, project, binding, allocation


async def review_git_action_workspace(*, db, uid, project, binding, allocation):
    """审查实际文件和可信元数据，不读取智能体 Git 配置。"""
    from yuxi.services.project_git_service import is_allocated_task_branch

    if allocation.usage_mode == "in_place":
        if (
            allocation.branch_name != binding.configured_base_branch
            or allocation.relative_path != binding.checkout_path
        ):
            raise PermissionError("资源分支或目录与持久分配不一致")
        with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
            return await executor.review(
                metadata=resource_metadata_path(binding.id), checkout=path, branch=allocation.branch_name
            )
    if not is_allocated_task_branch(allocation, uid) or allocation.branch_name == binding.configured_base_branch:
        raise PermissionError("任务分支身份不一致")
    bare, checkout = resolve_project_git_host_paths(
        uid, project.workdir_path, binding.directory_name, allocation.task_key
    )
    return await GitWorktreeExecutor().operate(
        bare=bare,
        checkout=checkout,
        branch=allocation.branch_name,
        task_key=allocation.task_key,
        private_root=resource_metadata_path(binding.id).parent,
        review_base=allocation.last_pushed_sha or allocation.base_sha,
    )


async def review_git_workspace_for_run(*, db, uid, run_id, repository_alias):
    """向根智能体提供可用于申请批准的实际 HEAD、内容树与差异。"""
    _, project, binding, allocation = await git_action_run_resource(
        db=db, uid=uid, run_id=run_id, repository_alias=repository_alias
    )
    value = await review_git_action_workspace(db=db, uid=uid, project=project, binding=binding, allocation=allocation)
    await db.commit()
    return value


async def request_git_action_for_run(
    *,
    db,
    uid,
    run_id,
    repository_alias,
    request_id,
    action,
    expected_head,
    expected_tree=None,
    message="",
    pull_number=None,
    expected_base=None,
):
    """先冻结批准依据，再创建同事务执行意图；严格保护始终等待人工决定。"""
    if action not in {"commit", "push", "merge"} or not request_id or len(request_id) > 128:
        raise HTTPException(status_code=422, detail="Git 动作或申请标识非法")
    try:
        expected_head = require_commit_sha(expected_head)
        if action != "merge":
            expected_tree = require_commit_sha(expected_tree)
        else:
            expected_base = require_commit_sha(expected_base)
    except ValueError:
        raise HTTPException(status_code=422, detail="请提供完整的 Git 审查 SHA") from None
    if action == "merge" and (not pull_number or pull_number < 1):
        raise HTTPException(status_code=422, detail="请填写合并请求编号")
    if action == "commit" and (not message.strip() or len(message) > 2000):
        raise HTTPException(status_code=422, detail="请填写 1 到 2000 字的提交说明")
    fingerprint = hashlib.sha256(
        json.dumps(
            [run_id, repository_alias, action, expected_head, expected_tree, message, pull_number, expected_base],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    run, project, binding, allocation = await git_action_run_resource(
        db=db, uid=uid, run_id=run_id, repository_alias=repository_alias
    )
    repo = ProjectGitActionRepository(db)
    existing = await repo.by_request(uid, request_id)
    if existing:
        if existing.fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="相同申请标识不能改变动作或审查快照")
        return existing.to_dict()
    await ProjectGitRepositoryStore(db).acquire_maintenance_lock(binding.id)
    provider, _ = await get_resource_provider(binding, ProjectGitRepositoryStore(db))
    target = None
    if action == "merge":
        from yuxi.services.project_git_pull_request_service import verify_resource_pull_request

        allocations = {
            item.branch_name: item
            for item in await ProjectGitRepositoryStore(db).list_project_worktrees(project.id, uid)
            if item.repository_id == binding.id
        }
        pull = await provider.get_pull_request(binding.repository_owner, binding.repository_name, pull_number)
        verify_resource_pull_request(binding, allocations, pull)
        parent = next((item for item in allocations.values() if item.id == allocation.source_parent_worktree_id), None)
        legal_targets = {binding.configured_base_branch, *([parent.branch_name] if parent else [])}
        if pull["head_branch"] != allocation.branch_name or pull["base_branch"] not in legal_targets:
            raise PermissionError("智能体只能合并自己的任务成果到资源目标或持久父任务分支")
        target = pull["base_branch"]
        base = await provider.get_branch(binding.repository_owner, binding.repository_name, target)
        if (
            pull["head_sha"] != expected_head
            or base.commit_sha != expected_base
            or pull["merged"]
            or pull["state"] != "open"
        ):
            raise HTTPException(status_code=409, detail="合并请求快照或状态已变化")
        diff = await provider.get_pull_request_diff(binding.repository_owner, binding.repository_name, pull_number)
        confirmed = await provider.get_pull_request(binding.repository_owner, binding.repository_name, pull_number)
        confirmed_base = await provider.get_branch(binding.repository_owner, binding.repository_name, target)
        if (
            confirmed["head_sha"] != expected_head
            or confirmed_base.commit_sha != expected_base
            or confirmed["head_branch"] != pull["head_branch"]
            or confirmed["base_branch"] != target
            or confirmed["merged"]
            or confirmed["state"] != "open"
        ):
            raise HTTPException(status_code=409, detail="冻结合并差异时分支或快照已变化")
    else:
        state = await review_git_action_workspace(
            db=db, uid=uid, project=project, binding=binding, allocation=allocation
        )
        if (
            state["head_sha"] != expected_head
            or state["tree_sha"] != expected_tree
            or (action == "push" and state["dirty"])
        ):
            raise HTTPException(status_code=409, detail="HEAD、内容树或 clean 状态已变化")
        diff = state.get("committed_diff", "") + "\n" + state.get("diff", "")
    effective_target = target or allocation.branch_name
    remotely_protected = await provider.is_branch_protected(
        binding.repository_owner, binding.repository_name, effective_target
    )
    canonical_target = effective_target == binding.configured_base_branch
    requires_human = remotely_protected or (canonical_target and binding.approval_mode == "protected")
    reason = (
        "Gitea 保护分支：需要人工批准"
        if remotely_protected
        else (
            "受保护项目资源：需要人工批准"
            if requires_human
            else ("资源自动授权规则" if canonical_target else "当前任务或持久父任务分支自动授权规则")
        )
    )
    row = ProjectGitAction(
        id=str(uuid.uuid4()),
        uid=uid,
        project_id=project.id,
        repository_id=binding.id,
        request_id=request_id,
        fingerprint=fingerprint,
        run_id=run.id,
        agent_slug=run.agent_slug,
        scope_key=allocation.runtime_scope_id,
        worktree_id=allocation.id,
        action=action,
        branch=allocation.branch_name,
        target_branch=target,
        expected_head=expected_head,
        expected_tree=expected_tree,
        expected_base=expected_base,
        pull_number=pull_number,
        message=message.strip(),
        diff=diff,
        approval_kind="required" if requires_human else "automatic",
        approval_reason=reason,
        approved_by=None if requires_human else run.id,
        approved_at=None if requires_human else utc_now_naive(),
        status="pending" if requires_human else "approved",
    )
    db.add(row)
    await db.flush()
    task = await enqueue_git_action_in_session(db, row) if not requires_human else None
    await db.commit()
    if task:
        await tasker.publish(task)
    return row.to_dict()


async def enqueue_git_action_in_session(db, row):
    """批准与 Durable Task 意图共用事务，发布必须发生在提交后。"""
    task = await tasker.create_in_session(
        db,
        name=f"Git {row.action} · {row.branch}",
        task_type="project_git_action",
        payload={"uid": row.uid, "project_id": row.project_id, "action_id": row.id},
        timeout_seconds=600,
    )
    row.task_id = task.id
    return task


async def list_project_git_actions(*, db, uid, project_id, limit=50, offset=0):
    """项目所有者查看持久批准与执行时间线。"""
    if await ProjectRepository(db).get_active_selectable_for_user(project_id, uid) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return [
        row.to_dict() for row in await ProjectGitActionRepository(db).list(uid, project_id, limit=limit, offset=offset)
    ]


async def decide_project_git_action(*, db, uid, project_id, action_id, approve):
    """人工批准或拒绝冻结申请，重复决定不能产生第二次执行。"""
    if await ProjectRepository(db).get_active_selectable_for_user(project_id, uid) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    await ProjectGitRepositoryStore(db).acquire_user_runtime_lock(uid)
    row = await ProjectGitActionRepository(db).get(uid, project_id, action_id, lock=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Git 申请不存在")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="此申请已决定，请查看历史结果")
    row.status = "approved" if approve else "rejected"
    row.approval_kind = "human"
    row.approved_by = uid
    row.approval_reason += "；" + ("项目所有者明确批准冻结快照" if approve else "项目所有者拒绝申请")
    row.approved_at = utc_now_naive()
    if not approve:
        row.finished_at = utc_now_naive()
    task = await enqueue_git_action_in_session(db, row) if approve else None
    await db.commit()
    if task:
        await tasker.publish(task)
    return row.to_dict()


async def get_git_action_for_run(*, db, uid, run_id, action_id):
    """根运行只能查看同一任务作用域的批准结果。"""
    run, project = await require_git_action_run(db=db, uid=uid, run_id=run_id)
    row = await ProjectGitActionRepository(db).get(uid, project.id, action_id)
    scope = await git_scope_for_run(db=db, uid=uid, project_id=project.id, run=run)
    if row is None or row.scope_key != scope:
        raise PermissionError("Git 申请不属于当前任务")
    return row.to_dict()


async def human_git_action(
    *, db, uid, project_id, action, repository_id=None, worktree_id=None, request_id=None, **snapshot
):
    """记录用户明确确认并交给同一执行 Owner，保持现有 HTTP 成果响应。"""
    if request_id:
        existing = await ProjectGitActionRepository(db).by_request(uid, request_id)
        if existing is not None:
            if (
                existing.project_id != project_id
                or existing.action != action
                or (repository_id is not None and existing.repository_id != repository_id)
                or (worktree_id is not None and existing.worktree_id != worktree_id)
                or existing.expected_head != snapshot.get("expected_head")
                or existing.expected_tree != snapshot.get("expected_tree")
                or existing.expected_base != snapshot.get("expected_base")
                or existing.pull_number != snapshot.get("number")
                or existing.message != snapshot.get("message", "")
            ):
                raise HTTPException(status_code=409, detail="相同申请标识不能改变审查快照")
            if await ProjectRepository(db).get_active_selectable_for_user(project_id, uid) is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            await db.commit()
            return await wait_human_git_action(db=db, uid=uid, project_id=project_id, action_id=existing.id)
    store = ProjectGitRepositoryStore(db)
    if worktree_id:
        allocation = await store.get_project_worktree(worktree_id, project_id, uid)
        if allocation is None:
            raise HTTPException(status_code=404, detail="工作树不存在")
        repository_id = allocation.repository_id
    project, binding, store = await get_resource_context(
        db=db, uid=uid, project_id=project_id, repository_id=repository_id, lock=True
    )
    if worktree_id:
        allocation = await store.get_project_worktree(worktree_id, project_id, uid, lock=True)
        if allocation is None or allocation.usage_mode != "worktree" or allocation.status != "ready":
            raise HTTPException(status_code=409, detail="工作树未就绪")
        if await store.has_nonterminal_run(project_id, allocation.runtime_scope_id, uid):
            raise HTTPException(status_code=409, detail="任务仍有根运行或子智能体执行")
        for slot in await store.project_occupancies(project_id, uid):
            if slot.repository_id == binding.id and await store.active_root_run(slot.active_run_id, uid):
                raise HTTPException(status_code=409, detail="同仓库仍有运行中的执行树")
        branch = allocation.branch_name
    else:
        allocation = None
        branch = binding.configured_base_branch
    if action == "merge":
        from yuxi.services.project_git_pull_request_service import verify_resource_pull_request

        provider, _ = await get_resource_provider(binding, store)
        allocations = {
            item.branch_name: item
            for item in await store.list_project_worktrees(project_id, uid)
            if item.repository_id == binding.id
        }
        pull = await provider.get_pull_request(binding.repository_owner, binding.repository_name, snapshot["number"])
        verify_resource_pull_request(binding, allocations, pull)
        allocation = allocations[pull["head_branch"]]
        branch = allocation.branch_name
        worktree_id = allocation.id
        snapshot["target_branch"] = pull["base_branch"]
    if action == "merge":
        base = await provider.get_branch(binding.repository_owner, binding.repository_name, pull["base_branch"])
        if pull["head_sha"] != snapshot["expected_head"] or base.commit_sha != snapshot["expected_base"]:
            raise HTTPException(status_code=409, detail="合并请求审查快照已变化")
        frozen_diff = await provider.get_pull_request_diff(
            binding.repository_owner, binding.repository_name, snapshot["number"]
        )
    else:
        if allocation is not None:
            state = await review_git_action_workspace(
                db=db, uid=uid, project=project, binding=binding, allocation=allocation
            )
        else:
            from yuxi.services.project_git_resource_service import review_project_git_resource

            state = await review_project_git_resource(db=db, uid=uid, project_id=project_id, repository_id=binding.id)
        if (
            state["head_sha"] != snapshot["expected_head"]
            or state["tree_sha"] != snapshot["expected_tree"]
            or (action == "push" and state["dirty"])
        ):
            raise HTTPException(status_code=409, detail="审查快照已变化，请重新查看差异")
        frozen_diff = state.get("committed_diff", "") + "\n" + state.get("diff", "")
    fingerprint = hashlib.sha256(
        json.dumps([project_id, repository_id, worktree_id, action, snapshot], sort_keys=True).encode()
    ).hexdigest()
    request_id = request_id or str(uuid.uuid4())
    repo = ProjectGitActionRepository(db)
    row = await repo.by_request(uid, request_id)
    if row and row.fingerprint != fingerprint:
        raise HTTPException(status_code=409, detail="相同申请标识不能改变审查快照")
    if row is None:
        row = ProjectGitAction(
            id=str(uuid.uuid4()),
            uid=uid,
            project_id=project_id,
            repository_id=binding.id,
            request_id=request_id,
            fingerprint=fingerprint,
            worktree_id=worktree_id,
            scope_key=allocation.runtime_scope_id if allocation else None,
            action=action,
            branch=branch,
            target_branch=snapshot.get("target_branch"),
            expected_head=snapshot["expected_head"],
            expected_tree=snapshot.get("expected_tree"),
            expected_base=snapshot.get("expected_base"),
            pull_number=snapshot.get("number"),
            message=snapshot.get("message", ""),
            diff=frozen_diff,
            approval_kind="human",
            approval_reason="项目所有者在成果界面明确确认精确快照",
            approved_by=uid,
            approved_at=utc_now_naive(),
            status="approved",
        )
        db.add(row)
        await db.flush()
        task = await enqueue_git_action_in_session(db, row)
        await db.commit()
        # 与后台 worker 竞争同一个 Task lease，重复投递不能重复执行。
        from yuxi.services.task_service import process_task

        await process_task({"worker_id": "git-human-http"}, task.id)
    else:
        await db.commit()
    return await wait_human_git_action(db=db, uid=uid, project_id=project_id, action_id=row.id)


async def wait_human_git_action(*, db, uid, project_id, action_id):
    """等待同一批准的执行结果；超时保留可从历史继续观察的申请。"""
    import asyncio

    for _ in range(610):
        row = await ProjectGitActionRepository(db).get(uid, project_id, action_id)
        if row.status == "succeeded":
            return row.result
        if row.status in {"failed", "rejected"}:
            raise HTTPException(status_code=409, detail=row.error or "Git 动作未完成，请查看审批历史并核对实际状态")
        await db.commit()
        await asyncio.sleep(1)
    raise HTTPException(status_code=409, detail=f"Git 动作仍待确认，请查看审批历史：{action_id}")
