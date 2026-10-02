"""第一负责人周期巡检：认领、只读核查、可观察产出与崩溃恢复。"""

from __future__ import annotations

from datetime import timedelta

from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
from yuxi.repositories.project_work_inspection_repository import ProjectWorkInspectionRepository
from yuxi.repositories.user_inbox_repository import UserInboxRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import ProjectWorkTask
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger

MIN_INSPECTION_INTERVAL_MINUTES = 1
MAX_INSPECTION_INTERVAL_MINUTES = 7 * 24 * 60
RECOVER_STALE_SECONDS = 60
INSPECTION_KIND = "task_inspection"

FINDING_IN_PROGRESS_WITHOUT_RUN = "in_progress_without_run"
FINDING_BLOCKED = "blocked"
FINDING_OVERDUE = "overdue"


async def inspect_task(db, task: ProjectWorkTask) -> tuple[str | None, str | None]:
    """只读核查任务状态，返回异常代码与说明；不使用任务状态代替 Run 事实。"""
    if task.status == "in_progress" and not await ProjectWorkExecutionRepository(db).has_active_task_work(task.id):
        return FINDING_IN_PROGRESS_WITHOUT_RUN, "任务标记为进行中，但没有待接受、排队或运行中的执行尝试。"
    if task.status == "blocked":
        return FINDING_BLOCKED, "任务处于受阻状态，需要第一负责人跟进。"
    if task.due_date is not None and task.due_date < utc_now_naive().date():
        return FINDING_OVERDUE, f"任务已过计划结束日期 {task.due_date.isoformat()}，仍未完成。"
    return None, None


async def process_inspection_run(run_id: str) -> None:
    """在单个事务内完成一次巡检：核查、按变化产出通知与评论、落库结论。"""
    async with pg_manager.get_async_session_context() as db:
        repo = ProjectWorkInspectionRepository(db)
        run = await repo.get_run_for_update(run_id)
        if run is None or run.status != "claimed":
            return
        now = utc_now_naive()
        task = await repo.get_task(run.task_id)
        if task is None:
            run.status = "failed"
            run.summary = "任务不存在"
            run.inspected_at = now
            run.updated_at = now
            await db.commit()
            return
        finding, summary = await inspect_task(db, task)
        if finding is not None and finding != await repo.last_completed_finding(task.id):
            owner = task.primary_owner_agent_slug
            display_name = await repo.get_agent_name(owner) or owner
            await repo.append_comment(
                task_id=task.id,
                content=f"自动巡检发现异常：{summary}",
                author_uid=f"agent:{owner}"[:64],
                author_name=f"{display_name} · 自动巡检",
            )
            await UserInboxRepository(db).record_occurrence(
                uid=task.created_by,
                kind=INSPECTION_KIND,
                source_id=run.id,
                project_id=task.project_id,
                title=f"任务巡检提醒：{task.title}",
                summary=summary,
            )
        run.finding = finding
        run.summary = summary
        run.status = "completed"
        run.inspected_at = now
        run.updated_at = now
        await db.commit()


async def run_project_work_inspection_tick(*, limit: int = 20) -> int:
    """批量认领到期巡检并产出结果；重复 tick 由 occurrence 唯一约束保证幂等。"""
    processed = 0
    for _ in range(max(0, limit)):
        async with pg_manager.get_async_session_context() as db:
            repo = ProjectWorkInspectionRepository(db)
            task = await repo.claim_due_task(now=utc_now_naive())
            if task is None:
                break
            scheduled_for = task.inspection_next_run_at
            now = utc_now_naive()
            task.inspection_next_run_at = scheduled_for + timedelta(minutes=task.inspection_interval_minutes)
            task.updated_at = now
            run = await repo.add_run(
                task=task,
                occurrence_key=f"scheduled:{scheduled_for.isoformat()}",
                created_at=now,
            )
            run_id = run.id
            await db.commit()
        try:
            await process_inspection_run(run_id)
        except Exception:
            logger.error(f"执行项目任务巡检失败: inspection_run={run_id}", exc_info=True)
        processed += 1
    return processed


async def recover_stale_inspections(*, limit: int = 100) -> int:
    """恢复 worker 崩溃后遗留的待处理巡检，避免重复产出。"""
    async with pg_manager.get_async_session_context() as db:
        rows = await ProjectWorkInspectionRepository(db).list_recoverable_runs(
            before=utc_now_naive() - timedelta(seconds=RECOVER_STALE_SECONDS),
            limit=limit,
        )
        run_ids = [row.id for row in rows]
    recovered = 0
    for run_id in run_ids:
        try:
            await process_inspection_run(run_id)
            recovered += 1
        except Exception:
            logger.error(f"恢复项目任务巡检失败: inspection_run={run_id}", exc_info=True)
    return recovered
