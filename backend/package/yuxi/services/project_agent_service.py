"""项目数字员工用例：项目归属、配置覆盖与运行范围校验。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.agents.buildin import AgentBackendNotFoundError, get_agent_backend
from yuxi.agents.context import filter_declared_config, normalize_agent_context_config
from yuxi.repositories.agent_repository import (
    AgentRepository,
    is_builtin_agent,
    merge_agent_config_json,
    user_can_manage_agent,
)
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.agent_config_service import prepare_agent_config_write
from yuxi.storage.postgres.models_business import Agent, User
from yuxi.utils.datetime_utils import utc_now_naive


class AgentProjectScopeDenied(ValueError):
    """项目数字员工被要求在其绑定项目之外运行。"""


# 覆盖层中按整段管理、可整体恢复继承的执行配置段。
_OVERRIDE_SECTION_FIELDS = frozenset({"sandbox", "coding"})


async def ensure_agent_project_scope(*, db: AsyncSession, agent_slug: str, project_id: str | None) -> None:
    """校验项目排他智能体的运行范围；没有任何绑定的智能体维持全局行为。"""
    bound_project_ids = await ProjectAgentRepository(db).list_project_ids_for_agent(agent_slug)
    if not bound_project_ids:
        return
    if project_id is not None and str(project_id) in bound_project_ids:
        return
    raise AgentProjectScopeDenied("该智能体属于其他项目，不能在当前会话使用")


async def load_project_agent_override(*, db: AsyncSession, agent_slug: str, project_id: str | None) -> dict | None:
    """读取绑定到该项目的配置覆盖 context；无绑定或空覆盖时返回 None。"""
    if project_id is None:
        return None
    binding = await ProjectAgentRepository(db).get(str(project_id), agent_slug)
    override = (binding.config_overrides or {}).get("context") if binding is not None else None
    return dict(override) if isinstance(override, dict) and override else None


async def resolve_effective_agent_context(
    *,
    agent_item: Agent,
    project_id: str | None,
    db: AsyncSession,
    user: User,
    context_schema,
) -> dict[str, Any]:
    """合并项目覆盖层后做授权归一，返回本次运行的规范化 context。"""
    base_context = (agent_item.config_json or {}).get("context")
    merged = dict(base_context) if isinstance(base_context, dict) else {}
    override = await load_project_agent_override(db=db, agent_slug=agent_item.slug, project_id=project_id)
    if override:
        merged.update(override)
    return await normalize_agent_context_config(merged, db=db, user=user, context_schema=context_schema)


async def _lock_manageable_project(*, project_id: str, db: AsyncSession, user: User):
    project = await ProjectRepository(db).lock_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在或不可管理")
    return project


async def _get_manageable_project(*, project_id: str, db: AsyncSession, user: User):
    """读路径不持有行锁：只校验归属与可管理状态。"""
    project = await ProjectRepository(db).get_for_user(project_id, str(user.uid))
    if project is None or project.status != "active" or project.selection_status != "selectable":
        raise HTTPException(status_code=404, detail="Project 不存在或不可管理")
    return project


async def _lock_agent_binding_mutations(*, db: AsyncSession, agent_slug: str) -> None:
    """按 Agent 串行化绑定变更，避免解绑删除与并发绑定互相踩踏。"""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"project-agent-binding:{agent_slug}"},
    )


async def _serialize_binding(*, agent: Agent, binding, db: AsyncSession, user: User, cache: dict) -> dict[str, Any]:
    try:
        backend = get_agent_backend(agent.backend_id)
    except AgentBackendNotFoundError:
        backend = None
    serialized = await AgentRepository(db).serialize(
        agent,
        user=user,
        include_configurable_items=True,
        backend_info_cache=cache,
    )
    serialized["config_overrides"] = binding.config_overrides or {}
    if backend is not None:
        serialized["effective_context"] = await resolve_effective_agent_context(
            agent_item=agent,
            project_id=binding.project_id,
            db=db,
            user=user,
            context_schema=backend.context_schema,
        )
    else:
        serialized["effective_context"] = {}
    return serialized


async def list_project_agents_view(*, project_id: str, db: AsyncSession, user: User) -> dict[str, Any]:
    """列出项目数字员工及其有效配置。"""
    project = await _get_manageable_project(project_id=project_id, db=db, user=user)
    bindings = await ProjectAgentRepository(db).list_for_project(project.id)
    agent_repo = AgentRepository(db)
    cache: dict = {}
    items = []
    for binding in bindings:
        agent = await agent_repo.get_by_slug(binding.agent_slug)
        if agent is None:
            continue
        items.append(await _serialize_binding(agent=agent, binding=binding, db=db, user=user, cache=cache))
    return {"project_id": project.id, "agents": items}


async def create_project_agent_view(
    *,
    project_id: str,
    name: str,
    backend_id: str,
    db: AsyncSession,
    user: User,
    slug: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    pics: list[str] | None = None,
    config_json: dict | None = None,
) -> dict[str, Any]:
    """在同一事务内创建私有 Agent 并绑定到项目；运行配置全部存入覆盖层。"""
    project = await _lock_manageable_project(project_id=project_id, db=db, user=user)
    try:
        backend = get_agent_backend(backend_id)
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filtered, resource_access = await prepare_agent_config_write(
        config_json or {"context": {}},
        context_schema=backend.context_schema,
        db=db,
        user=user,
    )
    overrides = merge_agent_config_json({"context": {}}, filtered, resource_access=resource_access)

    agent_repo = AgentRepository(db)
    agent = await agent_repo.create(
        name=name,
        backend_id=backend_id,
        slug=slug,
        description=description,
        icon=icon,
        pics=pics,
        config_json={"context": {}},
        creator=user,
        created_by=str(user.uid),
        commit=False,
    )
    binding = await ProjectAgentRepository(db).add(
        project_id=project.id,
        agent_slug=agent.slug,
        config_overrides=overrides,
        created_by=str(user.uid),
    )
    await db.commit()
    await db.refresh(agent)
    await db.refresh(binding)
    return await _serialize_binding(agent=agent, binding=binding, db=db, user=user, cache={})


async def bind_project_agent_view(
    *,
    project_id: str,
    agent_slug: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """把已有 Agent 绑定为项目数字员工；绑定后其运行范围收窄到绑定项目。"""
    project = await _lock_manageable_project(project_id=project_id, db=db, user=user)
    agent_repo = AgentRepository(db)
    agent = await agent_repo.get_visible_by_slug(slug=agent_slug, user=user, kind="main")
    if agent is None:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if is_builtin_agent(agent) or agent.is_default:
        raise HTTPException(status_code=409, detail="内置默认智能体不能绑定为项目数字员工")
    if not user_can_manage_agent(user, agent):
        raise HTTPException(status_code=403, detail="需要该智能体的管理权限才能绑定")

    await _lock_agent_binding_mutations(db=db, agent_slug=agent.slug)
    repo = ProjectAgentRepository(db)
    existing = await repo.get(project.id, agent.slug)
    if existing is not None:
        return await _serialize_binding(agent=agent, binding=existing, db=db, user=user, cache={})

    binding = await repo.add(
        project_id=project.id,
        agent_slug=agent.slug,
        config_overrides={},
        created_by=str(user.uid),
    )
    await db.commit()
    await db.refresh(binding)
    return await _serialize_binding(agent=agent, binding=binding, db=db, user=user, cache={})


async def update_project_agent_view(
    *,
    project_id: str,
    agent_slug: str,
    config_json: dict,
    reset_fields: list[str],
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """更新项目覆盖层；字段与资源引用按当前角色和可访问资源裁剪，reset_fields 恢复继承。"""
    project = await _lock_manageable_project(project_id=project_id, db=db, user=user)
    agent_repo = AgentRepository(db)
    agent = await agent_repo.get_visible_by_slug(slug=agent_slug, user=user, kind="any")
    if agent is None:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if not user_can_manage_agent(user, agent):
        raise HTTPException(status_code=403, detail="需要该智能体的管理权限才能修改")

    repo = ProjectAgentRepository(db)
    binding = await repo.get_for_update(project.id, agent.slug)
    if binding is None:
        raise HTTPException(status_code=404, detail="该智能体未绑定到此项目")

    try:
        backend = get_agent_backend(agent.backend_id)
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filtered, resource_access = await prepare_agent_config_write(
        config_json,
        context_schema=backend.context_schema,
        db=db,
        user=user,
    )
    overrides = merge_agent_config_json(
        binding.config_overrides,
        filtered,
        resource_access=resource_access,
    )
    if reset_fields:
        reset_sections = [field for field in reset_fields if field in _OVERRIDE_SECTION_FIELDS]
        for section in reset_sections:
            overrides.pop(section, None)
        context_fields = [field for field in reset_fields if field not in _OVERRIDE_SECTION_FIELDS]
        declared = filter_declared_config(
            {"context": {field: None for field in context_fields}}, backend.context_schema
        )
        declared_fields = set((declared.get("context") or {}).keys())
        override_context = overrides.get("context")
        if isinstance(override_context, dict):
            for field_name in declared_fields:
                override_context.pop(field_name, None)
    binding.config_overrides = overrides
    binding.updated_by = str(user.uid)
    binding.updated_at = utc_now_naive()
    await db.commit()
    await db.refresh(binding)
    return await _serialize_binding(agent=agent, binding=binding, db=db, user=user, cache={})


async def unbind_project_agent_view(
    *,
    project_id: str,
    agent_slug: str,
    delete_agent: bool,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """解绑项目数字员工；显式请求时删除不再被任何项目绑定的私有 Agent。"""
    project = await _lock_manageable_project(project_id=project_id, db=db, user=user)
    await _lock_agent_binding_mutations(db=db, agent_slug=agent_slug)
    repo = ProjectAgentRepository(db)
    binding = await repo.get_for_update(project.id, agent_slug)
    if binding is None:
        raise HTTPException(status_code=404, detail="该智能体未绑定到此项目")

    agent = await AgentRepository(db).get_by_slug(agent_slug)
    await db.delete(binding)
    await db.flush()

    deleted_agent = False
    if delete_agent:
        if agent is None:
            raise HTTPException(status_code=404, detail="智能体不存在")
        if not user_can_manage_agent(user, agent):
            raise HTTPException(status_code=403, detail="需要该智能体的管理权限才能删除")
        if is_builtin_agent(agent) or agent.is_default:
            raise HTTPException(status_code=409, detail="内置默认智能体不能删除")
        remaining = await repo.list_project_ids_for_agent(agent.slug)
        if remaining:
            raise HTTPException(status_code=409, detail="智能体还绑定在其他项目，不能删除")
        await db.delete(agent)
        deleted_agent = True

    await db.commit()
    return {"message": "解绑成功", "agent_slug": agent_slug, "deleted_agent": deleted_agent}
