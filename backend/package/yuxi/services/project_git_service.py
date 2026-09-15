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
    derive_repository_directory,
    derive_task_branch,
    derive_task_key,
    repository_relative_paths,
    require_commit_sha,
    resolve_project_git_host_paths,
    runtime_git_worktree_path,
)

WORKTREE_LEASE_SECONDS = 300


class ProjectGitBusyError(RuntimeError):
    """另一个 worker 正在准备相同任务 worktree。"""


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
        ):
            raise HTTPException(status_code=409, detail="request_id 已用于其他仓库绑定")
        return existing.to_dict(), None
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, uid)
    connection = await store.get_connection(connection_id, uid, active_only=True, lock=True)
    if project is None or connection is None:
        raise HTTPException(status_code=404, detail="Project 或 Git connection 不存在")
    normalized_alias = _validate_alias(alias)
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
        ):
            raise HTTPException(status_code=409, detail="repository alias 或 request_id 已存在") from exc
        binding = replay
        return binding.to_dict(), None
    return binding.to_dict(), (binding.id, binding.operation_generation)


async def list_project_repositories_view(*, uid: str, project_id: str, db) -> list[dict]:
    """列出当前用户 Project 的仓库绑定。"""
    await _require_selectable_project(uid, project_id, db)
    return [item.to_dict() for item in await ProjectGitRepositoryStore(db).list_project_bindings(project_id, uid)]


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
    binding.status = "deleting"
    binding.operation_generation += 1
    binding.last_error_code = binding.last_error_message = None
    await db.commit()
    return binding.to_dict(), (binding.id, binding.operation_generation)


async def list_project_worktrees_view(*, uid: str, project_id: str, db) -> list[dict]:
    """列出 Project 的任务 worktree。"""
    await _require_selectable_project(uid, project_id, db)
    return [item.to_dict() for item in await ProjectGitRepositoryStore(db).list_project_worktrees(project_id, uid)]


async def cleanup_project_worktree_view(*, uid: str, project_id: str, worktree_id: str, db) -> tuple[dict, str | None]:
    """验证安全条件并持久化异步 worktree 清理意图。"""
    store = ProjectGitRepositoryStore(db)
    worktree = await store.get_project_worktree(worktree_id, project_id, uid, lock=True)
    if worktree is None:
        raise HTTPException(status_code=404, detail="worktree 不存在")
    if worktree.status == "removed":
        return worktree.to_dict(), None
    if await store.has_nonterminal_run(project_id, worktree.runtime_scope_id, uid):
        raise HTTPException(status_code=409, detail="任务仍有运行中的 AgentRun")
    binding = await store.get_binding(worktree.repository_id, uid)
    project = await ProjectRepository(db).get_for_user(project_id, uid)
    if binding is None or project is None:
        raise HTTPException(status_code=404, detail="worktree 归属不存在")
    _bare_path, path = resolve_project_git_host_paths(
        uid, project.workdir_path, binding.directory_name, worktree.task_key
    )
    if path.exists():
        state = await GitExecutor().inspect_worktree(path)
        if not state.clean or not worktree.last_pushed_sha or state.head_sha != worktree.last_pushed_sha:
            raise HTTPException(status_code=409, detail="worktree 存在未提交或未推送进展")
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


async def prepare_project_git_worktrees(
    *, uid: str, project_id: str, workdir_path: str, runtime_scope_id: str, worker_id: str
) -> list[dict]:
    """在 Agent 构图前准备全部 active 仓库的根任务 worktree。"""
    async with pg_manager.get_async_session_context() as db:
        bindings = await ProjectGitRepositoryStore(db).list_project_bindings(project_id, uid)
    live = [item for item in bindings if item.status != "disabled"]
    if any(item.status != "active" for item in live):
        raise ProjectGitBusyError("Project Git repositories are not ready")
    snapshots = []
    for binding in live:
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


