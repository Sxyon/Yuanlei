"""Project 多仓库、任务 worktree 和可信 push 用例。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from yuxi.git.credentials import GitCredentialOwner, GitNotConfiguredError
from yuxi.git.executor import GitExecutionError, GitExecutor
from yuxi.git.hosting import create_git_hosting_provider
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.services.project_git_execution_service import git_scope_for_thread, git_scope_for_run
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import (
    GitConnection,
    GitCredential,
    ProjectGitRepository,
    ProjectGitWorktree,
)
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.git_paths import (
    derive_allocation_branch,
    derive_repository_directory,
    derive_task_key,
    normalize_base_branch,
    normalize_branch_slug,
    repository_relative_paths,
    require_commit_sha,
    resolve_project_git_host_paths,
    runtime_git_worktree_path,
)

WORKTREE_LEASE_SECONDS = 300


class ProjectGitBusyError(RuntimeError):
    """另一个 worker 正在准备相同任务 worktree。"""


class ProjectGitSelectionError(RuntimeError):
    """已选择仓库的持久配置无法继续当前 Run。"""


async def create_git_connection_view(
    *,
    uid: str,
    request_id: str,
    name: str,
    provider: str,
    api_origin: str,
    ssh_host: str,
    ssh_port: int,
    ssh_known_host_key: str,
    api_token: object,
    db,
) -> dict:
    """验证并幂等创建用户级 Git connection。"""
    api_token = _validate_api_token(api_token)
    store = ProjectGitRepositoryStore(db)
    existing = await store.get_connection_by_idempotency_key(_required(request_id, "request_id"), uid)
    if existing:
        if not await _connection_intent_matches(
            store=store,
            existing=existing,
            uid=uid,
            name=name,
            provider=provider,
            api_origin=api_origin,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_known_host_key=ssh_known_host_key,
            api_token=api_token,
        ):
            raise HTTPException(status_code=409, detail="request_id 已用于其他 Git connection")
        return existing.to_dict()
    _validate_known_host(ssh_known_host_key, ssh_host, ssh_port)
    owner = _credential_owner_http()
    try:
        git_provider = create_git_hosting_provider(
            provider=provider,
            api_origin=api_origin,
            api_token=_required(api_token, "api_token"),
            ssh_host=ssh_host,
            ssh_port=ssh_port,
        )
        await git_provider.verify_connection()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="无法验证 Gitea connection") from exc

    encrypted = owner.encrypt(uid=uid, purpose="gitea_api_token", plaintext=api_token)
    credential = _credential_model(encrypted)
    connection = GitConnection(
        id=str(uuid.uuid4()),
        uid=str(uid),
        name=_required(name, "name")[:100],
        provider=str(provider).lower(),
        api_origin=api_origin.rstrip("/"),
        ssh_host=ssh_host.strip(),
        ssh_port=int(ssh_port),
        ssh_known_host_key=ssh_known_host_key.strip(),
        api_token_credential_id=credential.id,
        idempotency_key=request_id.strip(),
    )
    try:
        await store.add_credential(credential)
        await store.add_connection(connection)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        replay = await store.get_connection_by_idempotency_key(request_id.strip(), uid)
        if replay is None or not await _connection_intent_matches(
            store=store,
            existing=replay,
            uid=uid,
            name=name,
            provider=provider,
            api_origin=api_origin,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_known_host_key=ssh_known_host_key,
            api_token=api_token,
        ):
            raise HTTPException(status_code=409, detail="connection 名称或 request_id 已存在") from exc
        connection = replay
    return connection.to_dict()


async def list_git_connections_view(*, uid: str, db) -> list[dict]:
    """列出当前用户 connections 的非敏感字段。"""
    return [item.to_dict() for item in await ProjectGitRepositoryStore(db).list_connections(uid)]


async def rotate_git_connection_credential_view(*, uid: str, connection_id: str, api_token: object, db) -> dict:
    """验证新 Token 后原子替换加密凭据。"""
    api_token = _validate_api_token(api_token)
    store = ProjectGitRepositoryStore(db)
    connection = await store.get_connection(connection_id, uid, active_only=True, lock=True)
    if connection is None:
        raise HTTPException(status_code=404, detail="Git connection 不存在")
    owner = _credential_owner_http()
    provider = create_git_hosting_provider(
        provider=connection.provider,
        api_origin=connection.api_origin,
        api_token=_required(api_token, "api_token"),
        ssh_host=connection.ssh_host,
        ssh_port=connection.ssh_port,
    )
    try:
        await provider.verify_connection()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="无法验证新的 Gitea Token") from exc
    old = await store.get_credential(connection.api_token_credential_id, uid)
    encrypted = owner.encrypt(uid=uid, purpose="gitea_api_token", plaintext=api_token)
    await store.add_credential(_credential_model(encrypted))
    connection.api_token_credential_id = encrypted.id
    connection.updated_at = utc_now_naive()
    if old:
        _destroy_credential(old)
    await db.commit()
    return connection.to_dict()


async def delete_git_connection_view(*, uid: str, connection_id: str, db) -> dict:
    """仅在没有活动绑定时停用 connection 并销毁 Token。"""
    store = ProjectGitRepositoryStore(db)
    connection = await store.get_connection(connection_id, uid, active_only=True, lock=True)
    if connection is None:
        raise HTTPException(status_code=404, detail="Git connection 不存在")
    if await store.connection_has_live_bindings(connection_id, uid):
        raise HTTPException(status_code=409, detail="connection 仍被 Project 仓库使用")
    credential = await store.get_credential(connection.api_token_credential_id, uid)
    if credential:
        _destroy_credential(credential)
    connection.status = "disabled"
    connection.updated_at = utc_now_naive()
    await db.commit()
    return {"message": "Git connection 已停用"}


async def create_project_repository_view(
    *,
    uid: str,
    project_id: str,
    request_id: str,
    connection_id: str,
    alias: str,
    repository_owner: str,
    repository_name: str,
    db,
    purpose: str = "项目仓库",
    configured_base_branch: str | None = None,
    allowed_base_branches: list[str] | None = None,
    checkout_path: str | None = None,
    usage_mode: str = "worktree",
    approval_mode: str = "protected",
) -> tuple[dict, tuple[str, int] | None]:
    """持久化 provisioning 意图；调用方提交后发布返回的 job。"""
    store = ProjectGitRepositoryStore(db)
    request_id = _required(request_id, "request_id")
    existing = await store.get_binding_by_idempotency_key(request_id, uid)
    if existing:
        if not _binding_intent_matches(
            existing,
            project_id=project_id,
            connection_id=connection_id,
            alias=alias,
            repository_owner=repository_owner,
            repository_name=repository_name,
            purpose=purpose,
            configured_base_branch=configured_base_branch,
            allowed_base_branches=allowed_base_branches,
            checkout_path=checkout_path,
            usage_mode=usage_mode,
            approval_mode=approval_mode,
        ):
            raise HTTPException(status_code=409, detail="request_id 已用于其他仓库绑定")
        return existing.to_dict(), None
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, uid)
    connection = await store.get_connection(connection_id, uid, active_only=True, lock=True)
    if project is None or connection is None:
        raise HTTPException(status_code=404, detail="Project 或 Git connection 不存在")
    normalized_alias = _validate_alias(alias)
    normalized_purpose = _validate_purpose(purpose, "purpose")
    normalized_configured, normalized_allowed = _normalize_repository_policy(
        configured_base_branch, allowed_base_branches
    )
    from yuxi.services.project_git_resource_service import normalize_resource_path

    try:
        normalized_path = normalize_resource_path(checkout_path or repository_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if usage_mode not in {"in_place", "worktree"} or approval_mode not in {"automatic", "protected"}:
        raise HTTPException(status_code=422, detail="资源使用或授权模式非法")
    for other in await store.list_project_bindings(project_id, uid):
        if other.status != "disabled" and other.checkout_path:
            if (
                normalized_path == other.checkout_path
                or normalized_path.startswith(other.checkout_path + "/")
                or other.checkout_path.startswith(normalized_path + "/")
            ):
                raise HTTPException(status_code=409, detail="资源目录与其他资源重叠")
    private_key, public_key, fingerprint = _generate_deploy_key()
    encrypted = _credential_owner_http().encrypt(uid=uid, purpose="deploy_private_key", plaintext=private_key)
    credential = _credential_model(encrypted)
    repository_id = str(uuid.uuid4())
    binding = ProjectGitRepository(
        id=repository_id,
        project_id=project.id,
        uid=str(uid),
        connection_id=connection.id,
        alias=normalized_alias,
        directory_name=derive_repository_directory(normalized_alias, repository_id),
        repository_owner=_validate_repository_part(repository_owner),
        repository_name=_validate_repository_part(repository_name),
        purpose=normalized_purpose,
        checkout_path=normalized_path,
        usage_mode=usage_mode,
        approval_mode=approval_mode,
        configured_base_branch=normalized_configured,
        allowed_base_branches=normalized_allowed,
        deploy_public_key=public_key,
        deploy_public_key_fingerprint=fingerprint,
        deploy_private_credential_id=credential.id,
        status="provisioning",
        operation_generation=1,
        idempotency_key=request_id,
    )
    try:
        await store.add_credential(credential)
        await store.add_binding(binding)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        replay = await store.get_binding_by_idempotency_key(request_id, uid)
        if replay is None or not _binding_intent_matches(
            replay,
            project_id=project_id,
            connection_id=connection_id,
            alias=alias,
            repository_owner=repository_owner,
            repository_name=repository_name,
            purpose=purpose,
            configured_base_branch=configured_base_branch,
            allowed_base_branches=allowed_base_branches,
            checkout_path=checkout_path,
            usage_mode=usage_mode,
            approval_mode=approval_mode,
        ):
            raise HTTPException(status_code=409, detail="repository alias 或 request_id 已存在") from exc
        binding = replay
        return binding.to_dict(), None
    return binding.to_dict(), (binding.id, binding.operation_generation)


async def list_project_repositories_view(*, uid: str, project_id: str, db) -> list[dict]:
    """列出当前用户 Project 的仓库绑定。"""
    await _require_selectable_project(uid, project_id, db)
    return [item.to_dict() for item in await ProjectGitRepositoryStore(db).list_project_bindings(project_id, uid)]


async def update_project_repository_policy_view(
    *,
    uid: str,
    project_id: str,
    repository_id: str,
    purpose: str,
    configured_base_branch: str | None,
    allowed_base_branches: list[str] | None,
    db,
) -> dict:
    """验证 Gitea 精确分支后更新只影响未来 allocation 的仓库策略。"""
    store = ProjectGitRepositoryStore(db)
    binding = await store.get_binding(repository_id, uid, lock=True)
    if binding is None or binding.project_id != project_id or binding.status != "active":
        raise HTTPException(status_code=409, detail="仓库当前不可更新策略")
    connection = await store.get_connection(binding.connection_id, uid, active_only=True)
    token_credential = (
        await store.get_credential(connection.api_token_credential_id, uid) if connection is not None else None
    )
    if connection is None or token_credential is None:
        raise HTTPException(status_code=409, detail="仓库连接不可用")
    normalized_purpose = _validate_purpose(purpose, "purpose")
    configured, allowed = _normalize_repository_policy(configured_base_branch, allowed_base_branches)
    effective_configured = configured or binding.default_branch
    if not effective_configured:
        raise HTTPException(status_code=409, detail="仓库远端默认分支尚未就绪")
    effective_allowed = allowed or [effective_configured]
    if effective_configured not in effective_allowed:
        raise HTTPException(status_code=422, detail="configured_base_branch 必须位于 allowed_base_branches")
    provider = create_git_hosting_provider(
        provider=connection.provider,
        api_origin=connection.api_origin,
        api_token=GitCredentialOwner().decrypt(token_credential),
        ssh_host=connection.ssh_host,
        ssh_port=connection.ssh_port,
    )
    try:
        for branch in effective_allowed:
            await provider.get_branch(binding.repository_owner, binding.repository_name, branch)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="仓库策略包含不存在的 Gitea 分支") from exc
    if binding.checkout_head_sha and effective_configured != binding.configured_base_branch:
        raise HTTPException(status_code=409, detail="已检出分支资源不能改为另一分支，请添加另一条资源")
    binding.purpose = normalized_purpose
    binding.configured_base_branch = effective_configured
    binding.allowed_base_branches = effective_allowed
    binding.updated_at = utc_now_naive()
    await db.commit()
    return binding.to_dict()


async def list_conversation_git_repositories_view(*, uid: str, thread_id: str, db) -> list[dict]:
    """列出根 Conversation 的可选仓库及当前 allocation。"""
    conversation, project = await _require_root_conversation(uid, thread_id, db)
    del conversation
    store = ProjectGitRepositoryStore(db)
    bindings = await store.list_project_bindings(project.id, uid)
    scope = await git_scope_for_thread(db=db, uid=uid, project_id=project.id, thread_id=thread_id)
    allocations = {item.repository_id: item for item in await store.list_scope_worktrees(scope, uid)}
    return [
        _conversation_repository_view(binding, allocations.get(binding.id), project.workdir_path)
        for binding in bindings
    ]


async def select_conversation_git_repository_view(
    *,
    uid: str,
    thread_id: str,
    request_id: str,
    repository_alias: str,
    base_branch: str,
    branch_kind: str,
    branch_slug: str,
    task_purpose: str,
    db,
) -> dict:
    """持久化用户对根任务仓库的选择，不在 HTTP 请求中执行 Git 副作用。"""
    _conversation, project = await _require_root_conversation(uid, thread_id, db, lock=True)
    store = ProjectGitRepositoryStore(db)
    await store.acquire_user_runtime_lock(uid)
    binding = await store.get_active_binding_by_alias(
        project_id=project.id,
        uid=uid,
        alias=_validate_alias(repository_alias),
        lock=True,
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Project 中不存在可用的仓库 alias")
    try:
        worktree = await _request_worktree_allocation(
            store=store,
            binding=binding,
            uid=uid,
            runtime_scope_id=await git_scope_for_thread(db=db, uid=uid, project_id=project.id, thread_id=thread_id),
            request_id=_required(request_id, "request_id"),
            selection_source="user",
            requested_by_run_id=None,
            base_branch=base_branch,
            branch_kind=branch_kind,
            branch_slug=branch_slug,
            task_purpose=task_purpose,
            explicit_retry=False,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="仓库 allocation 已并发创建") from exc
    return _conversation_repository_view(binding, worktree, project.workdir_path)


async def retry_conversation_git_repository_view(*, uid: str, thread_id: str, repository_id: str, db) -> dict:
    """显式把当前根任务的 prepare_failed allocation 恢复为 requested。"""
    _conversation, project = await _require_root_conversation(uid, thread_id, db, lock=True)
    store = ProjectGitRepositoryStore(db)
    binding = await store.get_binding(repository_id, uid, lock=True)
    scope = await git_scope_for_thread(db=db, uid=uid, project_id=project.id, thread_id=thread_id)
    worktree = await store.get_worktree(repository_id, scope, uid, lock=True)
    if binding is None or binding.project_id != project.id or worktree is None or worktree.status != "prepare_failed":
        raise HTTPException(status_code=409, detail="任务仓库当前不可重试")
    if binding.status != "active":
        raise HTTPException(status_code=409, detail="仓库绑定当前不可用")
    worktree.status = "requested"
    worktree.lease_owner = None
    worktree.lease_expires_at = None
    worktree.last_error_code = worktree.last_error_message = None
    worktree.updated_at = utc_now_naive()
    await db.commit()
    return _conversation_repository_view(binding, worktree, project.workdir_path)


async def retry_project_repository_view(*, uid: str, project_id: str, repository_id: str, db):
    """将失败操作写回可重试状态并返回提交后 job。"""
    store = ProjectGitRepositoryStore(db)
    binding = await store.get_binding(repository_id, uid, lock=True)
    if (
        binding is None
        or binding.project_id != project_id
        or binding.status not in {"provision_failed", "delete_failed"}
    ):
        raise HTTPException(status_code=409, detail="仓库当前不可重试")
    binding.status = "provisioning" if binding.status == "provision_failed" else "deleting"
    binding.operation_generation += 1
    binding.last_error_code = binding.last_error_message = None
    await db.commit()
    return binding.to_dict(), (binding.id, binding.operation_generation)


async def deactivate_project_repository_view(*, uid: str, project_id: str, repository_id: str, db):
    """先持久化撤权意图，保留本地仓库和远端任务分支。"""
    store = ProjectGitRepositoryStore(db)
    binding = await store.get_binding(repository_id, uid, lock=True)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="仓库绑定不存在")
    if binding.status == "disabled":
        return binding.to_dict(), None
    if await store.occupancies(binding.id, uid):
        raise HTTPException(status_code=409, detail="资源仍有占用或等待任务，请先处理成果并释放")
    binding.status = "deleting"
    binding.operation_generation += 1
    binding.last_error_code = binding.last_error_message = None
    await db.commit()
    return binding.to_dict(), (binding.id, binding.operation_generation)


async def list_project_worktrees_view(*, uid: str, project_id: str, db) -> list[dict]:
    """列出 Project 的任务 worktree。"""
    await _require_selectable_project(uid, project_id, db)
    return [item.to_dict() for item in await ProjectGitRepositoryStore(db).list_project_worktrees(project_id, uid)]


async def _worktree_cleanup_context(*, uid, project_id, worktree_id, db):
    """按用户、仓库、工作树顺序锁定，并撤销终态执行树的文件访问。"""
    from yuxi.services.project_git_execution_service import revoke_git_owner_runtime

    store = ProjectGitRepositoryStore(db)
    worktree = await store.get_project_worktree(worktree_id, project_id, uid)
    if worktree is None:
        raise HTTPException(status_code=404, detail="worktree 不存在")
    await store.acquire_user_runtime_lock(uid)
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, uid)
    binding = await store.get_binding(worktree.repository_id, uid, lock=True)
    if project is None or binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="worktree 归属不存在")
    await store.acquire_maintenance_lock(binding.id)
    worktree = await store.get_project_worktree(worktree_id, project_id, uid, lock=True)
    if worktree is None:
        raise HTTPException(status_code=404, detail="worktree 不存在")
    if worktree.usage_mode != "worktree" or not is_allocated_task_branch(worktree, uid):
        raise HTTPException(status_code=409, detail="此分配不是有效的隔离工作树")
    slots = [slot for slot in await store.project_occupancies(project_id, uid) if slot.repository_id == binding.id]
    if await store.has_nonterminal_run(project_id, worktree.runtime_scope_id, uid):
        raise HTTPException(status_code=409, detail="任务仍有运行中的 AgentRun")
    for slot in slots:
        if await store.active_root_run(slot.active_run_id, uid):
            raise HTTPException(status_code=409, detail="同仓库仍有根运行或子智能体执行")
    for slot in slots:
        if slot.status == "owned":
            await revoke_git_owner_runtime(db=db, uid=uid, project_id=project_id, run_id=slot.active_run_id)
    return project, binding, worktree


async def _inspect_or_cleanup_worktree(*, project, binding, worktree, cleanup=False):
    """只用可信临时索引检查或删除目录，保留任务分支引用。"""
    from yuxi.git.worktree_executor import GitWorktreeExecutor
    from yuxi.workspace.git_resource_paths import resource_metadata_path

    bare, path = resolve_project_git_host_paths(
        worktree.uid, project.workdir_path, binding.directory_name, worktree.task_key
    )
    if not path.exists():
        return
    state = await GitWorktreeExecutor().operate(
        bare=bare,
        checkout=path,
        branch=worktree.branch_name,
        task_key=worktree.task_key,
        private_root=resource_metadata_path(binding.id).parent,
        action="cleanup" if cleanup else "review",
        expected_head=worktree.last_pushed_sha,
    )
    if state["dirty"] or not worktree.last_pushed_sha or state["head_sha"] != worktree.last_pushed_sha:
        raise HTTPException(status_code=409, detail="worktree 存在未提交或未推送进展")


async def cleanup_project_worktree_view(*, uid: str, project_id: str, worktree_id: str, db) -> tuple[dict, str | None]:
    """验证安全条件并持久化异步 worktree 清理意图。"""
    project, binding, worktree = await _worktree_cleanup_context(
        uid=uid, project_id=project_id, worktree_id=worktree_id, db=db
    )
    if worktree.status == "removed":
        return worktree.to_dict(), None
    await _inspect_or_cleanup_worktree(project=project, binding=binding, worktree=worktree)
    worktree.status = "cleanup_pending"
    worktree.last_error_code = worktree.last_error_message = None
    await db.commit()
    return worktree.to_dict(), worktree.id


async def process_project_git_operation(ctx, repository_id: str, operation_generation: int) -> None:
    """执行可重试的仓库 provision 或撤权操作。"""
    del ctx
    async with _repository_operation_lock(repository_id):
        async with pg_manager.get_async_session_context() as db:
            from sqlalchemy import select

            binding = await db.scalar(select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id))
            if binding is None or binding.operation_generation != int(operation_generation):
                return
            status = binding.status
        if status in {"provisioning", "provision_failed"}:
            await _provision_repository(repository_id, operation_generation)
        elif status in {"deleting", "delete_failed"}:
            await _delete_repository(repository_id, operation_generation)


async def process_project_git_worktree_cleanup(ctx, worktree_id: str) -> None:
    """执行可重试的显式 worktree 清理意图。"""
    del ctx
    await _cleanup_project_worktree(worktree_id)


async def reconcile_project_git_operations() -> list[str]:
    """从 PostgreSQL 未完成意图重投 Project Git 操作。"""
    from yuxi.services.run_queue_service import enqueue_project_git_operation

    async with pg_manager.get_async_session_context() as db:
        store = ProjectGitRepositoryStore(db)
        pending = await store.list_pending_bindings()
        pending_worktrees = await store.list_pending_worktrees()
    enqueued = []
    for binding in pending:
        await enqueue_project_git_operation(binding.id, binding.operation_generation)
        enqueued.append(binding.id)
    from yuxi.services.run_queue_service import enqueue_project_git_worktree_cleanup

    for worktree in pending_worktrees:
        await enqueue_project_git_worktree_cleanup(worktree.id)
        enqueued.append(worktree.id)
    return enqueued


async def prepare_selected_project_git_worktrees(
    *, uid: str, project_id: str, workdir_path: str, runtime_scope_id: str, worker_id: str
) -> list[dict]:
    """在 Agent 构图前只准备当前根任务显式选择的仓库。"""
    async with pg_manager.get_async_session_context() as db:
        store = ProjectGitRepositoryStore(db)
        allocations = await store.list_scope_worktrees(runtime_scope_id, uid)
        pairs = [(item, await store.get_binding(item.repository_id, uid)) for item in allocations]
    snapshots = []
    for worktree, binding in pairs:
        if binding is None or binding.project_id != project_id:
            raise ProjectGitSelectionError("Selected Project Git repository ownership is invalid")
        if binding.status == "provisioning":
            raise ProjectGitBusyError("Selected Project Git repository is not ready")
        if binding.status != "active":
            raise ProjectGitSelectionError("Selected Project Git repository is disabled or deleting")
        if worktree.status == "prepare_failed":
            raise ProjectGitSelectionError("Selected Project Git worktree requires explicit retry")
        if worktree.status in {"cleanup_pending", "cleanup_failed"}:
            raise ProjectGitSelectionError("Selected Project Git worktree is being cleaned up")
        if worktree.status not in {"requested", "preparing", "ready"}:
            raise ProjectGitSelectionError("Selected Project Git worktree has an invalid state")
        try:
            snapshots.append(
                await _prepare_repository_worktree(
                    uid=uid,
                    binding_id=binding.id,
                    workdir_path=workdir_path,
                    runtime_scope_id=runtime_scope_id,
                    worker_id=worker_id,
                )
            )
        except GitExecutionError as exc:
            raise ProjectGitBusyError("Project Git worktree preparation must be retried") from exc
    return snapshots


async def project_git_enabled_for_project(*, uid: str, project_id: str) -> bool:
    """读取 Root graph 是否应装配 Project Git 管理工具。"""
    async with pg_manager.get_async_session_context() as db:
        return await ProjectGitRepositoryStore(db).project_has_non_disabled_binding(project_id, uid)


async def list_project_git_repositories_for_run(*, run_id: str, uid: str) -> dict:
    """从 ToolRuntime 重建 Root Run 授权并返回脱敏仓库列表。"""
    async with pg_manager.get_async_session_context() as db:
        run, _conversation, project = await _require_authorized_root_run(run_id, uid, db)
        store = ProjectGitRepositoryStore(db)
        bindings = await store.list_project_bindings(project.id, uid)
        scope = await git_scope_for_run(db=db, uid=uid, project_id=project.id, run=run)
        allocations = {item.repository_id: item for item in await store.list_scope_worktrees(scope, uid)}
        repositories = [
            _tool_repository_view(binding, allocations.get(binding.id), project.workdir_path)
            for binding in bindings
            if binding.status != "disabled" or binding.id in allocations
        ]
    return {"repositories": repositories}


async def prepare_project_git_worktree_for_run(
    *,
    run_id: str,
    uid: str,
    repository_alias: str,
    base_branch: str,
    branch_kind: str,
    branch_slug: str,
    task_purpose: str,
) -> dict:
    """在工具审批后持久化意图，再同步准备或幂等复用任务 worktree。"""
    from sqlalchemy import select
    from yuxi.storage.postgres.models_business import OperationLog, User

    async with pg_manager.get_async_session_context() as db:
        run, _conversation, project = await _require_authorized_root_run(run_id, uid, db)
        store = ProjectGitRepositoryStore(db)
        await store.acquire_user_runtime_lock(uid)
        binding = await store.get_active_binding_by_alias(
            project_id=project.id,
            uid=uid,
            alias=_validate_alias(repository_alias),
            lock=True,
        )
        if binding is None:
            raise PermissionError("Repository alias is not active for this Project")
        worktree = await _request_worktree_allocation(
            store=store,
            binding=binding,
            uid=uid,
            runtime_scope_id=await git_scope_for_run(db=db, uid=uid, project_id=project.id, run=run),
            request_id=None,
            selection_source="agent",
            requested_by_run_id=run.id,
            base_branch=base_branch,
            branch_kind=branch_kind,
            branch_slug=branch_slug,
            task_purpose=task_purpose,
            explicit_retry=True,
        )
        from yuxi.services.project_git_execution_service import reserve_git_resources_for_dispatch

        resources_ready = await reserve_git_resources_for_dispatch(
            db=db,
            uid=uid,
            project_id=project.id,
            thread_id=run.conversation_thread_id,
            run_id=run.id,
            requested_at=run.created_at,
        )
        if not resources_ready:
            await db.commit()
            raise ProjectGitBusyError("资源已排队，当前根运行不能写入；等待占用释放后继续任务")
        user_id = await db.scalar(select(User.id).where(User.uid == str(uid)))
        if user_id is None:
            raise PermissionError("Git prepare audit owner is unavailable")
        db.add(
            OperationLog(
                user_id=user_id,
                operation="git_prepare_worktree_requested",
                details=json.dumps(
                    {
                        "run_id": run.id,
                        "project_id": project.id,
                        "repository_id": binding.id,
                        "repository_alias": binding.alias,
                        "runtime_scope_id": run.runtime_scope_id,
                        "allocation_generation": worktree.allocation_generation,
                        "branch": worktree.branch_name,
                        "base_branch": worktree.base_branch,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        await db.commit()
        workdir_path = project.workdir_path
        scope = await git_scope_for_run(db=db, uid=uid, project_id=project.id, run=run)
        binding_id = binding.id
    result = await _prepare_repository_worktree(
        uid=uid,
        binding_id=binding_id,
        workdir_path=workdir_path,
        runtime_scope_id=scope,
        worker_id=f"tool:{run_id}",
    )

    async with pg_manager.get_async_session_context() as db:
        from yuxi.services.project_git_execution_service import refresh_git_owner_runtime

        run, _, _ = await _require_authorized_root_run(run_id, uid, db)
        await db.commit()
        await refresh_git_owner_runtime(db=db, uid=uid, run=run, workdir_path=workdir_path)
        await db.commit()
    return result


async def push_project_git_branch(
    *, run_id: str, uid: str, repository_alias: str, expected_head_sha: str, request_id: str | None = None
) -> dict:
    """旧推送工具也通过持久批准入口，不能绕过严格保护与审计。"""
    from yuxi.services.project_git_action_service import review_git_workspace_for_run, request_git_action_for_run

    async with pg_manager.get_async_session_context() as db:
        state = await review_git_workspace_for_run(db=db, uid=uid, run_id=run_id, repository_alias=repository_alias)
        return await request_git_action_for_run(
            db=db,
            uid=uid,
            run_id=run_id,
            repository_alias=repository_alias,
            request_id=request_id or str(uuid.uuid4()),
            action="push",
            expected_head=expected_head_sha,
            expected_tree=state["tree_sha"],
        )


async def _provision_repository(repository_id: str, generation: int) -> None:
    """注册或认领 deploy key，并初始化本地 bare mirror。"""
    bundle_path: Path | None = None
    try:
        async with pg_manager.get_async_session_context() as db:
            from sqlalchemy import select

            binding = await db.scalar(select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id))
            if (
                binding is None
                or binding.operation_generation != generation
                or binding.status not in {"provisioning", "provision_failed"}
            ):
                return
            store = ProjectGitRepositoryStore(db)
            connection = await store.get_connection(binding.connection_id, binding.uid, active_only=True)
            token_credential = (
                await store.get_credential(connection.api_token_credential_id, binding.uid) if connection else None
            )
            key_credential = await store.get_credential(binding.deploy_private_credential_id, binding.uid)
            project = await ProjectRepository(db).get_for_user(binding.project_id, binding.uid)
            if (
                connection is None
                or token_credential is None
                or key_credential is None
                or project is None
                or project.status != "active"
            ):
                raise RuntimeError("Git binding dependencies are unavailable")
            owner = GitCredentialOwner()
            api_token = owner.decrypt(token_credential)
            private_key = owner.decrypt(key_credential)
            provider_name = connection.provider
            api_origin = connection.api_origin
            ssh_host = connection.ssh_host
            ssh_port = connection.ssh_port
            repository_owner = binding.repository_owner
            repository_name = binding.repository_name
            configured_base_branch = getattr(binding, "configured_base_branch", None)
            allowed_base_branches = list(getattr(binding, "allowed_base_branches", None) or [])
            public_key = binding.deploy_public_key
            public_key_fingerprint = binding.deploy_public_key_fingerprint
            binding_uid = binding.uid
            has_resource_checkout = bool(getattr(binding, "checkout_path", None))
            title = f"yuxi:{binding.id}"
            bare_path, _ = resolve_project_git_host_paths(
                binding.uid, project.workdir_path, binding.directory_name, create_parents=True
            )
            known_hosts = connection.ssh_known_host_key
        provider = create_git_hosting_provider(
            provider=provider_name,
            api_origin=api_origin,
            api_token=api_token,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
        )
        metadata = await provider.get_repository(repository_owner, repository_name)
        effective_configured = configured_base_branch or metadata.default_branch
        effective_allowed = allowed_base_branches or [effective_configured]
        if effective_configured not in effective_allowed:
            raise RuntimeError("Configured base branch is not allowed")
        for branch_name in effective_allowed:
            await provider.get_branch(repository_owner, repository_name, branch_name)
        keys = await provider.list_deploy_keys(repository_owner, repository_name)
        remote_key = next(
            (
                item
                for item in keys
                if item.title == title and _public_key_fingerprint(item.key) == public_key_fingerprint
            ),
            None,
        )
        if remote_key is None:
            remote_key = await provider.create_deploy_key(
                repository_owner, repository_name, title=title, public_key=public_key
            )
        if remote_key.read_only:
            raise RuntimeError("Gitea deploy key is read-only")
        bundle_path = await GitExecutor().fetch_remote_bundle(
            remote_url=metadata.ssh_url, private_key=private_key, known_hosts=known_hosts
        )
        superseded = False
        async with pg_manager.get_async_session_context() as db:
            from sqlalchemy import select

            if has_resource_checkout:
                from yuxi.services.project_git_resource_service import guard_git_directory_initialization

                await guard_git_directory_initialization(db=db, uid=binding_uid)
            binding = await db.scalar(
                select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id).with_for_update()
            )
            if binding is None or binding.operation_generation != generation:
                superseded = True
            else:
                store = ProjectGitRepositoryStore(db)
                await store.acquire_maintenance_lock(repository_id)
                await GitExecutor().import_bundle(bundle_path=bundle_path, bare_path=bare_path)
                if binding.checkout_path:
                    from yuxi.services.project_git_resource_service import (
                        open_resource_checkout,
                        resource_metadata_path,
                    )

                    with open_resource_checkout(
                        binding.uid, project.workdir_path, binding.checkout_path, create=True
                    ) as (checkout, executor):
                        resource_state = await executor.prepare(
                            metadata=resource_metadata_path(binding.id),
                            checkout=checkout,
                            branch=effective_configured,
                            bundle=bundle_path,
                        )
                    binding.checkout_head_sha = resource_state["head_sha"]
                binding.remote_repository_id = metadata.id
                binding.canonical_ssh_url = metadata.ssh_url
                binding.default_branch = metadata.default_branch
                binding.configured_base_branch = effective_configured
                binding.allowed_base_branches = effective_allowed
                binding.remote_deploy_key_id = remote_key.id
                binding.status = "active"
                binding.last_error_code = binding.last_error_message = None
                binding.updated_at = utc_now_naive()
                await db.commit()
        if superseded:
            # 外部 key 已创建但持久意图已变更；旧 job 必须自行撤销，避免与 delete job 交错后遗留权限。
            await provider.delete_deploy_key(repository_owner, repository_name, remote_key.id)
    except Exception as exc:
        # 只透传守卫自身的受控文案，其余异常保持通用文案，避免把远端响应或路径写入可见错误。
        from yuxi.services.project_git_resource_service import GIT_DIRECTORY_BUSY_DETAIL

        blocked = isinstance(exc, HTTPException) and exc.status_code == 409 and exc.detail == GIT_DIRECTORY_BUSY_DETAIL
        await _record_binding_failure(
            repository_id,
            generation,
            "provision_failed",
            "git_provision_blocked" if blocked else "git_provision_failed",
            message=GIT_DIRECTORY_BUSY_DETAIL if blocked else None,
        )
        raise
    finally:
        if bundle_path:
            bundle_path.unlink(missing_ok=True)


async def _delete_repository(repository_id: str, generation: int) -> None:
    """撤销远端 deploy key 并销毁本仓库私钥。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            from sqlalchemy import select

            binding = await db.scalar(select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id))
            if binding is None or binding.operation_generation != generation:
                return
            store = ProjectGitRepositoryStore(db)
            connection = await store.get_connection(binding.connection_id, binding.uid)
            api_credential = (
                await store.get_credential(connection.api_token_credential_id, binding.uid) if connection else None
            )
            if connection is None or api_credential is None:
                raise RuntimeError("Git connection credential is unavailable for deploy key revocation")
            uid = binding.uid
            credential_id = binding.deploy_private_credential_id
            provider_args = {
                "provider": connection.provider,
                "api_origin": connection.api_origin,
                "api_token": GitCredentialOwner().decrypt(api_credential),
                "ssh_host": connection.ssh_host,
                "ssh_port": connection.ssh_port,
            }
            repository_owner = binding.repository_owner
            repository_name = binding.repository_name
            remote_key_id = binding.remote_deploy_key_id
            deploy_key_title = f"yuxi:{binding.id}"
            deploy_key_fingerprint = binding.deploy_public_key_fingerprint
        provider = create_git_hosting_provider(**provider_args)
        if remote_key_id is None:
            remote_keys = await provider.list_deploy_keys(repository_owner, repository_name)
            matching_key = next(
                (
                    item
                    for item in remote_keys
                    if item.title == deploy_key_title and _public_key_fingerprint(item.key) == deploy_key_fingerprint
                ),
                None,
            )
            remote_key_id = matching_key.id if matching_key else None
        if remote_key_id is not None:
            await provider.delete_deploy_key(repository_owner, repository_name, remote_key_id)
        async with pg_manager.get_async_session_context() as db:
            store = ProjectGitRepositoryStore(db)
            binding = await store.get_binding(repository_id, uid, lock=True)
            if binding is None or binding.operation_generation != generation:
                return
            key_credential = await store.get_credential(credential_id, uid)
            if key_credential:
                _destroy_credential(key_credential)
            binding.status = "disabled"
            binding.updated_at = utc_now_naive()
            await db.commit()
    except Exception:
        await _record_binding_failure(repository_id, generation, "delete_failed", "git_delete_failed")
        raise


