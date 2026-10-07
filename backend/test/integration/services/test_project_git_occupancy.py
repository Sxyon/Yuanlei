"""真实 PostgreSQL 验证目录 FIFO 与独立子工作区的占用边界。"""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.services.project_git_execution_service import reserve_git_resources_for_dispatch
from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import (
    AgentRun,
    GitConnection,
    GitCredential,
    Project,
    ProjectGitOccupancy,
    ProjectGitRepository,
    ProjectGitWorktree,
    ProjectWorkTask,
    ProjectWorkExecution,
    User,
)
from yuxi.utils.datetime_utils import utc_now_naive

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """仅使用独立测试 Schema。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """本测试不创建知识库。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """本测试不创建沙盒。"""
    yield


@pytest_asyncio.fixture
async def sessions():
    """创建隔离 Schema 并在测试结束删除所有测试事实。"""
    schema = "pytest_git_" + uuid.uuid4().hex[:16]
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = PostgresManager()
        manager.async_engine = engine
        manager._initialized = True
        await manager.create_business_tables()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add(User(uid="owner", username="owner", password_hash="test-only"))
            await db.flush()
            db.add(
                Project(
                    id="project",
                    uid="owner",
                    name="Git",
                    workdir_path="projects/git",
                    directory_mode="managed",
                    selection_status="selectable",
                )
            )
            db.add(
                GitCredential(
                    id="credential",
                    uid="owner",
                    purpose="gitea_api_token",
                    ciphertext=b"test-only",
                    nonce=b"test-only",
                    key_version=1,
                )
            )
            await db.flush()
            db.add(
                GitConnection(
                    id="connection",
                    uid="owner",
                    name="Git",
                    provider="gitea",
                    api_origin="http://test.invalid",
                    ssh_host="test.invalid",
                    ssh_port=22,
                    ssh_known_host_key="test-only",
                    api_token_credential_id="credential",
                    idempotency_key="connection",
                )
            )
            await db.flush()
            db.add(
                ProjectGitRepository(
                    id="repository",
                    project_id="project",
                    uid="owner",
                    connection_id="connection",
                    alias="repo",
                    directory_name="repo",
                    repository_owner="owner",
                    repository_name="repo",
                    deploy_public_key="test-only",
                    deploy_public_key_fingerprint="test-only",
                    deploy_private_credential_id="credential",
                    idempotency_key="repo",
                    status="active",
                    usage_mode="in_place",
                    approval_mode="protected",
                )
            )
            await db.commit()
        yield factory
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def seed_allocations(sessions, modes):
    """显式固定等待顺序，让并发调度不能改变 FIFO 事实。"""
    now = utc_now_naive()
    async with sessions() as db:
        for index, mode in enumerate(modes):
            scope = f"thread-{index}"
            db.add(
                ProjectGitWorktree(
                    id=f"workspace-{index}",
                    repository_id="repository",
                    project_id="project",
                    uid="owner",
                    runtime_scope_id=scope,
                    task_key=scope,
                    selection_source="user",
                    task_purpose="verify",
                    branch_kind="test",
                    branch_slug=scope,
                    branch_name=f"agent/{scope}",
                    base_branch="main",
                    relative_path=f"repos/{scope}",
                    usage_mode=mode,
                    status="requested",
                )
            )
            db.add(
                ProjectGitOccupancy(
                    id=f"slot-{index}",
                    repository_id="repository",
                    project_id="project",
                    uid="owner",
                    scope_key=scope,
                    status="queued",
                    requested_at=now + timedelta(seconds=index),
                )
            )
        await db.commit()


async def reserve(sessions, index):
    """每个候选使用独立真实事务争抢占用。"""
    async with sessions() as db:
        available = await reserve_git_resources_for_dispatch(
            db=db,
            uid="owner",
            project_id="project",
            thread_id=f"thread-{index}",
            run_id=f"planned-run-{index}",
            requested_at=utc_now_naive(),
        )
        await db.commit()
        return available


