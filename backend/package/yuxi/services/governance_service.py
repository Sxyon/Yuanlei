"""元垒项目治理用例：来源归一化、proposed→审核→canonical 生命周期与归属校验。

渠道（项目内 / Multica / GitHub / Gitea）只能创建 proposed 议题/任务；只有审核动作
写入审核责任人与时间后才成为 canonical，外部镜像没有直接写 canonical 的入口。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import (
    GOVERNANCE_SOURCE_CHANNELS,
    GovernanceDecision,
    GovernanceDecisionErratum,
    GovernanceReport,
    GovernanceTask,
    GovernanceTopic,
    Project,
    User,
)
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

_UNSET = object()
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


def _normalize_topic_reason(reason: str | None, *, required: bool) -> str | None:
    """校验修订或生命周期原因，使用明确的操作错误文案。"""
    normalized = _normalize_topic_text(reason, required=False)
    if required and normalized is None:
        raise HTTPException(status_code=422, detail={"code": "reason_required", "message": "请填写操作原因"})
    return normalized


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
        "admission_status": row.status,
        "progress": row.progress,
        "execution_hint": row.execution_hint,
        "archived_at": format_utc_datetime(row.archived_at),
        "deleted_at": format_utc_datetime(row.deleted_at),
        "revision_number": row.revision_number,
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
        "discussion_type": row.discussion_type,
        "revision_number": row.revision_number,
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


def _serialize_decision(row: GovernanceDecision, *, topic_execution_hint: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "topic_id": row.topic_id,
        "title": row.title,
        "conclusion": row.conclusion,
        "rationale": row.rationale,
        "status": row.status,
        "relation_type": row.relation_type,
        "target_decision_id": row.target_decision_id,
        "revision_number": row.revision_number,
        "topic_revision_number": row.topic_revision_number,
        "topic_execution_hint": topic_execution_hint,
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
    await repo.add_topic_revision(row, operator=str(user.uid), author_name=user.username, reason="创建议题")
    await repo.add_topic_event(row, kind="created", operator=str(user.uid), author_name=user.username)
    await db.commit()
    await db.refresh(row)
    return _serialize_topic(row)


async def list_governance_topics(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """读取当前用户项目下的议题列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_topics(project_id=project.id, include_archived=include_archived)
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
    expected_revision: int,
    reason: str,
) -> dict[str, Any]:
    """在同一事务保存议题当前内容与修订，拒绝并发覆盖。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.get_topic_for_update(topic_id=topic_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    _require_topic_writable(row)
    if row.revision_number != expected_revision:
        raise HTTPException(
            status_code=409, detail={"code": "revision_conflict", "message": "议题已被修改，请重新读取后保存"}
        )
    normalized_reason = _normalize_topic_reason(reason, required=True)
    row.title = normalize_title(title)
    row.summary = _normalize_topic_text(summary, required=False)
    row.revision_number += 1
    await repo.add_topic_revision(row, operator=str(user.uid), author_name=user.username, reason=normalized_reason)
    await repo.add_topic_event(
        row, kind="revised", operator=str(user.uid), author_name=user.username, reason=normalized_reason
    )
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
    topic = await repo.get_topic_for_update(topic_id=topic_id)
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
    discussion_type: str = "discussion",
) -> dict[str, Any]:
    """追加带意图与当前修订的讨论，不改变纳入及进度。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    topic = await repo.get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    row = await append_topic_discussion(repo=repo, topic=topic, user=user, content=content,
                                        discussion_type=discussion_type)
    await db.commit()
    await db.refresh(row)
    return _serialize_topic_comment(row)


