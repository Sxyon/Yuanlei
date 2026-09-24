"""专属沙盒执行租约：获取、心跳、释放与过期收敛。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.sandbox import SandboxScope
from yuxi.config import get_int_env
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentSandbox
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger

DEFAULT_LEASE_SECONDS = 120
DEFAULT_WAIT_SECONDS = 600
WAIT_POLL_SECONDS = 2.0


class SandboxBusyError(RuntimeError):
    """执行租约被其他持有者占用且等待超时。"""

    def __init__(
        self,
        *,
        owner_kind: str | None,
        owner_id: str | None,
        expires_at: datetime | None,
    ):
        expires_text = expires_at.isoformat() if expires_at is not None else "unknown"
        super().__init__(f"sandbox_busy: held by {owner_kind}:{owner_id} until {expires_text}")
        self.owner_kind = owner_kind
        self.owner_id = owner_id
        self.expires_at = expires_at


def sandbox_lease_seconds() -> int:
    return max(5, get_int_env("SANDBOX_LEASE_SECONDS", DEFAULT_LEASE_SECONDS))


def sandbox_lease_wait_seconds() -> int:
    return max(0, get_int_env("SANDBOX_LEASE_WAIT_SECONDS", DEFAULT_WAIT_SECONDS))


def sandbox_scope_from_key(scope_key: str | None) -> SandboxScope | None:
    """scope key 为专属形态时解析出 SandboxScope。"""
    runtime_scope_id = str(scope_key or "").strip()
    if not runtime_scope_id.startswith("agent-project:"):
        return None
    return SandboxScope.from_cache_key(runtime_scope_id)


async def sandbox_scope_for_run(db: AsyncSession, run) -> SandboxScope | None:
    """Run 的执行 scope 为专属形态时解析出 SandboxScope（yuanlei 映射优先）。"""
    from yuxi.services.run_scope_service import resolve_run_scope_key

    return sandbox_scope_from_key(await resolve_run_scope_key(db, run))


class SandboxLeaseService:
    """沙盒执行租约的数据库用例；acquire 使用独立事务，获取期间不持有行锁。"""

    def __init__(self, *, db: AsyncSession | None = None):
        self._db = db

    @asynccontextmanager
    async def _session(self):
        if self._db is not None:
            yield self._db, False
            return
        async with pg_manager.get_async_session_context() as db:
            yield db, True

    async def acquire(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: int | None = None,
        wait_timeout_seconds: int | None = None,
        now: datetime | None = None,
    ) -> AgentSandbox:
        """获取执行租约；被占用时按等待窗口轮询，超时抛 SandboxBusyError。"""
        ttl = int(ttl_seconds or sandbox_lease_seconds())
        wait_seconds = int(wait_timeout_seconds) if wait_timeout_seconds is not None else sandbox_lease_wait_seconds()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        waiting_recorded = False
        holder: AgentSandbox | None = None
        while True:
            current_time = now or utc_now_naive()
            acquired, holder = await self._try_acquire(
                uid=uid,
                agent_slug=agent_slug,
                project_id=project_id,
                owner_kind=owner_kind,
                owner_id=owner_id,
                ttl_seconds=ttl,
                current_time=current_time,
            )
            if acquired:
                return holder
            if not waiting_recorded:
                await self._append_event(
                    sandbox_id=holder.sandbox_id,
                    kind="lease_waiting",
                    actor_kind=owner_kind,
                    actor_id=owner_id,
                    payload={
                        "holder_kind": holder.lease_owner_kind,
                        "holder_id": holder.lease_owner_id,
                        "expires_at": holder.lease_expires_at.isoformat() if holder.lease_expires_at else None,
                    },
                    now=current_time,
                )
                waiting_recorded = True
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise SandboxBusyError(
                    owner_kind=holder.lease_owner_kind,
                    owner_id=holder.lease_owner_id,
                    expires_at=holder.lease_expires_at,
                )
            await asyncio.sleep(min(WAIT_POLL_SECONDS, remaining))

    async def heartbeat(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_id: str,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """按持有者续租；所有权不匹配或记录缺失返回 False（fencing）。"""
        ttl = int(ttl_seconds or sandbox_lease_seconds())
        current_time = now or utc_now_naive()
        async with self._session() as (db, own):
            repo = AgentSandboxRepository(db)
            row = await repo.get_for_update(uid=uid, agent_slug=agent_slug, project_id=project_id)
            if (
                row is None
                or row.lease_owner_id != owner_id
                or row.lease_expires_at is None
                or row.lease_expires_at <= current_time
            ):
                return False
            row.lease_expires_at = current_time + timedelta(seconds=ttl)
            row.lease_heartbeat_at = current_time
            row.updated_at = current_time
            await db.flush()
            if own:
                await db.commit()
            return True

    async def owns_active(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_id: str,
        now: datetime | None = None,
    ) -> bool:
        """锁定租约行并验证未过期 owner；供终态写入作为 fencing guard。"""
        current_time = now or utc_now_naive()
        async with self._session() as (db, _own):
            row = await AgentSandboxRepository(db).get_for_update(
                uid=uid,
                agent_slug=agent_slug,
                project_id=project_id,
            )
            return bool(
                row is not None
                and row.lease_owner_id == owner_id
                and row.lease_expires_at is not None
                and row.lease_expires_at > current_time
            )

    async def owns_active_prefix(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_kind: str,
        owner_id_prefix: str,
        now: datetime | None = None,
    ) -> bool:
        """验证指定类型与前缀的活跃 owner；供含 attempt token 的恢复扫描。"""
        current_time = now or utc_now_naive()
        async with self._session() as (db, _own):
            row = await AgentSandboxRepository(db).get_for_update(
                uid=uid,
                agent_slug=agent_slug,
                project_id=project_id,
            )
            return bool(
                row is not None
                and row.lease_owner_kind == owner_kind
                and str(row.lease_owner_id or "").startswith(owner_id_prefix)
                and row.lease_expires_at is not None
                and row.lease_expires_at > current_time
            )

    async def release(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_id: str,
        now: datetime | None = None,
    ) -> bool:
        """释放自己持有的租约；非持有者调用不会窃取，返回 False。"""
        current_time = now or utc_now_naive()
        async with self._session() as (db, own):
            repo = AgentSandboxRepository(db)
            row = await repo.get_for_update(uid=uid, agent_slug=agent_slug, project_id=project_id)
            if row is None or row.lease_owner_id != owner_id:
                return False
            row.lease_owner_kind = None
            row.lease_owner_id = None
            row.lease_expires_at = None
            row.lease_heartbeat_at = None
            row.updated_at = current_time
            await repo.append_event(
                sandbox_id=row.sandbox_id,
                kind="lease_released",
                actor_kind="system",
                actor_id=owner_id,
                now=current_time,
            )
            await db.flush()
            if own:
                await db.commit()
            return True

    async def reconcile_expired(self, *, now: datetime | None = None) -> int:
        """清理过期租约并记录事件；返回清理数量。"""
        current_time = now or utc_now_naive()
        async with self._session() as (db, own):
            repo = AgentSandboxRepository(db)
            candidate_ids = (
                (
                    await db.execute(
                        select(AgentSandbox.id).where(
                            AgentSandbox.lease_owner_id.is_not(None),
                            AgentSandbox.lease_expires_at.is_not(None),
                            AgentSandbox.lease_expires_at < current_time,
                        )
                    )
                )
                .scalars()
                .all()
            )
            reconciled = 0
            for sandbox_id in candidate_ids:
                row = await db.scalar(select(AgentSandbox).where(AgentSandbox.id == sandbox_id).with_for_update())
                if (
                    row is None
                    or row.lease_owner_id is None
                    or row.lease_expires_at is None
                    or row.lease_expires_at >= current_time
                ):
                    continue
                logger.warning(
                    "Reclaiming expired sandbox lease: sandbox=%s owner=%s:%s",
                    row.sandbox_id,
                    row.lease_owner_kind,
                    row.lease_owner_id,
                )
                prior_owner_kind = row.lease_owner_kind
                prior_owner_id = row.lease_owner_id
                row.lease_owner_kind = None
                row.lease_owner_id = None
                row.lease_expires_at = None
                row.lease_heartbeat_at = None
                row.updated_at = current_time
                await repo.append_event(
                    sandbox_id=row.sandbox_id,
                    kind="lease_expired",
                    actor_kind="system",
                    payload={"owner_kind": prior_owner_kind, "owner_id": prior_owner_id},
                    now=current_time,
                )
                reconciled += 1
            await db.flush()
            if own:
                await db.commit()
            return reconciled

    async def _try_acquire(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: int,
        current_time: datetime,
    ) -> tuple[bool, AgentSandbox]:
        async with self._session() as (db, own):
            repo = AgentSandboxRepository(db)
            row = await repo.get_for_update(uid=uid, agent_slug=agent_slug, project_id=project_id)
            if row is None:
                raise ValueError("sandbox binding not found")
            held_by_other = (
                row.lease_owner_id is not None
                and row.lease_owner_id != owner_id
                and row.lease_expires_at is not None
                and row.lease_expires_at > current_time
            )
            if held_by_other:
                return False, row
            newly_acquired = row.lease_owner_id != owner_id
            row.lease_owner_kind = owner_kind
            row.lease_owner_id = owner_id
            row.lease_expires_at = current_time + timedelta(seconds=ttl_seconds)
            row.lease_heartbeat_at = current_time
            row.updated_at = current_time
            if newly_acquired:
                await repo.append_event(
                    sandbox_id=row.sandbox_id,
                    kind="lease_acquired",
                    actor_kind=owner_kind,
                    actor_id=owner_id,
                    now=current_time,
                )
            await db.flush()
            if own:
                await db.commit()
            return True, row

    async def _append_event(
        self, *, sandbox_id: str, kind: str, actor_kind=None, actor_id=None, payload=None, now=None
    ) -> None:
        async with self._session() as (db, own):
            await AgentSandboxRepository(db).append_event(
                sandbox_id=sandbox_id,
                kind=kind,
                actor_kind=actor_kind,
                actor_id=actor_id,
                payload=payload,
                now=now,
            )
            if own:
                await db.commit()


async def acquire_sandbox_lease_for_run(*, run, scope: SandboxScope, project_id: str) -> None:
    """Run 执行前获取专属沙盒租约；busy 由调用方转成显式终态。"""
    await SandboxLeaseService().acquire(
        uid=scope.uid,
        agent_slug=scope.agent_slug or "",
        project_id=project_id,
        owner_kind="run",
        owner_id=str(run.id),
    )


async def renew_sandbox_lease_for_run(*, scope: SandboxScope, owner_id: str, now: datetime | None = None) -> bool:
    return await SandboxLeaseService().heartbeat(
        uid=scope.uid,
        agent_slug=scope.agent_slug or "",
        project_id=scope.project_id or "",
        owner_id=str(owner_id),
        now=now,
    )


async def release_sandbox_lease_for_run(*, scope: SandboxScope, owner_id: str) -> bool:
    return await SandboxLeaseService().release(
        uid=scope.uid,
        agent_slug=scope.agent_slug or "",
        project_id=scope.project_id or "",
        owner_id=str(owner_id),
    )
