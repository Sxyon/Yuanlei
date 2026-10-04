"""已批准 Git 动作的 Durable Task 执行与终态收敛。"""

import httpx

from fastapi import HTTPException

from yuxi.git.credentials import GitCredentialOwner
from yuxi.git.executor import GitExecutionError
from yuxi.git.worktree_executor import GitWorktreeExecutor
from yuxi.repositories.project_git_action_repository import ProjectGitActionRepository
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.services.project_git_action_service import git_action_run_resource, require_git_action_run
from yuxi.services.project_git_resource_service import get_resource_context, get_resource_provider
from yuxi.storage.postgres.manager import pg_manager
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.git_paths import resolve_project_git_host_paths
from yuxi.workspace.git_resource_paths import resource_metadata_path


async def run_project_git_action(context):
    """仅当前 Task attempt 执行已批准身份与快照，不自动重试未知副作用。"""
    uid, project_id, action_id = (context.payload[key] for key in ("uid", "project_id", "action_id"))

    async def start(db, task):
        row = await ProjectGitActionRepository(db).get(uid, project_id, action_id, lock=True)
        if row is None or row.task_id != task.id or row.status != "approved":
            raise PermissionError("Git 批准或执行 Owner 不一致")
        row.status = "running"
        row.started_at = utc_now_naive()

    await context.run_owned_transaction(start)
    await context.raise_if_cancelled()
    try:
        async with pg_manager.get_async_session_context() as db:
            # 用户锁先于领域对象；Task lease 不在长时间 Git I/O 期间持行锁。
            await ProjectGitRepositoryStore(db).acquire_user_runtime_lock(uid)
            row = await ProjectGitActionRepository(db).get(uid, project_id, action_id)
            if row is None or row.status != "running" or row.task_id != context.task_id:
                raise PermissionError("Git 申请不属于当前执行")
            approved_run = False
            run = await ProjectGitRepositoryStore(db).run_for_user(row.run_id, uid) if row.run_id else None
            if row.approval_kind == "automatic" or (
                row.approval_kind == "human" and row.approved_by == uid and run is not None and run.status == "running"
            ):
                approved_run = True
                recorded_binding = await ProjectGitRepositoryStore(db).get_binding(row.repository_id, uid)
                if recorded_binding is None:
                    raise PermissionError("批准后的资源已不可用")
                _, project, binding, allocation = await git_action_run_resource(
                    db=db,
                    uid=uid,
                    run_id=row.run_id,
                    repository_alias=recorded_binding.alias,
                )
                if (
                    binding.id != row.repository_id
                    or allocation.id != row.worktree_id
                    or allocation.runtime_scope_id != row.scope_key
                ):
                    raise PermissionError("批准后的任务资源分配已变化")
                await ProjectGitRepositoryStore(db).acquire_maintenance_lock(binding.id)
                provider, _ = await get_resource_provider(binding, ProjectGitRepositoryStore(db))
                target = row.target_branch or row.branch
                if row.approval_kind == "automatic" and (
                    (target == binding.configured_base_branch and binding.approval_mode != "automatic")
                    or await provider.is_branch_protected(binding.repository_owner, binding.repository_name, target)
                ):
                    raise PermissionError("执行前目标已受保护，需要重新申请人工批准")
            elif row.approval_kind == "human" and row.approved_by == uid:
                project, binding, store = await get_resource_context(
                    uid=uid, project_id=project_id, repository_id=row.repository_id, db=db, lock=True
                )
                allocation = await store.get_project_worktree(row.worktree_id, project_id, uid, lock=True)
            else:
                raise PermissionError("Git 操作缺少可验证批准")
            if row.worktree_id and (
                allocation is None
                or (row.action != "merge" and allocation.status != "ready")
                or allocation.branch_name != row.branch
            ):
                raise PermissionError("批准后分支或工作树已变化")
            if approved_run:
                await require_git_action_run(db=db, uid=uid, run_id=row.run_id, project_id=project_id)
            await context.raise_if_cancelled()
            result = await execute_approved_git_action(
                db=db,
                uid=uid,
                project=project,
                binding=binding,
                allocation=allocation,
                row=row,
                approved_run=approved_run,
            )
            await context.raise_if_cancelled()
            return result
    except (HTTPException, httpx.HTTPError, GitExecutionError, PermissionError, OSError, ValueError):
        # 不把 provider、路径或凭据错误正文写入 Task 日志与持久审计。
        raise RuntimeError("Git 动作未完成：请核对审查快照、目标保护、执行占用和实际 Git 状态") from None


