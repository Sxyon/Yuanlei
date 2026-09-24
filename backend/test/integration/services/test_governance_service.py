"""元垒项目治理域用例的真实 PostgreSQL 集成测试。

覆盖多来源归一化写读、重复外部标识拒绝、无来源输入拒绝，以及
proposed 未经审核不得成为 canonical 的数据库与用例双层约束。
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yuxi.services.governance_service import (
    create_governance_decision,
    create_governance_report,
    create_governance_task,
    create_governance_topic,
    get_governance_topic,
    list_governance_reports,
    list_governance_tasks,
    list_governance_topics,
    review_governance_task,
    review_governance_topic,
)
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import User

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
    """创建不触碰进程单例的隔离 manager。"""
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


async def _seed_user(engine, *, uid: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES (:username, :uid, 'x', 'user', 0, 0)"
            ),
            {"username": f"user-{uid}", "uid": uid},
        )


async def _seed_project(engine, *, project_id: str, uid: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                "VALUES (:project_id, :uid, 'Pytest', 'selectable', :workdir, 'linked')"
            ),
            {"project_id": project_id, "uid": uid, "workdir": f"projects/{project_id}"},
        )


async def _seed_agent(engine, *, slug: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO agents (slug, backend_id, name, pics, config_json, share_config, "
                "is_default, is_subagent) "
                "VALUES (:slug, 'ChatbotAgent', :slug, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, FALSE, FALSE)"
            ),
            {"slug": slug},
        )


async def _bind_agent(engine, *, project_id: str, slug: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                "VALUES (:id, :project_id, :slug, '{}'::jsonb)"
            ),
            {"id": str(uuid.uuid4()), "project_id": project_id, "slug": slug},
        )


async def _load_user(session: AsyncSession, uid: str) -> User:
    user = await session.scalar(select(User).where(User.uid == uid))
    assert user is not None
    return user


async def _seed_scope(manager) -> None:
    await _seed_user(manager.async_engine, uid="uid-owner")
    await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
    await _seed_agent(manager.async_engine, slug="employee")
    await _bind_agent(manager.async_engine, project_id="project-owner", slug="employee")


async def test_multi_source_topics_round_trip_with_traceable_source() -> None:
    """项目内 / Multica / GitHub / Gitea 四类来源议题写入后回读来源可追溯。"""
    async with _scoped_database("pytest_governance_sources") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            await create_governance_topic(
                project_id="project-owner",
                title="项目内议题",
                summary=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=session,
                user=user,
            )
            from_multica = await create_governance_topic(
                project_id="project-owner",
                title="来自 Multica",
                summary="协作平台提出",
                source_channel="multica",
                source_external_id="mul-42",
                source_url="https://multica.ai/issues/42",
                db=session,
                user=user,
            )
            await create_governance_topic(
                project_id="project-owner",
                title="来自 GitHub",
                summary=None,
                source_channel="github",
                source_external_id="owner/repo#7",
                source_url="https://github.com/owner/repo/issues/7",
                db=session,
                user=user,
            )
            await create_governance_topic(
                project_id="project-owner",
                title="来自 Gitea",
                summary=None,
                source_channel="gitea",
                source_external_id="gitea-9",
                source_url="https://gitea.invalid/owner/repo/issues/9",
                db=session,
                user=user,
            )

            topics = await list_governance_topics(project_id="project-owner", db=session, user=user)
            assert len(topics) == 4
            by_channel = {topic["source"]["channel"]: topic for topic in topics}
            assert set(by_channel) == {"project", "multica", "github", "gitea"}
            assert by_channel["project"]["source"] == {"channel": "project", "external_id": None, "url": None}
            assert by_channel["multica"]["source"]["external_id"] == "mul-42"
            assert by_channel["multica"]["status"] == "proposed"
            assert by_channel["github"]["source"]["url"] == "https://github.com/owner/repo/issues/7"

            reread = await get_governance_topic(
                project_id="project-owner", topic_id=from_multica["id"], db=session, user=user
            )
            assert reread["source"]["external_id"] == "mul-42"


async def test_duplicate_external_source_is_rejected() -> None:
    """同一 (project, channel, external_id) 重复落库被用例拒绝。"""
    async with _scoped_database("pytest_governance_dedupe") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            payload = dict(
                project_id="project-owner",
                title="Multica 议题",
                summary=None,
                source_channel="multica",
                source_external_id="mul-7",
                source_url="https://multica.ai/issues/7",
                db=session,
                user=user,
            )
            await create_governance_topic(**payload)
            with pytest.raises(HTTPException) as duplicate:
                await create_governance_topic(**payload)
            assert duplicate.value.status_code == 409
            assert duplicate.value.detail["code"] == "duplicate_source"

            topics = await list_governance_topics(project_id="project-owner", db=session, user=user)
            assert len(topics) == 1


async def test_missing_or_invalid_source_is_rejected() -> None:
    """缺渠道、外部渠道缺标识、项目内携带外部标识都被拒绝，且不落库。"""
    async with _scoped_database("pytest_governance_badsource") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")

            async def attempt(**overrides):
                payload = dict(
                    project_id="project-owner",
                    title="议题",
                    summary=None,
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=session,
                    user=user,
                )
                payload.update(overrides)
                return await create_governance_topic(**payload)

            with pytest.raises(HTTPException) as missing:
                await attempt(source_channel=None)
            assert missing.value.status_code == 422
            assert missing.value.detail["code"] == "invalid_source"

            with pytest.raises(HTTPException) as unknown:
                await attempt(source_channel="slack")
            assert unknown.value.status_code == 422

            with pytest.raises(HTTPException) as missing_external:
                await attempt(source_channel="github", source_external_id=None)
            assert missing_external.value.status_code == 422

            with pytest.raises(HTTPException) as project_with_external:
                await attempt(source_channel="project", source_external_id="x")
            assert project_with_external.value.status_code == 422

            topics = await list_governance_topics(project_id="project-owner", db=session, user=user)
            assert topics == []


async def test_proposed_requires_review_to_become_canonical() -> None:
    """proposed 议题写入时无审核责任人；未审核直改 canonical 被数据库拒绝；审核后才落库。"""
    async with _scoped_database("pytest_governance_review") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="待审核议题",
                summary=None,
                source_channel="github",
                source_external_id="owner/repo#11",
                source_url="https://github.com/owner/repo/issues/11",
                db=session,
                user=user,
            )
            assert topic["status"] == "proposed"
            assert topic["review"] == {"owner_uid": None, "reviewed_at": None, "note": None}

            # 未经审核直接把 proposed 改为 canonical 在数据库层被拒绝。
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        text("UPDATE governance_topics SET status = 'canonical' WHERE id = :id"),
                        {"id": topic["id"]},
                    )

            reviewed = await review_governance_topic(
                project_id="project-owner",
                topic_id=topic["id"],
                approve=True,
                review_note="排版归一后落库",
                db=session,
                user=user,
            )
            assert reviewed["status"] == "canonical"
            assert reviewed["review"]["owner_uid"] == "uid-owner"
            assert reviewed["review"]["reviewed_at"] is not None

            with pytest.raises(HTTPException) as again:
                await review_governance_topic(
                    project_id="project-owner",
                    topic_id=topic["id"],
                    approve=False,
                    review_note=None,
                    db=session,
                    user=user,
                )
            assert again.value.status_code == 409


async def test_task_source_normalization_and_assignee_boundary() -> None:
    """任务共享来源归一化，指派必须绑定项目数字员工，来源重复被拒。"""
    async with _scoped_database("pytest_governance_tasks") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="决策前置议题",
                summary=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=session,
                user=user,
            )
            decision = await create_governance_decision(
                project_id="project-owner",
                title="拆解任务",
                conclusion="先做数据模型",
                rationale="最小线性实现",
                topic_id=topic["id"],
                decided=True,
                db=session,
                user=user,
            )
            assert decision["status"] == "implemented"
            assert decision["decided_by"] == "uid-owner"

            task = await create_governance_task(
                project_id="project-owner",
                title="实现治理域",
                description="新增四表",
                topic_id=topic["id"],
                decision_id=decision["id"],
                assignee_agent_slug="employee",
                source_channel="github",
                source_external_id="owner/repo#21",
                source_url="https://github.com/owner/repo/issues/21",
                db=session,
                user=user,
            )
            assert task["status"] == "proposed"
            assert task["assignee_agent_slug"] == "employee"
            assert task["decision_id"] == decision["id"]

            with pytest.raises(HTTPException) as unbound:
                await create_governance_task(
                    project_id="project-owner",
                    title="越界指派",
                    description=None,
                    topic_id=None,
                    decision_id=None,
                    assignee_agent_slug="missing-agent",
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=session,
                    user=user,
                )
            assert unbound.value.status_code == 404

            with pytest.raises(HTTPException) as duplicate:
                await create_governance_task(
                    project_id="project-owner",
                    title="重复来源任务",
                    description=None,
                    topic_id=None,
                    decision_id=None,
                    assignee_agent_slug=None,
                    source_channel="github",
                    source_external_id="owner/repo#21",
                    source_url="https://github.com/owner/repo/issues/21",
                    db=session,
                    user=user,
                )
            assert duplicate.value.detail["code"] == "duplicate_source"

            reviewed = await review_governance_task(
                project_id="project-owner",
                task_id=task["id"],
                approve=True,
                review_note=None,
                db=session,
                user=user,
            )
            assert reviewed["status"] == "canonical"
            assert reviewed["review"]["owner_uid"] == "uid-owner"

            tasks = await list_governance_tasks(project_id="project-owner", db=session, user=user)
            assert len(tasks) == 1


async def test_report_records_artifact_reference_without_owning_run_state() -> None:
    """汇报记录引用 artifact 路径与产出 Run，不承载 Run 终态。"""
    async with _scoped_database("pytest_governance_reports") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            report = await create_governance_report(
                project_id="project-owner",
                title="周报",
                summary="本周进展",
                content={"completed": 3, "blocked": 1},
                source_run_id=None,
                artifact_path="reports/weekly.md",
                db=session,
                user=user,
            )
            assert report["artifact_path"] == "reports/weekly.md"
            assert report["content"] == {"completed": 3, "blocked": 1}
            assert "status" not in report

            reports = await list_governance_reports(project_id="project-owner", db=session, user=user)
            assert [item["id"] for item in reports] == [report["id"]]
