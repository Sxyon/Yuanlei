"""外部执行器委派与 Multica 入向同步的真实 PostgreSQL 集成测试。

覆盖统一接口委派、operation_id search-before-create、本地状态与远端投影分离、
结果物化边界、崩溃后可观察收敛，以及入向只产生 proposed 与游标去重。
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.delegation.contracts import (
    DelegationError,
    DelegationHandle,
    DelegationLeaseLostError,
    DelegationRequest,
    DelegationResult,
    ExecutorUnavailableError,
)
from yuxi.delegation.multica import MulticaExecutor, MulticaIssue
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.services.channel_sync_service import ChannelSyncService
from yuxi.services.delegation_service import DelegationService
from yuxi.services.governance_service import create_governance_topic
from yuxi.services.governance_service import create_governance_task, admit_governance_task
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import (
    AgentRun,
    ChannelDelegation,
    GovernanceTopic,
    User,
)
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.workdir import Workdir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离 Schema 测试不依赖运行中的 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 测试没有 HTTP 资源需要清理。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 测试没有 Sandbox 资源需要清理。"""
    yield


def _scoped_manager(engine) -> PostgresManager:
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    return manager


@asynccontextmanager
async def _scoped_database(prefix: str):
    """创建独立 PostgreSQL Schema 的业务表，并在退出时清理。"""
    schema = f"{prefix}_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = _scoped_manager(scoped_engine)
        await manager.create_business_tables()
        yield manager, async_sessionmaker(scoped_engine, expire_on_commit=False)
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def _seed_scope(engine, *, uid: str = "uid-owner", project_id: str = "project-owner") -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES (:username, :uid, 'x', 'user', 0, 0)"
            ),
            {"username": f"user-{uid}", "uid": uid},
        )
        await connection.execute(
            text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                "VALUES (:project_id, :uid, 'Pytest', 'selectable', :workdir, 'managed')"
            ),
            {"project_id": project_id, "uid": uid, "workdir": f"projects/{project_id}"},
        )
        await connection.execute(text("INSERT INTO project_work_tasks(id,project_id,number,title,status,created_by,created_at,updated_at) VALUES (:id,:p,'TEST-GEN-000001','正式工作','todo',:uid,NOW(),NOW())"), {"id": project_id + "-work", "p": project_id, "uid": uid})


async def _load_user(session, uid: str = "uid-owner") -> User:
    user = await session.scalar(select(User).where(User.uid == uid))
    assert user is not None
    return user


class _StubExecutor:
    """不接触外部系统的统一接口替身，用于验证编排与状态分离。"""

    def __init__(self, key: str = "stub", *, result: DelegationResult | None = None, fail: bool = False):
        self.key = key
        self.dispatched: list[str] = []
        self._result = result or DelegationResult(summary="done", text="stub result\n")
        self._fail = fail

    def capabilities(self) -> dict[str, bool]:
        return {"multi_turn": False, "remote_artifacts": False}

    async def dispatch(self, request: DelegationRequest) -> DelegationHandle:
        self.dispatched.append(request.operation_id)
        if self._fail:
            raise DelegationError("stub dispatch failed", error_code="stub_failed")
        return DelegationHandle(
            operation_id=request.operation_id,
            executor_key=self.key,
            external_ref="stub-1",
            remote_status="todo",
        )

    async def status(self, handle: DelegationHandle) -> str | None:
        return "done"

    async def collect(self, handle: DelegationHandle) -> DelegationResult:
        return self._result


class _FakeMulticaClient:
    """内存 Multica 客户端；按 updated_at 倒序分页，记录创建次数以证明 search-before-create。"""

    def __init__(self):
        self.issues: list[MulticaIssue] = []
        self.create_calls = 0
        self.calls = 0

    async def create_issue(self, *, title: str, description: str) -> MulticaIssue:
        self.calls += 1
        self.create_calls += 1
        issue = MulticaIssue(
            id=f"id-{self.create_calls}",
            identifier=f"YL-{self.create_calls}",
            title=title,
            description=description,
            status="todo",
            url=f"https://multica.invalid/issues/YL-{self.create_calls}",
            updated_at=f"2026-09-25T00:00:0{self.create_calls}Z",
        )
        self.issues.append(issue)
        return issue

    async def get_issue(self, *, issue_ref: str) -> MulticaIssue:
        self.calls += 1
        return next(issue for issue in self.issues if issue.identifier == issue_ref)

    async def search_issues(self, *, query: str, limit: int = 20) -> list[MulticaIssue]:
        self.calls += 1
        return [issue for issue in self.issues if query in issue.description][:limit]

    async def list_issues(self, *, limit: int = 50, offset: int = 0) -> list[MulticaIssue]:
        self.calls += 1
        ordered = sorted(self.issues, key=lambda issue: (issue.updated_at or "", issue.id), reverse=True)
        return ordered[offset : offset + limit]


