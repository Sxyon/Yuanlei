"""个人工作结果提交、验收及任务完成的事务 Owner。"""

import hashlib
import json
import uuid

from fastapi import HTTPException
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.services import project_work_service as work
from yuxi.services.project_task_git_outcome_service import inspect_task_git_outcomes
from yuxi.storage.minio import StorageError, get_minio_client
from yuxi.storage.postgres.models_business import ProjectWorkResult, ProjectWorkExecution
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive
from yuxi.workspace.workdir import Workdir


def conflict(message: str, code: str = "work_result_conflict") -> None:
    """返回可保留草稿的版本或状态冲突。"""
    raise HTTPException(status_code=409, detail={"code": code, "message": message})


async def evidence_data(*, repo, project, evidence: list[dict]) -> list[dict]:
    """在现有资源边界检查引用，不验证证据能否证明业务完成。"""
    values = []
    for item in evidence:
        kind, value = item["kind"], item["value"].strip()
        state, message = "available", "可访问，内容仍需人工核对"
        try:
            if kind == "url":
                url = TypeAdapter(AnyHttpUrl).validate_python(value)
                if url.username or url.password or any(c.isspace() or ord(c) < 32 for c in value):
                    raise ValueError("invalid URL")
                state, message = "reference_only", "网页仅为引用，未读取或验证"
            elif kind == "attachment":
                attachment = await repo.get_attachment(value)
                if attachment is None or attachment.task_id != item["task_id"]:
                    state, message = "unavailable", "附件已删除或不属于当前工作"
                else:
                    client = get_minio_client()
                    await client.adownload_file(
                        bucket_name=client.KB_BUCKETS["documents"], object_name=attachment.object_name
                    )
            elif kind == "file":
                Workdir.open_existing(repo.uid, project.workdir_path).read_file_prefix(value, 1)
            else:
                raise ValueError("unknown evidence kind")
        except (ValidationError, ValueError):
            state, message = "unavailable", "引用格式或文件路径无效"
        except PermissionError:
            state, message = "unavailable", "证据无读取权限"
        except FileNotFoundError:
            state, message = "unavailable", "文件已删除或不存在"
        except (OSError, StorageError):
            state, message = "unavailable", "证据读取失败，请检查文件或存储服务"
        values.append(
            {
                **item,
                "value": value,
                "submitted_availability": item.get("submitted_availability", item.get("availability", state)),
                "availability": state,
                "availability_message": message,
            }
        )
    return values


async def list_result_data(*, db, user, project, task) -> list[dict]:
    """读取结果快照与证据当前状态，历史正文保持原样。"""
    repo = ProjectWorkRepository(db, project_id=project.id, uid=str(user.uid))
    values = []
    for row in await repo.results(task.id):
        values.append(
            {
                "id": row.id,
                "task_id": row.task_id,
                "project_id": row.project_id,
                "summary": row.summary,
                "unresolved": row.unresolved,
                "evidence": await evidence_data(repo=repo, project=project, evidence=row.evidence or []),
                "source_execution_id": row.source_execution_id,
                "source_delegation_id": row.source_delegation_id,
                "criteria_snapshot": row.criteria_snapshot,
                "criteria_recorded": row.criteria_snapshot is not None,
                "origin_kind": row.origin_kind,
                "source_output": row.source_output,
                "requirements_snapshot": row.requirements_snapshot,
                "topic_feedbacks": [
                    {
                        "topic_id": feedback.topic_id,
                        "comment_id": feedback.comment_id,
                        "topic_revision": feedback.topic_revision,
                    }
                    for feedback in await repo.result_feedbacks(row.id)
                ],
                "criteria_revision": row.criteria_revision,
                "criteria_changed": row.criteria_revision != task.criteria_revision,
                "status": row.status,
                "version": row.version,
                "submitted_by": row.submitted_by,
                "created_at": format_utc_datetime(row.created_at),
                "review_comment": row.review_comment,
                "reviewed_by": row.reviewed_by,
                "reviewed_at": format_utc_datetime(row.reviewed_at),
            }
        )
    return values


async def update_requirements(
    *,
    db,
    user,
    project_id: str,
    task_id: str,
    description: str | None,
    acceptance_criteria: str,
    expected_revision: int,
) -> dict:
    """核对条件修订后更新要求，既有结果快照不变。"""
    await work.writable_project(db, user, project_id)
    task = await work.require_task(db, user, project_id, task_id, lock=True)
    if task.criteria_revision != expected_revision:
        conflict("验收要求已修改，请核对最新要求；本次草稿未保存")
    if task.acceptance_criteria != acceptance_criteria or task.description != description:
        task.acceptance_criteria = acceptance_criteria
        task.description = description
        task.criteria_revision += 1
        task.updated_at = utc_now_naive()
    await db.commit()
    return await work.get_task(db=db, user=user, project_id=project_id, task_id=task_id)