async def push_project_git_branch(*, run_id: str, uid: str, repository_alias: str, expected_head_sha: str) -> dict:
    """从 ToolRuntime 重建授权并推送精确任务分支。"""
    expected_sha = require_commit_sha(expected_head_sha)
    from sqlalchemy import select
    from yuxi.storage.postgres.models_business import AgentRun, Conversation, OperationLog, Project, User

    async with pg_manager.get_async_session_context() as db:
        row = await db.execute(
            select(AgentRun, Conversation, Project)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .join(Project, Project.id == Conversation.project_id)
            .where(
                AgentRun.id == run_id, AgentRun.uid == str(uid), Conversation.uid == str(uid), Project.uid == str(uid)
            )
            .with_for_update()
        )
        result = row.one_or_none()
        if result is None or result.Project.status != "active":
            raise PermissionError("Run is not authorized for an active Project")
        run, conversation, project = result
        if run.run_type == "subagent" or run.status != "running":
            raise PermissionError("Only a running Root AgentRun can push a task branch")
        store = ProjectGitRepositoryStore(db)
        binding = await store.get_active_binding_by_alias(
            project_id=project.id,
            uid=uid,
            alias=_validate_alias(repository_alias),
            lock=True,
        )
        if binding is None:
            raise PermissionError("Repository alias is not active for this Project")
        worktree = await store.get_worktree(binding.id, run.runtime_scope_id, uid, lock=True)
        if worktree is None or worktree.status != "ready":
            raise PermissionError("Task worktree is not ready")
        connection = await store.get_connection(binding.connection_id, uid, active_only=True)
        credential = await store.get_credential(binding.deploy_private_credential_id, uid)
        if connection is None or credential is None:
            raise PermissionError("Repository credential is unavailable")
        private_key = GitCredentialOwner().decrypt(credential)
        known_hosts = connection.ssh_known_host_key
        remote_url = binding.canonical_ssh_url
        branch = worktree.branch_name
        owner = binding.repository_owner
        name = binding.repository_name
        default_branch = binding.default_branch
        bare_path, worktree_path = resolve_project_git_host_paths(
            uid, project.workdir_path, binding.directory_name, worktree.task_key
        )
        state = await GitExecutor().inspect_worktree(worktree_path)
        if not state.clean or state.head_sha != expected_sha or state.branch != branch:
            raise GitExecutionError("worktree HEAD, branch or clean state changed after approval")
        if branch == default_branch or not branch.startswith(_branch_prefix()):
            raise PermissionError("Target branch is not an allocated task branch")
        api_credential = await store.get_credential(connection.api_token_credential_id, uid)
        if api_credential is None:
            raise PermissionError("Gitea API credential is unavailable")
        api_token = GitCredentialOwner().decrypt(api_credential)
        provider = create_git_hosting_provider(
            provider=connection.provider,
            api_origin=connection.api_origin,
            api_token=api_token,
            ssh_host=connection.ssh_host,
            ssh_port=connection.ssh_port,
        )
        if await provider.is_branch_protected(owner, name, branch):
            raise PermissionError("Protected branch cannot be pushed")
        pushed = await GitExecutor().push_commit(
            bare_path=bare_path,
            expected_sha=expected_sha,
            branch=branch,
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
        )
        worktree.last_observed_head_sha = pushed
        worktree.last_pushed_sha = pushed
        user_id = await db.scalar(select(User.id).where(User.uid == str(uid)))
        if user_id is None:
            raise PermissionError("Git push audit owner is unavailable")
        db.add(
            OperationLog(
                user_id=user_id,
                operation="git_push_branch",
                details=json.dumps(
                    {
                        "run_id": run.id,
                        "project_id": project.id,
                        "repository_id": binding.id,
                        "repository_alias": binding.alias,
                        "runtime_scope_id": run.runtime_scope_id,
                        "branch": branch,
                        "pushed_sha": pushed,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        await db.commit()
    return {"repository_alias": binding.alias, "branch": branch, "pushed_sha": pushed, "remote_verified": True}


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
            public_key = binding.deploy_public_key
            public_key_fingerprint = binding.deploy_public_key_fingerprint
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

            binding = await db.scalar(
                select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id).with_for_update()
            )
            if binding is None or binding.operation_generation != generation:
                superseded = True
            else:
                store = ProjectGitRepositoryStore(db)
                await store.acquire_maintenance_lock(repository_id)
                await GitExecutor().import_bundle(bundle_path=bundle_path, bare_path=bare_path)
                binding.remote_repository_id = metadata.id
                binding.canonical_ssh_url = metadata.ssh_url
                binding.default_branch = metadata.default_branch
                binding.remote_deploy_key_id = remote_key.id
                binding.status = "active"
                binding.last_error_code = binding.last_error_message = None
                binding.updated_at = utc_now_naive()
                await db.commit()
        if superseded:
            # 外部 key 已创建但持久意图已变更；旧 job 必须自行撤销，避免与 delete job 交错后遗留权限。
            await provider.delete_deploy_key(repository_owner, repository_name, remote_key.id)
    except Exception:
        await _record_binding_failure(repository_id, generation, "provision_failed", "git_provision_failed")
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

            worktree = await db.scalar(
                select(ProjectGitWorktree).where(ProjectGitWorktree.id == worktree_id).with_for_update()
            )
            if worktree is None or worktree.status not in {"cleanup_pending", "cleanup_failed"}:
                return
            store = ProjectGitRepositoryStore(db)
            binding = await store.get_binding(worktree.repository_id, worktree.uid)
            project = await ProjectRepository(db).get_for_user(worktree.project_id, worktree.uid)
            if binding is None or project is None:
                raise RuntimeError("Git worktree ownership is unavailable")
            if await store.has_nonterminal_run(worktree.project_id, worktree.runtime_scope_id, worktree.uid):
                raise RuntimeError("Git worktree still has active AgentRun")
            _bare_path, path = resolve_project_git_host_paths(
                worktree.uid,
                project.workdir_path,
                binding.directory_name,
                worktree.task_key,
            )
            if path.exists():
                state = await GitExecutor().inspect_worktree(path)
                if not state.clean or not worktree.last_pushed_sha or state.head_sha != worktree.last_pushed_sha:
                    raise RuntimeError("Git worktree has uncommitted or unpushed progress")
            await store.acquire_maintenance_lock(binding.id)
            await GitExecutor().remove_worktree(bare_path=bare_path, worktree_path=path)
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
    branch = derive_task_branch(uid, runtime_scope_id)
    now = utc_now_naive()
    async with pg_manager.get_async_session_context() as db:
        from sqlalchemy import select

        binding = await db.scalar(
            select(ProjectGitRepository).where(ProjectGitRepository.id == binding_id, ProjectGitRepository.uid == uid)
        )
        if binding is None or binding.status != "active":
            raise ProjectGitBusyError("Project Git repository is not active")
        store = ProjectGitRepositoryStore(db)
        worktree = await store.get_worktree(binding.id, runtime_scope_id, uid, lock=True)
        if worktree is None:
            _, relative_path = repository_relative_paths(binding.directory_name, task_key)
            worktree = ProjectGitWorktree(
                id=str(uuid.uuid4()),
                repository_id=binding.id,
                project_id=binding.project_id,
                uid=uid,
                runtime_scope_id=runtime_scope_id,
                task_key=task_key,
                branch_name=branch,
                base_branch=binding.default_branch,
                base_sha="",
                relative_path=relative_path,
            )
            try:
                await store.add_worktree(worktree)
            except IntegrityError as exc:
                await db.rollback()
                raise ProjectGitBusyError("Task worktree was created concurrently") from exc
        _, expected_relative_path = repository_relative_paths(binding.directory_name, task_key)
        if (
            worktree.task_key != task_key
            or worktree.branch_name != branch
            or worktree.base_branch != binding.default_branch
            or worktree.relative_path != expected_relative_path
        ):
            raise ProjectGitBusyError("Task worktree identity does not match its root scope")
        bare_path, path = resolve_project_git_host_paths(
            uid, workdir_path, binding.directory_name, task_key, create_parents=True
        )
        if worktree.status == "ready" and path.exists():
            state = await GitExecutor().inspect_worktree(path)
            if state.branch != branch:
                raise ProjectGitBusyError("Task worktree branch changed outside its allocation")
            return _worktree_snapshot(binding, worktree, workdir_path)
        if not await store.acquire_worktree_lease(
            worktree, owner=worker_id, expires_at=now + timedelta(seconds=WORKTREE_LEASE_SECONDS), now=now
        ):
            raise ProjectGitBusyError("Task worktree is being prepared")
        connection = await store.get_connection(binding.connection_id, uid, active_only=True)
        key_credential = await store.get_credential(binding.deploy_private_credential_id, uid)
        if connection is None or key_credential is None:
            raise ProjectGitBusyError("Git credentials are unavailable")
        private_key = GitCredentialOwner().decrypt(key_credential)
        remote_url = binding.canonical_ssh_url
        default_branch = binding.default_branch
        known_hosts = connection.ssh_known_host_key
        await db.commit()
    bundle = None
    try:
        bundle = await GitExecutor().fetch_remote_bundle(
            remote_url=remote_url, private_key=private_key, known_hosts=known_hosts
        )
        async with pg_manager.get_async_session_context() as db:
            store = ProjectGitRepositoryStore(db)
            worktree = await store.get_worktree(binding_id, runtime_scope_id, uid, lock=True)
            if worktree is None or worktree.lease_owner != worker_id:
                raise ProjectGitBusyError("Task worktree lease was lost")
            await store.acquire_maintenance_lock(binding_id)
            await GitExecutor().import_bundle(bundle_path=bundle, bare_path=bare_path)
            state = await GitExecutor().ensure_worktree(
                bare_path=bare_path, worktree_path=path, branch=branch, base_branch=default_branch
            )
            base_sha = await _rev_parse(bare_path, f"refs/remotes/origin/{default_branch}")
            worktree.base_sha = worktree.base_sha or base_sha
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
        "path": runtime_git_worktree_path(workdir_path, worktree.relative_path),
        "branch": worktree.branch_name,
        "base_branch": worktree.base_branch,
        "base_sha": worktree.base_sha,
        "status": "ready",
    }


async def _record_binding_failure(repository_id: str, generation: int, status: str, code: str) -> None:
    """在独立事务记录不含 secret 的仓库操作失败。"""
    async with pg_manager.get_async_session_context() as db:
        from sqlalchemy import select

        binding = await db.scalar(
            select(ProjectGitRepository).where(ProjectGitRepository.id == repository_id).with_for_update()
        )
        if binding and binding.operation_generation == generation:
            binding.status = status
            binding.last_error_code = code
            binding.last_error_message = "Git repository operation failed"
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
) -> bool:
    """比较 repository binding 幂等请求的完整业务 identity。"""
    return (
        existing.project_id == project_id
        and existing.connection_id == connection_id
        and existing.alias == alias.strip()
        and existing.repository_owner == repository_owner.strip()
        and existing.repository_name == repository_name.strip()
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


def _required(value: str, field: str) -> str:
    """规范化必填短文本。"""
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field} 不能为空")
    return normalized


def _branch_prefix() -> str:
    """读取已由路径模块校验的全局分支前缀。"""
    from yuxi.workspace.git_paths import configured_branch_prefix

    return configured_branch_prefix()
