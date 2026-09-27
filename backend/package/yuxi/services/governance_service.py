"""元垒项目治理用例：来源归一化、proposed→审核→canonical 生命周期与归属校验。

渠道（项目内 / Multica / GitHub / Gitea）只能创建 proposed 议题/任务；只有审核动作
写入审核责任人与时间后才成为 canonical，外部镜像没有直接写 canonical 的入口。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import (
    GOVERNANCE_SOURCE_CHANNELS,
    GovernanceDecision,
    GovernanceReport,
    GovernanceTask,
    GovernanceTopic,
    Project,
    User,
)
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

MAX_TITLE_LENGTH = 512
MAX_TOPIC_TEXT_LENGTH = 100_000


def normalize_title(title: str) -> str:
    """校验并归一议题/任务标题。"""
    normalized = str(title or "").strip()
    if not normalized or len(normalized) > MAX_TITLE_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_title", "message": f"标题长度必须为 1-{MAX_TITLE_LENGTH}"},
        )
    return normalized


def _normalize_topic_text(content: str | None, *, required: bool) -> str | None:
    """校验议题正文或回复，保留 Markdown 并限制单篇大小。"""
    normalized = str(content or "").strip()
    if required and not normalized:
        raise HTTPException(status_code=422, detail={"code": "invalid_comment", "message": "回复内容不能为空"})
    if len(normalized) > MAX_TOPIC_TEXT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={"code": "topic_text_too_long", "message": f"正文不能超过 {MAX_TOPIC_TEXT_LENGTH} 个字符"},
        )
    return normalized or None


def normalize_governance_source(
    *,
    source_channel: str | None,
    source_external_id: str | None,
    source_url: str | None,
) -> tuple[str, str | None, str | None]:
    """校验来源渠道与外部标识的组合，返回归一化三元组。

    项目内来源不携带外部标识与链接；外部渠道必须带非空外部标识。
    """
    channel = str(source_channel or "").strip()
    if channel not in GOVERNANCE_SOURCE_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_source",
                "message": f"来源渠道必须是 {list(GOVERNANCE_SOURCE_CHANNELS)} 之一",
            },
        )
    external_id = str(source_external_id).strip() if source_external_id else None
    url = str(source_url).strip() if source_url else None
    if channel == "project":
        if external_id or url:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_source", "message": "项目内来源不得携带外部标识或链接"},
            )
        return channel, None, None
    if not external_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_source", "message": "外部来源必须携带外部标识"},
        )
    return channel, external_id, url


def _source_payload(row: GovernanceTopic | GovernanceTask) -> dict[str, Any]:
    return {
        "channel": row.source_channel,
        "external_id": row.source_external_id,
        "url": row.source_url,
    }


def _review_payload(row: GovernanceTopic | GovernanceTask) -> dict[str, Any]:
    return {
        "owner_uid": row.review_owner_uid,
        "reviewed_at": format_utc_datetime(row.reviewed_at),
        "note": row.review_note,
    }


def _serialize_topic(row: GovernanceTopic) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "summary": row.summary,
        "status": row.status,
        "source": _source_payload(row),
        "review": _review_payload(row),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _serialize_topic_comment(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "topic_id": row.topic_id,
        "content": row.content,
        "author_name": row.author_name,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
    }


def _serialize_task(row: GovernanceTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "topic_id": row.topic_id,
        "decision_id": row.decision_id,
        "assignee_agent_slug": row.assignee_agent_slug,
        "source": _source_payload(row),
        "review": _review_payload(row),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _serialize_decision(row: GovernanceDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "topic_id": row.topic_id,
        "title": row.title,
        "conclusion": row.conclusion,
        "rationale": row.rationale,
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_at": format_utc_datetime(row.decided_at),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _serialize_report(row: GovernanceReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "summary": row.summary,
        "content": row.content or {},
        "source_run_id": row.source_run_id,
        "artifact_path": row.artifact_path,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


async def _require_project(*, project_id: str, db: AsyncSession, user: User) -> Project:
    """只在当前用户可管理的 active selectable Project 上操作，否则 404。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return project


