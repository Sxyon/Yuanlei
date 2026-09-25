"""元垒项目治理与督查板的 HTTP 适配层（yuanlei 域扩展）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.governance_service import (
    create_governance_report,
    create_governance_topic,
    review_governance_task,
    review_governance_topic,
)
from yuxi.services.inspection_board_service import (
    get_project_inspection_board,
    get_user_inspection_board,
)
from yuxi.storage.postgres.models_business import User

governance = APIRouter(tags=["governance"])


class GovernanceTopicCreate(BaseModel):
    """来源归一化创建 proposed 议题请求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=512)
    summary: str | None = None
    source_channel: str = Field(..., max_length=32)
    source_external_id: str | None = Field(None, max_length=191)
    source_url: str | None = Field(None, max_length=1024)


class GovernanceReview(BaseModel):
    """审核 proposed 议题/任务请求。"""

    model_config = ConfigDict(extra="forbid")

    approve: bool
    review_note: str | None = None


class GovernanceReportCreate(BaseModel):
    """记录定时任务产出汇报的请求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=512)
    summary: str | None = None
    content: dict[str, Any] | None = None
    source_run_id: str | None = Field(None, max_length=64)
    artifact_path: str | None = Field(None, max_length=512)


@governance.get("/projects/{project_id}/governance/board")
async def get_project_board(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取单个 Project 的督查板只读视图；不可见项目 404。"""
    return await get_project_inspection_board(project_id=project_id, db=db, user=current_user)


@governance.get("/governance/board")
async def get_cross_project_board(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """跨 Project 读取当前用户的 open 议题、待决策队列与阻塞项。"""
    return await get_user_inspection_board(db=db, user=current_user)


@governance.post("/projects/{project_id}/governance/topics")
async def create_topic(
    project_id: str,
    payload: GovernanceTopicCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """来源归一化创建一个 proposed 议题。"""
    return await create_governance_topic(
        project_id=project_id,
        title=payload.title,
        summary=payload.summary,
        source_channel=payload.source_channel,
        source_external_id=payload.source_external_id,
        source_url=payload.source_url,
        db=db,
        user=current_user,
    )


@governance.post("/projects/{project_id}/governance/topics/{topic_id}/review")
async def review_topic(
    project_id: str,
    topic_id: str,
    payload: GovernanceReview,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人审核议题，写入审核责任人后落为 canonical 或 rejected。"""
    return await review_governance_topic(
        project_id=project_id,
        topic_id=topic_id,
        approve=payload.approve,
        review_note=payload.review_note,
        db=db,
        user=current_user,
    )


@governance.post("/projects/{project_id}/governance/tasks/{task_id}/review")
async def review_task(
    project_id: str,
    task_id: str,
    payload: GovernanceReview,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """人审核任务，写入审核责任人后落为 canonical 或 rejected。"""
    return await review_governance_task(
        project_id=project_id,
        task_id=task_id,
        approve=payload.approve,
        review_note=payload.review_note,
        db=db,
        user=current_user,
    )


@governance.post("/projects/{project_id}/governance/reports")
async def create_report(
    project_id: str,
    payload: GovernanceReportCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """记录一份引用 Run 与 artifact 的汇报，不复制 Run 终态。"""
    return await create_governance_report(
        project_id=project_id,
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        source_run_id=payload.source_run_id,
        artifact_path=payload.artifact_path,
        db=db,
        user=current_user,
    )