async def append_topic_discussion(*, repo, topic, user, content, discussion_type, details=None):
    """在调用方事务中追加讨论及时间线；不自行提交。"""
    _require_topic_writable(topic)
    if discussion_type not in ("discussion", "reconsideration", "correction"):
        raise HTTPException(status_code=422, detail={"code": "invalid_discussion_type"})
    normalized_content = _normalize_topic_text(content, required=True)
    row = await repo.add_topic_comment(
        topic_id=topic.id,
        content=normalized_content or "",
        discussion_type=discussion_type,
        revision_number=topic.revision_number,
        author_name=user.username,
        operator=str(user.uid),
    )
    await repo.add_topic_event(
        topic,
        kind="comment",
        operator=str(user.uid),
        author_name=user.username,
        comment_id=row.id,
        details={"discussion_type": discussion_type, **(details or {})},
    )
    return row


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
    _require_topic_writable(row)
    if row.status != "proposed":
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_state", "status": row.status},
        )
    row.status = "canonical" if approve else "rejected"
    row.review_owner_uid = str(user.uid)
    row.reviewed_at = utc_now_naive()
    row.review_note = _normalize_topic_text(review_note, required=False)
    await repo.add_topic_event(
        row,
        kind="admitted" if approve else "rejected",
        operator=str(user.uid),
        author_name=user.username,
        reason=row.review_note,
    )
    await db.commit()
    await db.refresh(row)
    return _serialize_topic(row)


def _require_topic_writable(topic: GovernanceTopic) -> None:
    """归档对象恢复后维护，删除对象不可写。"""
    if topic.deleted_at is not None or topic.archived_at is not None:
        raise HTTPException(status_code=409, detail={"code": "topic_read_only", "message": "归档议题请先恢复"})