async def require_idle(db, task_id: str) -> None:
    """两类执行事实均已结束才能结束工作。"""
    await ChannelDelegationRepository(db).lock_task_delegations(task_id)
    if await ProjectWorkExecutionRepository(db).has_active_task_work(task_id) or await ChannelDelegationRepository(
        db
    ).has_active_task_work(task_id):
        conflict("工作仍有待接受、投递、执行或回收中的执行记录，请先等待或处理", "work_execution_active")


async def prepare_completion(*, db, user, project_id: str, task_id: str, confirmed: bool) -> None:
    """沿用 Git runtime 锁与成果检查，不在组合用例中提前提交。"""
    result = await inspect_task_git_outcomes(
        db=db, uid=str(user.uid), project_id=project_id, task_id=task_id, commit=False
    )
    if result["requires_attention"] and not confirmed:
        conflict("Git 成果仍需处理，请检查后明确选择保留成果再完成", "git_outcomes_confirmation_required")


async def complete_pending(*, db, user, task) -> None:
    """在 owning transaction 中统一完成守卫和一次完成通知。"""
    if task.status == "done":
        return
    if task.status == "cancelled":
        conflict("已取消工作须先重开，才能提交并完成")
    await require_idle(db, task.id)
    repo = ProjectWorkRepository(db, project_id=task.project_id, uid=str(user.uid))
    results = await repo.results(task.id)
    current = [
        row
        for row in results
        if row.status == "accepted"
        and row.criteria_snapshot is not None
        and row.criteria_revision == task.criteria_revision
    ]
    if not current:
        conflict("请先按当前要求提交并接受结果，再完成工作", "work_acceptance_required")
    project = await work.require_project(db, user, task.project_id)
    readable = False
    for row in current:
        checked = await evidence_data(repo=repo, project=project, evidence=row.evidence or [])
        if not any(item["availability"] == "unavailable" for item in checked):
            readable = True
            break
    if not readable:
        raise HTTPException(status_code=422, detail="当前已接受结果的证据不可访问，请提交可核对的新结果")
    task.status = "done"
    task.updated_at = utc_now_naive()
    await UserInboxRepository(db).record_occurrence(
        uid=task.created_by,
        kind="task_completed",
        source_id=task.id,
        project_id=task.project_id,
        title=f"任务已完成：{task.title}",
        summary=task.number,
    )


async def submit_result(
    *,
    db,
    user,
    project_id: str,
    task_id: str,
    request_id: str,
    summary: str,
    evidence: list[dict],
    unresolved: str,
    expected_revision: int,
    source_execution_id: str | None = None,
    source_delegation_id: str | None = None,
    complete: bool = False,
    git_outcomes_confirmed: bool = False,
) -> dict:
    """幂等提交人工结果；提交并完成在同一事务接受及结束工作。"""
    intent = {
        "summary": summary.strip(),
        "evidence": evidence,
        "unresolved": unresolved,
        "expected_revision": expected_revision,
        "source_execution_id": source_execution_id,
        "source_delegation_id": source_delegation_id,
        "complete": complete,
    }
    fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if complete:
        await ProjectGitRepositoryStore(db).acquire_user_runtime_lock(str(user.uid))
    project = await work.writable_project(db, user, project_id)
    task = await work.require_task(db, user, project_id, task_id, lock=True)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    existing = await repo.result(task.id, request_id=request_id)
    if existing:
        if existing.request_hash != fingerprint:
            conflict("该提交标识已用于不同内容，请重新提交")
        return await work.get_task(db=db, user=user, project_id=project_id, task_id=task_id)
    if complete:
        await prepare_completion(
            db=db, user=user, project_id=project_id, task_id=task_id, confirmed=git_outcomes_confirmed
        )
    if task.status == "cancelled":
        conflict("已取消工作须先重开再提交")
    if not intent["summary"]:
        raise HTTPException(status_code=422, detail="请填写结果摘要")
    if task.criteria_revision != expected_revision:
        conflict("验收要求已修改，请核对最新条件；结果草稿保留")
    await repo.validate_result_source(
        task_id=task.id, execution_id=source_execution_id, delegation_id=source_delegation_id
    )
    checked = await evidence_data(
        repo=repo, project=project, evidence=[{**item, "task_id": task.id} for item in evidence]
    )
    if any(item["availability"] == "unavailable" for item in checked):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "work_evidence_unavailable",
                "message": "证据不可访问，请修正引用后重试",
                "evidence": checked,
            },
        )
    row = await append_result(
        db=db,
        id=str(uuid.uuid4()),
        project_id=project_id,
        task_id=task.id,
        request_id=request_id,
        request_hash=fingerprint,
        summary=intent["summary"],
        unresolved=unresolved,
        evidence=checked,
        source_execution_id=source_execution_id,
        source_delegation_id=source_delegation_id,
        criteria_snapshot=task.acceptance_criteria or "",
        criteria_revision=task.criteria_revision,
        submitted_by=str(user.uid),
        status="pending",
        version=1,
        review_complete=False,
    )
    if complete:
        row.status = "accepted"
        row.version = 2
        row.review_comment = "人工提交并完成"
        row.reviewed_by = str(user.uid)
        row.reviewed_at = utc_now_naive()
        row.review_complete = True
        await db.flush()
        await complete_pending(db=db, user=user, task=task)
    await db.commit()
    return await work.get_task(db=db, user=user, project_id=project_id, task_id=task_id)


