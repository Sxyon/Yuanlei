"""Agent 外部执行器委派工具：统一入口委派、查询与回收（yuanlei 域）。

只在带 Project 的根 AgentRun 内重建授权范围；沙盒委派的句柄绑定被委派那一轮，
回收结果物化在 Project Workdir 边界内，不伪造 `agent_runs`，也不反向写治理状态。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.agents.toolkits.buildin.project_run_scope import resolve_project_run_scope
from yuxi.agents.toolkits.registry import tool
from yuxi.delegation.contracts import DelegationError, DelegationRequest
from yuxi.services.delegation_service import DelegationService
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentRun
from yuxi.workspace.workdir import Workdir

DELEGATION_TOOL_NAMES = frozenset(
    {
        "delegation_dispatch",
        "delegation_status",
        "delegation_collect",
        "delegation_list",
    }
)


async def _run_delegation_operation(
    runtime: ToolRuntime,
    operation: Callable[..., Awaitable[dict[str, Any]]],
) -> str:
    """校验运行范围并在独立事务中执行一次委派操作，失败返回结构化 JSON。"""
    try:
        context = getattr(runtime, "context", None)
        if getattr(context, "is_subagent_runtime", False):
            raise ValueError("子智能体不能委派外部执行器")
        run_id = str(getattr(context, "run_id", "") or "")
        uid = str(getattr(context, "uid", "") or "")
        worker_id = str(getattr(context, "worker_id", "") or "")
        if not run_id or not uid or not worker_id:
            raise ValueError("当前运行缺少 Project 上下文")
        async with pg_manager.get_async_session_context() as db:
            project_id, user = await resolve_project_run_scope(
                db=db, run_id=run_id, uid=uid, worker_id=worker_id, resource_label="外部执行器委派"
            )
            return json.dumps(
                await operation(db=db, project_id=project_id, user=user, runtime=runtime, run_id=run_id),
                ensure_ascii=False,
            )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return json.dumps({"error_code": detail.get("code", "delegation_unavailable"), **detail}, ensure_ascii=False)
    except DelegationError as exc:
        return json.dumps({"error_code": exc.error_code, "message": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error_code": "invalid_request", "message": str(exc)}, ensure_ascii=False)


async def _sandbox_metadata(db, runtime: ToolRuntime, run_id: str) -> dict[str, Any]:
    """为沙盒委派收集运行范围引导数据；Multica 委派忽略额外字段。"""
    context = runtime.context
    run = await db.get(AgentRun, str(run_id))
    agent_config = None
    if run is not None:
        from yuxi.repositories.agent_repository import AgentRepository

        agent = await AgentRepository(db).get_by_slug(run.agent_slug)
        agent_config = agent.config_json if agent is not None else None
    return {
        "uid": str(context.uid),
        "thread_id": str(context.thread_id),
        "runtime_scope_id": str(getattr(context, "runtime_scope_id", "") or context.thread_id),
        "workdir_relative_path": str(getattr(context, "workdir_relative_path", "") or ""),
        "conversation_id": run.conversation_id if run is not None else None,
        "agent_config": agent_config,
        "plan_only": True,
    }


async def _project_workdir(db, *, uid: str, project_id: str) -> Workdir:
    """打开当前 Project 的持久化 Workdir，回收结果只在该边界内物化。"""
    from yuxi.storage.postgres.models_business import Project
    from yuxi.workspace.paths import ensure_bound_user_workdir

    project = await db.get(Project, str(project_id))
    if project is None or str(project.uid) != str(uid):
        raise ValueError("Project 不存在")
    ensure_bound_user_workdir(str(uid), str(project.workdir_path))
    return Workdir.open_existing(str(uid), str(project.workdir_path))


def _parse_json_list(raw: str | None, label: str) -> tuple[dict[str, Any], ...]:
    if not raw or not str(raw).strip():
        return ()
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise ValueError(f"{label} 必须是 JSON 对象数组")
    return tuple(parsed)


def _parse_json_object(raw: str | None, label: str) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return parsed


@tool(
    category="buildin",
    tags=["项目", "协同"],
    display_name="委派外部执行器",
)
async def delegation_dispatch(
    executor_key: str,
    task: str,
    context_refs_json: str | None = None,
    budget_json: str | None = None,
    runtime: ToolRuntime = None,
) -> str:
    """把任务委派给已注册的外部执行器（opencode/codex/multica）并返回统一委派视图。

    同一接口委派、同一路径回收；沙盒执行器在专属沙盒内排队被委派的那一轮。
    """

    async def operation(*, db, project_id, user, run_id, runtime):
        service = DelegationService.build_default(db)
        request = DelegationRequest(
            operation_id="",
            project_id=project_id,
            task=task,
            initiator_run_id=str(run_id),
            context_refs=_parse_json_list(context_refs_json, "context_refs_json"),
            budget=_parse_json_object(budget_json, "budget_json"),
            metadata=await _sandbox_metadata(db, runtime, str(run_id)),
        )
        return await service.dispatch(executor_key=executor_key, request=request, uid=str(user.uid))

    return await _run_delegation_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目", "协同"],
    display_name="查询外部委派",
)
async def delegation_status(operation_id: str, runtime: ToolRuntime = None) -> str:
    """读取一条委派事实的统一视图，并刷新远端状态的只读投影。"""

    async def operation(*, db, project_id, user, run_id, runtime):
        return await DelegationService.build_default(db).status(operation_id=operation_id, project_id=project_id)

    return await _run_delegation_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目", "协同"],
    display_name="回收外部委派",
)
async def delegation_collect(operation_id: str, runtime: ToolRuntime = None) -> str:
    """回收被委派操作的结果，文本结果物化在 Project Workdir 内。"""

    async def operation(*, db, project_id, user, run_id, runtime):
        workdir = await _project_workdir(db, uid=str(user.uid), project_id=project_id)
        return await DelegationService.build_default(db).collect(
            operation_id=operation_id, project_id=project_id, workdir=workdir
        )

    return await _run_delegation_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目", "协同"],
    display_name="列出外部委派",
)
async def delegation_list(runtime: ToolRuntime = None) -> str:
    """列出当前 Project 的全部委派事实。"""

    async def operation(*, db, project_id, user, run_id, runtime):
        return await DelegationService.build_default(db).list_delegations(project_id=project_id)

    return await _run_delegation_operation(runtime, operation)


DELEGATION_TOOLS = (
    delegation_dispatch,
    delegation_status,
    delegation_collect,
    delegation_list,
)