async def execute_approved_git_action(*, db, uid, project, binding, allocation, row, approved_run=False):
    """实际副作用入口只接受持久批准字段，不接受工具任意 Git 命令。"""
    snapshot = {"expected_head": row.expected_head, "expected_tree": row.expected_tree}
    if row.action == "merge":
        provider, _ = await get_resource_provider(binding, ProjectGitRepositoryStore(db))
        pull = await provider.get_pull_request(binding.repository_owner, binding.repository_name, row.pull_number)
        if pull["head_branch"] != row.branch or pull["base_branch"] != row.target_branch:
            raise PermissionError("批准后的合并源或目标分支已变化")
        from yuxi.services.project_git_pull_request_service import merge_resource_pull_request

        return await merge_resource_pull_request(
            db=db,
            uid=uid,
            project_id=project.id,
            repository_id=binding.id,
            number=row.pull_number,
            expected_head=row.expected_head,
            expected_base=row.expected_base,
        )
    if row.approval_kind == "human" and not approved_run:
        if allocation is not None and allocation.usage_mode == "worktree":
            from yuxi.services.project_git_worktree_artifact_service import operate_worktree_artifact

            return await operate_worktree_artifact(
                db=db,
                uid=uid,
                project_id=project.id,
                worktree_id=allocation.id,
                action=row.action,
                **snapshot,
                **({"message": row.message} if row.action == "commit" else {}),
            )
        from yuxi.services.project_git_resource_service import commit_project_git_resource, push_project_git_resource

        function = commit_project_git_resource if row.action == "commit" else push_project_git_resource
        return await function(
            db=db,
            uid=uid,
            project_id=project.id,
            repository_id=binding.id,
            **snapshot,
            **({"message": row.message} if row.action == "commit" else {}),
        )
    if allocation.usage_mode == "in_place":
        from yuxi.services.project_git_resource_service import commit_project_git_resource, push_project_git_resource

        function = commit_project_git_resource if row.action == "commit" else push_project_git_resource
        return await function(
            db=db,
            uid=uid,
            project_id=project.id,
            repository_id=binding.id,
            **snapshot,
            **({"message": row.message} if row.action == "commit" else {}),
        )
    remote = None
    if row.action == "push":
        store = ProjectGitRepositoryStore(db)
        connection = await store.get_connection(binding.connection_id, uid, active_only=True)
        credential = await store.get_credential(binding.deploy_private_credential_id, uid)
        if connection is None or credential is None or not binding.canonical_ssh_url:
            raise PermissionError("Git 推送连接不可用")
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
        branch=row.branch,
        task_key=allocation.task_key,
        private_root=resource_metadata_path(binding.id).parent,
        action=row.action,
        review_base=allocation.last_pushed_sha or allocation.base_sha,
        remote=remote,
        **snapshot,
        **({"message": row.message} if row.action == "commit" else {}),
    )
    allocation.last_observed_head_sha = state["head_sha"]
    if "pushed_sha" in state:
        allocation.last_pushed_sha = state["pushed_sha"]
    await db.commit()
    return state


async def finish_project_git_action(db, task, result):
    """Git 结果与 Durable Task 成功在当前 attempt 同事务落库。"""
    row = await ProjectGitActionRepository(db).get(
        task.payload["uid"], task.payload["project_id"], task.payload["action_id"], lock=True
    )
    if row and row.task_id == task.id and row.status == "running":
        row.status = "succeeded"
        row.result = result
        row.finished_at = utc_now_naive()


async def fail_project_git_action(db, task, error):
    """崩溃、超时或拒绝后保留批准记录，并提示核对可能已有的副作用。"""
    row = await ProjectGitActionRepository(db).get(
        task.payload["uid"], task.payload["project_id"], task.payload["action_id"], lock=True
    )
    if row and row.task_id == task.id and row.status in {"approved", "running"}:
        row.status = "failed"
        row.error = "执行未完成或失去执行 Owner，请核对实际 Git 状态后重新申请；本申请不会自动重试。"
        row.finished_at = utc_now_naive()
