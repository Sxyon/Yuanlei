"""专属沙盒生命周期 supervisor：保活、空闲 suspend 与 inventory 对账。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.sandbox import get_sandbox_provider
from yuxi.config import get_int_env
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.sandbox_lifecycle_service import SandboxLifecycleService
from yuxi.services.sandbox_lease_service import SandboxLeaseService
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentSandbox, Project
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger

DEFAULT_IDLE_SUSPEND_SECONDS = 1800
MIN_IDLE_SUSPEND_SECONDS = 60


def sandbox_lifecycle_interval_seconds() -> int:
    """supervisor 周期（同时作为 keepalive 间隔下限）。"""
    return max(5, get_int_env("SANDBOX_LIFECYCLE_INTERVAL_SECONDS", 60))


def sandbox_idle_suspend_seconds() -> int:
    """记录未显式配置空闲阈值时的系统默认值。"""
    return max(
        MIN_IDLE_SUSPEND_SECONDS,
        get_int_env("SANDBOX_LIFECYCLE_IDLE_SUSPEND_SECONDS", DEFAULT_IDLE_SUSPEND_SECONDS),
    )


async def run_sandbox_lifecycle_tick(
    *,
    db: AsyncSession | None = None,
    provider=None,
    now: datetime | None = None,
) -> dict[str, int]:
    """执行一次收敛：保活、空闲 suspend、容器缺失对账与 generation 更新。

    传入 db 时由调用方负责提交；不传则使用独立事务并提交。
    """
    current_provider = provider if provider is not None else get_sandbox_provider()
    timestamp = now or utc_now_naive()
    if db is not None:
        return await _run_tick(db, current_provider, timestamp)
    async with pg_manager.get_async_session_context() as session:
        counts = await _run_tick(session, current_provider, timestamp)
        await session.commit()
        return counts


async def _run_tick(db: AsyncSession, provider, timestamp: datetime) -> dict[str, int]:
    repo = AgentSandboxRepository(db)
    lifecycle = SandboxLifecycleService(db, provider=provider)
    records = await asyncio.to_thread(provider.list_sandboxes)
    inventory = {record.sandbox_id: record for record in records}
    interval = sandbox_lifecycle_interval_seconds()
    default_idle = sandbox_idle_suspend_seconds()
    counts = {
        "checked": 0,
        "keepalive": 0,
        "suspended": 0,
        "generation_changed": 0,
        "leases_expired": 0,
    }
    counts["leases_expired"] = await SandboxLeaseService(db=db).reconcile_expired(now=timestamp)

    for row in await repo.list_all():
        counts["checked"] += 1
        if row.status != "active":
            continue
        if row.lease_owner_id is not None and row.lease_expires_at is not None and row.lease_expires_at > timestamp:
            # 活跃执行 owner 优先于 idle 策略；supervisor 不得删除其 runtime。
            continue
        try:
            record = inventory.get(row.sandbox_id)
            if record is None:
                await _suspend(row, lifecycle, db, reason="container_missing")
                counts["suspended"] += 1
                continue
            if record.generation and record.generation != row.generation:
                row.generation = record.generation
                row.updated_at = timestamp
                await repo.append_event(
                    sandbox_id=row.sandbox_id,
                    kind="rebuilt",
                    actor_kind="supervisor",
                    payload={"reason": "generation_changed", "generation": record.generation},
                    now=timestamp,
                )
                counts["generation_changed"] += 1
            if row.lifecycle != "resident" and _keepalive_due(row, timestamp, interval):
                alive = await asyncio.to_thread(provider.touch, row.sandbox_id)
                if not alive:
                    await _suspend(row, lifecycle, db, reason="container_missing")
                    counts["suspended"] += 1
                    continue
                row.last_keepalive_at = timestamp
                counts["keepalive"] += 1
            if row.lifecycle != "resident" and _idle_exceeded(row, timestamp, default_idle):
                await _suspend(row, lifecycle, db, reason="idle_suspend")
                counts["suspended"] += 1
                continue
            row.updated_at = timestamp
        except Exception:
            logger.opt(exception=True).error("Sandbox lifecycle tick failed for {}", row.sandbox_id)
    return counts


def _keepalive_due(row: AgentSandbox, timestamp: datetime, interval: int) -> bool:
    if row.last_keepalive_at is None:
        return True
    return (timestamp - row.last_keepalive_at).total_seconds() >= interval


def _idle_exceeded(row: AgentSandbox, timestamp: datetime, default_idle: int) -> bool:
    idle_seconds = row.idle_timeout_seconds if row.idle_timeout_seconds is not None else default_idle
    if idle_seconds <= 0 or row.last_activity_at is None:
        return False
    return (timestamp - row.last_activity_at).total_seconds() >= idle_seconds


async def _suspend(
    row: AgentSandbox,
    lifecycle: SandboxLifecycleService,
    db: AsyncSession,
    *,
    reason: str,
) -> None:
    workdir_path = await db.scalar(select(Project.workdir_path).where(Project.id == str(row.project_id)))
    if not workdir_path:
        raise RuntimeError(f"project {row.project_id} workdir is missing for sandbox {row.sandbox_id}")
    await lifecycle.suspend(
        uid=row.uid,
        agent_slug=row.agent_slug,
        project_id=row.project_id,
        workdir_path=workdir_path,
        reason=reason,
        actor_kind="supervisor",
    )
