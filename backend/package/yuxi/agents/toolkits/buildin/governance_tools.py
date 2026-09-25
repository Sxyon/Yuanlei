"""Agent 督查板与治理工具：秘书数字员工只读聚合、写汇报并开议题。

工具在带 Project 的运行中重建授权范围；只读聚合执行事实，写入的汇报只引用产出
Run 与 artifact，不终结、不改写任何 Run 状态。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from langgraph.prebuilt.tool_node import ToolRuntime

from yuxi.agents.toolkits.buildin.project_run_scope import resolve_project_run_scope
from yuxi.agents.toolkits.registry import tool
from yuxi.services.governance_service import create_governance_report, create_governance_topic
from yuxi.services.inspection_board_service import get_project_inspection_board
from yuxi.storage.postgres.manager import pg_manager


async def _run_governance_operation(
    runtime: ToolRuntime,
    operation: Callable[..., Awaitable[dict[str, Any]]],
) -> str:
    """校验运行范围并在独立事务中执行一次治理操作，失败返回结构化 JSON。"""
    try:
        context = getattr(runtime, "context", None)
        if getattr(context, "is_subagent_runtime", False):
            raise ValueError("子智能体不能访问项目督查板或写入治理事实")
        run_id = str(getattr(context, "run_id", "") or "")
        uid = str(getattr(context, "uid", "") or "")
        worker_id = str(getattr(context, "worker_id", "") or "")
        if not run_id or not uid or not worker_id:
            raise ValueError("当前运行缺少 Project 上下文")
        async with pg_manager.get_async_session_context() as db:
            project_id, user = await resolve_project_run_scope(
                db=db, run_id=run_id, uid=uid, worker_id=worker_id, resource_label="项目督查板"
            )
            result = await operation(db=db, project_id=project_id, user=user, run_id=run_id)
            return json.dumps(result, ensure_ascii=False)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return json.dumps(
            {"error_code": detail.get("code", "governance_unavailable"), **detail},
            ensure_ascii=False,
        )
    except ValueError as exc:
        return json.dumps({"error_code": "invalid_request", "message": str(exc)}, ensure_ascii=False)


def _parse_content(content_json: str | None) -> dict[str, Any]:
    """解析可选的结构化汇报载荷 JSON。"""
    raw = str(content_json or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("content_json 必须是 JSON 对象")
    return parsed


@tool(
    category="buildin",
    tags=["项目", "督查"],
    display_name="读取项目督查板",
)
async def governance_board_read(runtime: ToolRuntime = None) -> str:
    """读取当前 Project 的督查板只读视图：议题/任务/决策/汇报与最近 Run、失败。

    秘书数字员工汇总执行面事实、生成周期汇报前使用；只读，不写入也不改写任何 Run
    或治理状态。
    """

    async def operation(*, db, project_id, user, run_id):
        return await get_project_inspection_board(project_id=project_id, db=db, user=user)

    return await _run_governance_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目", "督查"],
    display_name="写入项目汇报",
)
async def governance_report_write(
    title: str,
    summary: str | None = None,
    content_json: str | None = None,
    artifact_path: str | None = None,
    runtime: ToolRuntime = None,
) -> str:
    """把一次督查汇总记录为项目汇报，引用产出 Run 与 artifact 路径。

    只在用户或定时任务要求产出周期汇报时使用。产出 Run 由当前运行自动绑定；本工具
    不终结、不改写任何 Run 状态。artifact_path 为 Workdir 相对产物路径。
    """

    async def operation(*, db, project_id, user, run_id):
        return await create_governance_report(
            project_id=project_id,
            title=title,
            summary=summary,
            content=_parse_content(content_json),
            source_run_id=run_id,
            artifact_path=artifact_path,
            db=db,
            user=user,
        )

    return await _run_governance_operation(runtime, operation)


@tool(
    category="buildin",
    tags=["项目", "督查"],
    display_name="打开项目议题",
)
async def governance_topic_open(
    title: str,
    summary: str | None = None,
    runtime: ToolRuntime = None,
) -> str:
    """由汇报结论打开一个 proposed 项目议题，等待人审核落库。

    只在需要把督查结论转为待决策议题时使用；固定项目内来源，不写 canonical。
    """

    async def operation(*, db, project_id, user, run_id):
        return await create_governance_topic(
            project_id=project_id,
            title=title,
            summary=summary,
            source_channel="project",
            source_external_id=None,
            source_url=None,
            db=db,
            user=user,
        )

    return await _run_governance_operation(runtime, operation)
