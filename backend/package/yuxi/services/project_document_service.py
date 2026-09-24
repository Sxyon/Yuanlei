"""项目命名 JSON 文档用例：归属校验、key/content 约束与结构化版本冲突。"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.project_document_repository import ProjectDocumentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import Project, ProjectDocument, User
from yuxi.utils.datetime_utils import format_utc_datetime

DOCUMENT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
MAX_DOCUMENT_CONTENT_BYTES = 256 * 1024


def validate_document_key(key: str) -> str:
    """校验文档 key 的字符合集与长度。"""
    normalized = str(key or "")
    if not DOCUMENT_KEY_PATTERN.fullmatch(normalized):
        raise ValueError("文档 key 只允许小写字母、数字、点、短横线和下划线，长度 1-120")
    return normalized


def encode_document_content(content: Any) -> bytes:
    """按持久化语义序列化 JSON 内容并限制大小。"""
    try:
        encoded = json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("文档 content 必须是可序列化的 JSON") from exc
    if len(encoded) > MAX_DOCUMENT_CONTENT_BYTES:
        raise ValueError(f"文档 content 超过 {MAX_DOCUMENT_CONTENT_BYTES} 字节上限")
    return encoded


def _version_conflict(current_version: int) -> HTTPException:
    """构造携带当前版本的结构化 409。"""
    return HTTPException(
        status_code=409,
        detail={"code": "version_conflict", "current_version": current_version},
    )


def _serialize_document(row: ProjectDocument) -> dict[str, Any]:
    return {
        "key": row.key,
        "content": row.content,
        "version": int(row.version),
        "updated_at": format_utc_datetime(row.updated_at),
    }


async def _get_selectable_project(*, project_id: str, db: AsyncSession, user: User) -> Project:
    """读路径只按归属与可管理状态校验；不可见项目统一 404。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return project


async def get_project_document_view(
    *,
    project_id: str,
    key: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """读取当前用户项目下的命名 JSON 文档。"""
    normalized_key = validate_document_key(key)
    project = await _get_selectable_project(project_id=project_id, db=db, user=user)
    row = await ProjectDocumentRepository(db).get(project_id=project.id, key=normalized_key)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _serialize_document(row)


async def put_project_document_view(
    *,
    project_id: str,
    key: str,
    expected_version: int,
    content: Any,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """创建或替换文档；advisory lock 与乐观 version 共同保证不静默丢写。"""
    normalized_key = validate_document_key(key)
    encode_document_content(content)
    project = await _get_selectable_project(project_id=project_id, db=db, user=user)
    repo = ProjectDocumentRepository(db)
    await repo.lock_key(project_id=project.id, key=normalized_key)
    existing = await repo.get_for_update(project_id=project.id, key=normalized_key)
    if expected_version == 0:
        if existing is not None:
            raise _version_conflict(int(existing.version))
        row = await repo.add(
            project_id=project.id,
            key=normalized_key,
            content=content,
            operator=str(user.uid),
        )
    else:
        if existing is None:
            raise _version_conflict(0)
        if int(existing.version) != expected_version:
            raise _version_conflict(int(existing.version))
        repo.apply_content(row=existing, content=content, operator=str(user.uid))
        row = existing
    await db.commit()
    await db.refresh(row)
    return _serialize_document(row)