async def test_in_place_fifo_survives_concurrent_dispatch_and_persists_owner(sessions):
    await seed_allocations(sessions, ["in_place", "in_place", "in_place"])
    result = await asyncio.gather(reserve(sessions, 2), reserve(sessions, 1), reserve(sessions, 0))
    assert result == [False, False, True]
    async with sessions() as db:
        slots = list(await db.scalars(select(ProjectGitOccupancy).order_by(ProjectGitOccupancy.requested_at)))
        assert [(slot.status, slot.active_run_id) for slot in slots] == [
            ("owned", "planned-run-0"),
            ("queued", None),
            ("queued", None),
        ]
    assert await reserve(sessions, 1) is False


async def test_isolated_worktree_does_not_join_in_place_checkout_queue(sessions):
    await seed_allocations(sessions, ["in_place", "worktree"])
    assert await asyncio.gather(reserve(sessions, 0), reserve(sessions, 1)) == [True, True]
    async with sessions() as db:
        slots = list(await db.scalars(select(ProjectGitOccupancy)))
        assert {slot.active_run_id for slot in slots if slot.status == "owned"} == {"planned-run-0", "planned-run-1"}


async def test_parent_scope_change_is_blocked_by_shared_child_history_only(sessions):
    async with sessions() as db:
        db.add(
            ProjectWorkTask(
                id="root",
                project_id="project",
                number="ROOT",
                title="Root",
                created_by="owner",
            )
        )
        await db.flush()
        for task_id, mode in (("shared", "inherit"), ("isolated", "isolated")):
            db.add(
                ProjectWorkTask(
                    id=task_id,
                    project_id="project",
                    number=task_id,
                    title=task_id,
                    parent_id="root",
                    created_by="owner",
                    git_workspace_mode=mode,
                )
            )
        await db.flush()
        db.add(
            ProjectWorkExecution(
                id="isolated-execution",
                task_id="isolated",
                project_id="project",
                uid="owner",
                agent_slug="agent",
                status="completed",
                prompt="verify",
                request_id="isolated-request",
                thread_id="isolated-thread",
            )
        )
        await db.commit()
    async with sessions() as db:
        store = ProjectGitRepositoryStore(db)
        assert await store.task_tree_has_git_history(task_id="root", project_id="project", uid="owner") is False
        assert await store.task_tree_has_git_history(task_id="isolated", project_id="project", uid="owner") is True
        db.add(
            ProjectWorkExecution(
                id="shared-execution",
                task_id="shared",
                project_id="project",
                uid="owner",
                agent_slug="agent",
                status="completed",
                prompt="verify",
                request_id="shared-request",
                thread_id="shared-thread",
            )
        )
        await db.commit()
    async with sessions() as db:
        store = ProjectGitRepositoryStore(db)
        assert await store.task_tree_has_git_history(task_id="root", project_id="project", uid="owner") is True


async def test_user_has_nonterminal_runs_excludes_terminal_interrupted_run(sessions):
    """interrupted 属终态，不能永久阻止资源目录初始化。"""
    async with sessions() as db:
        for index, status in enumerate(("completed", "failed", "cancelled", "interrupted")):
            db.add(
                AgentRun(
                    id=f"terminal-{status}",
                    uid="owner",
                    conversation_thread_id=f"thread-{index}",
                    runtime_scope_id=f"scope-{index}",
                    agent_slug="test",
                    status=status,
                    request_id=f"request-{index}",
                )
            )
        await db.commit()
        store = ProjectGitRepositoryStore(db)
        assert await store.user_has_nonterminal_runs("owner") is False

        db.add(
            AgentRun(
                id="active-running",
                uid="owner",
                conversation_thread_id="thread-active",
                runtime_scope_id="thread-active",
                agent_slug="test",
                status="running",
                request_id="request-active",
            )
        )
        await db.commit()
        assert await store.user_has_nonterminal_runs("owner") is True
        assert await store.task_tree_has_git_history(task_id="root", project_id="project", uid="other") is False
