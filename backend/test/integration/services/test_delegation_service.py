"""外部执行器委派与 Multica 入向同步的真实 PostgreSQL 集成测试。

覆盖统一接口委派、operation_id search-before-create、本地状态与远端投影分离、
结果物化边界、崩溃后可观察收敛，以及入向只产生 proposed 与游标去重。
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.delegation.contracts import (
    DelegationError,
    DelegationHandle,
    DelegationRequest,
    DelegationResult,
    ExecutorUnavailableError,
)
from yuxi.delegation.multica import MulticaExecutor, MulticaIssue
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.services.channel_sync_service import ChannelSyncService
from yuxi.services.delegation_service import DelegationService
from yuxi.services.governance_service import create_governance_topic
from yuxi.services.governance_service import create_governance_task, review_governance_task
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import (
    AgentRun,
    ChannelDelegation,
    GovernanceTopic,
    User,
)
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
    """内存 Multica 客户端；记录创建次数以证明 search-before-create。"""

    def __init__(self):
        self.issues: list[MulticaIssue] = []
        self.create_calls = 0

    async def create_issue(self, *, title: str, description: str) -> MulticaIssue:
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
        return next(issue for issue in self.issues if issue.identifier == issue_ref)

    async def search_issues(self, *, query: str, limit: int = 20) -> list[MulticaIssue]:
        return [issue for issue in self.issues if query in issue.description][:limit]

    async def list_issues(self, *, updated_after: str | None, limit: int = 50, offset: int = 0) -> list[MulticaIssue]:
        issues = list(self.issues)
        if updated_after:
            issues = [issue for issue in issues if (issue.updated_at or "") > updated_after]
        return issues[offset : offset + limit]


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
                    '{}'::jsonb, '{}'::jsonb, FALSE, FALSE)"""
                )
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

            await review_governance_task(
                project_id="project-owner",
                task_id=task["id"],
                approve=True,
                review_note=None,
                db=db,
                user=user,
            )
            view = await service.dispatch_project_task(
                project_id="project-owner", task_id=task["id"], executor_key="codex", user=user
            )
            assert view["governance_task_id"] == task["id"]
            assert view["task"] == "交付功能\n\n写完并验证"
            assert (await service.list_delegations(project_id="project-owner"))[0]["governance_task_id"] == task["id"]


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
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="只留下意图"),
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
                request=DelegationRequest(operation_id="", project_id="project-owner", task="做一件事"),
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
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="失败任务"),
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
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="x"),
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
                request=DelegationRequest(operation_id="", project_id="project-owner", task="委派远端"),
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
                request=DelegationRequest(operation_id="", project_id="project-owner", task="远端任务"),
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
                    request=DelegationRequest(operation_id="", project_id="project-owner", task="任务"),
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
                request=DelegationRequest(operation_id="", project_id="project-owner", task="任务"),
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

            # 崩溃后重跑：游标已推进到最新，同一页不会重复导入。
            second = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner")
            assert second["imported"] == 0
            assert second["skipped"] == 0
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 2
            cursor = await service.get_cursor(project_id="project-owner")
            assert cursor is not None and cursor["cursor"] == "2026-09-25T00:00:02Z"


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
            assert result["cursor"] == "2026-09-25T00:00:03Z"
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 3

            follow_up = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert follow_up["imported"] == 0
            assert follow_up["skipped"] == 0


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
            assert cursor is not None and cursor["cursor"] == "2026-09-25T00:00:02Z"

            second = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert second["imported"] == 0
            assert second["skipped"] == 0


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
            assert "error" not in result
            assert any("hit page cap" in message for message in warnings)
            assert await db.scalar(select(func.count()).select_from(GovernanceTopic)) == 2

            cursor = await service.get_cursor(project_id="project-owner")
            assert cursor is not None and cursor["cursor"] is None

            # 游标未推进 → 下一轮重取同页（此处命中 409 去重），证明未静默跳过未取回项。
            follow_up = await service.pull_multica(project_id="project-owner", actor_uid="uid-owner", limit=2)
            assert follow_up["imported"] == 0
            assert follow_up["skipped"] == 2
            assert follow_up["cursor"] is None
