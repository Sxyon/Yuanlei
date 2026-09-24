"""项目命名 JSON 文档的 HTTP 适配层（yuanlei 域扩展）。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_document_service import (
    get_project_document_view,
    put_project_document_view,
)
from yuxi.storage.postgres.models_business import User

project_documents = APIRouter(prefix="/projects/{project_id}/documents", tags=["project-documents"])


class ProjectDocumentWrite(BaseModel):
    """创建或替换命名 JSON 文档请求。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(..., ge=0)
    content: Any


@project_documents.get("/{key}")
async def get_project_document(
    project_id: str,
    key: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取命名 JSON 文档的只读视图。"""
    try:
        return await get_project_document_view(
            project_id=project_id,
            key=key,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_documents.put("/{key}")
async def put_project_document(
    project_id: str,
    key: str,
    payload: ProjectDocumentWrite,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建或替换命名 JSON 文档；版本不一致返回 409。"""
    try:
        return await put_project_document_view(
            project_id=project_id,
            key=key,
            expected_version=payload.expected_version,
            content=payload.content,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