async def create_governance_topic(
    *,
    project_id: str,
    title: str,
    summary: str | None,
    source_channel: str | None,
    source_external_id: str | None,
    source_url: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """来源归一化创建一个 proposed 议题；重复外部标识拒绝。"""
    normalized_title = normalize_title(title)
    channel, external_id, url = normalize_governance_source(
        source_channel=source_channel,
        source_external_id=source_external_id,
        source_url=source_url,
    )
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    if external_id is not None and await repo.find_topic_by_source(
        project_id=project.id, source_channel=channel, source_external_id=external_id
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_source", "source_channel": channel, "external_id": external_id},
        )
    row = await repo.add_topic(
        project_id=project.id,
        title=normalized_title,
        summary=_normalize_topic_text(summary, required=False),
        source_channel=channel,
        source_external_id=external_id,
        source_url=url,
        operator=str(user.uid),
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_topic(row)


async def list_governance_topics(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> list[dict[str, Any]]:
    """读取当前用户项目下的议题列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_topics(project_id=project.id)
    return [_serialize_topic(row) for row in rows]


async def get_governance_topic(
    *,
    project_id: str,
    topic_id: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """读取当前用户项目下的单个议题。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    row = await GovernanceRepository(db).get_topic(topic_id=topic_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    return _serialize_topic(row)


async def update_governance_topic(
    *,
    project_id: str,
    topic_id: str,
    title: str,
    summary: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """只允许更新仍待审议议题的标题与 Markdown 正文。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.get_topic_for_update(topic_id=topic_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    if row.status != "proposed":
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "status": row.status})
    row.title = normalize_title(title)
    row.summary = _normalize_topic_text(summary, required=False)
    await db.commit()
    await db.refresh(row)
    return _serialize_topic(row)


async def list_governance_topic_comments(
    *,
    project_id: str,
    topic_id: str,
    db: AsyncSession,
    user: User,
) -> list[dict[str, Any]]:
    """读取项目议题讨论串；审核后的议题仍可回看。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    topic = await repo.get_topic(topic_id=topic_id)
    if topic is None or topic.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    rows = await repo.list_topic_comments(topic_id=topic.id)
    return [_serialize_topic_comment(row) for row in rows]


async def create_governance_topic_comment(
    *,
    project_id: str,
    topic_id: str,
    content: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """在待审议议题下追加回复，并与审核共享议题行锁。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    topic = await repo.get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    if topic.status != "proposed":
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "status": topic.status})
    normalized_content = _normalize_topic_text(content, required=True)
    row = await repo.add_topic_comment(
        topic_id=topic.id,
        content=normalized_content or "",
        author_name=user.username,
        operator=str(user.uid),
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_topic_comment(row)


async def review_governance_topic(
    *,
    project_id: str,
    topic_id: str,
    approve: bool,
    review_note: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """审核 proposed 议题：写入审核责任人后落为 canonical 或 rejected。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.get_topic_for_update(topic_id=topic_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    if row.status != "proposed":
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_state", "status": row.status},
        )
    row.status = "canonical" if approve else "rejected"
    row.review_owner_uid = str(user.uid)
    row.reviewed_at = utc_now_naive()
    row.review_note = review_note
    await db.commit()
    await db.refresh(row)
    return _serialize_topic(row)


async def create_governance_task(
    *,
    project_id: str,
    title: str,
    description: str | None,
    topic_id: str | None,
    decision_id: str | None,
    assignee_agent_slug: str | None,
    source_channel: str | None,
    source_external_id: str | None,
    source_url: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """来源归一化创建一个 proposed 任务；重复外部标识与越界指派拒绝。"""
    normalized_title = normalize_title(title)
    channel, external_id, url = normalize_governance_source(
        source_channel=source_channel,
        source_external_id=source_external_id,
        source_url=source_url,
    )
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    if topic_id is not None:
        topic = await repo.get_topic(topic_id=topic_id)
        if topic is None or topic.project_id != project.id:
            raise HTTPException(status_code=404, detail="来源议题不存在")
    if decision_id is not None:
        decision = await repo.get_decision(decision_id=decision_id)
        if decision is None or decision.project_id != project.id:
            raise HTTPException(status_code=404, detail="来源决策不存在")
    if assignee_agent_slug is not None:
        binding = await ProjectAgentRepository(db).get(project.id, assignee_agent_slug)
        if binding is None:
            raise HTTPException(status_code=404, detail="指派数字员工未绑定该项目")
    if external_id is not None and await repo.find_task_by_source(
        project_id=project.id, source_channel=channel, source_external_id=external_id
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_source", "source_channel": channel, "external_id": external_id},
        )
    row = await repo.add_task(
        project_id=project.id,
        title=normalized_title,
        description=description,
        topic_id=topic_id,
        decision_id=decision_id,
        assignee_agent_slug=assignee_agent_slug,
        source_channel=channel,
        source_external_id=external_id,
        source_url=url,
        operator=str(user.uid),
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_task(row)


async def list_governance_tasks(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> list[dict[str, Any]]:
    """读取当前用户项目下的任务列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_tasks(project_id=project.id)
    return [_serialize_task(row) for row in rows]


async def review_governance_task(
    *,
    project_id: str,
    task_id: str,
    approve: bool,
    review_note: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """审核 proposed 任务：写入审核责任人后落为 canonical 或 rejected。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.get_task_for_update(task_id=task_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status != "proposed":
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "status": row.status})
    row.status = "canonical" if approve else "rejected"
    row.review_owner_uid = str(user.uid)
    row.reviewed_at = utc_now_naive()
    row.review_note = review_note
    await db.commit()
    await db.refresh(row)
    return _serialize_task(row)


async def create_governance_decision(
    *,
    project_id: str,
    title: str,
    conclusion: str,
    rationale: str | None,
    topic_id: str | None,
    decided: bool,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """记录人拍板决策；decided 为真时落为 implemented。"""
    normalized_title = normalize_title(title)
    normalized_conclusion = str(conclusion or "").strip()
    if not normalized_conclusion:
        raise HTTPException(status_code=422, detail={"code": "invalid_conclusion", "message": "结论不能为空"})
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    if topic_id is not None:
        topic = await repo.get_topic(topic_id=topic_id)
        if topic is None or topic.project_id != project.id:
            raise HTTPException(status_code=404, detail="来源议题不存在")
    row = await repo.add_decision(
        project_id=project.id,
        title=normalized_title,
        conclusion=normalized_conclusion,
        rationale=rationale,
        topic_id=topic_id,
        decided=decided,
        operator=str(user.uid),
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_decision(row)


async def create_governance_report(
    *,
    project_id: str,
    title: str,
    summary: str | None,
    content: Any,
    source_run_id: str | None,
    artifact_path: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """记录由定时任务产出的汇报；只引用 Run/artifact，不复制其终态。"""
    normalized_title = normalize_title(title)
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.add_report(
        project_id=project.id,
        title=normalized_title,
        summary=summary,
        content=content if content is not None else {},
        source_run_id=source_run_id,
        artifact_path=artifact_path,
        operator=str(user.uid),
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_report(row)


async def list_governance_reports(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> list[dict[str, Any]]:
    """读取当前用户项目下的汇报列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_reports(project_id=project.id)
    return [_serialize_report(row) for row in rows]


async def list_governance_decisions(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> list[dict[str, Any]]:
    """读取当前用户项目下的决策列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_decisions(project_id=project.id)
    return [_serialize_decision(row) for row in rows]
