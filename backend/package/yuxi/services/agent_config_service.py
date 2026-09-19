from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.agents.backends.sandbox.policy import parse_sandbox_policy
from yuxi.agents.buildin import get_agent_backend
from yuxi.agents.context import BaseContext, filter_config_by_role, resolve_agent_resource_options
from yuxi.agents.presets import discover_agent_presets
from yuxi.coding.credentials import VALID_EXECUTORS
from yuxi.repositories.agent_repository import AGENT_RESOURCE_CONFIG_FIELDS, AgentRepository
from yuxi.storage.postgres.models_business import User


def validate_agent_execution_config(config_json: dict[str, Any]) -> None:
    """校验 sandbox/coding 执行配置块；非法值在写入边界显式失败。"""
    sandbox = config_json.get("sandbox")
    if sandbox is not None:
        if not isinstance(sandbox, dict):
            raise ValueError("sandbox 配置必须是对象")
        parse_sandbox_policy(sandbox)

    coding = config_json.get("coding")
    if coding is None:
        return
    if not isinstance(coding, dict):
        raise ValueError("coding 配置必须是对象")

    executors = coding.get("executors")
    if executors is not None:
        valid = isinstance(executors, list) and all(
            isinstance(item, str) and item.strip().lower() in VALID_EXECUTORS
            for item in executors
        )
        if not valid:
            raise ValueError(f"coding.executors 只能是 {sorted(VALID_EXECUTORS)} 中的执行器")

    default_executor = coding.get("default_executor")
    if default_executor is not None:
        valid = (
            isinstance(default_executor, str)
            and default_executor.strip().lower() in VALID_EXECUTORS
        )
        if not valid:
            raise ValueError(
                f"coding.default_executor 只能是 {sorted(VALID_EXECUTORS)} 中的执行器或 null"
            )


async def prepare_agent_config_write(
    config_json: dict[str, Any],
    *,
    context_schema: type[BaseContext] | None,
    db: AsyncSession,
    user: User,
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    """过滤可写配置，并解析本次资源补丁对应的可访问键。"""
    filtered = filter_config_by_role(config_json, user.role, context_schema)
    validate_agent_execution_config(filtered)
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


async def initialize_agent_presets(db: AsyncSession) -> None:
    """确认所有角色后端存在，再按既有落库规则初始化。"""
    presets = discover_agent_presets()
    for preset in presets:
        get_agent_backend(preset.backend_id)
    repository = AgentRepository(db)
    for preset in presets:
        await repository.ensure_preset(preset)
