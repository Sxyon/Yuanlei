"""督查板只读正式工作、业务结果、治理与执行事实。

工作受阻只取正式工作blocked；执行异常按每项工作两类入口的最新尝试判定，
旧异常保留历史。统计与分页从同一授权集合派生，不写入进度或图关系副本。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.inspection_board_repository import InspectionBoardRepository
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


def _page(items: list[dict], *, offset: int = 0, limit: int = 5) -> dict:
    """统计与分页使用同一筛选集合。"""
    return {"total": len(items), "offset": offset, "limit": limit, "items": items[offset : offset + limit]}


async def _read_overview(*, project_id: str, db: AsyncSession, governance: dict) -> tuple[dict, dict]:
    """从正式工作与结果派生只读概览，当前关联与冻结依据分开。"""
    repo = InspectionBoardRepository(db)
    base = f"/projects/{project_id}"
    today = utc_now_naive().date()
    works = await repo.list_work_facts(project_id=project_id)
    for row in works:
        row["overdue"] = row["status"] not in {"done", "cancelled"} and bool(
            row["due_date"] and row["due_date"] < today
        )
        row["due_date"] = row["due_date"].isoformat() if row["due_date"] else None
        row["updated_at"] = format_utc_datetime(row["updated_at"])
        row["url"] = f"{base}/work/tasks/{row['id']}"
    results = await repo.list_result_facts(project_id=project_id)
    for row in results:
        row["created_at"] = format_utc_datetime(row["created_at"])
        row["url"] = f"{base}/work/tasks/{row['task_id']}#work-result-{row['id']}"
        source_id = row["source_execution_id"] or row["source_delegation_id"]
        prefix = "execution" if row["source_execution_id"] else "delegation"
        row["history_url"] = f"{base}/work/tasks/{row['task_id']}#work-{prefix}-{source_id}" if source_id else None
    pending = []
    for key, kind, query in (
        ("pending_topics", "topic", "topic_id"),
        ("pending_tasks", "suggestion", "task_id"),
        ("pending_decisions", "decision", "decision_id"),
    ):
        pending.extend(
            {**row, "kind": kind, "url": f"{base}/inspection?{query}={row['id']}"} for row in governance[key]
        )
    pending.sort(key=lambda row: (row.get("created_at") or "", row["id"]), reverse=True)
    counts = {
        status: sum(row["status"] == status for row in works)
        for status in ("todo", "in_progress", "blocked", "done", "cancelled")
    }
    pending_results = [row for row in results if row["status"] == "pending"]
    attempts = await repo.list_attempt_facts(project_id=project_id)
    current, historical, seen = [], [], set()
    for row in attempts:
        key = (row["kind"], row["task_id"])
        latest = key not in seen
        seen.add(key)
        abnormal = row["status"] in {"failed", "interrupted"} or row.get("remote_status") in {"failed", "interrupted"}
        if not abnormal:
            continue
        row["created_at"] = format_utc_datetime(row["created_at"])
        row["url"] = f"{base}/work/tasks/{row['task_id']}#work-{row['kind']}-{row['id']}"
        (current if latest and row["work_status"] not in {"done", "cancelled"} else historical).append(row)
    for rows in (current, historical):
        rows.sort(key=lambda row: (row["created_at"] or "", row["id"]), reverse=True)
    feedbacks = await repo.list_feedback_facts(project_id=project_id)
    for row in feedbacks:
        row["created_at"] = format_utc_datetime(row["created_at"])
        row["url"] = f"{base}/inspection?topic_id={row['topic_id']}"
        row["result_url"] = f"{base}/work/tasks/{row['task_id']}#work-result-{row['result_id']}"
    collections = {
        "pending": pending,
        "work": works,
        "results": pending_results,
        "exceptions": current,
        "historical_exceptions": historical,
        "feedback": feedbacks,
    }
    overview = {key: _page(rows) for key, rows in collections.items()}
    overview.update(as_of_date=today.isoformat(), timezone="UTC")
    overview["pending"]["counts"] = {
        key: len(governance[key]) for key in ("pending_topics", "pending_tasks", "pending_decisions")
    }
    overview["work"].update(
        status_counts=counts, blocked_count=counts["blocked"], overdue_count=sum(row["overdue"] for row in works)
    )
    overview["results"]["work_count"] = len({row["task_id"] for row in pending_results})
    graph = {"work": _page(works, limit=10), "results": _page(results, limit=10), "feedback": feedbacks}
    return {"overview": overview, "graph": graph}, collections


def _summarize(boards: list[dict[str, Any]]) -> dict[str, int]:
    """跨项目聚合正式工作与业务结果，历史Run不作为业务阻塞。"""
    return {
        "projects": len(boards),
        "open_topics": sum(len(b["governance"]["open_topics"]) for b in boards),
        "pending_topics": sum(b["overview"]["pending"]["counts"]["pending_topics"] for b in boards),
        "pending_tasks": sum(b["overview"]["pending"]["counts"]["pending_tasks"] for b in boards),
        "pending_decisions": sum(b["overview"]["pending"]["counts"]["pending_decisions"] for b in boards),
        "blockers": sum(b["overview"]["work"]["blocked_count"] for b in boards),
        "overdue_work": sum(b["overview"]["work"]["overdue_count"] for b in boards),
        "pending_results": sum(b["overview"]["results"]["total"] for b in boards),
        "pending_result_work": sum(b["overview"]["results"]["work_count"] for b in boards),
        "current_exceptions": sum(b["overview"]["exceptions"]["total"] for b in boards),
    }


async def _build_project_board(*, project: Project, db: AsyncSession, user: User) -> tuple[dict, dict]:
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
    board = {
        "project": {"id": project_id, "name": project.name},
        "governance": {
            "topics": topics,
            "tasks": tasks,
            "decisions": decisions,
            "reports": reports,
            "pending_topics": [t for t in topics if t["admission_status"] == "proposed"],
            "open_topics": [t for t in topics if t["progress"] == "open"],
            "pending_tasks": [row for row in tasks if row["status"] in {"proposed", "canonical"} and not row["work"]],
            "pending_decisions": [row for row in decisions if row["status"] == "draft"],
        },
        "execution": {
            "run_status_counts": await run_repo.count_runs_by_status(project_id=project_id, uid=uid),
            "recent_runs": [_serialize_run_fact(row) for row in recent_runs],
            "blocked_runs": [_serialize_run_fact(row) for row in blocked_runs],
        },
    }

    facts, collections = await _read_overview(project_id=project_id, db=db, governance=board["governance"])
    board.update(facts)
    return board, collections


async def get_project_inspection_board(*, project_id: str, db: AsyncSession, user: User) -> dict[str, Any]:
    """读取当前用户单个 Project 的督查板视图；不可见项目 404。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    board, _ = await _build_project_board(project=project, db=db, user=user)
    board["generated_at"] = format_utc_datetime(utc_now_naive())
    return board


async def get_user_inspection_board(*, db: AsyncSession, user: User) -> dict[str, Any]:
    """跨项目读取当前用户可见项目的待处理、正式工作与业务结果。"""
    projects = await ProjectRepository(db).list_selectable_for_user(str(user.uid))
    boards = [(await _build_project_board(project=project, db=db, user=user))[0] for project in projects]
    return {
        "generated_at": format_utc_datetime(utc_now_naive()),
        "summary": _summarize(boards),
        "projects": boards,
    }


async def list_project_overview(
    *, project_id: str, section: str, offset: int, limit: int, db: AsyncSession, user: User
) -> dict:
    """读取与默认卡片同口径的授权分页列表。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    board, collections = await _build_project_board(project=project, db=db, user=user)
    return {
        **_page(collections[section], offset=offset, limit=limit),
        "as_of_date": board["overview"]["as_of_date"],
        "timezone": "UTC",
    }
