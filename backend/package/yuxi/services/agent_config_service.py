from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.agents.context import BaseContext, filter_config_by_role, resolve_agent_resource_options
from yuxi.repositories.agent_repository import AGENT_RESOURCE_CONFIG_FIELDS
from yuxi.storage.postgres.models_business import User


async def prepare_agent_config_write(
    config_json: dict[str, Any],
    *,
    context_schema: type[BaseContext] | None,
    db: AsyncSession,
    user: User,
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """过滤可写配置，并解析本次资源补丁对应的可访问键。"""
    filtered = filter_config_by_role(config_json, user.role, context_schema)
    context = filtered.get("context")
    if not isinstance(context, dict):
        return filtered, {}

    submitted_fields = {
        field_name
        for field_name in AGENT_RESOURCE_CONFIG_FIELDS & context.keys()
        if isinstance(context[field_name], list) and context[field_name]
    }
    if not submitted_fields:
        return filtered, {}

    option_fields = submitted_fields - {"preload_skills"}
    if "preload_skills" in submitted_fields:
        option_fields.add("skills")
    options = await resolve_agent_resource_options(option_fields, db=db, user=user)

    resource_access: dict[str, set[str]] = {}
    for field_name in submitted_fields:
        option_field = "skills" if field_name == "preload_skills" else field_name
        if option_field not in options:
            raise RuntimeError(f"智能体资源字段 {field_name} 缺少权限解析结果")
        resource_access[field_name] = {option["key"] for option in options[option_field]}
    return filtered, resource_access
