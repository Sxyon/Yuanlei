"""项目完整分支资源与可信提交的用户用例。"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath

from fastapi import HTTPException

from yuxi.git.credentials import GitCredentialOwner
from yuxi.git.executor import GitExecutor
from yuxi.git.hosting import create_git_hosting_provider
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.git_paths import normalize_base_branch
from yuxi.workspace.git_resource_paths import normalize_resource_path, open_resource_checkout, resource_metadata_path

GIT_DIRECTORY_BUSY_DETAIL = "当前用户仍有运行或待审批运行，请结束后再初始化 Git 资源目录"


async def guard_git_directory_initialization(*, db, uid: str):
    """新保护目录出现前阻止旧 RW 挂载存活，活动运行期间明确拒绝初始化。"""
    from yuxi.agents.backends.sandbox import get_sandbox_provider

    store = ProjectGitRepositoryStore(db)
    await store.acquire_user_runtime_lock(uid)
    if await store.user_has_nonterminal_runs(uid):
        raise HTTPException(status_code=409, detail=GIT_DIRECTORY_BUSY_DETAIL)
    await asyncio.to_thread(get_sandbox_provider().revoke_user_git_runtimes, uid)


async def get_resource_context(
    *, uid: str, project_id: str, repository_id: str, db, lock: bool = False, allow_incomplete: bool = False
):
    """在用户与项目边界回读分支资源，副作用时锁定项目及资源。"""
    repository = ProjectRepository(db)
    if lock:
        await ProjectGitRepositoryStore(db).acquire_user_runtime_lock(uid)
    project = (
        await repository.lock_active_selectable_for_user(project_id, uid)
        if lock
        else await repository.get_active_selectable_for_user(project_id, uid)
    )
    store = ProjectGitRepositoryStore(db)
    binding = await store.get_binding(repository_id, uid, lock=lock)
    allowed_statuses = {"active", "provision_failed"} if allow_incomplete else {"active"}
    if project is None or binding is None or binding.project_id != project_id or binding.status not in allowed_statuses:
        raise HTTPException(status_code=404, detail="项目 Git 资源不存在或未就绪")
    if lock:
        await store.acquire_maintenance_lock(binding.id)
    return project, binding, store


async def get_resource_provider(binding, store):
    """在可信边界取得远端元数据访问能力。"""
    connection = await store.get_connection(binding.connection_id, binding.uid, active_only=True)
    token = await store.get_credential(connection.api_token_credential_id, binding.uid) if connection else None
    if connection is None or token is None:
        raise HTTPException(status_code=409, detail="Git 连接不可用")
    provider = create_git_hosting_provider(
        provider=connection.provider,
        api_origin=connection.api_origin,
        api_token=GitCredentialOwner().decrypt(token),
        ssh_host=connection.ssh_host,
        ssh_port=connection.ssh_port,
    )
    return provider, connection


async def list_resource_branches(*, uid: str, project_id: str, repository_id: str, db):
    """返回真实远端分支供配置选择。"""
    _, binding, store = await get_resource_context(uid=uid, project_id=project_id, repository_id=repository_id, db=db)
    provider, _ = await get_resource_provider(binding, store)
    return await provider.list_branches(binding.repository_owner, binding.repository_name)


async def configure_project_git_resource(
    *,
    uid: str,
    project_id: str,
    repository_id: str,
    checkout_path: str,
    branch: str,
    usage_mode: str,
    approval_mode: str,
    db,
):
    """检查空目标目录及真实分支后配置资源，已有 checkout 不原地覆盖。"""
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    try:
        relative = normalize_resource_path(checkout_path)
        branch = normalize_base_branch(branch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if usage_mode not in {"in_place", "worktree"} or approval_mode not in {"automatic", "protected"}:
        raise HTTPException(status_code=422, detail="资源使用或授权模式非法")
    slots = await store.occupancies(binding.id, uid)
    if slots and (binding.usage_mode != usage_mode or binding.approval_mode != approval_mode):
        raise HTTPException(status_code=409, detail="资源仍有占用或等待任务，请先释放后再修改模式")
    if binding.checkout_head_sha is not None:
        if binding.checkout_path != relative or binding.configured_base_branch != branch:
            raise HTTPException(status_code=409, detail="已检出资源的目录与分支固定，请添加另一条资源")
    for other in await store.list_project_bindings(project_id, uid):
        if other.id == binding.id or other.status == "disabled" or not other.checkout_path:
            continue
        parts = PurePosixPath(relative).parts
        other_parts = PurePosixPath(other.checkout_path).parts
        if parts[: len(other_parts)] == other_parts or other_parts[: len(parts)] == parts:
            raise HTTPException(status_code=409, detail="资源目录与其他资源重叠")
    provider, _ = await get_resource_provider(binding, store)
    await provider.get_branch(binding.repository_owner, binding.repository_name, branch)
    if binding.checkout_head_sha is None:
        with open_resource_checkout(uid, project.workdir_path, relative, create=True) as (path, _):
            if any(path.iterdir()):
                raise HTTPException(status_code=409, detail="目标目录已有内容，请选择空目录")
    binding.checkout_path = relative
    binding.configured_base_branch = branch
    binding.allowed_base_branches = sorted(set([*(binding.allowed_base_branches or []), branch]))
    binding.usage_mode = usage_mode
    binding.approval_mode = approval_mode
    binding.updated_at = utc_now_naive()
    await db.commit()
    return binding.to_dict()


async def prepare_project_git_resource(*, uid: str, project_id: str, repository_id: str, db):
    """把所选分支完整检出到资源目录，保留已有内容与可信 HEAD。"""
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    if not binding.checkout_path:
        raise HTTPException(status_code=409, detail="请先配置项目资源目录")
    if not binding.checkout_head_sha:
        await guard_git_directory_initialization(db=db, uid=uid)
    metadata = resource_metadata_path(binding.id)
    provider, connection = await get_resource_provider(binding, store)
    branch = binding.configured_base_branch or binding.default_branch
    await provider.get_branch(binding.repository_owner, binding.repository_name, branch)
    credential = await store.get_credential(binding.deploy_private_credential_id, uid)
    if credential is None:
        raise HTTPException(status_code=409, detail="仓库凭据不可用")
    bundle = await GitExecutor().fetch_remote_bundle(
        remote_url=binding.canonical_ssh_url,
        private_key=GitCredentialOwner().decrypt(credential),
        known_hosts=connection.ssh_known_host_key,
    )
    try:
        with open_resource_checkout(uid, project.workdir_path, binding.checkout_path, create=True) as (path, executor):
            if metadata.exists() and binding.checkout_head_sha:
                result = await executor.review(metadata=metadata, checkout=path, branch=branch)
            else:
                result = await executor.prepare(metadata=metadata, checkout=path, branch=branch, bundle=bundle)
        binding.checkout_head_sha = result["head_sha"]
        binding.updated_at = utc_now_naive()
        await db.commit()
        return {**binding.to_dict(), "review": result}
    finally:
        bundle.unlink(missing_ok=True)


async def review_project_git_resource(*, uid: str, project_id: str, repository_id: str, db):
    """读取资源当前可审查内容，缺失文件或可信元数据时显式失败。"""
    project, binding, _ = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True, allow_incomplete=True
    )
    if not binding.checkout_path:
        raise HTTPException(status_code=409, detail="资源尚未检出")
    with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
        metadata = resource_metadata_path(binding.id)
        branch = binding.configured_base_branch if binding.checkout_head_sha else executor.prepared_branch(metadata)
        result = await executor.review(metadata=metadata, checkout=path, branch=branch)
        return {**result, "incomplete_checkout": not bool(binding.checkout_head_sha)}


async def commit_project_git_resource(
    *,
    uid: str,
    project_id: str,
    repository_id: str,
    expected_head: str,
    expected_tree: str,
    message: str,
    db,
):
    """由已认证用户确认资源提交，智能体没有直接修改可信元数据的入口。"""
    project, binding, _ = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    if not message.strip() or len(message) > 2000:
        raise HTTPException(status_code=422, detail="请填写 1 到 2000 字的提交说明")
    if not binding.checkout_head_sha:
        raise HTTPException(status_code=409, detail="资源尚未检出")
    with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
        result = await executor.commit(
            metadata=resource_metadata_path(binding.id),
            checkout=path,
            branch=binding.configured_base_branch,
            expected_head=expected_head,
            expected_tree=expected_tree,
            message=message.strip(),
        )
    binding.checkout_head_sha = result["head_sha"]
    binding.updated_at = utc_now_naive()
    await db.commit()
    return result


async def push_project_git_resource(
    *, uid: str, project_id: str, repository_id: str, expected_head: str, expected_tree: str, db
):
    """人工确认无未提交修改的精确 HEAD，推送并回读远端事实。"""
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    if not binding.checkout_head_sha:
        raise HTTPException(status_code=409, detail="资源尚未检出")
    connection = await store.get_connection(binding.connection_id, uid, active_only=True)
    credential = await store.get_credential(binding.deploy_private_credential_id, uid)
    if connection is None or credential is None or not binding.canonical_ssh_url:
        raise HTTPException(status_code=409, detail="远端推送连接或凭据不可用")
    metadata = resource_metadata_path(binding.id)
    with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
        review = await executor.review(metadata=metadata, checkout=path, branch=binding.configured_base_branch)
        if review["dirty"] or review["head_sha"] != expected_head or review["tree_sha"] != expected_tree:
            raise HTTPException(status_code=409, detail="资源存在未提交改动或审查快照已变化，请刷新并确认")
        pushed = await GitExecutor().push_commit(
            bare_path=metadata,
            expected_sha=expected_head,
            branch=binding.configured_base_branch,
            remote_url=binding.canonical_ssh_url,
            private_key=GitCredentialOwner().decrypt(credential),
            known_hosts=connection.ssh_known_host_key,
        )
        await executor.record_remote_head(
            bare_path=metadata, branch=binding.configured_base_branch, verified_sha=pushed
        )
        result = await executor.review(metadata=metadata, checkout=path, branch=binding.configured_base_branch)
    for allocation in await store.list_project_worktrees(project_id, uid):
        if allocation.repository_id == binding.id and allocation.usage_mode == "in_place":
            allocation.last_pushed_sha = pushed
    await db.commit()
    return {**result, "pushed_sha": pushed}


async def discard_project_git_resource(
    *,
    uid: str,
    project_id: str,
    repository_id: str,
    expected_head: str,
    expected_tree: str,
    db,
):
    """人工确认并在根运行停止后清理未提交内容，持续占用另行释放。"""
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True, allow_incomplete=True
    )
    if not binding.checkout_path:
        raise HTTPException(status_code=409, detail="资源尚未检出")
    if not binding.checkout_head_sha:
        await guard_git_directory_initialization(db=db, uid=uid)
    for slot in await store.occupancies(binding.id, uid):
        if await store.active_root_run(slot.active_run_id, uid):
            raise HTTPException(status_code=409, detail="资源仍有执行中的根运行或子智能体，不能清理")
    with open_resource_checkout(uid, project.workdir_path, binding.checkout_path) as (path, executor):
        metadata = resource_metadata_path(binding.id)
        branch = binding.configured_base_branch if binding.checkout_head_sha else executor.prepared_branch(metadata)
        return await executor.discard(
            metadata=metadata,
            checkout=path,
            branch=branch,
            expected_head=expected_head,
            expected_tree=expected_tree,
        )
