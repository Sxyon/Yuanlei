"""项目蓝图文档的 HTTP 适配层（yuanlei 域扩展）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_blueprint_service import (
    archive_project_blueprint_view,
    create_project_blueprint_view,
    get_project_blueprint_archive_view,
    get_project_blueprint_view,
    list_project_blueprint_archives_view,
    list_project_blueprint_view,
    put_project_blueprint_view,
)
from yuxi.storage.postgres.models_business import User

project_blueprints = APIRouter(prefix="/projects/{project_id}/blueprint", tags=["project-blueprint"])


class ProjectBlueprintWrite(BaseModel):
    """创建或替换蓝图文档请求。"""

    model_config = ConfigDict(extra="forbid")

    content: str


class ProjectBlueprintCreate(ProjectBlueprintWrite):
    """新建蓝图请求，名称由前端补全为受控 Markdown 文件名。"""

    name: str


@project_blueprints.get("")
async def list_project_blueprint(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出 Project Workdir 固定蓝图目录内的文档。"""
    return await list_project_blueprint_view(project_id=project_id, db=db, user=current_user)


@project_blueprints.post("", status_code=201)
async def create_project_blueprint(
    project_id: str,
    payload: ProjectBlueprintCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """独占创建蓝图文件，同名文件返回 409。"""
    try:
        return await create_project_blueprint_view(
            project_id=project_id,
            name=payload.name,
            content=payload.content,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_blueprints.get("/history")
async def list_project_blueprint_archives(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出可回顾的蓝图归档。"""
    return await list_project_blueprint_archives_view(project_id=project_id, db=db, user=current_user)


@project_blueprints.get("/history/{archive_name}")
async def get_project_blueprint_archive(
    project_id: str,
    archive_name: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """回读单份归档蓝图。"""
    try:
        return await get_project_blueprint_archive_view(
            project_id=project_id,
            archive_name=archive_name,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_blueprints.get("/{name}")
async def get_project_blueprint(
    project_id: str,
    name: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取单个蓝图文档。"""
    try:
        return await get_project_blueprint_view(project_id=project_id, name=name, db=db, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_blueprints.put("/{name}")
async def put_project_blueprint(
    project_id: str,
    name: str,
    payload: ProjectBlueprintWrite,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """创建或整体替换蓝图文档。"""
    try:
        return await put_project_blueprint_view(
            project_id=project_id,
            name=name,
            content=payload.content,
            db=db,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@project_blueprints.post("/{name}/archive")
async def archive_project_blueprint(
    project_id: str,
    name: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """归档整份当前蓝图，保留可回读文件。"""
    try:
        return await archive_project_blueprint_view(project_id=project_id, name=name, db=db, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
