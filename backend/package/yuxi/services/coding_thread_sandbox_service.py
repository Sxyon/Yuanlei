"""会话视角的专属沙盒状态与终端直达用例。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.agents.backends.sandbox import SandboxScope
from yuxi.coding.terminal_ticket import DEFAULT_TICKET_TTL_SECONDS, issue_terminal_ticket
from yuxi.repositories.agent_repository import AgentRepository
from yuxi.repositories.agent_sandbox_repository import AgentSandboxRepository
from yuxi.repositories.conversation_repository import ConversationRepository
from yuxi.services.coding_credential_service import CodingCredentialService
from yuxi.services.coding_session_service import CodingSessionService
from yuxi.services.sandbox_lifecycle_service import (
    SandboxLifecycleService,
    resolve_agent_sandbox_policy,
)
from yuxi.services.workdir_service import resolve_conversation_workdir_path
from yuxi.storage.postgres.models_business import CodingSession


class CodingThreadSandboxError(RuntimeError):
    """会话沙盒不可用（线程无效或非专属）。"""

    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class CodingThreadSandboxService:
    """把专属沙盒状态与终端入口暴露到具体会话。"""

    def __init__(self, db: AsyncSession, *, provider=None):
        self.db = db
        self._provider = provider

    async def _conversation_context(self, *, uid: str, thread_id: str):
        conversation = await ConversationRepository(self.db).get_conversation_by_thread_id(
            str(thread_id)
        )
        if conversation is None or str(conversation.uid) != str(uid):
            raise CodingThreadSandboxError("会话不存在", status_code=404)
        agent = await AgentRepository(self.db).get_by_slug(str(conversation.agent_id or ""))
        policy = await resolve_agent_sandbox_policy(
            db=self.db,
            agent_config=(agent.config_json if agent is not None else None),
            agent_slug=str(conversation.agent_id or ""),
            project_id=str(conversation.project_id or "") or None,
        )
        return conversation, agent, policy

    async def status(self, *, uid: str, thread_id: str) -> dict:
        """会话侧沙盒摘要：非专属返回 enabled=false，不做任何沙盒写操作。"""
        conversation, _agent, policy = await self._conversation_context(
            uid=uid, thread_id=thread_id
        )
        base = {
            "enabled": False,
            "mode": policy.mode,
            "agent_slug": conversation.agent_id,
            "project_id": conversation.project_id,
            "sandbox": None,
            "scope_key": None,
        }
        if not policy.is_dedicated or not conversation.project_id:
            return base
        agent_slug = str(conversation.agent_id or "")
        project_id = str(conversation.project_id)
        scope = SandboxScope.agent_project(
            uid=str(uid), agent_slug=agent_slug, project_id=project_id
        )
        row = await AgentSandboxRepository(self.db).get_for_update(
            uid=str(uid), agent_slug=agent_slug, project_id=project_id
        )
        base["enabled"] = True
        base["scope_key"] = scope.cache_key
        if row is not None:
            base["sandbox"] = {
                "sandbox_id": row.sandbox_id,
                "status": row.status,
                "lifecycle": row.lifecycle,
                "generation": row.generation,
                "last_activity_at": (
                    row.last_activity_at.isoformat() if row.last_activity_at else None
                ),
                "lease_owner_kind": row.lease_owner_kind,
            }
        return base

    async def _ensure_runtime(self, *, uid: str, thread_id: str):
        """解析会话的专属 scope 并确保 runtime 就绪，返回复用所需上下文。"""
        conversation, agent, policy = await self._conversation_context(
            uid=uid, thread_id=thread_id
        )
        if not policy.is_dedicated or not conversation.project_id:
            raise CodingThreadSandboxError("该会话未使用专属沙盒")
        agent_slug = str(conversation.agent_id or "")
        project_id = str(conversation.project_id)
        scope = SandboxScope.agent_project(
            uid=str(uid), agent_slug=agent_slug, project_id=project_id
        )
        workdir_path = await resolve_conversation_workdir_path(
            conversation=conversation, uid=str(uid), db=self.db
        )
        credentials = CodingCredentialService(self.db)
        settings = await credentials.resolve_settings(
            agent_config=(agent.config_json if agent is not None else None),
            agent_slug=agent_slug,
            project_id=project_id,
        )
        environment = await credentials.build_coding_environment(
            uid=str(uid), executors=list(settings.executors)
        )
        await SandboxLifecycleService(self.db, provider=self._provider).ensure_ready(
            uid=str(uid),
            agent_slug=agent_slug,
            project_id=project_id,
            policy=policy,
            workdir_path=workdir_path,
            credential_fingerprint=environment.fingerprint,
            env_overrides=environment.env,
        )
        return {
            "scope_key": scope.cache_key,
            "agent_slug": agent_slug,
            "project_id": project_id,
            "workdir_path": workdir_path,
            "executor": settings.default_executor or (settings.executors[0] if settings.executors else "opencode"),
        }

    async def open_terminal(self, *, uid: str, thread_id: str) -> dict:
        """按会话解析专属 scope，确保 runtime 就绪后签发终端门票。"""
        ready = await self._ensure_runtime(uid=uid, thread_id=thread_id)
        scope_key = str(ready["scope_key"])
        project_id = str(ready["project_id"])
        executor = str(ready["executor"])
        workdir_path = str(ready["workdir_path"])
        session = await self._reuse_terminal_session(
            uid=str(uid),
            scope_key=scope_key,
            executor=executor,
            project_id=project_id,
            workdir_path=workdir_path,
        )
        await self.db.commit()
        ticket = issue_terminal_ticket(uid=str(uid), session_id=session.id)
        return {
            "session_id": session.id,
            "ticket": ticket,
            "ws_path": f"/api/coding/sessions/{session.id}/terminal?ticket={ticket}",
            "expires_in": DEFAULT_TICKET_TTL_SECONDS,
        }

    async def _reuse_terminal_session(
        self,
        *,
        uid: str,
        scope_key: str,
        executor: str,
        project_id: str,
        workdir_path: str,
    ) -> CodingSession:
        existing = await self.db.scalar(
            select(CodingSession)
            .where(
                CodingSession.uid == str(uid),
                CodingSession.runtime_scope_id == str(scope_key),
                CodingSession.status.in_(("pending", "idle")),
            )
            .order_by(CodingSession.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return existing
        return await CodingSessionService(self.db).create_session(
            uid=str(uid),
            project_id=str(project_id),
            runtime_scope_id=str(scope_key),
            executor=str(executor),
            workdir_path=str(workdir_path),
            title="终端会话",
            policy={"executor": executor, "source": "terminal"},
        )
