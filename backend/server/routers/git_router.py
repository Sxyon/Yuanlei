"""用户级 Git connection HTTP 适配层。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_git_service import (
    create_git_connection_view,
    delete_git_connection_view,
    list_git_connections_view,
    rotate_git_connection_credential_view,
)
from yuxi.storage.postgres.models_business import User

git = APIRouter(prefix="/git", tags=["git"])


class GitConnectionCreate(BaseModel):
    """Gitea connection 创建请求。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    provider: str
    api_origin: str
    ssh_host: str
    ssh_port: int = Field(ge=1, le=65535)
    ssh_known_host_key: str = Field(min_length=1, max_length=8192)
    api_token: str = Field(min_length=1, max_length=4096)


class GitCredentialUpdate(BaseModel):
    """write-only Gitea Token 更新请求。"""

    model_config = ConfigDict(extra="forbid")
    api_token: str = Field(min_length=1, max_length=4096)


@git.get("/connections")
async def list_git_connections(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """列出当前用户 Git connections。"""
    return await list_git_connections_view(uid=str(current_user.uid), db=db)


@git.post("/connections")
async def create_git_connection(
    request: Request,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """验证并创建 Gitea connection。"""
    payload = await _parse_secret_payload(request, GitConnectionCreate)
    return await create_git_connection_view(uid=str(current_user.uid), db=db, **payload.model_dump())


@git.put("/connections/{connection_id}/credential")
async def rotate_git_connection_credential(
    connection_id: str,
    request: Request,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """替换 connection 的 write-only Token。"""
    payload = await _parse_secret_payload(request, GitCredentialUpdate)
    return await rotate_git_connection_credential_view(
        uid=str(current_user.uid), connection_id=connection_id, api_token=payload.api_token, db=db
    )


@git.delete("/connections/{connection_id}")
async def delete_git_connection(
    connection_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """停用未被使用的 Git connection。"""
    return await delete_git_connection_view(uid=str(current_user.uid), connection_id=connection_id, db=db)


async def _parse_secret_payload(request: Request, model_type):
    """解析含 write-only secret 的请求，任何校验错误都返回固定脱敏信息。"""
    try:
        payload = await request.json()
        return model_type.model_validate(payload)
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(status_code=422, detail="Git connection 请求非法") from None