async def _cleanup_project_worktree(worktree_id: str) -> None:
    """回读清理前条件，在 repository maintenance lock 内移除 worktree。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            from sqlalchemy import select

            worktree = await db.scalar(select(ProjectGitWorktree).where(ProjectGitWorktree.id == worktree_id))
            if worktree is None or worktree.status not in {"cleanup_pending", "cleanup_failed"}:
                return
            project, binding, worktree = await _worktree_cleanup_context(
                uid=worktree.uid, project_id=worktree.project_id, worktree_id=worktree_id, db=db
            )
            if worktree.status not in {"cleanup_pending", "cleanup_failed"}:
                return
            await _inspect_or_cleanup_worktree(project=project, binding=binding, worktree=worktree, cleanup=True)
            worktree.status = "removed"
            worktree.lease_owner = None
            worktree.lease_expires_at = None
            worktree.last_error_code = worktree.last_error_message = None
            worktree.updated_at = utc_now_naive()
            await db.commit()
    except Exception:
        await _record_worktree_cleanup_failure(worktree_id)
        raise


async def _prepare_repository_worktree(
    *, uid: str, binding_id: str, workdir_path: str, runtime_scope_id: str, worker_id: str
) -> dict:
    """取得 lease 后刷新 bare repo 并创建或复用任务 worktree。"""
    task_key = derive_task_key(uid, runtime_scope_id)
    now = utc_now_naive()
    async with pg_manager.get_async_session_context() as db:
        store = ProjectGitRepositoryStore(db)
        await store.acquire_user_runtime_lock(uid)
        binding = await store.get_binding(binding_id, uid, lock=True)
        if binding is None or binding.status != "active":
            raise ProjectGitBusyError("Project Git repository is not active")
        slot = await store.occupancy(binding.id, runtime_scope_id, uid)
        worktree = await store.get_worktree(binding.id, runtime_scope_id, uid, lock=True)
        if worktree is None:
            raise ProjectGitSelectionError("Task repository was not selected")
        if worktree.usage_mode == "in_place":
            from yuxi.services.project_git_resource_service import open_resource_checkout, resource_metadata_path

            if slot is None or slot.status != "owned":
                raise ProjectGitBusyError("项目资源正在等待持续占用")
            if (
                worktree.relative_path != binding.checkout_path
                or worktree.branch_name != binding.configured_base_branch
            ):
                raise ProjectGitSelectionError("资源目录或分支与任务分配不一致")
            with open_resource_checkout(uid, workdir_path, binding.checkout_path) as (checkout, executor):
                state = await executor.review(
                    metadata=resource_metadata_path(binding.id),
                    checkout=checkout,
                    branch=binding.configured_base_branch,
                )
            worktree.last_observed_head_sha = state["head_sha"]
            worktree.base_sha = worktree.base_sha or state["head_sha"]
            worktree.status = "ready"
            await db.commit()
            return _worktree_snapshot(binding, worktree, workdir_path)
        _, expected_relative_path = repository_relative_paths(binding.directory_name, task_key)
        if worktree.task_key != task_key or worktree.relative_path != expected_relative_path:
            raise ProjectGitBusyError("Task worktree identity does not match its root scope")
        branch = worktree.branch_name
        base_branch = worktree.base_branch
        if branch in {base_branch, binding.default_branch} or not is_allocated_task_branch(worktree, uid):
            raise ProjectGitSelectionError("Task worktree branch is not a valid allocation branch")
        bare_path, path = resolve_project_git_host_paths(
            uid, workdir_path, binding.directory_name, task_key, create_parents=True
        )
        if worktree.status == "ready" and path.exists():
            state = await GitExecutor().inspect_worktree(path)
            if state.branch != branch:
                raise ProjectGitBusyError("Task worktree branch changed outside its allocation")
            return _worktree_snapshot(binding, worktree, workdir_path)
        if worktree.status == "prepare_failed":
            raise ProjectGitSelectionError("Task worktree requires explicit retry")
        if worktree.status not in {"requested", "preparing", "ready"}:
            raise ProjectGitSelectionError("Task worktree is not preparable")
        if not await store.acquire_worktree_lease(
            worktree, owner=worker_id, expires_at=now + timedelta(seconds=WORKTREE_LEASE_SECONDS), now=now
        ):
            raise ProjectGitBusyError("Task worktree is being prepared")
        connection = await store.get_connection(binding.connection_id, uid, active_only=True)
        key_credential = await store.get_credential(binding.deploy_private_credential_id, uid)
        api_credential = (
            await store.get_credential(connection.api_token_credential_id, uid) if connection is not None else None
        )
        if connection is None or key_credential is None or api_credential is None:
            raise ProjectGitBusyError("Git credentials are unavailable")
        credential_owner = GitCredentialOwner()
        private_key = credential_owner.decrypt(key_credential)
        api_token = credential_owner.decrypt(api_credential)
        remote_url = binding.canonical_ssh_url
        known_hosts = connection.ssh_known_host_key
        provider_args = {
            "provider": connection.provider,
            "api_origin": connection.api_origin,
            "api_token": api_token,
            "ssh_host": connection.ssh_host,
            "ssh_port": connection.ssh_port,
        }
        repository_owner = binding.repository_owner
        repository_name = binding.repository_name
        await db.commit()
    bundle = None
    try:
        provider = create_git_hosting_provider(**provider_args)
        if await provider.is_branch_protected(repository_owner, repository_name, branch):
            raise PermissionError("Protected branch cannot be allocated")
        bundle = await GitExecutor().fetch_remote_bundle(
            remote_url=remote_url, private_key=private_key, known_hosts=known_hosts
        )
        async with pg_manager.get_async_session_context() as db:
            store = ProjectGitRepositoryStore(db)
            await store.acquire_user_runtime_lock(uid)
            await store.get_binding(binding_id, uid, lock=True)
            await store.acquire_maintenance_lock(binding_id)
            worktree = await store.get_worktree(binding_id, runtime_scope_id, uid, lock=True)
            if worktree is None or worktree.lease_owner != worker_id:
                raise ProjectGitBusyError("Task worktree lease was lost")
            await GitExecutor().import_bundle(bundle_path=bundle, bare_path=bare_path)
            fetched_base_sha = await _rev_parse(bare_path, f"refs/remotes/origin/{base_branch}")
            if worktree.base_sha is None:
                worktree.base_sha = fetched_base_sha
            remote_branch_sha = await _try_rev_parse(bare_path, f"refs/remotes/origin/{branch}")
            if remote_branch_sha is not None and worktree.last_pushed_sha != remote_branch_sha:
                raise GitExecutionError("remote task branch belongs to another allocation history")
            if worktree.source_parent_worktree_id:
                parent = await store.get_project_worktree(worktree.source_parent_worktree_id, worktree.project_id, uid)
                if parent is None or parent.repository_id != binding_id:
                    raise ProjectGitSelectionError("隔离工作区的父资源不存在或归属不一致")
                if parent.usage_mode == "in_place":
                    from yuxi.services.project_git_resource_service import resource_metadata_path

                    await GitExecutor().import_local_commit(
                        source=resource_metadata_path(binding_id),
                        destination=bare_path,
                        sha=worktree.base_sha,
                    )
            state = await GitExecutor().ensure_worktree(
                bare_path=bare_path,
                worktree_path=path,
                branch=branch,
                base_branch=base_branch,
                base_sha=worktree.base_sha,
            )
            worktree.last_observed_head_sha = state.head_sha
            worktree.status = "ready"
            worktree.lease_owner = None
            worktree.lease_expires_at = None
            worktree.last_error_code = worktree.last_error_message = None
            await db.commit()
    except Exception:
        await _record_worktree_failure(binding_id, runtime_scope_id, uid, worker_id)
        raise
    finally:
        if bundle:
            bundle.unlink(missing_ok=True)
    return _worktree_snapshot(binding, worktree, workdir_path)


def _worktree_snapshot(binding: ProjectGitRepository, worktree: ProjectGitWorktree, workdir_path: str) -> dict:
    """构造不包含远端和凭据的 Agent Git 运行快照。"""
    return {
        "alias": binding.alias,
        "repository_id": binding.id,
        "purpose": binding.purpose,
        "task_purpose": worktree.task_purpose,
        "path": runtime_git_worktree_path(workdir_path, worktree.relative_path),
        "branch": worktree.branch_name,
        "base_branch": worktree.base_branch,
        "base_sha": worktree.base_sha,
        "selection_source": worktree.selection_source,
        "usage_mode": worktree.usage_mode,
        "approval_mode": binding.approval_mode,
        "status": "ready",
    }


async def _request_worktree_allocation(
    *,
    store: ProjectGitRepositoryStore,
    binding: ProjectGitRepository,
    uid: str,
    runtime_scope_id: str,
    request_id: str | None,
    selection_source: str,
    requested_by_run_id: str | None,
    base_branch: str,
    branch_kind: str,
    branch_slug: str,
    task_purpose: str,
    explicit_retry: bool,
) -> ProjectGitWorktree:
    """幂等创建或重新激活一个根任务仓库 allocation。"""
    current = await store.get_worktree(binding.id, runtime_scope_id, uid, lock=True)
    usage_mode = current.usage_mode if current is not None and current.status != "removed" else binding.usage_mode
    source_parent = None
    parent_sha = None
    if (current is None or current.status == "removed") and runtime_scope_id.startswith("task:"):
        from yuxi.services.project_git_execution_service import git_scope_for_task

        task = await store.task_for_project(runtime_scope_id[5:], binding.project_id)
        if task is None:
            raise HTTPException(status_code=409, detail="Git 工作区任务不存在")
        if task.parent_id and task.git_workspace_mode == "isolated":
            parent = await store.task_for_project(task.parent_id, binding.project_id)
            if parent is None:
                raise HTTPException(status_code=409, detail="父任务不存在，不能创建隔离工作区")
            parent_scope = await git_scope_for_task(db=store.db, task=parent, project_id=binding.project_id)
            source_parent = await store.get_worktree(binding.id, parent_scope, uid, lock=True)
            if source_parent is None or source_parent.status != "ready":
                raise HTTPException(status_code=409, detail="父任务尚未准备此资源，不能从父级创建隔离工作区")
            usage_mode = "worktree"
            if source_parent.usage_mode == "in_place":
                from yuxi.services.project_git_resource_service import resource_metadata_path

                parent_sha = await _rev_parse(
                    resource_metadata_path(binding.id), f"refs/heads/{source_parent.branch_name}"
                )
            else:
                project = await ProjectRepository(store.db).get_for_user(binding.project_id, uid)
                _, parent_path = resolve_project_git_host_paths(
                    uid, project.workdir_path, binding.directory_name, source_parent.task_key
                )
                parent_state = await GitExecutor().inspect_worktree(parent_path)
                if parent_state.branch != source_parent.branch_name:
                    raise HTTPException(status_code=409, detail="父任务分支与持久分配不一致")
                parent_sha = parent_state.head_sha
    try:
        normalized_base = normalize_base_branch(base_branch)
        normalized_slug = normalize_branch_slug(branch_slug)
        branch = (
            current.branch_name
            if current is not None and current.status != "removed"
            else (
                normalized_base
                if usage_mode == "in_place"
                else derive_allocation_branch(branch_kind, normalized_slug, uid, runtime_scope_id)
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_kind = str(branch_kind).strip()
    normalized_purpose = _validate_purpose(task_purpose, "task_purpose")
    if normalized_base not in (binding.allowed_base_branches or []):
        raise HTTPException(status_code=422, detail="base_branch 不在仓库允许列表")
    if usage_mode != "in_place" and branch in {normalized_base, binding.default_branch}:
        raise HTTPException(status_code=422, detail="任务分支不能等于 base/default branch")

    if usage_mode == "in_place" and (
        not binding.checkout_head_sha or not binding.checkout_path or normalized_base != binding.configured_base_branch
    ):
        raise HTTPException(status_code=409, detail="直接修改模式必须使用已经检出的资源分支")

    if request_id:
        replay = await store.get_worktree_by_selection_request(request_id, uid, lock=True)
        if replay is not None:
            if replay.repository_id != binding.id or replay.runtime_scope_id != runtime_scope_id:
                raise HTTPException(status_code=409, detail="request_id 已用于其他任务仓库")
            if not _allocation_intent_matches(
                replay, normalized_base, normalized_kind, normalized_slug, normalized_purpose, branch
            ):
                raise HTTPException(status_code=409, detail="request_id 已用于其他仓库意图")
            return replay

    worktree = current
    task_key = derive_task_key(uid, runtime_scope_id)
    _, relative_path = repository_relative_paths(binding.directory_name, task_key)
    if usage_mode == "in_place":
        relative_path = binding.checkout_path
    if worktree is None:
        worktree = ProjectGitWorktree(
            id=str(uuid.uuid4()),
            repository_id=binding.id,
            project_id=binding.project_id,
            uid=str(uid),
            runtime_scope_id=runtime_scope_id,
            task_key=task_key,
            selection_source=selection_source,
            task_purpose=normalized_purpose,
            branch_kind=normalized_kind,
            branch_slug=normalized_slug,
            requested_by_run_id=requested_by_run_id,
            allocation_generation=1,
            selection_request_id=request_id,
            branch_name=branch,
            base_branch=normalized_base,
            base_sha=parent_sha,
            usage_mode=usage_mode,
            source_parent_worktree_id=source_parent.id if source_parent else None,
            relative_path=relative_path,
            status="requested",
        )
        return await store.add_worktree(worktree)

    same_intent = _allocation_intent_matches(
        worktree, normalized_base, normalized_kind, normalized_slug, normalized_purpose, branch
    )
    if worktree.status != "removed":
        if not same_intent:
            raise HTTPException(status_code=409, detail="当前任务已为该仓库固定其他分支意图")
        if worktree.status == "prepare_failed" and explicit_retry:
            worktree.status = "requested"
            worktree.lease_owner = None
            worktree.lease_expires_at = None
            worktree.last_error_code = worktree.last_error_message = None
        return worktree

    worktree.allocation_generation += 1
    worktree.selection_source = selection_source
    worktree.requested_by_run_id = requested_by_run_id
    worktree.selection_request_id = request_id
    worktree.usage_mode = usage_mode
    worktree.source_parent_worktree_id = source_parent.id if source_parent else None
    worktree.relative_path = relative_path
    worktree.status = "requested"
    worktree.lease_owner = None
    worktree.lease_expires_at = None
    worktree.last_error_code = worktree.last_error_message = None
    if not same_intent:
        worktree.task_purpose = normalized_purpose
        worktree.branch_kind = normalized_kind
        worktree.branch_slug = normalized_slug
        worktree.branch_name = branch
        worktree.base_branch = normalized_base
        worktree.base_sha = parent_sha
        worktree.last_observed_head_sha = None
        worktree.last_pushed_sha = None
    worktree.updated_at = utc_now_naive()
    return worktree


def _allocation_intent_matches(
    worktree: ProjectGitWorktree,
    base_branch: str,
    branch_kind: str,
    branch_slug: str,
    task_purpose: str,
    branch_name: str,
) -> bool:
    """比较当前 generation 的稳定仓库意图。"""
    return (
        worktree.base_branch == base_branch
        and worktree.branch_kind == branch_kind
        and worktree.branch_slug == branch_slug
        and worktree.task_purpose == task_purpose
        and worktree.branch_name == branch_name
    )


def _conversation_repository_view(
    binding: ProjectGitRepository, worktree: ProjectGitWorktree | None, workdir_path: str
) -> dict:
    """构造 Conversation 仓库设置视图，不暴露远端和宿主路径。"""
    allocation = worktree.to_dict() if worktree is not None else None
    if allocation is not None:
        allocation["sandbox_path"] = (
            runtime_git_worktree_path(workdir_path, worktree.relative_path) if worktree.status == "ready" else None
        )
        allocation.pop("relative_path", None)
    return {
        "id": binding.id,
        "alias": binding.alias,
        "purpose": binding.purpose,
        "status": binding.status,
        "default_branch": binding.default_branch,
        "default_base_branch": binding.configured_base_branch or binding.default_branch,
        "allowed_base_branches": binding.allowed_base_branches or [],
        "allocation": allocation,
    }


def _tool_repository_view(
    binding: ProjectGitRepository, worktree: ProjectGitWorktree | None, workdir_path: str
) -> dict:
    """构造模型可见的最小仓库发现结果。"""
    result = _conversation_repository_view(binding, worktree, workdir_path)
    allocation = result.pop("allocation")
    result["task_allocation_status"] = allocation["status"] if allocation else None
    if allocation:
        result["task_branch"] = allocation["branch"]
        result["task_path"] = allocation["sandbox_path"]
        result["task_purpose"] = allocation["task_purpose"]
    return result


async def _require_root_conversation(uid: str, thread_id: str, db, *, lock: bool = False):
    """由公开 thread identity 回读当前用户的根 Conversation 与 Project。"""
    from sqlalchemy import select
    from yuxi.storage.postgres.models_business import Conversation, Project

    query = (
        select(Conversation, Project)
        .join(Project, Project.id == Conversation.project_id)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.uid == str(uid),
            Conversation.status != "deleted",
            Project.uid == str(uid),
            Project.status == "active",
        )
    )
    if lock:
        query = query.with_for_update(of=Conversation)
    result = (await db.execute(query)).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation 不存在")
    conversation, project = result
    if conversation.status == "subagent":
        raise HTTPException(status_code=409, detail="SubAgent Conversation 不能管理任务仓库")
    return conversation, project


async def _require_authorized_root_run(run_id: str, uid: str, db):
    """从数据库关系重建 Git 管理工具的 Root Run 授权。"""
    from sqlalchemy import select
    from yuxi.storage.postgres.models_business import AgentRun, Conversation, Project

    result = (
        await db.execute(
            select(AgentRun, Conversation, Project)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .join(Project, Project.id == Conversation.project_id)
            .where(
                AgentRun.id == run_id,
                AgentRun.uid == str(uid),
                Conversation.uid == str(uid),
                Project.uid == str(uid),
            )
            .with_for_update(of=(AgentRun, Conversation))
        )
    ).one_or_none()
    if result is None:
        raise PermissionError("Run is not authorized for Project Git")
    run, conversation, project = result
    if run.run_type == "subagent" or run.status != "running" or project.status != "active":
        raise PermissionError("Only a running Root AgentRun can manage Project Git")
    return run, conversation, project


async def _record_binding_failure(
    repository_id: str, generation: int, status: str, code: str, *, message: str | None = None
) -> None:
    """在独立事务记录不含 secret 的仓库操作失败，仅接受调用方给定的受控文案。"""
    async with pg_manager.get_async_session_context() as db:
        from sqlalchemy import select

        binding = await db.scalar(
            select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id).with_for_update()
        )
        if binding and binding.operation_generation == generation:
            binding.status = status
            binding.last_error_code = code
            binding.last_error_message = message or "Git repository operation failed"
            binding.updated_at = utc_now_naive()
            await db.commit()


async def _record_worktree_failure(binding_id: str, scope: str, uid: str, worker_id: str) -> None:
    """记录当前 lease 所属 worktree 的准备失败。"""
    async with pg_manager.get_async_session_context() as db:
        store = ProjectGitRepositoryStore(db)
        worktree = await store.get_worktree(binding_id, scope, uid, lock=True)
        if worktree and worktree.lease_owner == worker_id:
            worktree.status = "prepare_failed"
            worktree.lease_owner = None
            worktree.lease_expires_at = None
            worktree.last_error_code = "git_prepare_failed"
            worktree.last_error_message = "Git worktree preparation failed"
            await db.commit()


async def _record_worktree_cleanup_failure(worktree_id: str) -> None:
    """记录不含路径和 secret 的 worktree 清理失败。"""
    async with pg_manager.get_async_session_context() as db:
        from sqlalchemy import select

        worktree = await db.scalar(
            select(ProjectGitWorktree).where(ProjectGitWorktree.id == worktree_id).with_for_update()
        )
        if worktree and worktree.status in {"cleanup_pending", "cleanup_failed"}:
            worktree.status = "cleanup_failed"
            worktree.last_error_code = "git_cleanup_failed"
            worktree.last_error_message = "Git worktree cleanup failed"
            worktree.updated_at = utc_now_naive()
            await db.commit()


@asynccontextmanager
async def _repository_operation_lock(repository_id: str):
    """用 PostgreSQL session lock 串行化同一 binding 的完整远端副作用。"""
    from sqlalchemy import text

    key = f"project-git-operation:{repository_id}"
    pg_manager.initialize()
    if pg_manager.async_engine is None:
        raise RuntimeError("PostgreSQL is required for Project Git operations")
    async with pg_manager.async_engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
        # AsyncConnection 保留同一物理连接；commit 后 session lock 仍持有且不占用数据库事务。
        await connection.commit()
        try:
            yield
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
            await connection.commit()


async def _rev_parse(bare_path: Path, ref: str) -> str:
    """无凭据回读 bare repo commit。"""
    import asyncio
    import subprocess

    def run() -> str:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "--git-dir", str(bare_path), "rev-parse", f"{ref}^{{commit}}"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        return result.stdout.strip()

    return await asyncio.to_thread(run)


async def _try_rev_parse(bare_path: Path, ref: str) -> str | None:
    """回读可选 ref；不存在返回 None，其他 Git 错误仍显式失败。"""
    import asyncio
    import subprocess

    def run() -> str | None:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "--git-dir", str(bare_path), "rev-parse", f"{ref}^{{commit}}"],
            check=False,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        if result.returncode == 128:
            return None
        raise GitExecutionError("failed to inspect optional Git ref")

    return await asyncio.to_thread(run)


async def _require_selectable_project(uid: str, project_id: str, db):
    """要求 Project 可由当前用户管理。"""
    project = await ProjectRepository(db).get_for_user(project_id, uid)
    if project is None or project.status != "active" or project.selection_status != "selectable":
        raise HTTPException(status_code=404, detail="Project 不存在")
    return project


def _credential_owner_http() -> GitCredentialOwner:
    """把缺失 master key 映射为可选 Git 能力 503。"""
    try:
        return GitCredentialOwner()
    except GitNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"code": "git_not_configured"}) from exc


async def _connection_intent_matches(
    *,
    store: ProjectGitRepositoryStore,
    existing: GitConnection,
    uid: str,
    name: str,
    provider: str,
    api_origin: str,
    ssh_host: str,
    ssh_port: int,
    ssh_known_host_key: str,
    api_token: str,
) -> bool:
    """比较 connection 幂等请求的完整输入，不持久化明文 Token。"""
    credential = await store.get_credential(existing.api_token_credential_id, uid)
    if credential is None:
        return False
    try:
        stored_token = _credential_owner_http().decrypt(credential)
    except Exception:
        return False
    return (
        existing.name == name.strip()
        and existing.provider == provider.strip().lower()
        and existing.api_origin == api_origin.rstrip("/")
        and existing.ssh_host == ssh_host.strip()
        and existing.ssh_port == int(ssh_port)
        and existing.ssh_known_host_key == ssh_known_host_key.strip()
        and hmac.compare_digest(stored_token, str(api_token))
    )


def _binding_intent_matches(
    existing: ProjectGitRepository,
    *,
    project_id: str,
    connection_id: str,
    alias: str,
    repository_owner: str,
    repository_name: str,
    purpose: str,
    configured_base_branch: str | None,
    allowed_base_branches: list[str] | None,
    checkout_path: str | None = None,
    usage_mode: str = "worktree",
    approval_mode: str = "protected",
) -> bool:
    """比较 repository binding 幂等请求的完整业务 identity。"""
    try:
        normalized_configured, normalized_allowed = _normalize_repository_policy(
            configured_base_branch, allowed_base_branches
        )
        normalized_purpose = _validate_purpose(purpose, "purpose")
    except HTTPException:
        return False
    return (
        existing.project_id == project_id
        and existing.connection_id == connection_id
        and existing.alias == alias.strip()
        and existing.repository_owner == repository_owner.strip()
        and existing.repository_name == repository_name.strip()
        and getattr(existing, "purpose", "项目仓库") == normalized_purpose
        and getattr(existing, "configured_base_branch", None) == normalized_configured
        and list(getattr(existing, "allowed_base_branches", None) or []) == normalized_allowed
        and (getattr(existing, "checkout_path", None) or repository_name) == (checkout_path or repository_name)
        and (getattr(existing, "usage_mode", None) or "worktree") == usage_mode
        and (getattr(existing, "approval_mode", None) or "protected") == approval_mode
    )


def _credential_model(encrypted) -> GitCredential:
    """把加密结果转为持久化模型。"""
    return GitCredential(
        id=encrypted.id,
        uid=encrypted.uid,
        purpose=encrypted.purpose,
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
    )


def _destroy_credential(credential: GitCredential) -> None:
    """销毁数据库中的当前密文引用。"""
    credential.ciphertext = b""
    credential.nonce = b""
    credential.status = "destroyed"
    credential.destroyed_at = utc_now_naive()


def _generate_deploy_key() -> tuple[str, str, str]:
    """生成每仓库独立的 Ed25519 deploy keypair。"""
    key = Ed25519PrivateKey.generate()
    private_key = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
    ).decode()
    public_key = (
        key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    )
    return private_key, public_key, _public_key_fingerprint(public_key)


def _public_key_fingerprint(public_key: str) -> str:
    """计算 OpenSSH 公钥 SHA256 fingerprint。"""
    parts = public_key.strip().split()
    if len(parts) < 2:
        raise ValueError("invalid SSH public key")
    digest = hashlib.sha256(base64.b64decode(parts[1])).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def _validate_known_host(value: str, ssh_host: str, ssh_port: int) -> None:
    """校验用户明确提供的 SSH known-host 信任锚。"""
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip() and not line.startswith("#")]
    expected = ssh_host if int(ssh_port) == 22 else f"[{ssh_host}]:{int(ssh_port)}"
    if not lines or not any(line.split(maxsplit=1)[0] == expected for line in lines):
        raise HTTPException(status_code=422, detail="ssh_known_host_key 与 SSH endpoint 不匹配")


def _validate_alias(value: str) -> str:
    """校验仓库显示 alias；路径从服务端另行派生。"""
    alias = _required(value, "alias")
    if len(alias) > 80 or alias in {".", ".."} or any(ord(char) < 32 for char in alias):
        raise HTTPException(status_code=422, detail="repository alias 非法")
    return alias


def _validate_repository_part(value: str) -> str:
    """校验 Gitea owner/name 标识。"""
    normalized = _required(value, "repository identity")
    if len(normalized) > 255 or any(char in normalized for char in "/\\:@") or normalized in {".", ".."}:
        raise HTTPException(status_code=422, detail="Gitea repository identity 非法")
    return normalized


def _validate_api_token(value: object) -> str:
    """在 service 边界校验 write-only Token，并只返回固定错误。"""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise HTTPException(status_code=422, detail="Gitea API Token 非法")
    return value


def _validate_purpose(value: str, field: str) -> str:
    """校验仓库用途等用户可见短说明。"""
    normalized = _required(value, field)
    if len(normalized) > 500 or any(ord(char) < 32 and char not in "\n\t" for char in normalized):
        raise HTTPException(status_code=422, detail=f"{field} 非法")
    return normalized


def _normalize_repository_policy(
    configured_base_branch: str | None, allowed_base_branches: list[str] | None
) -> tuple[str | None, list[str]]:
    """规范化精确 base branch 策略并保留用户顺序。"""
    try:
        configured = normalize_base_branch(configured_base_branch) if configured_base_branch else None
        if allowed_base_branches is None:
            allowed = []
        elif not isinstance(allowed_base_branches, list):
            raise ValueError("allowed_base_branches must be a list")
        else:
            allowed = list(dict.fromkeys(normalize_base_branch(item) for item in allowed_base_branches))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Git base branch 策略非法") from exc
    if configured is not None and allowed and configured not in allowed:
        raise HTTPException(status_code=422, detail="configured_base_branch 必须位于 allowed_base_branches")
    return configured, allowed


def _required(value: str, field: str) -> str:
    """规范化必填短文本。"""
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field} 不能为空")
    return normalized


def is_allocated_task_branch(worktree, uid: str) -> bool:
    """验证持久化分配身份，保留已存在的旧 codex 分支消费者。"""
    if worktree.branch_kind == "legacy":
        return worktree.branch_name.endswith(f"/task-{derive_task_key(uid, worktree.runtime_scope_id)}")
    expected = derive_allocation_branch(worktree.branch_kind, worktree.branch_slug, uid, worktree.runtime_scope_id)
    legacy = "codex/" + expected[len(_branch_prefix()) :]
    return worktree.branch_name in {expected, legacy}


def _branch_prefix() -> str:
    """读取已由路径模块校验的全局分支前缀。"""
    from yuxi.workspace.git_paths import configured_branch_prefix

    return configured_branch_prefix()
