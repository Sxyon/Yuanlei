"""Agent 专属沙盒的生命周期用例：策略解析、ensure_ready、suspend 与事件。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.sandbox import SandboxConnection, SandboxScope, get_sandbox_provider
from yuxi.agents.backends.sandbox.policy import SandboxPolicy, resolve_sandbox_policy
from yuxi.repositories.agent_repository import AgentRepository
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.storage.postgres.models_business import AgentSandbox
from yuxi.utils.datetime_utils import utc_now_naive


class SandboxRebuildConfirmationRequired(RuntimeError):
    """resume_policy=confirm 时，suspend 后必须由用户确认才能重建。"""

    def __init__(self, *, scope_key: str, sandbox_id: str, suspended_at: datetime | None):
        super().__init__(f"sandbox rebuild requires confirmation for scope {scope_key}")
        self.scope_key = scope_key
        self.sandbox_id = sandbox_id
        self.suspended_at = suspended_at


DEFAULT_DEDICATED_MAX_PER_USER = 3
DEFAULT_RESIDENT_MAX_PER_USER = 1


class SandboxQuotaExceededError(RuntimeError):
    """用户专属/常驻沙盒数量超过系统配额。"""

    error_code = "sandbox_quota_exceeded"

    def __init__(self, *, limit_key: str, limit: int, current: int):
        super().__init__(f"sandbox_quota_exceeded: {limit_key} limit={limit} current={current}")
        self.limit_key = limit_key
        self.limit = limit
        self.current = current


async def sandbox_quota_limits(db: AsyncSession) -> tuple[int, int]:
    """读取管理员配置的每用户配额上限（记录缺失时用默认值）。"""
    from yuxi.config.options import get_option, system_options

    record = await get_option(db, system_options.key)
    stored = dict(record.value or {}) if record is not None else {}
    resolved = system_options.resolve(stored)
    dedicated = resolved.get("sandbox_dedicated_max_per_user")
    resident = resolved.get("sandbox_resident_max_per_user")
    return (
        int(dedicated) if dedicated is not None else DEFAULT_DEDICATED_MAX_PER_USER,
        int(resident) if resident is not None else DEFAULT_RESIDENT_MAX_PER_USER,
    )


async def enforce_sandbox_quota(db: AsyncSession, *, uid: str, policy: SandboxPolicy) -> None:
    """创建新专属沙盒前强制每用户配额；已有记录不计新增。"""
    if not policy.is_dedicated:
        return
    rows = (await db.execute(select(AgentSandbox).where(AgentSandbox.uid == str(uid)))).scalars().all()
    dedicated_max, resident_max = await sandbox_quota_limits(db)
    if len(rows) >= dedicated_max:
        raise SandboxQuotaExceededError(
            limit_key="sandbox_dedicated_max_per_user",
            limit=dedicated_max,
            current=len(rows),
        )
    if policy.lifecycle == "resident":
        resident_count = sum(1 for row in rows if row.lifecycle == "resident")
        if resident_count >= resident_max:
            raise SandboxQuotaExceededError(
                limit_key="sandbox_resident_max_per_user",
                limit=resident_max,
                current=resident_count,
            )


async def resolve_agent_sandbox_policy(
    *,
    db: AsyncSession,
    agent_config: dict | None,
    agent_slug: str,
    project_id: str | None,
) -> SandboxPolicy:
    """读取 agent 默认与项目覆盖层，解析出本次生效的沙盒策略。"""
    agent_block = (agent_config or {}).get("sandbox")
    project_block = None
    if project_id:
        binding = await ProjectAgentRepository(db).get(str(project_id), agent_slug)
        if binding is not None:
            raw = (binding.config_overrides or {}).get("sandbox")
            project_block = raw if isinstance(raw, dict) else None
    return resolve_sandbox_policy(agent_block=agent_block, project_block=project_block)


def runtime_scope_for_policy(
    *,
    uid: str,
    agent_slug: str,
    project_id: str,
    conversation_thread_id: str,
    policy: SandboxPolicy,
) -> str:
    """按策略给出 Run 的 runtime_scope_id；shared 保持会话线程。"""
    if not policy.is_dedicated:
        return str(conversation_thread_id)
    return SandboxScope.agent_project(uid=uid, agent_slug=agent_slug, project_id=project_id).cache_key


async def resolve_dispatch_runtime_scope(
    *,
    db: AsyncSession,
    uid: str,
    agent_slug: str,
    project_id: str,
    conversation_thread_id: str,
) -> str:
    """派发/恢复 Run 时解析策略并返回持久 runtime scope。"""
    agent = await AgentRepository(db).get_by_slug(agent_slug)
    policy = await resolve_agent_sandbox_policy(
        db=db,
        agent_config=(agent.config_json if agent is not None else None),
        agent_slug=agent_slug,
        project_id=project_id,
    )
    return runtime_scope_for_policy(
        uid=uid,
        agent_slug=agent_slug,
        project_id=project_id,
        conversation_thread_id=conversation_thread_id,
        policy=policy,
    )


class SandboxLifecycleService:
    """专属沙盒的 ensure_ready / suspend 用例；事务提交由调用方决定。"""

    def __init__(self, db: AsyncSession, *, provider=None):
        self.db = db
        self.repo = AgentSandboxRepository(db)
        self._provider = provider

    @property
    def provider(self):
        return self._provider if self._provider is not None else get_sandbox_provider()

    async def ensure_binding(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        policy: SandboxPolicy,
    ) -> AgentSandbox:
        """只物化专属沙盒持久绑定，不创建、释放或重建 runtime。"""
        row, _created = await self._ensure_binding(
            uid=uid,
            agent_slug=agent_slug,
            project_id=project_id,
            policy=policy,
        )
        return row

    async def _ensure_binding(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        policy: SandboxPolicy,
    ) -> tuple[AgentSandbox, bool]:
        if not policy.is_dedicated:
            raise ValueError("ensure_binding requires a dedicated sandbox policy")
        scope = SandboxScope.agent_project(uid=uid, agent_slug=agent_slug, project_id=project_id)
        row = await self.repo.get_for_update(uid=uid, agent_slug=agent_slug, project_id=project_id)
        created = row is None
        if row is None:
            await enforce_sandbox_quota(db=self.db, uid=uid, policy=policy)
            row = await self.repo.add(
                uid=uid,
                agent_slug=agent_slug,
                project_id=project_id,
                scope_key=scope.cache_key,
                sandbox_id=scope.sandbox_id,
                lifecycle=policy.lifecycle,
                resume_policy=policy.resume_policy,
                idle_timeout_seconds=policy.provisioner_idle_timeout,
            )
        else:
            self._apply_policy(row, policy)
        return row, created

    async def ensure_ready(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        policy: SandboxPolicy,
        workdir_path: str | None,
        credential_fingerprint: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> SandboxConnection:
        """确保专属沙盒可用：复用、按策略重建，或抛出需要确认的异常。"""
        if not policy.is_dedicated:
            raise ValueError("ensure_ready requires a dedicated sandbox policy")
        scope = SandboxScope.agent_project(uid=uid, agent_slug=agent_slug, project_id=project_id)
        row, created = await self._ensure_binding(
            uid=uid,
            agent_slug=agent_slug,
            project_id=project_id,
            policy=policy,
        )
        if created:
            return await self._rebuild(
                row=row,
                scope=scope,
                policy=policy,
                workdir_path=workdir_path,
                credential_fingerprint=credential_fingerprint,
                env_overrides=env_overrides,
                event_kind="created",
            )

        if row.status == "suspended":
            return await self._resume_or_raise(
                row=row,
                scope=scope,
                policy=policy,
                workdir_path=workdir_path,
                credential_fingerprint=credential_fingerprint,
                env_overrides=env_overrides,
            )

        connection = self.provider.get_scope(scope, create_if_missing=False, workdir_path=workdir_path)
        if connection is None:
            await self._mark_suspended(row, reason="container_missing")
            return await self._resume_or_raise(
                row=row,
                scope=scope,
                policy=policy,
                workdir_path=workdir_path,
                credential_fingerprint=credential_fingerprint,
                env_overrides=env_overrides,
            )
        if credential_fingerprint is not None and row.credential_fingerprint != credential_fingerprint:
            await self.suspend(
                uid=uid,
                agent_slug=agent_slug,
                project_id=project_id,
                workdir_path=workdir_path,
                reason="credential_changed",
                actor_kind="system",
            )
            return await self._resume_or_raise(
                row=row,
                scope=scope,
                policy=policy,
                workdir_path=workdir_path,
                credential_fingerprint=credential_fingerprint,
                env_overrides=env_overrides,
            )
        self._touch_row(row, connection)
        return connection

    async def suspend(
        self,
        *,
        uid: str,
        agent_slug: str,
        project_id: str,
        workdir_path: str | None,
        reason: str,
        actor_kind: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        """释放 runtime 并把记录收敛为 suspended；容器已不存在时幂等成功。"""
        scope = SandboxScope.agent_project(uid=uid, agent_slug=agent_slug, project_id=project_id)
        row = await self.repo.get_for_update(uid=uid, agent_slug=agent_slug, project_id=project_id)
        if row is None:
            raise ValueError("sandbox binding not found")
        if row.status != "suspended":
            self.provider.release_scope(scope, workdir_path=workdir_path)
            await self._mark_suspended(row, reason=reason, actor_kind=actor_kind, actor_id=actor_id)

    async def _resume_or_raise(
        self,
        *,
        row: AgentSandbox,
        scope: SandboxScope,
        policy: SandboxPolicy,
        workdir_path: str | None,
        credential_fingerprint: str | None,
        env_overrides: dict[str, str] | None = None,
    ) -> SandboxConnection:
        if policy.resume_policy == "confirm":
            raise SandboxRebuildConfirmationRequired(
                scope_key=row.scope_key,
                sandbox_id=row.sandbox_id,
                suspended_at=row.suspended_at,
            )
        return await self._rebuild(
            row=row,
            scope=scope,
            policy=policy,
            workdir_path=workdir_path,
            credential_fingerprint=credential_fingerprint,
            env_overrides=env_overrides,
            event_kind="rebuilt",
        )

    async def _rebuild(
        self,
        *,
        row: AgentSandbox,
        scope: SandboxScope,
        policy: SandboxPolicy,
        workdir_path: str | None,
        credential_fingerprint: str | None,
        env_overrides: dict[str, str] | None = None,
        event_kind: str,
    ) -> SandboxConnection:
        connection = self.provider.get_scope(
            scope,
            create_if_missing=True,
            workdir_path=workdir_path,
            lifecycle=policy.lifecycle,
            idle_timeout_seconds=policy.provisioner_idle_timeout,
            env_overrides=env_overrides,
        )
        if connection is None:
            raise RuntimeError("sandbox provider failed to create a dedicated sandbox")
        now = utc_now_naive()
        row.status = "active"
        row.generation = connection.generation
        row.suspended_at = None
        row.error_code = None
        row.error_message = None
        row.last_activity_at = now
        row.last_keepalive_at = now
        row.updated_at = now
        if credential_fingerprint is not None:
            row.credential_fingerprint = credential_fingerprint
        await self.repo.append_event(
            sandbox_id=row.sandbox_id,
            kind=event_kind,
            actor_kind="system",
            payload={"generation": connection.generation},
            now=now,
        )
        return connection

    async def _mark_suspended(
        self,
        row: AgentSandbox,
        *,
        reason: str,
        actor_kind: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        now = utc_now_naive()
        row.status = "suspended"
        row.generation = None
        row.suspended_at = now
        row.updated_at = now
        await self.repo.append_event(
            sandbox_id=row.sandbox_id,
            kind="suspended",
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload={"reason": reason},
            now=now,
        )

    @staticmethod
    def _apply_policy(row: AgentSandbox, policy: SandboxPolicy) -> None:
        row.lifecycle = policy.lifecycle
        row.resume_policy = policy.resume_policy
        row.idle_timeout_seconds = policy.provisioner_idle_timeout
        row.updated_at = utc_now_naive()

    @staticmethod
    def _touch_row(row: AgentSandbox, connection: SandboxConnection) -> None:
        now = utc_now_naive()
        row.generation = connection.generation or row.generation
        row.last_activity_at = now
        row.updated_at = now