async def test_project_task_delegation_requires_review_and_keeps_task_link() -> None:
    """仅已审核且已指派的项目任务能委派，读模型可回读来源任务。"""
    async with _scoped_database("pytest_project_task_delegation") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with manager.async_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO agents
                    (slug, backend_id, name, pics, config_json, share_config, is_default, is_subagent)
                    VALUES ('project-worker', 'ChatbotAgent', 'Worker', '[]'::jsonb,
                    '{"coding": {"executors": ["codex"]}}'::jsonb,
                    CAST(:share_config AS jsonb), FALSE, FALSE)"""
                ),
                {
                    "share_config": json.dumps(
                        {
                            "version": 2,
                            "read_scope": {"access_level": "user", "user_uids": ["uid-owner"]},
                            "manage_scope": {"access_level": "user", "user_uids": ["uid-owner"]},
                        }
                    )
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                    "VALUES ('binding-1', 'project-owner', 'project-worker', '{}'::jsonb)"
                )
            )
        async with sessions() as db:
            user = await _load_user(db)
            task = await create_governance_task(
                project_id="project-owner",
                title="交付功能",
                description="写完并验证",
                topic_id=None,
                decision_id=None,
                assignee_agent_slug="project-worker",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            service = DelegationService(db, executors=[_StubExecutor("codex")])
            with pytest.raises(HTTPException) as pending:
                await service.dispatch_project_task(
                    project_id="project-owner", task_id=task["id"], executor_key="codex", user=user
                )
            assert pending.value.status_code == 409

            admitted = await admit_governance_task(project_id="project-owner", task_id=task["id"], mode="link", work_task_id="project-owner-work", db=db, user=user)
            await db.execute(text("UPDATE project_work_tasks SET title='交付功能', description='写完并验证', primary_owner_agent_slug='project-worker' WHERE id='project-owner-work'"))
            await db.commit()
            task_id = admitted["work"]["id"]
            await db.execute(
                text(
                    "UPDATE agents SET share_config = "
                    "jsonb_set(share_config, '{manage_scope,user_uids}', CAST(:uids AS jsonb)) "
                    "WHERE slug = 'project-worker'"
                ),
                {"uids": json.dumps(["another-user"])},
            )
            await db.commit()
            with pytest.raises(HTTPException) as revoked:
                await service.dispatch_work_task(
                    project_id="project-owner", task_id=task_id, executor_key="codex", user=user
                )
            assert revoked.value.status_code == 403
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 0

            await db.execute(
                text(
                    "UPDATE agents SET share_config = "
                    "jsonb_set(share_config, '{manage_scope,user_uids}', CAST(:uids AS jsonb)) "
                    "WHERE slug = 'project-worker'"
                ),
                {"uids": json.dumps(["uid-owner"])},
            )
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            await db.execute(
                text(
                    "UPDATE agents SET share_config = "
                    "jsonb_set(share_config, '{read_scope,user_uids}', CAST(:uids AS jsonb)) "
                    "WHERE slug = 'project-worker'"
                ),
                {"uids": json.dumps(["another-user"])},
            )
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            with pytest.raises(HTTPException) as invisible:
                await service.dispatch_work_task(
                    project_id="project-owner", task_id=task_id, executor_key="codex", user=user
                )
            assert invisible.value.status_code == 409
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 0

            await db.execute(
                text(
                    "UPDATE agents SET share_config = "
                    "jsonb_set(share_config, '{read_scope,user_uids}', CAST(:uids AS jsonb)) "
                    "WHERE slug = 'project-worker'"
                ),
                {"uids": json.dumps(["uid-owner"])},
            )
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            await db.execute(text(
                "UPDATE project_agents SET config_overrides = "
                "'{\"coding\": {\"default_executor\": \"codex\"}}'::jsonb WHERE id = 'binding-1'"
            ))
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            with pytest.raises(HTTPException) as disabled_executor:
                await service.dispatch_work_task(
                    project_id="project-owner", task_id=task_id, executor_key="opencode", user=user
                )
            assert disabled_executor.value.status_code == 422
            assert disabled_executor.value.detail["code"] == "executor_not_enabled"
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 0
            await db.execute(text(
                "UPDATE project_agents SET config_overrides = "
                "'{\"coding\": {\"executors\": []}}'::jsonb WHERE id = 'binding-1'"
            ))
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            with pytest.raises(HTTPException) as empty_executors:
                await service.dispatch_work_task(
                    project_id="project-owner", task_id=task_id, executor_key="codex", user=user
                )
            assert empty_executors.value.status_code == 422
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 0
            await db.execute(text(
                "UPDATE project_agents SET config_overrides = "
                "'{\"coding\": {\"default_executor\": \"codex\"}}'::jsonb WHERE id = 'binding-1'"
            ))
            await db.commit()
            db.expire_all()
            await db.refresh(user)
            view = await service.dispatch_work_task(
                project_id="project-owner", task_id=task_id, executor_key="codex", user=user
            )
            assert view["work_task_id"] == task_id
            assert view["task"] == "交付功能\n\n写完并验证"
            assert (await service.list_delegations(project_id="project-owner"))[0]["work_task_id"] == task_id


async def test_failed_dispatch_rolls_back_partial_executor_writes() -> None:
    """执行器失败时只保留投递意图和错误，不提交半成品副作用。"""
    async with _scoped_database("pytest_dispatch_rollback") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:

            class PartialExecutor(_StubExecutor):
                """先写入未提交渠道行再模拟执行器失败。"""

                async def dispatch(self, request):
                    await db.execute(
                        text(
                            "INSERT INTO channel_sync_cursors (id, channel, project_id, created_at, updated_at) "
                            "VALUES ('partial-cursor', 'multica', 'project-owner', NOW(), NOW())"
                        )
                    )
                    raise DelegationError("partial failure", error_code="partial_failure")

            service = DelegationService(db, executors=[PartialExecutor("codex")])
            with pytest.raises(DelegationError):
                await service.dispatch(
                    executor_key="codex",
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="只留下意图", metadata={"work_task_id": "project-owner-work"}),
                    uid="uid-owner",
                )
            assert await db.scalar(text("SELECT COUNT(*) FROM channel_sync_cursors")) == 0
            assert (
                await db.scalar(text("SELECT COUNT(*) FROM channel_delegations WHERE error_code='partial_failure'"))
                == 1
            )


async def test_failed_recovery_rolls_back_partial_executor_writes() -> None:
    """恢复重投失败时不提交执行器半成品，并保留可观察的 pending 错误。"""
    async with _scoped_database("pytest_recovery_rollback") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            await ChannelDelegationRepository(db).add_delegation(
                operation_id="recover-1",
                project_id="project-owner",
                executor_key="codex",
                task="恢复任务",
                request_json={"metadata": {}},
                initiator_run_id=None,
                created_by="uid-owner",
            )
            await db.commit()

            class PartialExecutor(_StubExecutor):
                """模拟恢复期间先写入半成品再报错。"""

                async def dispatch(self, request):
                    await db.execute(
                        text(
                            "INSERT INTO channel_sync_cursors (id, channel, project_id, created_at, updated_at) "
                            "VALUES ('partial-recovery', 'multica', 'project-owner', NOW(), NOW())"
                        )
                    )
                    raise DelegationError("partial recovery", error_code="partial_recovery")

            counts = await DelegationService(db, executors=[PartialExecutor("codex")]).converge()
            assert counts["failed"] == 1
            assert await db.scalar(text("SELECT COUNT(*) FROM channel_sync_cursors")) == 0
            row = await ChannelDelegationRepository(db).get_by_operation_id(operation_id="recover-1")
            assert row.dispatch_state == "pending"
            assert row.error_code == "executor_dispatch_failed"


async def test_dispatch_persists_intent_unified_view_and_executor_unavailable() -> None:
    """先持久化投递意图；未注册执行器结构化失败；同一接口可委派不同执行器。"""
    async with _scoped_database("pytest_delegation_dispatch") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            stub = _StubExecutor("opencode")
            failing = _StubExecutor("codex", fail=True)
            service = DelegationService(db, executors=[stub, failing])

            view = await service.dispatch(
                executor_key="opencode",
                request=DelegationRequest(operation_id="", project_id="project-owner", task="做一件事", metadata={"work_task_id": "project-owner-work"}),
                uid="uid-owner",
            )
            assert view["dispatch_state"] == "dispatched"
            assert view["executor_key"] == "opencode"
            assert view["external_ref"] == "stub-1"
            assert view["remote_status"] == "todo"
            assert stub.dispatched == [view["operation_id"]]

            with pytest.raises(DelegationError) as failed:
                await service.dispatch(
                    executor_key="codex",
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="失败任务", metadata={"work_task_id": "project-owner-work"}),
                    uid="uid-owner",
                )
            assert failed.value.error_code == "stub_failed"
            rows = await db.scalars(select(ChannelDelegation).where(ChannelDelegation.executor_key == "codex"))
            beta_row = list(rows)[0]
            assert beta_row.dispatch_state == "pending"
            assert beta_row.error_code == "stub_failed"
            assert beta_row.lease_expires_at is None

            with pytest.raises(ExecutorUnavailableError) as unavailable:
                await service.dispatch(
                    executor_key="missing",
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="x", metadata={"work_task_id": "project-owner-work"}),
                    uid="uid-owner",
                )
            assert unavailable.value.error_code == "executor_unavailable"
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 2


async def test_multica_search_before_create_adopts_lost_response() -> None:
    """同一 operation_id 崩溃后重投经标记核对采纳已有工作项，不产生第二个。"""
    async with _scoped_database("pytest_delegation_multica") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            service = DelegationService(db, executors=[MulticaExecutor(client)])
            view = await service.dispatch(
                executor_key="multica",
                request=DelegationRequest(operation_id="", project_id="project-owner", task="委派远端", metadata={"work_task_id": "project-owner-work"}),
                uid="uid-owner",
            )
            assert client.create_calls == 1
            assert view["external_ref"] == "YL-1"

            # 模拟「远端已创建但句柄未落库」：把本地行退回 pending。
            row = await ChannelDelegationRepository(db).get_by_operation_id(
                operation_id=view["operation_id"], for_update=True
            )
            row.dispatch_state = "pending"
            row.external_ref = None
            row.external_url = None
            row.remote_status = None
            row.owner_token = None
            row.lease_expires_at = None
            await db.commit()

            counts = await service.converge()
            assert counts["redispatched"] == 1
            assert client.create_calls == 1
            refreshed = await ChannelDelegationRepository(db).get_by_operation_id(operation_id=view["operation_id"])
            assert refreshed.dispatch_state == "dispatched"
            assert refreshed.external_ref == "YL-1"


async def test_local_state_and_remote_projection_stay_separate() -> None:
    """刷新远端只读投影不改写 dispatch_state，也不产生新的 agent_runs。"""
    async with _scoped_database("pytest_delegation_projection") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            service = DelegationService(db, executors=[MulticaExecutor(client)])
            view = await service.dispatch(
                executor_key="multica",
                request=DelegationRequest(operation_id="", project_id="project-owner", task="远端任务", metadata={"work_task_id": "project-owner-work"}),
                uid="uid-owner",
            )
            client.issues[0] = MulticaIssue(
                id="id-1", identifier="YL-1", title="远端任务", description="x", status="done", url=None
            )
            runs_before = await db.scalar(select(func.count()).select_from(AgentRun))
            refreshed = await service.status(operation_id=view["operation_id"], project_id="project-owner")
            assert refreshed["remote_status"] == "done"
            assert refreshed["dispatch_state"] == "dispatched"
            assert await db.scalar(select(func.count()).select_from(AgentRun)) == runs_before


async def test_collect_materializes_inside_workdir_boundary() -> None:
    """回收文本结果物化在 Workdir 内，越界路径被边界拒绝。"""
    async with _scoped_database("pytest_delegation_workdir") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        uid = "uid-owner"
        tmp_root = Path(os.environ.get("TMPDIR", "/tmp")) / f"yuanlei-delegation-{uuid.uuid4().hex}"
        (tmp_root / "shared" / uid / "workspace" / "projects" / "project-owner").mkdir(parents=True)
        os.environ["YUXI_USER_DATA_DIR"] = str(tmp_root)
        try:
            async with sessions() as db:
                service = DelegationService(
                    db,
                    executors=[_StubExecutor("opencode", result=DelegationResult(summary="ok", text="回收内容"))],
                )
                view = await service.dispatch(
                    executor_key="opencode",
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="任务", metadata={"work_task_id": "project-owner-work"}),
                    uid=uid,
                )
                workdir = Workdir.open_existing(uid, "projects/project-owner")
                collected = await service.collect(
                    operation_id=view["operation_id"], project_id="project-owner", workdir=workdir
                )
                assert collected["dispatch_state"] == "reclaimed"
                artifact = collected["artifact_path"]
                assert artifact == f".yuanlei/delegations/{view['operation_id']}/result.md"
                assert (workdir.read_file(f"/{artifact}", max_bytes=1024)).decode() == "回收内容"

                with pytest.raises(ValueError):
                    workdir.replace_file("/../escape.md", b"x")
        finally:
            os.environ.pop("YUXI_USER_DATA_DIR", None)


async def test_converge_resets_interrupted_collecting_row() -> None:
    """崩溃中断的 collecting 行由确定性收敛复位为可回收状态。"""
    async with _scoped_database("pytest_delegation_converge") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            service = DelegationService(db, executors=[_StubExecutor("opencode")])
            view = await service.dispatch(
                executor_key="opencode",
                request=DelegationRequest(operation_id="", project_id="project-owner", task="任务", metadata={"work_task_id": "project-owner-work"}),
                uid="uid-owner",
            )
            row = await ChannelDelegationRepository(db).get_by_operation_id(
                operation_id=view["operation_id"], for_update=True
            )
            row.dispatch_state = "collecting"
            await db.commit()
            counts = await service.converge()
            assert counts["released"] == 1
            refreshed = await ChannelDelegationRepository(db).get_by_operation_id(operation_id=view["operation_id"])
            assert refreshed.dispatch_state == "dispatched"
            assert refreshed.owner_token is None


async def test_multica_inbound_sync_only_proposed_and_deduped_by_cursor() -> None:
    """入向同步只创建 proposed；重复拉取按外部标识去重并推进游标。"""
    async with _scoped_database("pytest_channel_sync") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            await client.create_issue(title="远端议题一", description="来自 Multica")
            await client.create_issue(title="远端议题二", description="来自 Multica")
            service = ChannelSyncService(db, client=client)

            first = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner")
            assert first["imported"] == 2
            assert first["skipped"] == 0

            topics = list(await db.scalars(select(GovernanceTopic)))
            assert len(topics) == 2
            assert {topic.status for topic in topics} == {"proposed"}
            assert {topic.source_channel for topic in topics} == {"multica"}

            # 崩溃后重跑：游标已推进到最新，边界秒重复项靠去重跳过，不再新增落库。
            second = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner")
            assert second["imported"] == 0
            assert second["skipped"] == 1
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 2
            cursor = await service.get_cursor(project_id="project-owner")
            assert cursor is not None
            assert json.loads(cursor["cursor"]) == {"id": "id-2", "updated_at": "2026-09-25T00:00:02.000000+00:00"}


async def test_multica_inbound_sync_pages_past_limit_without_cursor_skip() -> None:
    """待取回项超过单页 limit 时，有界分页取回全部且游标不跳过后续项。"""
    async with _scoped_database("pytest_channel_sync_pages") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            for index in range(3):
                await client.create_issue(title=f"远端议题{index}", description="来自 Multica")
            service = ChannelSyncService(db, client=client)

            result = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert result["imported"] == 3
            assert result["skipped"] == 0
            assert json.loads(result["cursor"]) == {"id": "id-3", "updated_at": "2026-09-25T00:00:03.000000+00:00"}
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 3

            follow_up = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert follow_up["imported"] == 0
            assert follow_up["skipped"] == 1


async def test_multica_inbound_sync_full_duplicate_page_advances_cursor() -> None:
    """整页命中重复时仍把游标推进到该页最大 updated_at，下一次不再重取整页。"""
    async with _scoped_database("pytest_channel_sync_dupe") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            await client.create_issue(title="远端议题一", description="来自 Multica")
            await client.create_issue(title="远端议题二", description="来自 Multica")
            actor = await _load_user(db)
            for issue in client.issues:
                await create_governance_topic(
                    project_id="project-owner",
                    title=issue.title,
                    summary=issue.description,
                    source_channel="multica",
                    source_external_id=issue.identifier,
                    source_url=issue.url,
                    db=db,
                    user=actor,
                )
            service = ChannelSyncService(db, client=client)

            first = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert first["imported"] == 0
            assert first["skipped"] == 2
            cursor = await service.get_cursor(project_id="project-owner")
            assert cursor is not None
            assert json.loads(cursor["cursor"]) == {"id": "id-2", "updated_at": "2026-09-25T00:00:02.000000+00:00"}

            second = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert second["imported"] == 0
            assert second["skipped"] == 1


async def test_multica_inbound_sync_holds_cursor_when_page_cap_hit(monkeypatch) -> None:
    """触顶分页上限时保持原游标并显式告警，不把游标推进到已取回页而静默跳过未取回项。"""
    warnings: list[str] = []
    monkeypatch.setattr(
        "yuxi.services.channel_sync_service.logger.warning",
        lambda message, *args: warnings.append(message.format(*args)),
    )
    async with _scoped_database("pytest_channel_sync_cap") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            for index in range(3):
                await client.create_issue(title=f"远端议题{index}", description="来自 Multica")
            monkeypatch.setattr("yuxi.services.channel_sync_service.MULTICA_SYNC_MAX_PAGES", 1)
            service = ChannelSyncService(db, client=client)

            # 待取回 3 项、单页 limit 2、页上限 1：满页触顶，本轮只导入一页。
            result = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert result["imported"] == 2
            assert result["skipped"] == 0
            # 未确认整批取回 → 游标保持原值（未初始化仍为空），不前进到该页最大 updated_at。
            assert result["cursor"] is None
            assert "页上限" in result["error"]
            assert any("hit page cap" in message for message in warnings)
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 2

            cursor = await service.get_cursor(project_id="project-owner")
            assert cursor is not None and cursor["cursor"] is None
            assert cursor["last_synced_at"] is None
            assert "页上限" in cursor["last_error"]

            # 游标未推进 → 下一轮重取同页（此处命中 409 去重），证明未静默跳过未取回项。
            follow_up = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert follow_up["imported"] == 0
            assert follow_up["skipped"] == 2
            assert follow_up["cursor"] is None


async def test_multica_expired_owner_cannot_overwrite_new_cursor_owner() -> None:
    """旧同步租约过期后不得清除新同步的 owner 与游标。"""
    async with _scoped_database("pytest_channel_sync_fencing") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as first_db, sessions() as second_db:
            first = ChannelSyncService(first_db, client=_FakeMulticaClient())
            second = ChannelSyncService(second_db, client=_FakeMulticaClient())
            old = await first._claim_cursor(project_id="project-owner")
            old_token = old.owner_token
            await first_db.execute(
                text("UPDATE channel_sync_cursors SET lease_expires_at = :expired"),
                {"expired": utc_now_naive() - timedelta(seconds=1)},
            )
            await first_db.commit()

            current = await second._claim_cursor(project_id="project-owner")
            assert current.owner_token != old_token
            current.cursor_value = "2026-09-25T00:00:02Z"
            await second_db.commit()

            with pytest.raises(DelegationLeaseLostError):
                await first._finish_cursor(
                    project_id="project-owner",
                    owner_token=old_token,
                    cursor_value="2026-09-25T00:00:03Z",
                    last_error=None,
                )
            retained = await ChannelDelegationRepository(second_db).get_cursor_for_update(
                channel="multica", project_id="project-owner"
            )
            assert retained.owner_token == current.owner_token
            assert retained.cursor_value == "2026-09-25T00:00:02Z"


async def test_multica_converge_does_not_release_owner_claimed_after_listing(monkeypatch) -> None:
    """worker 列表读取后被新 owner 认领的游标，不得按旧快照释放。"""
    async with _scoped_database("pytest_channel_sync_reclaim_race") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as first_db, sessions() as second_db:
            first = ChannelSyncService(first_db, client=_FakeMulticaClient())
            second = ChannelSyncService(second_db, client=_FakeMulticaClient())
            cursor = await first._claim_cursor(project_id="project-owner")
            await first_db.execute(
                text("UPDATE channel_sync_cursors SET lease_expires_at = :expired"),
                {"expired": utc_now_naive() - timedelta(seconds=1)},
            )
            await first_db.commit()
            await first_db.refresh(cursor)

            original_list = first.repo.list_cursors_for_channel
            new_token = None

            async def list_then_reclaim(*, channel):
                nonlocal new_token
                rows = await original_list(channel=channel)
                reclaimed = await second._claim_cursor(project_id="project-owner")
                new_token = reclaimed.owner_token
                return rows

            monkeypatch.setattr(first.repo, "list_cursors_for_channel", list_then_reclaim)
            counts = await first.converge()

            assert counts["released"] == 0
            assert counts["failed"] == 1
            retained = await ChannelDelegationRepository(second_db).get_cursor_for_update(
                channel="multica", project_id="project-owner"
            )
            assert retained.owner_token == new_token


async def test_multica_inbound_sync_same_updated_at_boundary_not_lost() -> None:
    """同一 updated_at 下不同 id：边界秒内的新项不被游标漏掉，也不重复落库。"""
    async with _scoped_database("pytest_channel_sync_ties") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            for suffix in ("a", "b"):
                client.issues.append(
                    MulticaIssue(
                        id=f"id-{suffix}",
                        identifier=f"YL-tie-{suffix}",
                        title=f"同秒 {suffix}",
                        description="来自 Multica",
                        status="todo",
                        url=f"https://multica.invalid/issues/YL-tie-{suffix}",
                        updated_at="2026-09-25T00:00:05Z",
                    )
                )
            service = ChannelSyncService(db, client=client)

            first = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=1)
            assert first["imported"] == 2
            assert first["skipped"] == 0
            assert json.loads(first["cursor"]) == {"id": "id-b", "updated_at": "2026-09-25T00:00:05.000000+00:00"}

            # 同一 updated_at 下新增 id 更小的项：并列次序不可依赖，必须仍被取回而非跳过。
            client.issues.append(
                MulticaIssue(
                    id="id-0",
                    identifier="YL-tie-0",
                    title="同秒 0",
                    description="来自 Multica",
                    status="todo",
                    url="https://multica.invalid/issues/YL-tie-0",
                    updated_at="2026-09-25T00:00:05Z",
                )
            )
            second = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=1)
            assert second["imported"] == 1
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 3
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(GovernanceTopic)
                    .where(GovernanceTopic.source_external_id == "YL-tie-0")
                )
                == 1
            )

            # 再跑一轮：边界秒内项只靠去重跳过，最终不重不漏。
            third = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=1)
            assert third["imported"] == 0
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 3


async def test_multica_inbound_sync_fails_closed_on_malformed_cursor() -> None:
    """畸形 cursor_value 必须 fail-closed：报 error、不发外部请求、原游标保留、不落库。"""
    async with _scoped_database("pytest_channel_sync_bad_cursor") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            client = _FakeMulticaClient()
            await client.create_issue(title="不应被拉取的议题", description="来自 Multica")
            cursor_row = await ChannelDelegationRepository(db).add_cursor(channel="multica", project_id="project-owner")
            malformed = "{not-json"
            cursor_row.cursor_value = malformed
            await db.commit()
            service = ChannelSyncService(db, client=client)
            client.calls = 0

            result = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner")

            assert "error" in result
            assert client.calls == 0
            assert result["cursor"] == malformed
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 0
            retained = await service.get_cursor(project_id="project-owner")
            assert retained is not None and retained["cursor"] == malformed

async def test_new_delegation_requires_work_and_preserves_old_collect_path():
    """新委派必须归属正式工作，旧无归属委派仍能回收而不伪造工作完成。"""
    async with _scoped_database("pytest_delegation_legacy") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with sessions() as db:
            service = DelegationService(db, executors=[_StubExecutor("codex")])
            with pytest.raises(HTTPException) as missing:
                await service.dispatch(executor_key="codex", uid="uid-owner",
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="旁路"))
            assert missing.value.detail["code"] == "formal_work_required"
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 0
            old = await ChannelDelegationRepository(db).add_delegation(operation_id="old-delegation",
                project_id="project-owner", executor_key="codex", task="历史执行",
                request_json={"metadata": {}}, initiator_run_id=None, created_by="uid-owner")
            old.dispatch_state = "dispatched"
            old.external_ref = "old-reference"
            await db.commit()
            result = await service.collect(operation_id="old-delegation", project_id="project-owner")
            assert result["dispatch_state"] == "reclaimed" and result["work_task_id"] is None
            await db.refresh(old)
            assert old.result_summary == "done" and old.work_task_id is None
            assert await db.scalar(text("SELECT status FROM project_work_tasks WHERE id='project-owner-work'")) == "todo"


async def test_v30_to_v31_migration_keeps_legacy_delegations_empty_and_is_reentrant():
    """真实旧结构升级不推断映射或执行依据，重复迁移保持既有定位。"""
    async with _scoped_database("pytest_admission_migration") as (manager, sessions):
        await _seed_scope(manager.async_engine)
        async with manager.async_engine.begin() as conn:
            await conn.execute(text("DROP TABLE work_suggestion_admissions"))
            for col in ('work_task_id', 'source_topic_id', 'source_decision_id', 'source_decision_revision'):
                await conn.execute(text(f"ALTER TABLE channel_delegations DROP COLUMN {col} CASCADE"))
            await conn.execute(text("ALTER TABLE governance_tasks DROP CONSTRAINT uq_governance_tasks_id_project"))
            await conn.execute(text("INSERT INTO channel_delegations(id,operation_id,project_id,executor_key,task,request_json,dispatch_state,attempts,result_json,created_at,updated_at) VALUES('old','old','project-owner','codex','旧输入','{}','dispatched',1,'{}',NOW(),NOW())"))
        await manager.upgrade_yuanlei_schema_v30_to_v31()
        async with manager.async_engine.begin() as conn:
            row = (await conn.execute(text("SELECT task,work_task_id,source_decision_id FROM channel_delegations WHERE id='old'"))).one()
            assert tuple(row) == ('旧输入', None, None)
            assert await conn.scalar(text("SELECT count(*) FROM work_suggestion_admissions")) == 0
            await conn.execute(text("UPDATE channel_delegations SET work_task_id='project-owner-work' WHERE id='old'"))
        await manager.upgrade_yuanlei_schema_v30_to_v31()
        async with manager.async_engine.connect() as conn:
            assert await conn.scalar(text("SELECT work_task_id FROM channel_delegations WHERE id='old'")) == 'project-owner-work'

async def test_delegation_tool_preserves_attempt_source_and_rejects_other_work(monkeypatch):
    """真实工具调用保留当次定位，当前来源变化不重写委派输入。"""
    from types import SimpleNamespace
    from test.integration.services.test_project_dashboard_tool import _seed_run
    from yuxi.agents.toolkits.buildin import delegation_tools
    from yuxi.services.governance_service import create_governance_decision, operate_governance_decision
    from yuxi.storage.postgres.models_business import ProjectWorkTask, ProjectWorkExecution

    async with _scoped_database("pytest_delegation_tool") as (manager, sessions):
        manager.AsyncSession = sessions
        await _seed_run(sessions, uid="uid-owner", project_id="project-owner", thread_id="thread-1", run_id="run-1")
        async with sessions() as db:
            user = await _load_user(db)
            source = await create_governance_decision(project_id="project-owner", title="旧依据", conclusion="原要求", rationale=None, topic_id=None, db=db, user=user)
            await operate_governance_decision(project_id="project-owner", decision_id=source['id'], action='approve', expected_revision=1, reason='批准', db=db, user=user)
            db.add(ProjectWorkTask(id="work", project_id="project-owner", number="T-GEN-000001", title="正式工作", created_by="uid-owner"))
            await db.flush()
            db.add(ProjectWorkExecution(id="attempt", task_id="work", project_id="project-owner", uid="uid-owner", agent_slug="main", status="submitted", prompt="当次固定输入", request_id="work-request", thread_id="work-thread", source_decision_id=source['id'], source_decision_revision=2))
            run = await db.get(AgentRun, 'run-1')
            run.origin_metadata = {"project_work_task_id": "work", "project_work_execution_id": "attempt"}
            await db.commit()
        monkeypatch.setattr(delegation_tools, 'pg_manager', manager)
        monkeypatch.setattr(DelegationService, 'build_default', classmethod(lambda cls, db, **kwargs: cls(db, executors=[_StubExecutor('multica')])))
        runtime = SimpleNamespace(context=SimpleNamespace(uid="uid-owner", run_id="run-1", worker_id="worker-current", thread_id="thread-1"))
        denied = json.loads(await delegation_tools.delegation_dispatch.coroutine(executor_key="multica", task="错误归属", work_task_id="other", runtime=runtime))
        assert denied['error_code'] == 'invalid_request'
        result = json.loads(await delegation_tools.delegation_dispatch.coroutine(executor_key="multica", task="固定子任务", runtime=runtime))
        assert result['work_task_id'] == 'work' and result['source_decision_id'] == source['id'] and result['source_decision_revision'] == 2
        async with sessions() as db:
            row = await ChannelDelegationRepository(db).get_by_operation_id(operation_id=result['operation_id'])
            assert row.task == '固定子任务' and row.work_task_id == 'work'
            assert row.request_json['metadata']['source_decision_id'] == source['id']
            assert (await db.get(ProjectWorkTask, 'work')).source_decision_id is None
            run = await db.get(AgentRun, 'run-1'); run.origin_metadata = {}; await db.commit()
        missing = json.loads(await delegation_tools.delegation_dispatch.coroutine(executor_key="multica", task="没有工作", runtime=runtime))
        assert missing['error_code'] == 'formal_work_required'
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ChannelDelegation)) == 1


async def test_delegation_tool_locks_project_before_run():
    """项目被占用时工具未抢占 Run 行，避免 HTTP 外键与工具死锁。"""
    import asyncio
    from test.integration.services.test_project_dashboard_tool import _seed_run
    from yuxi.agents.toolkits.buildin.project_run_scope import resolve_project_run_scope

    async with _scoped_database("pytest_delegation_lock") as (manager, sessions):
        await _seed_run(sessions, uid="uid-owner", project_id="project-owner", thread_id="thread-1", run_id="run-1")
        async with manager.async_engine.connect() as holder, manager.async_engine.connect() as observer:
            await holder.begin()
            holder_pid = await holder.scalar(text('SELECT pg_backend_pid()'))
            await holder.execute(text("SELECT id FROM projects WHERE id='project-owner' FOR UPDATE"))
            async def operation():
                async with sessions() as db:
                    result = await resolve_project_run_scope(db=db, run_id='run-1', uid='uid-owner', worker_id='worker-current', lock_project_first=True)
                    await db.commit()
                    return result[0]
            pending = asyncio.create_task(operation())
            try:
                for _ in range(100):
                    await observer.commit()
                    waiting = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND :pid=ANY(pg_blocking_pids(pid))"), {'pid': holder_pid})
                    if waiting: break
                    await asyncio.sleep(.02)
                assert waiting, '工具必须正在等待该项目锁'
                # 恢复旧 Run→Project 顺序，这个 NOWAIT 会因 Run 已被占用而失败。
                await observer.execute(text("SELECT id FROM agent_runs WHERE id='run-1' FOR UPDATE NOWAIT"))
                await observer.rollback()
            finally:
                await holder.rollback()
                assert await asyncio.wait_for(pending, 5) == 'project-owner'
