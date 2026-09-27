"""Agent 项目 Dashboard 读写工具：只在带 Project 的运行中解析范围并重新授权。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.agents.toolkits.buildin.project_run_scope import resolve_project_run_scope
from yuxi.agents.toolkits.registry import tool
from yuxi.services.project_dashboard_service import (
    get_project_dashboard_view,
    write_project_dashboard_view,
)
from yuxi.storage.postgres.manager import pg_manager


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
            project_id, user = await resolve_project_run_scope(
                db=db, run_id=run_id, uid=uid, worker_id=worker_id, resource_label="项目 Dashboard"
            )
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