async def operate_governance_topic(
    *,
    project_id: str,
    topic_id: str,
    action: str,
    reason: str | None,
    execution_hint: str | None,
    decision_id: str | None,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """执行议题局部生命周期操作，不写入决策、任务或运行状态。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    if action == "decide":
        await repo.lock_decision_project(project.id)
    topic = await repo.get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project.id:
        raise HTTPException(status_code=404, detail="议题不存在")
    if action != "restore":
        _require_topic_writable(topic)
    normalized_reason = _normalize_topic_reason(reason, required=action in ("resubmit", "reopen", "close", "delete"))
    details = {}
    if action == "resubmit" and topic.status == "rejected":
        topic.status = "proposed"
        topic.review_owner_uid = topic.reviewed_at = topic.review_note = None
    elif action == "decide" and topic.status == "canonical" and topic.progress == "open":
        decision = await repo.get_decision(decision_id=decision_id or "")
        if (
            decision is None
            or decision.project_id != project.id
            or decision.topic_id != topic.id
            or decision.status != "approved"
        ):
            raise HTTPException(
                status_code=409, detail={"code": "decision_required", "message": "请选择当前议题已批准的关联决策"}
            )
        topic.progress = "decided"
        topic.execution_hint = None
        details = {"decision_id": decision.id}
    elif action == "close" and topic.progress in ("open", "decided"):
        topic.progress = "closed"
    elif action == "reopen" and topic.progress in ("decided", "closed"):
        if execution_hint not in ("continue", "pause_recommended"):
            raise HTTPException(status_code=422, detail={"code": "execution_hint_required"})
        topic.progress = "open"
        topic.execution_hint = execution_hint
        details = {"execution_hint": execution_hint}
    elif action == "archive":
        topic.archived_at = utc_now_naive()
    elif action == "restore" and topic.archived_at is not None:
        topic.archived_at = None
    elif action == "delete":
        references = await repo.topic_references(topic.id)
        if references:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "topic_referenced",
                    "message": f"议题存在业务引用（{'、'.join(references)}），请归档",
                    "references": references,
                },
            )
        topic.deleted_at = utc_now_naive()
    else:
        raise HTTPException(status_code=409, detail={"code": "invalid_state", "message": "当前状态不能执行此操作"})
    await repo.add_topic_event(
        topic, kind=action, operator=str(user.uid), author_name=user.username, reason=normalized_reason, details=details
    )
    await db.commit()
    return _serialize_topic(topic)


async def get_governance_topic_timeline(
    *, project_id: str, topic_id: str, before: int | None, limit: int, db: AsyncSession, user: User
) -> dict[str, Any]:
    """读取权限范围内的倒序时间线及其历史正文。"""
    await get_governance_topic(project_id=project_id, topic_id=topic_id, db=db, user=user)
    rows = await GovernanceRepository(db).list_topic_timeline(topic_id, before=before, limit=limit + 1)
    items = []
    for event, revision, comment in rows[:limit]:
        items.append(
            {
                "sequence": event.sequence,
                "kind": event.kind,
                "created_at": format_utc_datetime(event.created_at),
                "author_name": event.author_name,
                "created_by": event.created_by,
                "reason": event.reason,
                "details": event.details,
                "revision_number": event.revision_number,
                "revision": {
                    "number": revision.number,
                    "title": revision.title,
                    "summary": revision.summary,
                    "origin": revision.origin,
                }
                if revision
                else None,
                "comment": _serialize_topic_comment(comment) if comment else None,
            }
        )
    return {"items": items, "next_before": items[-1]["sequence"] if len(rows) > limit else None}


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
    if decision_id is not None:
        await repo.lock_decision_project(project.id)
    if topic_id is not None:
        topic = await repo.get_topic_for_update(topic_id=topic_id)
        if topic is None or topic.project_id != project.id:
            raise HTTPException(status_code=404, detail="来源议题不存在")
        _require_topic_writable(topic)
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
    result = []
    repo = GovernanceRepository(db)
    for row in rows:
        item = _serialize_task(row)
        mapping = await repo.admission(row.id)
        item["work"] = _admitted_work(mapping) if mapping else None
        result.append(item)
    return result


def _admitted_work(mapping) -> dict:
    """提供映射及正式工作跳转事实。"""
    admission, work = mapping
    return {
        "id": work.id,
        "number": work.number,
        "title": work.title,
        "mode": admission.mode,
        "created_by": admission.created_by,
        "created_at": format_utc_datetime(admission.created_at),
        "reason": admission.reason,
    }


async def admit_governance_task(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    task_id: str,
    mode: str,
    work_task_id: str | None = None,
    review_note: str | None = None,
    title: str | None = None,
    description: str | None = _UNSET,
    topic_id: str | None = _UNSET,
    source_decision_id: str | None = _UNSET,
    review_confirmed: bool = False,
) -> dict:
    """在一次事务中审核建议并创建或关联正式工作。"""
    from yuxi.services.project_work_service import create_task_pending
    from yuxi.repositories.project_work_repository import ProjectWorkRepository

    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(404, detail="项目不存在")
    repo = GovernanceRepository(db)
    suggestion = await repo.get_task_for_update(task_id=task_id)
    if suggestion is None or suggestion.project_id != project_id:
        raise HTTPException(404, detail="工作建议不存在")
    mapping = await repo.admission(task_id)
    if mapping:
        if mode != mapping[0].mode or (mode == "link" and work_task_id != mapping[0].work_task_id):
            raise HTTPException(
                409,
                detail={
                    "code": "suggestion_already_admitted",
                    "message": "建议已纳入其他正式工作，请打开原工作",
                    "work": _admitted_work(mapping),
                },
            )
        return {"suggestion_id": task_id, "work": _admitted_work(mapping)}
    if suggestion.status not in {"proposed", "canonical"}:
        raise HTTPException(409, detail={"code": "suggestion_rejected", "message": "被拒绝的建议不能纳入"})
    if mode == "create":
        description = suggestion.description if description is _UNSET else description
        topic_id = suggestion.topic_id if topic_id is _UNSET else topic_id
        source_decision_id = suggestion.decision_id if source_decision_id is _UNSET else source_decision_id
        work = await create_task_pending(
            db=db,
            user=user,
            project_id=project_id,
            title=title or suggestion.title,
            description=description,
            topic_id=topic_id,
            source_decision_id=source_decision_id,
            review_confirmed=review_confirmed,
            parent_id=None,
            primary_owner_agent_slug=suggestion.assignee_agent_slug,
        )
    elif mode == "link" and work_task_id:
        work = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_task(
            work_task_id, lock=True
        )
        if work is None:
            raise HTTPException(404, detail="所选正式工作不属于当前项目")
    else:
        raise HTTPException(422, detail="请选择新建工作或关联当前项目已有工作")
    if suggestion.status == "proposed":
        suggestion.status = "canonical"
        suggestion.review_owner_uid = str(user.uid)
        suggestion.reviewed_at = utc_now_naive()
        suggestion.review_note = review_note
    await repo.add_admission(
        suggestion_id=task_id,
        work_task_id=work.id,
        project_id=project_id,
        mode=mode,
        uid=str(user.uid),
        reason=review_note,
    )
    await db.commit()
    return {"suggestion_id": task_id, "work": _admitted_work(await repo.admission(task_id))}


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
    if approve:
        raise HTTPException(409, detail={"code": "admission_required", "message": "请通过纳入为工作完成审核"})
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(404, detail="项目不存在")
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


async def _decision_event(repo, row, *, kind: str, reason: str, user: User, details: dict | None = None):
    """在同一事务保存局部历史和关联议题节点。"""
    details = details or {}
    await repo.add_decision_event(row, kind=kind, reason=reason, details=details, user=user)
    if row.topic_id:
        topic = await repo.get_topic_for_update(topic_id=row.topic_id)
        if topic:
            await repo.add_topic_event(
                topic,
                kind=f"decision_{kind}",
                reason=reason,
                operator=str(user.uid),
                author_name=user.username,
                details={
                    **details,
                    "decision_id": row.id,
                    "decision_title": row.title,
                    "decision_revision": row.revision_number,
                    "target_decision_id": row.target_decision_id,
                },
            )


async def _decision_target(
    repo, *, project_id: str, relation_type: str, target_decision_id: str | None, decision_id=None
):
    """关系必须指向同项目有效决策，普通决策不携带目标。"""
    if relation_type == "ordinary" and target_decision_id is None:
        return None
    if (
        relation_type not in ("supplement", "replacement")
        or not target_decision_id
        or target_decision_id == decision_id
    ):
        raise HTTPException(422, detail={"code": "invalid_relation", "message": "请选择补充或整条替代的目标决策"})
    target = await repo.get_decision_for_update(target_decision_id)
    if target is None or target.project_id != project_id:
        raise HTTPException(404, detail="目标决策不存在")
    if target.status != "approved":
        raise HTTPException(
            409, detail={"code": "target_not_approved", "message": "原依据已变化，请重新选择当前有效决策"}
        )
    return target


def _decision_version(row, expected_revision: int):
    """冲突显式返回，客户端保留未保存草案。"""
    if row.revision_number != expected_revision:
        raise HTTPException(
            409,
            detail={
                "code": "revision_conflict",
                "message": "决策已被修改，请保留草稿并重新读取",
                "current_revision": row.revision_number,
            },
        )


async def _locked_decision(*, project_id: str, decision_id: str, db: AsyncSession, user: User):
    """统一授权和项目先行锁顺序。"""
    await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    await repo.lock_decision_project(project_id)
    row = await repo.get_decision_for_update(decision_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, detail="决策不存在")
    return repo, row


async def _decision_topic(repo, *, project_id: str, topic_id: str | None):
    """创建、修订及批准时核对来源议题可写。"""
    if not topic_id:
        return None
    topic = await repo.get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project_id:
        raise HTTPException(404, detail="来源议题不存在")
    _require_topic_writable(topic)
    return topic


async def create_governance_decision(
    *,
    project_id: str,
    title: str,
    conclusion: str,
    rationale: str | None,
    topic_id: str | None,
    db: AsyncSession,
    user: User,
    relation_type: str = "ordinary",
    target_decision_id: str | None = None,
) -> dict[str, Any]:
    """只新增草案，不自动批准或确认议题。"""
    await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    await repo.lock_decision_project(project_id)
    await _decision_target(
        repo, project_id=project_id, relation_type=relation_type, target_decision_id=target_decision_id
    )
    topic = await _decision_topic(repo, project_id=project_id, topic_id=topic_id)
    row = await repo.add_decision(
        project_id=project_id,
        title=normalize_title(title),
        conclusion=_normalize_topic_text(conclusion, required=True),
        rationale=_normalize_topic_text(rationale, required=False),
        topic_id=topic_id,
        relation_type=relation_type,
        target_decision_id=target_decision_id,
        topic_revision_number=topic.revision_number if topic else None,
        operator=str(user.uid),
    )
    await repo.add_decision_revision(row, reason="新增草案", user=user)
    await _decision_event(repo, row, kind="created", reason="新增草案", user=user)
    await db.commit()
    return _serialize_decision(row)


async def update_governance_decision(
    *,
    project_id: str,
    decision_id: str,
    title: str,
    conclusion: str,
    rationale: str | None,
    topic_id: str | None,
    relation_type: str,
    target_decision_id: str | None,
    expected_revision: int,
    reason: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """修订草案并追加快照，已批准原文不可覆盖。"""
    repo, row = await _locked_decision(project_id=project_id, decision_id=decision_id, db=db, user=user)
    _decision_version(row, expected_revision)
    if row.status != "draft":
        raise HTTPException(
            409, detail={"code": "decision_read_only", "message": "批准原文不可覆盖，请追加勘误或新决策"}
        )
    reason = _normalize_topic_reason(reason, required=True)
    await _decision_target(
        repo,
        project_id=project_id,
        relation_type=relation_type,
        target_decision_id=target_decision_id,
        decision_id=row.id,
    )
    topic = await _decision_topic(repo, project_id=project_id, topic_id=topic_id)
    old_topic_id = row.topic_id
    row.title = normalize_title(title)
    row.conclusion = _normalize_topic_text(conclusion, required=True)
    row.rationale = _normalize_topic_text(rationale, required=False)
    row.topic_id, row.relation_type, row.target_decision_id = topic_id, relation_type, target_decision_id
    row.topic_revision_number = topic.revision_number if topic else None
    row.revision_number += 1
    await repo.add_decision_revision(row, reason=reason, user=user)
    await _decision_event(
        repo, row, kind="revised", reason=reason, user=user, details={"previous_topic_id": old_topic_id}
    )
    if old_topic_id and old_topic_id != topic_id:
        old_topic = await repo.get_topic_for_update(topic_id=old_topic_id)
        if old_topic:
            await repo.add_topic_event(
                old_topic,
                kind="decision_moved",
                operator=str(user.uid),
                author_name=user.username,
                reason=reason,
                details={"decision_id": row.id, "decision_title": row.title, "topic_id": topic_id},
            )
    await db.commit()
    return _serialize_decision(row)


async def operate_governance_decision(
    *,
    project_id: str,
    decision_id: str,
    action: str,
    expected_revision: int,
    reason: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """批准、撤销与受引用保护的草案删除均保留局部历史。"""
    repo, row = await _locked_decision(project_id=project_id, decision_id=decision_id, db=db, user=user)
    if action == "approve" and row.status == "approved" and expected_revision == row.revision_number - 1:
        return _serialize_decision(row)
    _decision_version(row, expected_revision)
    reason = _normalize_topic_reason(reason, required=True)
    if action == "approve" and row.status == "draft":
        target = await _decision_target(
            repo,
            project_id=project_id,
            relation_type=row.relation_type,
            target_decision_id=row.target_decision_id,
            decision_id=row.id,
        )
        topic = await _decision_topic(repo, project_id=project_id, topic_id=row.topic_id)
        row.status, row.decided_by, row.decided_at = "approved", str(user.uid), utc_now_naive()
        row.topic_revision_number = topic.revision_number if topic else None
        row.revision_number += 1
        await repo.add_decision_revision(row, reason=reason, user=user)
        if target:
            if row.relation_type == "replacement":
                target.status = "superseded"
            await _decision_event(
                repo,
                target,
                kind="superseded" if row.relation_type == "replacement" else "supplemented",
                reason=reason,
                user=user,
                details={"related_decision_id": row.id},
            )
        await _decision_event(repo, row, kind="approved", reason=reason, user=user)
    elif action == "revoke" and row.status == "approved":
        row.status = "revoked"
        await _decision_event(repo, row, kind="revoked", reason=reason, user=user)
    elif action == "delete" and row.status == "draft":
        references = await repo.decision_references(row.id)
        if references:
            raise HTTPException(
                409, detail={"code": "decision_referenced", "message": "已有引用，不能删除", "references": references}
            )
        row.deleted_at = utc_now_naive()
        await _decision_event(repo, row, kind="deleted", reason=reason, user=user)
    else:
        raise HTTPException(409, detail={"code": "invalid_state", "message": "当前决策状态不支持此操作"})
    await db.commit()
    return _serialize_decision(row)


async def create_governance_decision_erratum(
    *,
    project_id: str,
    decision_id: str,
    field: str,
    original_text: str,
    corrected_text: str,
    reason: str,
    meaning_unchanged: bool,
    expected_revision: int,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """追加声明不改变业务含义的文字勘误，保留批准原文。"""
    repo, row = await _locked_decision(project_id=project_id, decision_id=decision_id, db=db, user=user)
    _decision_version(row, expected_revision)
    if row.status == "draft":
        raise HTTPException(409, detail="草案请直接修订")
    original_text = _normalize_topic_text(original_text, required=True)
    corrected_text = _normalize_topic_text(corrected_text, required=True)
    if (
        not meaning_unchanged
        or field not in ("title", "conclusion", "rationale")
        or original_text not in (getattr(row, field, None) or "")
        or original_text == corrected_text
    ):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_erratum",
                "message": "请选取批准原文中的文字并确认含义不变；数值、范围、条件变化请新增决策",
            },
        )
    reason = _normalize_topic_reason(reason, required=True)
    erratum = GovernanceDecisionErratum(
        id=str(uuid.uuid4()),
        decision_id=row.id,
        revision_number=row.revision_number,
        field=field,
        original_text=original_text,
        corrected_text=corrected_text,
        reason=reason,
        meaning_unchanged=True,
        created_by=str(user.uid),
        author_name=user.username,
    )
    db.add(erratum)
    await db.flush()
    await _decision_event(
        repo,
        row,
        kind="erratum",
        reason=reason,
        user=user,
        details={
            "erratum_id": erratum.id,
            "field": field,
            "original_text": original_text,
            "corrected_text": corrected_text,
        },
    )
    await db.commit()
    return _serialize_decision(row)


async def get_governance_decision(
    *,
    project_id: str,
    decision_id: str,
    db: AsyncSession,
    user: User,
    before: int | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """读取决策原文、勘误、双向关系和倒序局部时间线。"""
    await _require_project(project_id=project_id, db=db, user=user)
    repo = GovernanceRepository(db)
    row = await repo.get_decision(decision_id=decision_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, detail="决策不存在")
    decisions = await repo.list_decisions(project_id=project_id)
    targets = {decision.id: decision for decision in decisions}
    target = targets.get(row.target_decision_id)
    result = _serialize_decision(row)
    result["target"] = _serialize_decision(target) if target else None
    result["related_decisions"] = [
        _serialize_decision(other) for other in decisions if other.target_decision_id == row.id
    ]
    result["requires_review"] = row.relation_type == "supplement" and target is not None and target.status != "approved"
    result["references"] = await repo.decision_references(row.id)
    result["tasks"] = [
        _serialize_task(task) for task in await repo.list_tasks(project_id=project_id) if task.decision_id == row.id
    ]
    result["errata"] = [
        {
            key: getattr(erratum, key)
            for key in (
                "id",
                "revision_number",
                "field",
                "original_text",
                "corrected_text",
                "reason",
                "created_by",
                "author_name",
            )
        }
        | {"created_at": format_utc_datetime(erratum.created_at)}
        for erratum in await repo.list_decision_errata(row.id)
    ]
    events = await repo.list_decision_events(row.id, before=before, limit=limit + 1)
    result["timeline"] = [
        {
            "sequence": event.sequence,
            "kind": event.kind,
            "reason": event.reason,
            "details": event.details,
            "revision_number": event.revision_number,
            "created_by": event.created_by,
            "author_name": event.author_name,
            "created_at": format_utc_datetime(event.created_at),
            "snapshot": revision.snapshot,
            "origin": revision.origin,
        }
        for event, revision in events[:limit]
    ]
    result["next_before"] = events[limit - 1][0].sequence if len(events) > limit else None
    return result


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
    repo = GovernanceRepository(db)
    rows = await repo.list_decisions(project_id=project.id)
    topics = await repo.list_topics(project_id=project.id, include_archived=True)
    hints = {topic.id: topic.execution_hint for topic in topics}
    targets = {row.id: row for row in rows}
    return [
        _serialize_decision(row, topic_execution_hint=hints.get(row.topic_id))
        | {
            "requires_review": row.relation_type == "supplement"
            and row.target_decision_id in targets
            and targets[row.target_decision_id].status != "approved",
        }
        for row in rows
    ]
