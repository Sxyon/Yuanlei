"""独立项目工作任务、问题单与讨论用例。"""

from __future__ import annotations

import re

from fastapi import HTTPException
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.storage.postgres.models_business import (
    ProjectWorkComment, ProjectWorkIssue, ProjectWorkReference, ProjectWorkTask, User,
)
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9]{1,11}\Z")
TASK_STATUSES = frozenset({"todo", "in_progress", "blocked", "done", "cancelled"})
ISSUE_STATUSES = frozenset({"open", "resolved", "closed"})
HTTP_URL = TypeAdapter(AnyHttpUrl)


def _code(value: str) -> str:
    """规范化人工配置的编号缩写。"""
    normalized = value.strip().upper()
    if not CODE_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="缩写须为 2-12 位大写字母或数字，并以字母开头")
    return normalized


def _text(value: str, *, limit: int, label: str) -> str:
    """校验工作对象的必填文本。"""
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise HTTPException(status_code=422, detail=f"{label}长度须为 1-{limit}")
    return normalized


async def _project(db: AsyncSession, user: User, project_id: str):
    """限定在当前用户的可管理项目内。"""
    row = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if row is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return row


async def _writable_project(db: AsyncSession, user: User, project_id: str):
    """锁定当前用户可写项目，避免软删除与状态变更交错。"""
    row = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if row is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return row


async def _task(db: AsyncSession, user: User, project_id: str, task_id: str, *, lock: bool = False) -> ProjectWorkTask:
    """读取当前项目任务，跨项目视为不存在。"""
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_task(task_id, lock=lock)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


async def _issue(
    db: AsyncSession, user: User, project_id: str, task_id: str, issue_id: str, *, lock: bool = False
) -> ProjectWorkIssue:
    """读取当前任务的问题单。"""
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_issue(issue_id, lock=lock)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="Issue 不存在")
    return row


def _task_data(row: ProjectWorkTask) -> dict:
    """序列化任务当前事实。"""
    return {
        "id": row.id,
        "project_id": row.project_id,
        "topic_id": row.topic_id,
        "parent_id": row.parent_id,
        "number": row.number,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "primary_owner_agent_slug": row.primary_owner_agent_slug,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _issue_data(row: ProjectWorkIssue, task_number: str) -> dict:
    """序列化问题单及稳定展示编号。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "number": f"{task_number}-I{row.sequence}",
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _comment_data(row: ProjectWorkComment) -> dict:
    """序列化追加式讨论。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "issue_id": row.issue_id,
        "content": row.content,
        "author_uid": row.author_uid,
        "author_name": row.author_name,
        "source_run_id": row.source_run_id,
        "created_at": format_utc_datetime(row.created_at),
    }


