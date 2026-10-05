"""独立项目工作任务、问题单与讨论用例。"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.repositories.project_work_inspection_repository import ProjectWorkInspectionRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.services.project_work_inspection_service import (
    MAX_INSPECTION_INTERVAL_MINUTES,
    MIN_INSPECTION_INTERVAL_MINUTES,
)
from yuxi.storage.minio import StorageError, get_minio_client
from yuxi.storage.postgres.models_business import (
    ProjectWorkAttachment,
    ProjectWorkComment,
    ProjectWorkInspectionRun,
    ProjectWorkIssue,
    ProjectWorkReference,
    ProjectWorkTask,
    User,
)
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive
from yuxi.utils.upload_utils import read_upload_with_limit

CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9]{1,11}\Z")
TASK_STATUSES = frozenset({"todo", "in_progress", "blocked", "done", "cancelled"})
ISSUE_STATUSES = frozenset({"open", "resolved", "closed"})
HTTP_URL = TypeAdapter(AnyHttpUrl)
MAX_ATTACHMENT_SIZE_BYTES = 5 * 1024 * 1024
ATTACHMENT_ALLOWED_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".log",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
    }
)


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
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "primary_owner_agent_slug": row.primary_owner_agent_slug,
        "git_workspace_mode": row.git_workspace_mode or "inherit",
        "knowledge_ids": row.knowledge_ids or [],
        "inspection_enabled": row.inspection_enabled,
        "inspection_interval_minutes": row.inspection_interval_minutes,
        "inspection_next_run_at": format_utc_datetime(row.inspection_next_run_at),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _attachment_data(row: ProjectWorkAttachment) -> dict:
    """序列化任务文件附件元数据。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
    }


