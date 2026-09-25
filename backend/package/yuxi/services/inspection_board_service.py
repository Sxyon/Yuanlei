"""督查板只读聚合用例：秘书数字员工与 Dashboard/Taskboard 的单一事实源读视图。

只读聚合治理四表与上游 Run 事实，不写入、不持有执行状态；跨项目视图从当前
用户 selectable Project 直接读取来源，不建立镜像。`open` 指仍待人审核/待决策的
`proposed` 条目，`blockers` 指失败或中断的 Run。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.inspection_board_repository import BLOCKED_RUN_STATUSES, InspectionBoardRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.governance_service import (
    list_governance_decisions,
    list_governance_reports,
    list_governance_tasks,
    list_governance_topics,
)
from yuxi.storage.postgres.models_business import AgentRun, Project, User
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

RECENT_RUN_LIMIT = 20
RECENT_BLOCKED_LIMIT = 10
PENDING_STATUS = "proposed"


def _serialize_run_fact(row: AgentRun) -> dict[str, Any]:
    """把 Run 投影为只读执行事实，不复制终态之外的状态。"""
    return {
        "id": row.id,
        "agent_slug": row.agent_slug,
        "status": row.status,
        "source": row.source,
        "conversation_thread_id": row.conversation_thread_id,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "created_at": format_utc_datetime(row.created_at),
        "finished_at": format_utc_datetime(row.finished_at),
    }


def _pending(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """筛出仍待审核/待决策的 proposed 条目。"""
    return [row for row in rows if row.get("status") == PENDING_STATUS]


def _summarize(boards: list[dict[str, Any]]) -> dict[str, int]:
    """汇总跨项目待决策队列与阻塞项。"""
    return {
        "projects": len(boards),
        "open_topics": sum(len(board["governance"]["pending_topics"]) for board in boards),
        "pending_tasks": sum(len(board["governance"]["pending_tasks"]) for board in boards),
        "pending_decisions": sum(len(board["governance"]["pending_decisions"]) for board in boards),
        "blockers": sum(
            board["execution"]["run_status_counts"].get(status, 0)
            for board in boards
            for status in BLOCKED_RUN_STATUSES
        ),
    }


async def _build_project_board(*, project: Project, db: AsyncSession, user: User) -> dict[str, Any]:
    """读取单个 Project 的治理事实与执行事实，不做任何写入。"""
    project_id = str(project.id)
    uid = str(user.uid)
    topics = await list_governance_topics(project_id=project_id, db=db, user=user)
    tasks = await list_governance_tasks(project_id=project_id, db=db, user=user)
    decisions = await list_governance_decisions(project_id=project_id, db=db, user=user)
    reports = await list_governance_reports(project_id=project_id, db=db, user=user)
    run_repo = InspectionBoardRepository(db)
    recent_runs = await run_repo.list_recent_runs(project_id=project_id, uid=uid, limit=RECENT_RUN_LIMIT)
    blocked_runs = await run_repo.list_blocked_runs(project_id=project_id, uid=uid, limit=RECENT_BLOCKED_LIMIT)
    return {
        "project": {"id": project_id, "name": project.name},
        "governance": {
            "topics": topics,
            "tasks": tasks,
            "decisions": decisions,
            "reports": reports,
            "pending_topics": _pending(topics),
            "pending_tasks": _pending(tasks),
            "pending_decisions": _pending(decisions),
        },
        "execution": {
            "run_status_counts": await run_repo.count_runs_by_status(project_id=project_id, uid=uid),
            "recent_runs": [_serialize_run_fact(row) for row in recent_runs],
            "blocked_runs": [_serialize_run_fact(row) for row in blocked_runs],
        },
    }


async def get_project_inspection_board(*, project_id: str, db: AsyncSession, user: User) -> dict[str, Any]:
    """读取当前用户单个 Project 的督查板视图；不可见项目 404。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    board = await _build_project_board(project=project, db=db, user=user)
    board["generated_at"] = format_utc_datetime(utc_now_naive())
    return board


async def get_user_inspection_board(*, db: AsyncSession, user: User) -> dict[str, Any]:
    """跨项目读取当前用户所有 selectable Project 的 open 议题、待决策队列与阻塞项。"""
    projects = await ProjectRepository(db).list_selectable_for_user(str(user.uid))
    boards = [await _build_project_board(project=project, db=db, user=user) for project in projects]
    return {
        "generated_at": format_utc_datetime(utc_now_naive()),
        "summary": _summarize(boards),
        "projects": boards,
    }
