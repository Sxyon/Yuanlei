"""通过用户自己的 Git 连接读取绑定候选，不持久化远端目录。"""

import httpx
from fastapi import HTTPException

from yuxi.git.credentials import GitCredentialOwner
from yuxi.git.hosting import create_git_hosting_provider
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore


async def connection_discovery_provider(*, uid: str, connection_id: str, db):
    """只允许连接所有者解密凭据，远端调用前释放只读事务。"""
    store = ProjectGitRepositoryStore(db)
    connection = await store.get_connection(connection_id, uid, active_only=True)
    if connection is None:
        raise HTTPException(status_code=404, detail="Git 连接不存在")
    credential = await store.get_credential(connection.api_token_credential_id, uid)
    if credential is None:
        raise HTTPException(status_code=409, detail="Git 连接凭据不可用")
    provider = create_git_hosting_provider(
        provider=connection.provider,
        api_origin=connection.api_origin,
        api_token=GitCredentialOwner().decrypt(credential),
        ssh_host=connection.ssh_host,
        ssh_port=connection.ssh_port,
    )
    await db.commit()
    return provider


async def list_connection_repositories(*, uid: str, connection_id: str, db):
    """返回当前连接 Token 可访问的仓库列表。"""
    provider = await connection_discovery_provider(uid=uid, connection_id=connection_id, db=db)
    try:
        return await provider.list_repositories()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="无法读取 Gitea 仓库，请检查连接与 Token 的仓库读取权限") from exc


async def list_connection_branches(*, uid: str, connection_id: str, owner: str, name: str, db):
    """在绑定前读取所选仓库分支，绑定操作仍独立校验远端身份。"""
    provider = await connection_discovery_provider(uid=uid, connection_id=connection_id, db=db)
    try:
        return await provider.list_branches(owner, name)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="无法读取 Gitea 分支，请检查仓库是否存在及读取权限") from exc
