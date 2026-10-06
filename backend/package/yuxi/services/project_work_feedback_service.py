"""明确确认的结果反馈：议题事务与蓝图文件保存分别拥有事实。"""

import hashlib
import json
import uuid

from fastapi import HTTPException

from yuxi.repositories.governance_repository import GovernanceRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.services import project_work_service as work
from yuxi.services.governance_service import append_topic_discussion
from yuxi.services.project_blueprint_service import get_project_blueprint_view, put_project_blueprint_view
from yuxi.services.project_work_result_service import conflict
from yuxi.storage.postgres.models_business import ProjectWorkResultTopicFeedback


async def load_result(*, db, user, project_id, task_id, result_id, lock=False):
    """按项目→工作→结果顺序读取反馈来源。"""
    project = await (work.writable_project if lock else work.require_project)(db, user, project_id)
    task = await work.require_task(db, user, project.id, task_id, lock=lock)
    repo = ProjectWorkRepository(db, project_id=project.id, uid=str(user.uid))
    result = await repo.result(task.id, result_id=result_id, lock=lock)
    if result is None:
        raise HTTPException(status_code=404, detail="结果不存在")
    return project, task, result, repo


def feedback_text(task, result):
    """生成包含结果状态与人工意见的可编辑反馈正文。"""
    status = {"pending": "待验收", "accepted": "已接受", "not_accepted": "未接受"}[result.status]
    return (
        f"## 工作 {task.number}：{task.title}\n\n"
        f"结果 {result.id} · {status} · 要求修订 {result.criteria_revision or '未记录'}\n\n"
        f"{result.summary}\n\n未解决事项：{result.unresolved or '未记录'}\n\n"
        f"验收意见：{result.review_comment or '尚未验收'}"
    )


async def topic_feedback(
    *,
    db,
    user,
    project_id,
    task_id,
    result_id,
    topic_id,
    content,
    discussion_type,
    request_id,
    expected_result_version,
    expected_topic_revision,
):
    """同事务追加评论、历史及双向定位；重复确认不重复写入。"""
    project, task, result, repo = await load_result(
        db=db, user=user, project_id=project_id, task_id=task_id, result_id=result_id, lock=True
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            [topic_id, content, discussion_type, expected_result_version, expected_topic_revision], ensure_ascii=False
        ).encode()
    ).hexdigest()
    previous = await repo.result_feedbacks(result.id, request_id=request_id)
    if previous:
        if previous[0].request_hash != fingerprint:
            conflict("该确认标识已用于不同反馈")
        return {"topic_id": previous[0].topic_id, "comment_id": previous[0].comment_id}
    governance = GovernanceRepository(db)
    topic = await governance.get_topic_for_update(topic_id=topic_id)
    if topic is None or topic.project_id != project.id:
        raise HTTPException(status_code=404, detail="目标议题不存在")
    if result.version != expected_result_version or topic.revision_number != expected_topic_revision:
        conflict("结果或议题已修改，请核对最新版本；反馈草稿保留")
    comment = await append_topic_discussion(
        repo=governance,
        topic=topic,
        user=user,
        content=content,
        discussion_type=discussion_type,
        details={"result_id": result.id, "work_task_id": task.id, "result_version": result.version},
    )
    db.add(
        ProjectWorkResultTopicFeedback(
            id=str(uuid.uuid4()),
            project_id=project.id,
            result_id=result.id,
            topic_id=topic.id,
            comment_id=comment.id,
            topic_revision=topic.revision_number,
            result_version=result.version,
            request_id=request_id,
            request_hash=fingerprint,
            created_by=str(user.uid),
        )
    )
    await db.commit()
    return {"topic_id": topic.id, "comment_id": comment.id}


async def preview_blueprint(*, db, user, project_id, task_id, result_id, name):
    """读取目标原文并生成复盘预览；不写文件。"""
    _, task, result, _ = await load_result(
        db=db, user=user, project_id=project_id, task_id=task_id, result_id=result_id
    )
    document = await get_project_blueprint_view(project_id=project_id, name=name, db=db, user=user)
    return {
        **document,
        "original_content": document["content"],
        "content": document["content"].rstrip() + "\n\n" + feedback_text(task, result) + "\n",
        "result_version": result.version,
    }


async def save_blueprint(
    *,
    db,
    user,
    project_id,
    task_id,
    result_id,
    name,
    content,
    expected_hash,
    expected_identity,
    expected_result_version,
):
    """确认预览后保存，重试已保存正文可回读，冲突不覆盖。"""
    _, _, result, _ = await load_result(
        db=db, user=user, project_id=project_id, task_id=task_id, result_id=result_id, lock=True
    )
    if result.version != expected_result_version:
        conflict("结果验收状态已改变，请重新预览；复盘草稿保留")
    document = await get_project_blueprint_view(project_id=project_id, name=name, db=db, user=user)
    if document["content"] == content:
        return document
    return await put_project_blueprint_view(
        project_id=project_id,
        name=name,
        content=content,
        expected_hash=expected_hash,
        expected_identity=expected_identity,
        db=db,
        user=user,
    )
