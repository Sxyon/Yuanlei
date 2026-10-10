"""个人协作者连接与目标的薄HTTP边界。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.repositories.collaborator_repository import CollaboratorRepository
from yuxi.services.collaborator_service import CollaboratorService
from yuxi.storage.postgres.models_business import User
from yuxi.delegation.contracts import DelegationError

collaborators = APIRouter(prefix="/collaborators", tags=["collaborators"])


class ConnectionInput(BaseModel):
    """本人连接的有限配置与秘密输入。"""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=1024)
    project_ids: list[str] = Field(max_length=32)
    token: SecretStr | None = None
    expected_revision: int | None = Field(None, ge=1)
    enabled: bool = True


class TargetInput(BaseModel):
    """目标只引用远端身份，不能自报核验成功。"""

    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=64)
    remote_identity: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=128)
    expected_revision: int | None = Field(None, ge=1)
    enabled: bool = True


async def connection_write(payload, uid, db, identifier=None):
    """委托连接用例并固定当前认证主体。"""
    values = payload.model_dump(exclude={"token"})
    try:
        return await CollaboratorService(db).save_connection(
            uid=uid, identifier=identifier, token=payload.token.get_secret_value() if payload.token else None, **values
        )
    except DelegationError as exc:
        raise HTTPException(409, detail={"code": exc.error_code}) from exc


@collaborators.post("/connections")
async def create_connection(
    payload: ConnectionInput, user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """创建本人的连接。"""
    return await connection_write(payload, str(user.uid), db)


@collaborators.put("/connections/{identifier}")
async def update_connection(
    identifier: str,
    payload: ConnectionInput,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """CAS修改或禁用本人连接。"""
    return await connection_write(payload, str(user.uid), db, identifier)


@collaborators.get("/connections")
async def list_connections(user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """只读本人连接，不输出秘密。"""
    service = CollaboratorService(db)
    return [await service.connection_view(row) for row in await service.repo.connections(str(user.uid))]


@collaborators.post("/targets")
async def create_target(
    payload: TargetInput, user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """创建固定目标，核验另行执行。"""
    return await CollaboratorService(db).save_target(uid=str(user.uid), **payload.model_dump())


@collaborators.put("/targets/{identifier}")
async def update_target(
    identifier: str, payload: TargetInput, user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """CAS修改或禁用固定目标。"""
    return await CollaboratorService(db).save_target(uid=str(user.uid), identifier=identifier, **payload.model_dump())


@collaborators.get("/connections/{identifier}/targets")
async def list_targets(identifier: str, user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """列出本人连接下的目标。"""
    repo = CollaboratorRepository(db)
    if await repo.connection(identifier, str(user.uid)) is None:
        raise HTTPException(404, detail="连接不存在")
    return [CollaboratorService.target_view(row) for row in await repo.targets(identifier, str(user.uid))]


@collaborators.post("/targets/{identifier}/check")
async def check_target(identifier: str, user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """仅执行目标与策略的公开只读核验。"""
    try:
        return await CollaboratorService(db).check_target(identifier, str(user.uid))
    except DelegationError as exc:
        raise HTTPException(409, detail={"code": exc.error_code}) from exc