async def review_result(
    *,
    db,
    user,
    project_id: str,
    task_id: str,
    result_id: str,
    status: str,
    comment: str,
    expected_version: int,
    expected_revision: int,
    complete: bool = False,
    git_outcomes_confirmed: bool = False,
) -> dict:
    """首次人工验收固化意见，已验收结果仅允许相同意图重放。"""
    if status == "not_accepted" and not comment.strip():
        raise HTTPException(status_code=422, detail="未接受结果请填写原因")
    if status not in {"accepted", "not_accepted"} or (complete and status != "accepted"):
        raise HTTPException(status_code=422, detail="未接受结果不能完成工作")
    if complete:
        await ProjectGitRepositoryStore(db).acquire_user_runtime_lock(str(user.uid))
    project = await work.writable_project(db, user, project_id)
    task = await work.require_task(db, user, project_id, task_id, lock=True)
    repo = ProjectWorkRepository(db, project_id=project_id, uid=str(user.uid))
    row = await repo.result(task.id, result_id=result_id, lock=True)
    if row is None:
        raise HTTPException(status_code=404, detail="结果不存在")
    if row.status != "pending":
        if (row.status, row.review_comment, row.review_complete) != (status, comment, complete):
            conflict("该结果已验收，补充或改正请提交新结果")
        return await work.get_task(db=db, user=user, project_id=project_id, task_id=task_id)
    if complete:
        await prepare_completion(
            db=db, user=user, project_id=project_id, task_id=task_id, confirmed=git_outcomes_confirmed
        )
    if row.version != expected_version or task.criteria_revision != expected_revision:
        conflict("结果或验收条件已修改，请核对最新版本；本次意见保留")
    if status == "accepted":
        if row.criteria_snapshot is None:
            conflict("本次执行未记录可核对的验收条件，请补充人工结果；不会推断旧依据")
        if row.criteria_revision != task.criteria_revision:
            conflict("结果按旧条件提交，请按当前要求提交新结果")
        checked = await evidence_data(repo=repo, project=project, evidence=row.evidence or [])
        if any(item["availability"] == "unavailable" for item in checked):
            raise HTTPException(status_code=422, detail="证据已不可访问，请提交可核对的新结果")
    row.status, row.review_comment = status, comment
    row.version += 1
    row.reviewed_by, row.reviewed_at = str(user.uid), utc_now_naive()
    row.review_complete = complete
    await db.flush()
    if complete:
        await complete_pending(db=db, user=user, task=task)
    await db.commit()
    return await work.get_task(db=db, user=user, project_id=project.id, task_id=task.id)


async def append_result(*, db, **values):
    """仅追加并刷新结果，提交由人工用例或执行终态 Owner 完成。"""
    row = ProjectWorkResult(**values)
    db.add(row)
    await db.flush()
    return row


async def import_execution_result(*, db, project, source, summary, output_fact, evidence):
    """在已锁定的项目及工作事务中导入当次输出，不读取当前条件。"""
    repo = ProjectWorkRepository(db, project_id=project.id, uid=str(project.uid))
    execution_id = source.id if isinstance(source, ProjectWorkExecution) else None
    delegation_id = None if execution_id else source.id
    task_id = source.task_id if execution_id else source.work_task_id
    if not task_id:
        return None
    existing = await repo.automatic_result(execution_id=execution_id, delegation_id=delegation_id)
    if existing:
        return existing
    snapshot = source.context_snapshot or {}
    requirements = next((item for item in snapshot.get("items", []) if item.get("kind") == "requirements"), {})
    criteria = requirements.get("acceptance_criteria")
    revision = requirements.get("revision")
    checked = await evidence_data(
        repo=repo, project=project, evidence=[{**item, "task_id": task_id} for item in evidence]
    )
    identity = f"automatic:{'execution' if execution_id else 'delegation'}:{source.id}"
    return await append_result(
        db=db,
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
        project_id=project.id,
        task_id=task_id,
        request_id=str(uuid.uuid5(uuid.NAMESPACE_OID, identity)),
        request_hash=hashlib.sha256(identity.encode()).hexdigest(),
        summary=summary.strip()[:100_000],
        unresolved="",
        evidence=checked,
        source_execution_id=execution_id,
        source_delegation_id=delegation_id,
        criteria_snapshot=criteria,
        criteria_revision=revision,
        origin_kind="automatic",
        source_output=output_fact,
        requirements_snapshot=requirements or None,
        submitted_by=str(project.uid),
        status="pending",
        version=1,
        review_complete=False,
    )
