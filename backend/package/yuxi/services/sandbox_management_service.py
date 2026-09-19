"""专属沙盒管理用例：用户视图、配额用量、手动回收与重建。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.sandbox import SandboxScope, get_sandbox_provider
from yuxi.repositories.agent_repository import AgentRepository
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.services.coding_credential_service import CodingCredentialService
from yuxi.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    resolve_agent_sandbox_policy,
    sandbox_quota_limits,
)
from yuxi.storage.postgres.models_business import AgentSandbox, Project


def _sandbox_view(row: AgentSandbox) -> dict:
    return {
        "agent_slug": row.agent_slug,
        "project_id": row.project_id,
        "scope_key": row.scope_key,
        "sandbox_id": row.sandbox_id,
        "lifecycle": row.lifecycle,
        "resume_policy": row.resume_policy,
        "status": row.status,
        "generation": row.generation,
        "idle_timeout_seconds": row.idle_timeout_seconds,
        "credential_fingerprint": row.credential_fingerprint,
        "lease_owner_kind": row.lease_owner_kind,
        "lease_owner_id": row.lease_owner_id,
        "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
        "suspended_at": row.suspended_at.isoformat() if row.suspended_at else None,
        "error_code": row.error_code,
    }


class SandboxManagementService:
    """读视图与手动操作；手动操作同样走生命周期状态机与事件。"""

    def __init__(self, db: AsyncSession, *, provider=None):
        self.db = db
        self._provider = provider

    @property
    def provider(self):
        return self._provider if self._provider is not None else get_sandbox_provider()

    async def list_user_sandboxes(self, *, uid: str) -> dict:
        rows = (
            await self.db.execute(
                select(AgentSandbox)
                .where(AgentSandbox.uid == str(uid))
                .order_by(AgentSandbox.updated_at.desc(), AgentSandbox.id.desc())
            )
        ).scalars().all()
        dedicated_max, resident_max = await sandbox_quota_limits(self.db)
        active = [row for row in rows if row.status == "active"]
        resident = [row for row in rows if row.lifecycle == "resident" and row.status != "error"]
        return {
            "sandboxes": [_sandbox_view(row) for row in rows],
            "quota": {
                "dedicated_max_per_user": dedicated_max,
                "resident_max_per_user": resident_max,
                "dedicated_used": len(rows),
                "resident_used": len(resident),
                "active": len(active),
            },
        }

    async def _project_workdir(self, *, uid: str, project_id: str) -> str:
        workdir = await self.db.scalar(
            select(Project.workdir_path).where(
                Project.id == str(project_id), Project.uid == str(uid)
            )
        )
        if not workdir:
            raise ValueError("project not found for sandbox management")
        return str(workdir)

    async def suspend(self, *, uid: str, agent_slug: str, project_id: str) -> dict:
        """手动回收 runtime；保留记录，下次使用按 resume_policy 重建。"""
        workdir = await self._project_workdir(uid=uid, project_id=project_id)
        await SandboxLifecycleService(self.db, provider=self.provider).suspend(
            uid=str(uid),
            agent_slug=str(agent_slug),
            project_id=str(project_id),
            workdir_path=workdir,
            reason="manual_suspend",
            actor_kind="user",
            actor_id=str(uid),
        )
        await self.db.commit()
        row = await AgentSandboxRepository(self.db).get_for_update(
            uid=str(uid), agent_slug=str(agent_slug), project_id=str(project_id)
        )
        return _sandbox_view(row) if row is not None else {}

    async def rebuild(self, *, uid: str, agent_slug: str, project_id: str) -> dict:
        """手动重建：先回收旧 runtime，再按当前策略与凭据重建。"""
        workdir = await self._project_workdir(uid=uid, project_id=project_id)
        agent = await AgentRepository(self.db).get_by_slug(str(agent_slug))
        policy = await resolve_agent_sandbox_policy(
            db=self.db,
            agent_config=(agent.config_json if agent is not None else None),
            agent_slug=str(agent_slug),
            project_id=str(project_id),
        )
        if not policy.is_dedicated:
            raise ValueError("agent does not use a dedicated sandbox")
        credentials = CodingCredentialService(self.db)
        env, fingerprint = await credentials.build_coding_environment(
            uid=str(uid),
            executors=credentials.declared_executors(
                agent.config_json if agent is not None else None
            ),
        )
        lifecycle = SandboxLifecycleService(self.db, provider=self.provider)
        await lifecycle.suspend(
            uid=str(uid),
            agent_slug=str(agent_slug),
            project_id=str(project_id),
            workdir_path=workdir,
            reason="manual_rebuild",
            actor_kind="user",
            actor_id=str(uid),
        )
        connection = await lifecycle.ensure_ready(
            uid=str(uid),
            agent_slug=str(agent_slug),
            project_id=str(project_id),
            policy=policy,
            workdir_path=workdir,
            credential_fingerprint=fingerprint,
            env_overrides=env,
        )
        await self.db.commit()
        row = await AgentSandboxRepository(self.db).get_for_update(
            uid=str(uid), agent_slug=str(agent_slug), project_id=str(project_id)
        )
        view = _sandbox_view(row) if row is not None else {}
        view["generation"] = connection.generation or view.get("generation")
        return view

    @staticmethod
    def scope_for(*, uid: str, agent_slug: str, project_id: str) -> SandboxScope:
        return SandboxScope.agent_project(
            uid=uid, agent_slug=agent_slug, project_id=project_id
        )
