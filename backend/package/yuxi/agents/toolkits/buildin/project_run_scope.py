"""Agent 工具的项目 Run 授权范围解析：从 Run→Conversation→Project 重建并校验 lease。"""

from __future__ import annotations

from sqlalchemy import select

from yuxi.repositories.user_repository import UserRepository
from yuxi.storage.postgres.models_business import AgentRun, Conversation, Project, User
from yuxi.utils.datetime_utils import utc_now_naive


async def resolve_project_run_scope(
    *, db, run_id: str, uid: str, worker_id: str, resource_label: str = "项目", lock_project_first: bool = False
) -> tuple[str, User]:
    """用 Run、Conversation、Project 的关联重建当前调用的授权范围。"""
    statement = (
        select(AgentRun, Conversation, Project)
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .join(Project, Project.id == Conversation.project_id)
        .where(
            AgentRun.id == run_id,
            AgentRun.uid == uid,
            Conversation.uid == uid,
            Conversation.status != "deleted",
            Project.uid == uid,
            Project.status == "active",
            Project.selection_status == "selectable",
        )
    )
    if lock_project_first:
        # 新委派与 HTTP 的项目锁先于 Run；随后重验完整授权及 lease。
        project_id = await db.scalar(statement.with_only_columns(Project.id))
        if project_id is None:
            raise ValueError(f"当前运行无权访问{resource_label}")
        await db.execute(select(Project).where(Project.id == project_id).with_for_update())
    statement = statement.with_for_update(of=AgentRun)
    result = (await db.execute(statement)).one_or_none()
    if result is None:
        raise ValueError(f"当前运行无权访问{resource_label}")
    run, conversation, project = result
    if run.run_type == "subagent" or conversation.status == "subagent" or run.status != "running":
        raise ValueError(f"只有正在执行的根 AgentRun 可以访问{resource_label}")
    if run.worker_id != worker_id or run.lease_expires_at is None or run.lease_expires_at <= utc_now_naive():
        raise ValueError(f"只有当前有效 AgentRun lease owner 可以访问{resource_label}")
    user = await UserRepository().get_by_uid_with_db(db, uid)
    if user is None:
        raise ValueError("当前用户不存在")
    return str(project.id), user
