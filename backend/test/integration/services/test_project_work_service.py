"""独立项目任务在真实 PostgreSQL 上的编号、归属与讨论证据。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.services.project_work_service import (
    add_comment,
    configure_project_code,
    configure_topic_code,
    create_issue,
    create_task,
    get_issue,
    get_task,
    list_topics,
    update_task,
)
from yuxi.services.project_agent_service import unbind_project_agent_view
from yuxi.repositories.project_work_repository import ProjectWorkRepository
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


async def test_project_work_numbering_issue_discussion_and_scope() -> None:
    """并发编号唯一，跨项目父任务与跨任务问题单均拒绝。"""
    schema = f"pytest_work_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = object.__new__(PostgresManager)
        PostgresManager.__init__(manager)
        manager.async_engine = scoped_engine
        manager._initialized = True
        await manager.create_business_tables()
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
        async with scoped_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                    "VALUES ('work-user', 'work-user', 'x', 'user', 0, 0), "
                    "('work-outsider', 'work-outsider', 'x', 'user', 0, 0)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) VALUES "
                    "('work-a', 'work-user', 'A', 'selectable', 'projects/a', 'managed'), "
                    "('work-b', 'work-user', 'B', 'selectable', 'projects/b', 'managed')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO governance_topics "
                    "(id, project_id, title, status, source_channel, created_at, updated_at) "
                    "VALUES ('work-topic', 'work-a', 'Topic', 'proposed', 'project', NOW(), NOW())"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO agents "
                    "(slug, backend_id, name, pics, config_json, share_config, is_default, is_subagent) "
                    "VALUES ('work-agent', 'ChatbotAgent', 'Work Agent', '[]'::jsonb, '{}'::jsonb, "
                    "'{}'::jsonb, FALSE, FALSE)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                    "VALUES ('work-binding', 'work-a', 'work-agent', '{}'::jsonb)"
                )
            )
        user = User(uid="work-user", username="work-user")
        async with sessions() as db:
            assert (await configure_project_code(db=db, user=user, project_id="work-a", code="WORK"))["code"] == "WORK"
        async with sessions() as db:
            await configure_project_code(db=db, user=user, project_id="work-b", code="WORKB")
        async with sessions() as db:
            assert await list_topics(db=db, user=user, project_id="work-a") == [
                {"id": "work-topic", "title": "Topic", "status": "proposed", "code": None}
            ]
            with pytest.raises(HTTPException) as outsider_topics:
                await list_topics(
                    db=db, user=User(uid="work-outsider", username="work-outsider"), project_id="work-a"
                )
            assert outsider_topics.value.status_code == 404
        async with sessions() as db:
            with pytest.raises(HTTPException) as reserved:
                await configure_topic_code(db=db, user=user, project_id="work-a", topic_id="work-topic", code="GEN")
            assert reserved.value.status_code == 422
            await configure_topic_code(db=db, user=user, project_id="work-a", topic_id="work-topic", code="TOP")
        async with sessions() as db:
            assert await list_topics(db=db, user=user, project_id="work-a") == [
                {"id": "work-topic", "title": "Topic", "status": "proposed", "code": "TOP"}
            ]

        async def make_task(title: str) -> dict:
            async with sessions() as db:
                return await create_task(
                    db=db,
                    user=user,
                    project_id="work-a",
                    title=title,
                    description=None,
                    topic_id="work-topic",
                    parent_id=None,
                    primary_owner_agent_slug=None,
                )

        first, second = await asyncio.gather(make_task("first"), make_task("second"))
        assert {first["number"], second["number"]} == {"WORK-TOP-000001", "WORK-TOP-000002"}
        async with sessions() as db:
            outsider_repo = ProjectWorkRepository(db, project_id="work-a", uid="work-outsider")
            assert await outsider_repo.get_task(first["id"]) is None
            with pytest.raises(ValueError):
                await outsider_repo.list_comments()
            with pytest.raises(PermissionError):
                await outsider_repo.add_comment(
                    task_id=first["id"],
                    issue_id=None,
                    content="bypass",
                    author_uid="work-outsider",
                    author_name="Outsider",
                )
            with pytest.raises(PermissionError):
                await outsider_repo.add_task(
                    project_id="work-a",
                    number="WORK-GEN-999999",
                    title="bypass",
                    description=None,
                    topic_id=None,
                    parent_id=None,
                    primary_owner_agent_slug=None,
                    created_by="work-outsider",
                )
        async with sessions() as db:
            with pytest.raises(HTTPException) as missing_owner:
                await create_task(
                    db=db,
                    user=user,
                    project_id="work-a",
                    title="invalid owner",
                    description=None,
                    topic_id=None,
                    parent_id=None,
                    primary_owner_agent_slug="unbound",
                )
            assert missing_owner.value.status_code == 404
        async with sessions() as db:
            with pytest.raises(HTTPException) as foreign_parent:
                await create_task(
                    db=db,
                    user=user,
                    project_id="work-b",
                    title="foreign parent",
                    description=None,
                    topic_id=None,
                    parent_id=first["id"],
                    primary_owner_agent_slug=None,
                )
            assert foreign_parent.value.status_code == 404

        async with sessions() as db:
            child = await create_task(
                db=db,
                user=user,
                project_id="work-a",
                title="child",
                description=None,
                topic_id=None,
                parent_id=first["id"],
                primary_owner_agent_slug=None,
            )
        assert child["parent_id"] == first["id"]
        async with sessions() as db:
            owned = await create_task(
                db=db,
                user=user,
                project_id="work-a",
                title="owned",
                description=None,
                topic_id=None,
                parent_id=None,
                primary_owner_agent_slug="work-agent",
            )
        async with sessions() as db:
            with pytest.raises(HTTPException) as still_responsible:
                await unbind_project_agent_view(
                    project_id="work-a",
                    agent_slug="work-agent",
                    delete_agent=False,
                    db=db,
                    user=user,
                )
            assert still_responsible.value.status_code == 409
            assert (await get_task(db=db, user=user, project_id="work-a", task_id=owned["id"]))[
                "primary_owner_agent_slug"
            ] == "work-agent"
        async with sessions() as db:
            issue = await create_issue(
                db=db,
                user=user,
                project_id="work-a",
                task_id=first["id"],
                title="problem",
                description="details",
            )
        assert issue["number"] == f"{first['number']}-I1"
        async with sessions() as db:
            comment = await add_comment(
                db=db,
                user=user,
                project_id="work-a",
                task_id=first["id"],
                issue_id=issue["id"],
                content="conclusion",
            )
        assert comment["content"] == "conclusion"
        async with sessions() as db:
            detail = await get_task(db=db, user=user, project_id="work-a", task_id=first["id"])
            assert [item["id"] for item in detail["issues"]] == [issue["id"]]
            with pytest.raises(HTTPException) as foreign_issue:
                await get_issue(db=db, user=user, project_id="work-a", task_id=second["id"], issue_id=issue["id"])
            assert foreign_issue.value.status_code == 404
        async with sessions() as db:
            updated = await update_task(db=db, user=user, project_id="work-a", task_id=first["id"], status="blocked")
            assert updated["status"] == "blocked"
        async with scoped_engine.connect() as conn:
            numbers = [
                row[0]
                for row in await conn.execute(
                    text("SELECT number FROM project_work_tasks WHERE project_id = 'work-a' ORDER BY number")
                )
            ]
            assert numbers == ["WORK-GEN-000003", "WORK-GEN-000004", "WORK-TOP-000001", "WORK-TOP-000002"]
        async with scoped_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO project_topic_codes (topic_id, project_id, code) "
                            "VALUES ('work-topic', 'work-b', 'BAD')"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO project_work_tasks "
                            "(id, project_id, topic_id, number, title, status, created_by) "
                            "VALUES ('cross-topic', 'work-b', 'work-topic', 'BAD-TOP-1', 'Cross', 'todo', 'work-user')"
                        )
                    )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO project_work_tasks "
                            "(id, project_id, parent_id, number, title, status, created_by) "
                            "VALUES ('cross-parent', 'work-b', :parent, 'BAD-GEN-1', 'Cross', 'todo', 'work-user')"
                        ),
                        {"parent": first["id"]},
                    )
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
