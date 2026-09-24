"""Agent 项目 Dashboard 读写工具：只在带 Project 的运行中解析范围并重新授权。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from langgraph.prebuilt.tool_node import ToolRuntime
from sqlalchemy import select

from yuxi.agents.toolkits.registry import tool
from yuxi.repositories.user_repository import UserRepository
from yuxi.services.project_dashboard_service import (
    get_project_dashboard_view,
    write_project_dashboard_view,
)
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentRun, Conversation, Project, User
from yuxi.utils.datetime_utils import utc_now_naive


async def _resolve_project_scope(*, db, run_id: str, uid: str, worker_id: str) -> tuple[str, User]:
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
        .with_for_update(of=AgentRun)
    )
    result = (await db.execute(statement)).one_or_none()
    if result is None:
        raise ValueError("当前运行无权访问项目 Dashboard")
    run, conversation, project = result
    if run.run_type == "subagent" or conversation.status == "subagent" or run.status != "running":
        raise ValueError("只有正在执行的根 AgentRun 可以访问项目 Dashboard")
    if (
        run.worker_id != worker_id
        or run.lease_expires_at is None
        or run.lease_expires_at <= utc_now_naive()
    ):
        raise ValueError("只有当前有效 AgentRun lease owner 可以访问项目 Dashboard")
    user = await UserRepository().get_by_uid_with_db(db, uid)
    if user is None:
        raise ValueError("当前用户不存在")
    return str(project.id), user


async def _run_dashboard_operation(
    runtime: ToolRuntime,
    operation: Callable[..., Awaitable[dict[str, Any]]],
) -> str:
    """校验运行范围并在独立事务中执行一次 Dashboard 操作，失败返回结构化 JSON。"""
    try:
        context = getattr(runtime, "context", None)
        if getattr(context, "is_subagent_runtime", False):
            raise ValueError("子智能体不能读取或修改项目 Dashboard")
        run_id = str(getattr(context, "run_id", "") or "")
        uid = str(getattr(context, "uid", "") or "")
        worker_id = str(getattr(context, "worker_id", "") or "")
        if not run_id or not uid or not worker_id:
            raise ValueError("当前运行缺少 Project 上下文")
        async with pg_manager.get_async_session_context() as db:
            project_id, user = await _resolve_project_scope(db=db, run_id=run_id, uid=uid, worker_id=worker_id)
            result = await operation(db=db, project_id=project_id, user=user)
            return json.dumps(result, ensure_ascii=False)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return json.dumps(
            {"error_code": detail.get("code", "dashboard_unavailable"), **detail},
            ensure_ascii=False,
        )
    except ValueError as exc:
        return json.dumps({"error_code": "invalid_request", "message": str(exc)}, ensure_ascii=False)


@tool(
    category="buildin",
    tags=["项目"],
    display_name="读取项目 Dashboard",
)
async def dashboard_read(runtime: ToolRuntime = None) -> str:
    """读取当前 Project 的静态 Dashboard 页面状态、revision、hash 与 HTML。

    仅在用户明确要求查看、创建或修改项目 Dashboard 时使用；不修改任何数据。
    """

    async def operation(*, db, project_id, user):
        return await get_project_dashboard_view(project_id=project_id, db=db, user=user)

    return await _run_dashboard_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目"],
    display_name="更新项目 Dashboard",
)
async def dashboard_write(
    html: str,
    expected_revision: int,
    runtime: ToolRuntime = None,
) -> str:
    """用完整静态 HTML/CSS 创建或更新当前 Project 的 Dashboard 入口页面。

    仅在用户明确要求生成或修改项目 Dashboard 时使用。必须携带提交前读到的
    revision。第一版不支持脚本、动态 bridge 或 iframe 内数据读取；返回
    revision_conflict 时先调用 dashboard_read 读取最新页面，合并用户要求后重新提交，不能自动重试旧内容。
    """

    async def operation(*, db, project_id, user):
        return await write_project_dashboard_view(
            project_id=project_id,
            expected_revision=expected_revision,
            html=html,
            db=db,
            user=user,
        )

    return await _run_dashboard_operation(runtime, operation)
