"""编码执行器凭据的 HTTP 表面：用户级与管理员全局。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.coding.credentials import CodingNotConfiguredError
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialWrite,
    mask_credential,
)
from yuxi.storage.postgres.models_business import User

user_coding_credentials = APIRouter(prefix="/user/coding-credentials", tags=["coding-credentials"])
admin_coding_credentials = APIRouter(prefix="/system/coding-credentials", tags=["coding-credentials"])


class CodingCredentialPayload(BaseModel):
    """write-only 凭据写入请求；引用模式可不携带 api_key。"""

    model_config = ConfigDict(extra="forbid")
    executor: str = Field(min_length=1, max_length=16)
    provider: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=8192)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=255)
    extra: dict | None = None
    source: str = Field(default="manual", max_length=16)
    model_provider_id: str | None = Field(default=None, max_length=100)
    key_mode: str | None = Field(default=None, max_length=16)


async def _parse_payload(request: Request) -> CodingCredentialPayload:
    """解析含 write-only secret 的请求，任何校验错误都返回固定脱敏信息。"""
    try:
        payload = await request.json()
        return CodingCredentialPayload.model_validate(payload)
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(status_code=422, detail="编码凭据请求非法") from None


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CodingNotConfiguredError):
        return HTTPException(
            status_code=503,
            detail=(
                "编码凭据加密未配置或无效：请在 .env 设置 YUXI_CODING_CREDENTIAL_KEY"
                "（32 字节 base64url，可运行 `bash scripts/init.sh` 生成），并执行 docker compose up -d --force-recreate api worker（restart 不会刷新环境变量）"
            ),
        )
    # 服务层 ValueError 只包含非密校验原因（供应商/模型/模式），直接回显便于前端提示。
    return HTTPException(status_code=422, detail=str(exc) or "编码凭据请求非法")


@user_coding_credentials.get("")
async def list_user_coding_credentials(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await CodingCredentialService(db).list_masked(scope="user", uid=str(current_user.uid))


@user_coding_credentials.get("/model-providers")
async def list_user_model_provider_options(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """用户可见的掩码供应商选择器：只含 provider_id/名称/base_url/chat 模型。"""
    return await CodingCredentialService(db).list_model_provider_options()


@user_coding_credentials.put("")
async def upsert_user_coding_credential(
    request: Request,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    payload = await _parse_payload(request)
    service = CodingCredentialService(db)
    try:
        row = await service.upsert(
            scope="user",
            uid=str(current_user.uid),
            payload=CodingCredentialWrite(**payload.model_dump()),
            actor=str(current_user.uid),
        )
    except (ValueError, CodingNotConfiguredError) as exc:
        raise _service_error(exc) from None
    return mask_credential(row)


@user_coding_credentials.delete("")
async def delete_user_coding_credential(
    executor: str,
    provider: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await CodingCredentialService(db).delete(
        scope="user",
        uid=str(current_user.uid),
        executor=executor,
        provider=provider,
        actor=str(current_user.uid),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="编码凭据不存在")
    return {"success": True}


@admin_coding_credentials.get("")
async def list_global_coding_credentials(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await CodingCredentialService(db).list_masked(scope="global")


@admin_coding_credentials.put("")
async def upsert_global_coding_credential(
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    payload = await _parse_payload(request)
    service = CodingCredentialService(db)
    try:
        row = await service.upsert(
            scope="global",
            uid=None,
            payload=CodingCredentialWrite(**payload.model_dump()),
            actor=str(current_user.uid),
        )
    except (ValueError, CodingNotConfiguredError) as exc:
        raise _service_error(exc) from None
    return mask_credential(row)


@admin_coding_credentials.delete("")
async def delete_global_coding_credential(
    executor: str,
    provider: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await CodingCredentialService(db).delete(
        scope="global",
        uid=None,
        executor=executor,
        provider=provider,
        actor=str(current_user.uid),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="编码凭据不存在")
    return {"success": True}
