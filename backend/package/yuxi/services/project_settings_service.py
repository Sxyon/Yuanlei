"""项目设置用例，管理属性与访问权限保持独立。"""

from datetime import date

from fastapi import HTTPException

from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.repositories.project_settings_repository import ProjectSettingsRepository
from yuxi.repositories.user_repository import UserRepository
from yuxi.storage.postgres.models_business import ProjectSettings
from yuxi.utils.datetime_utils import utc_now_naive


def validate_project_settings(values: dict) -> None:
    """校验管理属性与日历日期，不触发执行状态转换。"""
    if values["work_status"] not in {"planned", "in_progress", "paused", "completed", "cancelled"}:
        raise HTTPException(422, "项目状态非法")
    if values["priority"] not in {"urgent", "high", "medium", "low", "none"}:
        raise HTTPException(422, "优先级非法")
    if values["owner_type"] not in {"none", "member", "agent"}:
        raise HTTPException(422, "负责人类型非法")
    if (values["owner_type"] == "none") != (values["owner_id"] is None):
        raise HTTPException(422, "负责人类型与身份不一致")
    if len(values["description"]) > 255:
        raise HTTPException(422, "项目描述最多 255 字符")
    start: date | None = values["start_date"]
    due: date | None = values["due_date"]
    if start and due and start > due:
        raise HTTPException(422, "截止日期不得早于开始日期")


async def get_project_settings(*, user, project_id: str, db) -> dict:
    """读取设置及可选资源，失去权限的关联仅返回不可访问标记。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(404, "项目不存在")
    repository = ProjectSettingsRepository(db)
    settings = await repository.get(project_id)
    values = (
        settings.to_dict()
        if settings
        else {
            "work_status": "planned",
            "priority": "none",
            "owner_type": "member",
            "owner_id": project.uid,
            "description": "",
            "start_date": None,
            "due_date": None,
        }
    )
    candidates, visible_ids = await repository.knowledge(user)
    names = {item["kb_id"]: item["name"] for item in candidates}
    links = [
        {"kb_id": kb_id, "name": names.get(kb_id), "accessible": kb_id in visible_ids}
        for kb_id in await repository.linked_ids(project_id)
    ]
    return {
        "project": project.to_dict(),
        "settings": values,
        "members": await repository.members(),
        "agents": await repository.agents(project_id),
        "knowledge_candidates": candidates,
        "knowledge_links": links,
    }


async def update_project_settings(*, user, project_id: str, name: str, values: dict, db) -> dict:
    """在同一事务保存名称和管理属性，不改变 Project 执行与授权。"""
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise HTTPException(422, "项目名称不能为空且最多 255 字符")
    validate_project_settings(values)
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(404, "项目不存在")
    if values["owner_type"] == "member":
        member = await UserRepository(db).get_by_uid(values["owner_id"])
        if member is None or member.is_deleted:
            raise HTTPException(422, "负责人不是有效平台成员")
    elif values["owner_type"] == "agent":
        if await ProjectAgentRepository(db).get_for_update(project_id, values["owner_id"]) is None:
            raise HTTPException(422, "负责人智能体未绑定该项目")
    repository = ProjectSettingsRepository(db)
    settings = await repository.get(project_id)
    if settings is None:
        settings = ProjectSettings(project_id=project_id)
        db.add(settings)
    for key, value in values.items():
        setattr(settings, key, value)
    project.name = normalized_name
    project.updated_at = utc_now_naive()
    await db.commit()
    return await get_project_settings(user=user, project_id=project_id, db=db)


async def update_project_knowledge_links(*, user, project_id: str, kb_ids: list[str], db) -> dict:
    """替换项目弱关联，允许保留不可读旧关联或解除它。"""
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(404, "项目不存在")
    repository = ProjectSettingsRepository(db)
    _, visible = await repository.knowledge(user)
    existing = set(await repository.linked_ids(project_id))
    selected = sorted(set(kb_ids))
    if set(selected) - visible - existing:
        raise HTTPException(403, "不能关联无读取权限的知识库")
    await repository.replace_links(project_id, selected)
    project.updated_at = utc_now_naive()
    await db.commit()
    return await get_project_settings(user=user, project_id=project_id, db=db)
