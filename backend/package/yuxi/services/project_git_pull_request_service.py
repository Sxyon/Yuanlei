"""用户在项目内创建、查看和实际合并 Gitea 合并请求。"""

from fastapi import HTTPException

from yuxi.services.project_git_resource_service import get_resource_context, get_resource_provider


async def resource_pull_request_context(*, uid, project_id, repository_id, db, lock=False):
    """源分支必须是当前资源持久分配的任务分支，目标属于资源或父任务。"""
    project, binding, store = await get_resource_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=lock
    )
    allocations = {
        value.branch_name: value
        for value in await store.list_project_worktrees(project_id, uid)
        if value.repository_id == repository_id and value.branch_name != binding.configured_base_branch
    }
    provider, _ = await get_resource_provider(binding, store)
    return project, binding, allocations, provider


def verify_resource_pull_request(binding, allocations, value):
    """拒绝外部 fork、其他资源分支和未受项目管理的目标分支。"""
    if (
        value["head_repository_id"] != binding.remote_repository_id
        or value["base_repository_id"] != binding.remote_repository_id
        or value["head_branch"] not in allocations
        or value["base_branch"] not in {binding.configured_base_branch, *allocations}
    ):
        raise HTTPException(status_code=409, detail="合并请求的仓库、源分支或目标分支不属于当前项目资源")


async def list_resource_pull_requests(*, uid, project_id, repository_id, db):
    """从 Gitea 回读已分配任务分支的合并请求状态。"""
    _, binding, allocations, provider = await resource_pull_request_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db
    )
    values = await provider.list_pull_requests(binding.repository_owner, binding.repository_name)
    result = []
    for value in values:
        if value["head_branch"] not in allocations:
            continue
        if (
            value["head_repository_id"] != binding.remote_repository_id
            or value["base_repository_id"] != binding.remote_repository_id
            or value["base_branch"] not in {binding.configured_base_branch, *allocations}
        ):
            continue
        if not value["merged"] and value["state"] == "open":
            target = await provider.get_branch(binding.repository_owner, binding.repository_name, value["base_branch"])
            value = {**value, "base_sha": target.commit_sha}
        result.append(value)
    return result


async def create_resource_pull_request(*, uid, project_id, repository_id, head_branch, base_branch, title, body, db):
    """用户明确选择已推送任务分支及资源目标后创建真实合并请求。"""
    _, binding, allocations, provider = await resource_pull_request_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    if head_branch not in allocations or base_branch not in {binding.configured_base_branch, *allocations}:
        raise HTTPException(status_code=409, detail="请选择当前资源分配的任务分支及合法目标分支")
    if head_branch == base_branch or not title.strip():
        raise HTTPException(status_code=422, detail="源分支与目标分支必须不同，并填写标题")
    allocation = allocations[head_branch]
    remote = await provider.get_branch(binding.repository_owner, binding.repository_name, head_branch)
    if not allocation.last_pushed_sha or remote.commit_sha != allocation.last_pushed_sha:
        raise HTTPException(status_code=409, detail="任务分支尚未推送或远端 HEAD 已变化，请先查看并推送当前结果")
    value = await provider.create_pull_request(
        binding.repository_owner,
        binding.repository_name,
        head=head_branch,
        base=base_branch,
        title=title.strip(),
        body=body,
    )
    verify_resource_pull_request(binding, allocations, value)
    target = await provider.get_branch(binding.repository_owner, binding.repository_name, value["base_branch"])
    return {**value, "base_sha": target.commit_sha}


async def merge_resource_pull_request(*, uid, project_id, repository_id, number, expected_head, expected_base, db):
    """确认源 HEAD 与合并前目标状态；源由远端 CAS 校验，目标不能原子锁定。"""
    _, binding, allocations, provider = await resource_pull_request_context(
        uid=uid, project_id=project_id, repository_id=repository_id, db=db, lock=True
    )
    value = await provider.get_pull_request(binding.repository_owner, binding.repository_name, number)
    verify_resource_pull_request(binding, allocations, value)
    if value["merged"]:
        return value
    target = await provider.get_branch(binding.repository_owner, binding.repository_name, value["base_branch"])
    if value["head_sha"] != expected_head or target.commit_sha != expected_base:
        raise HTTPException(status_code=409, detail="合并请求的源或目标 HEAD 已变化，请刷新并重新确认")
    if value["state"] != "open" or value["mergeable"] is not True:
        raise HTTPException(status_code=409, detail="合并请求未开放、存在冲突或状态尚未就绪")
    return await provider.merge_pull_request(
        binding.repository_owner,
        binding.repository_name,
        number,
        head_sha=expected_head,
    )