def _reference_data(row: ProjectWorkReference) -> dict:
    """序列化任务网页引用。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "title": row.title,
        "url": row.url,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
    }


async def configure_project_code(*, db: AsyncSession, user: User, project_id: str, code: str) -> dict:
    """首次固化项目缩写，重复同值请求幂等。"""
    normalized = _code(code)
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    existing = await repo.get_project_code(project_id)
    if existing is not None:
        if existing.code != normalized:
            raise HTTPException(status_code=409, detail="项目缩写已经固化")
        return {"project_id": project_id, "code": existing.code}
    try:
        await repo.set_project_code(project_id, normalized)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="项目缩写已被使用") from exc
    return {"project_id": project_id, "code": normalized}


async def get_project_code(*, db: AsyncSession, user: User, project_id: str) -> dict:
    """读取当前项目已固化的缩写。"""
    await _project(db, user, project_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_project_code(project_id)
    return {"project_id": project_id, "code": row.code if row else None}


async def configure_topic_code(*, db: AsyncSession, user: User, project_id: str, topic_id: str, code: str) -> dict:
    """为当前项目议题固化缩写。"""
    normalized = _code(code)
    if normalized == "GEN":
        raise HTTPException(status_code=422, detail="GEN 保留给无议题任务")
    await _project(db, user, project_id)
    topic = await GovernanceRepository(db).get_topic(topic_id=topic_id)
    if topic is None or topic.project_id != project_id:
        raise HTTPException(status_code=404, detail="议题不存在")
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    existing = await repo.get_topic_code(topic_id)
    if existing is not None:
        if existing.code != normalized:
            raise HTTPException(status_code=409, detail="议题缩写已经固化")
        return {"topic_id": topic_id, "code": existing.code}
    try:
        await repo.set_topic_code(project_id, topic_id, normalized)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="议题缩写已被使用") from exc
    return {"topic_id": topic_id, "code": normalized}


async def create_task(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    title: str,
    description: str | None,
    topic_id: str | None,
    parent_id: str | None,
    primary_owner_agent_slug: str | None,
) -> dict:
    """在项目缩写行锁内分配唯一编号并创建任务。"""
    normalized_title = _text(title, limit=512, label="标题")
    await _writable_project(db, user, project_id)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    if parent_id is not None:
        await _task(db, user, project_id, parent_id)
    topic_code = "GEN"
    if topic_id is not None:
        topic = await GovernanceRepository(db).get_topic(topic_id=topic_id)
        if topic is None or topic.project_id != project_id:
            raise HTTPException(status_code=404, detail="议题不存在")
        configured = await repo.get_topic_code(topic_id)
        if configured is None:
            raise HTTPException(status_code=409, detail="议题缩写尚未固化")
        topic_code = configured.code
    if primary_owner_agent_slug is not None:
        binding = await ProjectAgentRepository(db).get_for_update(project_id, primary_owner_agent_slug)
        if binding is None:
            raise HTTPException(status_code=404, detail="第一负责人未绑定该项目")
    project_code = await repo.get_project_code(project_id, lock=True)
    if project_code is None:
        raise HTTPException(status_code=409, detail="项目缩写尚未配置")
    number = f"{project_code.code}-{topic_code}-{project_code.next_number:06d}"
    project_code.next_number += 1
    row = await repo.add_task(
        project_id=project_id,
        number=number,
        title=normalized_title,
        description=description,
        topic_id=topic_id,
        parent_id=parent_id,
        primary_owner_agent_slug=primary_owner_agent_slug,
        created_by=str(user.uid),
    )
    await db.commit()
    return _task_data(row)


async def list_tasks(*, db: AsyncSession, user: User, project_id: str) -> list[dict]:
    """列出当前项目的工作任务。"""
    await _project(db, user, project_id)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    return [_task_data(row) for row in await repo.list_tasks(project_id)]


async def get_task(*, db: AsyncSession, user: User, project_id: str, task_id: str) -> dict:
    """读取任务详情和对应讨论。"""
    await _project(db, user, project_id)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    task = await _task(db, user, project_id, task_id)
    issues = await repo.list_issues(task.id)
    comments = await repo.list_comments(task_id=task.id)
    references = await repo.list_references(task.id)
    return {
        **_task_data(task),
        "issues": [_issue_data(row, task.number) for row in issues],
        "comments": [_comment_data(row) for row in comments],
        "references": [_reference_data(row) for row in references],
    }


async def add_reference(
    *, db: AsyncSession, user: User, project_id: str, task_id: str, title: str, url: str
) -> dict:
    """在项目归属边界内追加 HTTP(S) 网页引用。"""
    normalized_title = _text(title, limit=512, label="引用标题")
    normalized_url = url.strip()
    try:
        parsed = HTTP_URL.validate_python(normalized_url)
        valid = (
            len(normalized_url) <= 2048
            and len(str(parsed)) <= 2048
            and normalized_url.lower().startswith(("http://", "https://"))
            and parsed.host is not None
            and parsed.username is None
            and parsed.password is None
            and not any(char.isspace() or ord(char) < 32 for char in normalized_url)
        )
    except ValidationError:
        valid = False
    if not valid:
        raise HTTPException(status_code=422, detail="引用 URL 须为不含凭据的 HTTP(S) 地址")
    await _writable_project(db, user, project_id)
    await _task(db, user, project_id, task_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).add_reference(
        task_id=task_id, title=normalized_title, url=str(parsed), created_by=str(user.uid)
    )
    await db.commit()
    return _reference_data(row)


async def remove_reference(
    *, db: AsyncSession, user: User, project_id: str, task_id: str, reference_id: str
) -> dict:
    """从当前项目任务移除网页引用。"""
    await _writable_project(db, user, project_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_reference(reference_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="任务引用不存在")
    await db.delete(row)
    await db.commit()
    return {"id": reference_id, "deleted": True}


async def update_task(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    task_id: str,
    status: str | None = None,
    primary_owner_agent_slug: str | None = None,
    update_owner: bool = False,
) -> dict:
    """修改任务状态或转移第一负责人。"""
    await _writable_project(db, user, project_id)
    task = await _task(db, user, project_id, task_id, lock=True)
    if status is not None:
        if status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail="任务状态无效")
        if status in {"done", "cancelled"} and await ProjectWorkExecutionRepository(db).has_active_task_work(task.id):
            raise HTTPException(status_code=409, detail="任务仍有待接受或执行中的智能体工作")
        if status == "done" and task.status != "done":
            await UserInboxRepository(db).add_once(
                uid=task.created_by,
                kind="task_completed",
                source_id=task.id,
                project_id=project_id,
                title=f"任务已完成：{task.title}",
                summary=task.number,
            )
        task.status = status
    if update_owner:
        if primary_owner_agent_slug is not None:
            binding = await ProjectAgentRepository(db).get_for_update(project_id, primary_owner_agent_slug)
            if binding is None:
                raise HTTPException(status_code=404, detail="第一负责人未绑定该项目")
        task.primary_owner_agent_slug = primary_owner_agent_slug
    task.updated_at = utc_now_naive()
    await db.commit()
    return _task_data(task)


async def create_issue(
    *, db: AsyncSession, user: User, project_id: str, task_id: str, title: str, description: str | None
) -> dict:
    """在任务行锁内分配问题单序号。"""
    normalized_title = _text(title, limit=512, label="标题")
    await _writable_project(db, user, project_id)
    task = await _task(db, user, project_id, task_id, lock=True)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    sequence = await repo.next_issue_sequence(task.id)
    issue = await repo.add_issue(
        task_id=task.id,
        sequence=sequence,
        title=normalized_title,
        description=description,
        created_by=str(user.uid),
    )
    await db.commit()
    return _issue_data(issue, task.number)


async def get_issue(*, db: AsyncSession, user: User, project_id: str, task_id: str, issue_id: str) -> dict:
    """读取问题单及讨论。"""
    await _project(db, user, project_id)
    task = await _task(db, user, project_id, task_id)
    issue = await _issue(db, user, project_id, task.id, issue_id)
    comments = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).list_comments(
        issue_id=issue.id
    )
    return {**_issue_data(issue, task.number), "comments": [_comment_data(row) for row in comments]}


async def update_issue(
    *, db: AsyncSession, user: User, project_id: str, task_id: str, issue_id: str, status: str
) -> dict:
    """修改当前任务内问题单状态。"""
    if status not in ISSUE_STATUSES:
        raise HTTPException(status_code=422, detail="Issue 状态无效")
    await _writable_project(db, user, project_id)
    task = await _task(db, user, project_id, task_id)
    issue = await _issue(db, user, project_id, task.id, issue_id, lock=True)
    issue.status = status
    issue.updated_at = utc_now_naive()
    await db.commit()
    return _issue_data(issue, task.number)


async def add_comment(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    task_id: str,
    content: str,
    issue_id: str | None = None,
) -> dict:
    """在已授权任务或问题单上追加讨论。"""
    normalized = _text(content, limit=100_000, label="评论")
    await _project(db, user, project_id)
    task = await _task(db, user, project_id, task_id)
    if issue_id is not None:
        await _issue(db, user, project_id, task.id, issue_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).add_comment(
        task_id=None if issue_id else task.id,
        issue_id=issue_id,
        content=normalized,
        author_uid=str(user.uid),
        author_name=user.username,
    )
    await db.commit()
    return _comment_data(row)