def _inspection_data(row: ProjectWorkInspectionRun) -> dict:
    """序列化一次巡检结果。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "status": row.status,
        "finding": row.finding,
        "summary": row.summary,
        "inspected_at": format_utc_datetime(row.inspected_at),
        "created_at": format_utc_datetime(row.created_at),
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
            raise HTTPException(
                status_code=409, detail={"code": "project_code_locked", "message": "项目缩写已固定，不能修改"}
            )
        return {"project_id": project_id, "code": existing.code}
    try:
        await repo.set_project_code(project_id, normalized)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "project_code_taken", "message": "项目缩写已被其他项目使用，请换一个"}
        ) from exc
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
    topic = await GovernanceRepository(db).get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project_id or topic.archived_at is not None:
        raise HTTPException(status_code=404, detail="议题不存在")
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    existing = await repo.get_topic_code(topic_id)
    if existing is not None:
        if existing.code != normalized:
            raise HTTPException(
                status_code=409, detail={"code": "topic_code_locked", "message": "议题缩写已经固化，不能修改"}
            )
        return {"topic_id": topic_id, "code": existing.code}
    try:
        await repo.set_topic_code(project_id, topic_id, normalized)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "topic_code_taken", "message": "议题缩写已被其他议题使用，请换一个"}
        ) from exc
    return {"topic_id": topic_id, "code": normalized}


async def list_topics(*, db: AsyncSession, user: User, project_id: str) -> list[dict]:
    """列出当前项目议题及其已固化缩写，供建任务时选择。"""
    await _project(db, user, project_id)
    topics = await GovernanceRepository(db).list_topics(project_id=project_id)
    codes = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).list_topic_codes()
    return [
        {
            "id": row.id,
            "title": row.title,
            "admission_status": row.status,
            "progress": row.progress,
            "code": codes.get(row.id),
        }
        for row in topics
    ]


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
    start_date: date | None = None,
    due_date: date | None = None,
) -> dict:
    """在项目缩写行锁内分配唯一编号并创建任务。"""
    normalized_title = _text(title, limit=512, label="标题")
    if start_date and due_date and start_date > due_date:
        raise HTTPException(status_code=422, detail="计划结束日期不能早于开始日期")
    await _writable_project(db, user, project_id)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    if parent_id is not None:
        await _task(db, user, project_id, parent_id)
    topic_code = "GEN"
    if topic_id is not None:
        topic = await GovernanceRepository(db).get_topic_for_update(topic_id=topic_id)
        if topic is None or topic.project_id != project_id or topic.archived_at is not None:
            raise HTTPException(status_code=404, detail="议题不存在")
        configured = await repo.get_topic_code(topic_id)
        if configured is None:
            raise HTTPException(
                status_code=409, detail={"code": "topic_code_required", "message": "请先为所选议题配置缩写，再创建任务"}
            )
        topic_code = configured.code
    if primary_owner_agent_slug is not None:
        binding = await ProjectAgentRepository(db).get_for_update(project_id, primary_owner_agent_slug)
        if binding is None:
            raise HTTPException(status_code=404, detail="第一负责人未绑定该项目")
    project_code = await repo.get_project_code(project_id, lock=True)
    if project_code is None:
        raise HTTPException(
            status_code=409, detail={"code": "project_code_required", "message": "请先设置项目编号缩写，再创建任务"}
        )
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
        start_date=start_date,
        due_date=due_date,
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
    attachments = await repo.list_attachments(task.id)
    inspection_runs = await ProjectWorkInspectionRepository(db).list_runs_for_task(task.id)
    from yuxi.repositories.project_settings_repository import ProjectSettingsRepository

    settings = ProjectSettingsRepository(db)
    linked = set(await settings.linked_ids(project_id))
    candidates, _ = await settings.knowledge(user) if linked else ([], set())
    return {
        **_task_data(task),
        "knowledge_candidates": [item for item in candidates if item["kb_id"] in linked],
        "issues": [_issue_data(row, task.number) for row in issues],
        "comments": [_comment_data(row) for row in comments],
        "references": [_reference_data(row) for row in references],
        "attachments": [_attachment_data(row) for row in attachments],
        "inspection_runs": [_inspection_data(row) for row in inspection_runs],
    }


async def add_reference(*, db: AsyncSession, user: User, project_id: str, task_id: str, title: str, url: str) -> dict:
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


async def remove_reference(*, db: AsyncSession, user: User, project_id: str, task_id: str, reference_id: str) -> dict:
    """从当前项目任务移除网页引用。"""
    await _writable_project(db, user, project_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_reference(reference_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="任务引用不存在")
    await db.delete(row)
    await db.commit()
    return {"id": reference_id, "deleted": True}


def _safe_file_name(file_name: str | None) -> str:
    """去掉目录成分，保留可安全展示的文件名。"""
    safe = Path(file_name or "").name.replace("/", "_").replace("\\", "_").strip(" .")
    return safe or "attachment.bin"


async def add_attachment(*, db: AsyncSession, user: User, project_id: str, task_id: str, file: UploadFile) -> dict:
    """在项目归属边界内校验并存储任务文件附件。"""
    await _writable_project(db, user, project_id)
    await _task(db, user, project_id, task_id)
    file_name = _safe_file_name(file.filename)
    if Path(file_name).suffix.lower() not in ATTACHMENT_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="不支持该文件类型")
    try:
        content = await read_upload_with_limit(
            file,
            max_size_bytes=MAX_ATTACHMENT_SIZE_BYTES,
            too_large_message="附件过大，当前仅支持 5 MB 以内的文件",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    attachment_id = str(uuid.uuid4())
    object_name = f"project_work/{project_id}/{task_id}/{attachment_id}/{file_name}"
    minio_client = get_minio_client()
    bucket_name = minio_client.KB_BUCKETS["documents"]
    try:
        await minio_client.aupload_file(
            bucket_name=bucket_name, object_name=object_name, data=content, content_type=file.content_type
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"附件上传失败: {exc}") from exc
    try:
        row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).add_attachment(
            task_id=task_id,
            file_name=file_name,
            content_type=file.content_type,
            file_size=len(content),
            object_name=object_name,
            created_by=str(user.uid),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        await _delete_attachment_object(bucket_name, object_name)
        raise
    return _attachment_data(row)


async def remove_attachment(*, db: AsyncSession, user: User, project_id: str, task_id: str, attachment_id: str) -> dict:
    """移除当前项目任务的文件附件及其对象。"""
    await _writable_project(db, user, project_id)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    row = await repo.get_attachment(attachment_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="任务附件不存在")
    object_name = row.object_name
    await db.delete(row)
    await db.commit()
    await _delete_attachment_object(get_minio_client().KB_BUCKETS["documents"], object_name)
    return {"id": attachment_id, "deleted": True}


async def get_attachment_for_download(
    *, db: AsyncSession, user: User, project_id: str, task_id: str, attachment_id: str
) -> tuple[bytes, ProjectWorkAttachment]:
    """在项目归属边界内读取附件内容，供下载响应装配。"""
    await _project(db, user, project_id)
    row = await ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid)).get_attachment(attachment_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="任务附件不存在")
    try:
        content = await get_minio_client().adownload_file(
            bucket_name=get_minio_client().KB_BUCKETS["documents"], object_name=row.object_name
        )
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=f"任务附件内容不可用: {exc}") from exc
    return content, row


async def _delete_attachment_object(bucket_name: str, object_name: str) -> None:
    """尽力删除对象存储内容，失败只记录不回滚已提交的元数据。"""
    try:
        await get_minio_client().adelete_file(bucket_name=bucket_name, object_name=object_name)
    except StorageError:
        pass


async def update_task(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    task_id: str,
    status: str | None = None,
    git_workspace_mode: str | None = None,
    knowledge_ids: list[str] | None = None,
    primary_owner_agent_slug: str | None = None,
    update_owner: bool = False,
    start_date: date | None = None,
    due_date: date | None = None,
    update_start_date: bool = False,
    update_due_date: bool = False,
    inspection_enabled: bool | None = None,
    inspection_interval_minutes: int | None = None,
    update_inspection: bool = False,
) -> dict:
    """修改任务状态、转移第一负责人或调整周期巡检配置。"""
    await _writable_project(db, user, project_id)
    task = await _task(db, user, project_id, task_id, lock=True)
    if knowledge_ids is not None:
        from yuxi.repositories.project_settings_repository import ProjectSettingsRepository

        if await ProjectWorkExecutionRepository(db).has_active_task_work(task.id):
            raise HTTPException(status_code=409, detail="任务有待接受或执行中的工作，不能改变执行知识库")
        settings = ProjectSettingsRepository(db)
        _, visible = await settings.knowledge(user)
        linked = set(await settings.linked_ids(project_id))
        selected = list(dict.fromkeys(knowledge_ids))
        if set(selected) - (visible & linked):
            raise HTTPException(status_code=403, detail="任务知识库必须已关联项目且当前可访问")
        task.knowledge_ids = selected
    if git_workspace_mode is not None:
        from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore

        if git_workspace_mode not in {"inherit", "isolated"}:
            raise HTTPException(status_code=422, detail="任务 Git 工作区模式非法")
        if task.git_workspace_mode != git_workspace_mode:
            if await ProjectGitRepositoryStore(db).task_tree_has_git_history(
                task_id=task.id, project_id=project_id, uid=str(user.uid)
            ):
                raise HTTPException(
                    status_code=409, detail="任务或共享子任务已有工作区或执行记录，不能改变历史 Git 作用域"
                )
            task.git_workspace_mode = git_workspace_mode
    if status is not None:
        if status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail="任务状态无效")
        if status in {"done", "cancelled"} and await ProjectWorkExecutionRepository(db).has_active_task_work(task.id):
            raise HTTPException(status_code=409, detail="任务仍有待接受或执行中的智能体工作")
        if status == "done" and task.status != "done":
            await UserInboxRepository(db).record_occurrence(
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
        if primary_owner_agent_slug is None:
            task.inspection_enabled = False
            task.inspection_next_run_at = None
    if update_start_date or update_due_date:
        next_start = start_date if update_start_date else task.start_date
        next_due = due_date if update_due_date else task.due_date
        if next_start and next_due and next_start > next_due:
            raise HTTPException(status_code=422, detail="计划结束日期不能早于开始日期")
        task.start_date = next_start
        task.due_date = next_due
    if update_inspection:
        _apply_inspection_config(task, enabled=inspection_enabled, interval_minutes=inspection_interval_minutes)
    task.updated_at = utc_now_naive()
    await db.commit()
    return _task_data(task)


def _apply_inspection_config(task: ProjectWorkTask, *, enabled: bool | None, interval_minutes: int | None) -> None:
    """按当前负责人收敛任务周期巡检计划，启用时立即安排首次核查。"""
    if interval_minutes is not None:
        if not MIN_INSPECTION_INTERVAL_MINUTES <= interval_minutes <= MAX_INSPECTION_INTERVAL_MINUTES:
            raise HTTPException(
                status_code=422,
                detail=f"巡检周期须为 {MIN_INSPECTION_INTERVAL_MINUTES}-{MAX_INSPECTION_INTERVAL_MINUTES} 分钟",
            )
        task.inspection_interval_minutes = interval_minutes
    next_enabled = task.inspection_enabled if enabled is None else enabled
    if next_enabled:
        if task.primary_owner_agent_slug is None:
            raise HTTPException(status_code=409, detail="请先设置第一负责人，再启用周期巡检")
        if task.inspection_interval_minutes is None:
            raise HTTPException(status_code=422, detail="请先设置巡检周期")
        task.inspection_enabled = True
        task.inspection_next_run_at = utc_now_naive()
    else:
        task.inspection_enabled = False
        task.inspection_next_run_at = None


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
