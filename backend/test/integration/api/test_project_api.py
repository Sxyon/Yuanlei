from __future__ import annotations

import asyncio
import os
import re
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test.live_api_cleanup import (
    make_test_conversation_metadata,
    make_test_conversation_title,
    make_test_resource_id,
)
from yuxi.repositories.conversation_repository import ConversationRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services.agent_run_service import prepare_agent_run_creation_scope
from yuxi.services.project_service import delete_project_view
from yuxi.services.subagent_run_service import SubagentRunService
from yuxi.storage.postgres.models_business import Conversation, Project, SubagentThread, User
from yuxi.workspace.paths import user_workdir_host_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@asynccontextmanager
async def _database_connection():
    """为当前测试 loop 创建独立 PostgreSQL 连接。"""
    dsn = os.environ["POSTGRES_URL"].replace("+asyncpg", "")
    connection = await asyncpg.connect(dsn)
    try:
        yield connection
    finally:
        await connection.close()


async def _default_agent_slug(test_client, headers: dict[str, str]) -> str:
    response = await test_client.get("/api/agent", headers=headers)
    assert response.status_code == 200, response.text
    agent = next(item for item in response.json()["agents"] if item.get("is_default"))
    return str(agent.get("slug") or agent["agent_id"])


@pytest_asyncio.fixture()
async def linked_directory(test_client, admin_headers):
    """创建并在用例结束后删除 linked Project 使用的目录。"""

    directory_name = f"pytest-linked-{uuid.uuid4().hex[:10]}"
    response = await test_client.post(
        "/api/workspace/directory",
        headers=admin_headers,
        json={"parent_path": "/", "name": directory_name},
    )
    assert response.status_code == 200, response.text
    try:
        yield directory_name
    finally:
        response = await test_client.request(
            "DELETE",
            "/api/workspace/file",
            headers=admin_headers,
            params={"path": directory_name},
        )
        assert response.status_code in {200, 404}, response.text


@pytest_asyncio.fixture()
async def project_lifecycle_database():
    """为 Project 生命周期竞态测试隔离数据库资源。"""
    engine = create_async_engine(os.environ["POSTGRES_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    uid = f"pytest-user-{uuid.uuid4()}"
    project_id = str(uuid.uuid4())

    try:
        async with session_factory() as session:
            session.add(User(username=uid, uid=uid, password_hash="test"))
            session.add(
                Project(
                    id=project_id,
                    uid=uid,
                    name="SubAgent lifecycle",
                    selection_status="selectable",
                    workdir_path=f"projects/{project_id}",
                    directory_mode="managed",
                )
            )
            await session.commit()

        try:
            yield session_factory, uid, project_id
        finally:
            async with session_factory() as session:
                await session.execute(delete(SubagentThread).where(SubagentThread.uid == uid))
                await session.execute(delete(Conversation).where(Conversation.uid == uid))
                await session.execute(delete(Project).where(Project.uid == uid))
                await session.execute(delete(User).where(User.uid == uid))
                await session.commit()
    finally:
        await engine.dispose()


async def _create_lifecycle_conversation(
    session_factory,
    *,
    uid: str,
    project_id: str,
    thread_id: str,
    label: str,
    status: str,
) -> int:
    """创建并提交竞态测试使用的 Conversation。"""
    async with session_factory() as session:
        conversation = Conversation(
            thread_id=thread_id,
            uid=uid,
            agent_id="default-chatbot",
            title=make_test_conversation_title(label),
            status=status,
            project_id=project_id,
            extra_metadata=make_test_conversation_metadata(label),
        )
        session.add(conversation)
        await session.commit()
        return conversation.id


async def test_default_thread_creates_implicit_project_with_exclusive_binding(test_client, admin_headers):
    response = await test_client.post(
        "/api/chat/thread",
        headers=admin_headers,
        json={
            "agent_id": await _default_agent_slug(test_client, admin_headers),
            "title": make_test_conversation_title("implicit-project"),
            "metadata": make_test_conversation_metadata("implicit-project"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_id"]
    assert re.fullmatch(
        rf"projects/\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}_{re.escape(payload['project_id'][:8])}(?:-[1-9]\d*)?",
        payload["workdir_path"],
    )

    async with _database_connection() as db:
        row = await db.fetchrow(
            "SELECT c.uid, c.project_id, p.selection_status, p.directory_mode, p.workdir_path "
            "FROM conversations c JOIN projects p ON p.id = c.project_id AND p.uid = c.uid "
            "WHERE c.thread_id = $1",
            payload["id"],
        )
    assert row["project_id"] == payload["project_id"]
    assert row["selection_status"] == "implicit"
    assert row["directory_mode"] == "managed"
    assert row["workdir_path"] == payload["workdir_path"]
    assert user_workdir_host_dir(str(row["uid"]), str(row["workdir_path"])).is_dir()


async def test_linked_project_and_thread_selection_keep_directory_bytes(
    test_client,
    admin_headers,
    linked_directory,
):
    directory_name = linked_directory
    project_response = await test_client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "request_id": make_test_resource_id("linked-project"),
            "name": "Linked",
            "workdir": {"mode": "linked", "path": directory_name},
        },
    )
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()

    thread_response = await test_client.post(
        "/api/chat/thread",
        headers=admin_headers,
        json={
            "agent_id": await _default_agent_slug(test_client, admin_headers),
            "project_id": project["id"],
            "title": make_test_conversation_title("linked-project"),
            "metadata": make_test_conversation_metadata("linked-project"),
        },
    )
    assert thread_response.status_code == 200, thread_response.text
    thread = thread_response.json()
    assert thread["project_id"] == project["id"]
    assert thread["workdir_path"] == directory_name

    rebind = await test_client.put(
        f"/api/chat/thread/{thread['id']}",
        headers=admin_headers,
        json={"project_id": str(uuid.uuid4())},
    )
    assert rebind.status_code == 422, rebind.text

    legacy_direct_path = await test_client.post(
        "/api/chat/thread",
        headers=admin_headers,
        json={
            "agent_id": await _default_agent_slug(test_client, admin_headers),
            "workdir_path": directory_name,
        },
    )
    assert legacy_direct_path.status_code == 422, legacy_direct_path.text

    duplicate = await test_client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "request_id": make_test_resource_id("duplicate-linked-project"),
            "name": "Duplicate",
            "workdir": {"mode": "linked", "path": directory_name},
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["id"] != project["id"]
    assert duplicate.json()["workdir_path"] == directory_name

    invalid_paths = ["/", "../outside", f"{directory_name}/missing"]
    for path in invalid_paths:
        invalid = await test_client.post(
            "/api/projects",
            headers=admin_headers,
            json={
                "request_id": make_test_resource_id("invalid-linked-project"),
                "name": "Invalid",
                "workdir": {"mode": "linked", "path": path},
            },
        )
        assert invalid.status_code in {400, 404}, (path, invalid.text)


async def test_project_rename_and_delete_soft_delete_conversations_but_keep_workdir(
    test_client,
    admin_headers,
    linked_directory,
    standard_user,
):
    project_response = await test_client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "request_id": make_test_resource_id("managed-lifecycle"),
            "name": "Before rename",
            "workdir": {"mode": "linked", "path": linked_directory},
        },
    )
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()

    marker_response = await test_client.post(
        "/api/workspace/directory",
        headers=admin_headers,
        json={"parent_path": f"/{linked_directory}", "name": "keep"},
    )
    assert marker_response.status_code == 200, marker_response.text

    agent_slug = await _default_agent_slug(test_client, admin_headers)
    thread_ids = []
    for suffix in ("one", "two"):
        thread_response = await test_client.post(
            "/api/chat/thread",
            headers=admin_headers,
            json={
                "agent_id": agent_slug,
                "project_id": project["id"],
                "title": make_test_conversation_title(f"project-delete-{suffix}"),
                "metadata": make_test_conversation_metadata(f"project-delete-{suffix}"),
            },
        )
        assert thread_response.status_code == 200, thread_response.text
        thread_ids.append(thread_response.json()["id"])

    cross_user_rename = await test_client.put(
        f"/api/projects/{project['id']}",
        headers=standard_user["headers"],
        json={"name": "Forbidden"},
    )
    assert cross_user_rename.status_code == 404, cross_user_rename.text

    cross_user_delete = await test_client.delete(
        f"/api/projects/{project['id']}",
        headers=standard_user["headers"],
    )
    assert cross_user_delete.status_code == 404, cross_user_delete.text

    rename_response = await test_client.put(
        f"/api/projects/{project['id']}",
        headers=admin_headers,
        json={"name": "After rename"},
    )
    assert rename_response.status_code == 200, rename_response.text
    assert rename_response.json()["name"] == "After rename"

    delete_response = await test_client.delete(
        f"/api/projects/{project['id']}",
        headers=admin_headers,
    )
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["deleted_conversations"] == 2

    projects_response = await test_client.get("/api/projects", headers=admin_headers)
    assert projects_response.status_code == 200, projects_response.text
    assert project["id"] not in {item["id"] for item in projects_response.json()}

    threads_response = await test_client.get("/api/chat/threads", headers=admin_headers)
    assert threads_response.status_code == 200, threads_response.text
    assert set(thread_ids).isdisjoint({item["id"] for item in threads_response.json()})

    marker_read = await test_client.get(
        "/api/workspace/tree",
        headers=admin_headers,
        params={"path": f"/{linked_directory}", "include_unbound_project_dirs": True},
    )
    assert marker_read.status_code == 200, marker_read.text
    assert "keep" in {entry["name"] for entry in marker_read.json()["entries"]}

    async with _database_connection() as db:
        project_row = await db.fetchrow(
            "SELECT status, deleted_at FROM projects WHERE id = $1",
            project["id"],
        )
        conversation_rows = await db.fetch(
            "SELECT thread_id, status FROM conversations WHERE project_id = $1 ORDER BY thread_id",
            project["id"],
        )

    assert project_row["status"] == "deleted"
    assert project_row["deleted_at"] is not None
    assert {row["thread_id"] for row in conversation_rows} == set(thread_ids)
    assert {row["status"] for row in conversation_rows} == {"deleted"}

    repeated_delete = await test_client.delete(
        f"/api/projects/{project['id']}",
        headers=admin_headers,
    )
    assert repeated_delete.status_code == 404, repeated_delete.text


async def test_project_delete_waits_for_locked_conversation_creation(
    test_client,
    admin_headers,
    linked_directory,
):
    project_response = await test_client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "request_id": make_test_resource_id("project-delete-race"),
            "name": "Concurrent lifecycle",
            "workdir": {"mode": "linked", "path": linked_directory},
        },
    )
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()

    dsn = os.environ["POSTGRES_URL"]
    raw_dsn = dsn.replace("+asyncpg", "")
    creator_connection = await asyncpg.connect(raw_dsn)
    engine = create_async_engine(dsn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    creator_transaction = creator_connection.transaction()
    await creator_transaction.start()
    thread_id = str(uuid.uuid4())

    async def delete_project():
        async with session_factory() as session:
            return await delete_project_view(
                uid=project["uid"],
                project_id=project["id"],
                db=session,
            )

    try:
        locked_project = await creator_connection.fetchrow(
            "SELECT id, uid FROM projects WHERE id = $1 AND uid = $2 FOR UPDATE",
            project["id"],
            project["uid"],
        )
        assert locked_project is not None

        delete_task = asyncio.create_task(delete_project())
        await asyncio.sleep(0.05)
        assert not delete_task.done()

        await creator_connection.execute(
            "INSERT INTO conversations "
            "(thread_id, uid, agent_id, title, status, is_pinned, project_id, extra_metadata) "
            "VALUES ($1, $2, $3, $4, 'active', FALSE, $5, '{}'::json)",
            thread_id,
            project["uid"],
            "default-chatbot",
            make_test_conversation_title("project-delete-race"),
            project["id"],
        )
        await creator_transaction.commit()
        delete_result = await asyncio.wait_for(delete_task, timeout=5)
        assert delete_result["deleted_conversations"] == 1

        async with _database_connection() as database:
            project_status = await database.fetchval("SELECT status FROM projects WHERE id = $1", project["id"])
            conversation_status = await database.fetchval(
                "SELECT status FROM conversations WHERE thread_id = $1",
                thread_id,
            )
        assert project_status == "deleted"
        assert conversation_status == "deleted"
    finally:
        if creator_connection.is_in_transaction():
            await creator_transaction.rollback()
        await creator_connection.close()
        await engine.dispose()


async def test_project_delete_waits_for_real_subagent_conversation_creation(
    monkeypatch: pytest.MonkeyPatch,
    project_lifecycle_database,
):
    """真实 SubAgent 写入边界与 Project 删除使用同一行锁。"""
    session_factory, uid, project_id = project_lifecycle_database
    parent_thread_id = f"pytest-subagent-parent-{uuid.uuid4()}"
    agent_slug = "default-chatbot"
    child_thread_id = f"pytest-subdel-{uuid.uuid4()}"
    child_boundary_reached = asyncio.Event()
    allow_child_creation = asyncio.Event()
    original_ensure_child = SubagentRunService._ensure_child_conversation

    parent_conversation_id = await _create_lifecycle_conversation(
        session_factory,
        uid=uid,
        project_id=project_id,
        thread_id=parent_thread_id,
        label="subagent-project-delete-race",
        status="active",
    )

    async def pause_before_child_creation(self, **kwargs):
        child_boundary_reached.set()
        await allow_child_creation.wait()
        return await original_ensure_child(self, **kwargs)

    monkeypatch.setattr(SubagentRunService, "_ensure_child_conversation", pause_before_child_creation)

    async def create_subagent_relation():
        async with session_factory() as session:
            relation = await SubagentRunService(session)._ensure_thread_relation(
                child_thread_id=child_thread_id,
                uid=uid,
                agent_item=SimpleNamespace(slug=agent_slug, name="Worker"),
                creator_run=SimpleNamespace(
                    id=f"parent-run-{uuid.uuid4()}",
                    conversation_id=parent_conversation_id,
                    conversation_thread_id=parent_thread_id,
                ),
                continuing=False,
            )
            await session.commit()
            return relation.child_conversation_id

    async def delete_project():
        async with session_factory() as session:
            return await delete_project_view(uid=uid, project_id=project_id, db=session)

    creator_task = asyncio.create_task(create_subagent_relation())
    delete_task = None
    try:
        await asyncio.wait_for(child_boundary_reached.wait(), timeout=5)
        delete_task = asyncio.create_task(delete_project())
        await asyncio.sleep(0.05)
        assert not delete_task.done()

        allow_child_creation.set()
        child_conversation_id = await asyncio.wait_for(creator_task, timeout=5)
        delete_result = await asyncio.wait_for(delete_task, timeout=5)
        assert delete_result["deleted_conversations"] == 2

        async with _database_connection() as database:
            rows = await database.fetch(
                "SELECT id, status FROM conversations WHERE project_id = $1 ORDER BY id",
                project_id,
            )
            project_status = await database.fetchval("SELECT status FROM projects WHERE id = $1", project_id)

        assert project_status == "deleted"
        assert child_conversation_id in {row["id"] for row in rows}
        assert {row["status"] for row in rows} == {"deleted"}
    finally:
        allow_child_creation.set()
        tasks = [task for task in (creator_task, delete_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_subagent_rejects_parent_conversation_deleted_after_initial_read(
    monkeypatch: pytest.MonkeyPatch,
    project_lifecycle_database,
):
    """父 Conversation 在首次读取后被删除时，锁定复核必须拒绝创建子线程。"""
    session_factory, uid, project_id = project_lifecycle_database
    parent_thread_id = f"pytest-subagent-parent-{uuid.uuid4()}"
    child_thread_id = f"pytest-subdel-{uuid.uuid4()}"
    project_lookup_reached = asyncio.Event()
    allow_project_lookup = asyncio.Event()
    original_lock_active = ProjectRepository.lock_active_for_user

    parent_conversation_id = await _create_lifecycle_conversation(
        session_factory,
        uid=uid,
        project_id=project_id,
        thread_id=parent_thread_id,
        label="deleted-parent-race",
        status="active",
    )

    async def pause_before_project_lock(self, project_id, uid):
        project_lookup_reached.set()
        await allow_project_lookup.wait()
        return await original_lock_active(self, project_id, uid)

    monkeypatch.setattr(ProjectRepository, "lock_active_for_user", pause_before_project_lock)

    async def create_subagent_relation():
        async with session_factory() as session:
            return await SubagentRunService(session)._ensure_thread_relation(
                child_thread_id=child_thread_id,
                uid=uid,
                agent_item=SimpleNamespace(slug="default-chatbot", name="Worker"),
                creator_run=SimpleNamespace(
                    id=f"parent-run-{uuid.uuid4()}",
                    conversation_id=parent_conversation_id,
                    conversation_thread_id=parent_thread_id,
                ),
                continuing=False,
            )

    creator_task = asyncio.create_task(create_subagent_relation())
    try:
        await asyncio.wait_for(project_lookup_reached.wait(), timeout=5)
        async with _database_connection() as database:
            await database.execute(
                "UPDATE conversations SET status = 'deleted' WHERE id = $1",
                parent_conversation_id,
            )
        allow_project_lookup.set()

        with pytest.raises(ValueError, match="父运行任务的 Conversation 不存在"):
            await asyncio.wait_for(creator_task, timeout=5)

        async with _database_connection() as database:
            child_count = await database.fetchval(
                "SELECT COUNT(*) FROM conversations WHERE thread_id = $1",
                child_thread_id,
            )
            relation_count = await database.fetchval(
                "SELECT COUNT(*) FROM subagent_threads WHERE child_thread_id = $1",
                child_thread_id,
            )
        assert child_count == 0
        assert relation_count == 0
    finally:
        allow_project_lookup.set()
        if not creator_task.done():
            creator_task.cancel()
        await asyncio.gather(creator_task, return_exceptions=True)


async def test_subagent_run_scope_rejects_child_conversation_deleted_after_initial_read(
    project_lifecycle_database,
):
    """子 Conversation 在首次读取后被删除时，run scope 的锁定复核必须拒绝。"""
    session_factory, uid, project_id = project_lifecycle_database
    child_thread_id = f"pytest-subdel-{uuid.uuid4()}"
    initial_read_done = asyncio.Event()
    allow_scope_lock = asyncio.Event()

    child_conversation_id = await _create_lifecycle_conversation(
        session_factory,
        uid=uid,
        project_id=project_id,
        thread_id=child_thread_id,
        label="deleted-child-race",
        status="subagent",
    )

    async def prepare_scope_after_initial_read():
        async with session_factory() as session:
            cached = await ConversationRepository(session).get_conversation_by_id(child_conversation_id)
            assert cached is not None
            assert cached.status == "subagent"
            initial_read_done.set()
            await allow_scope_lock.wait()
            return await prepare_agent_run_creation_scope(
                agent_slug="default-chatbot",
                conversation_thread_id=child_thread_id,
                current_uid=uid,
                db=session,
                request_id=f"request-{uuid.uuid4()}",
                run_type="subagent",
                agent_kind="subagent",
            )

    scope_task = asyncio.create_task(prepare_scope_after_initial_read())
    try:
        await asyncio.wait_for(initial_read_done.wait(), timeout=5)
        async with _database_connection() as database:
            await database.execute(
                "UPDATE conversations SET status = 'deleted' WHERE id = $1",
                child_conversation_id,
            )
        allow_scope_lock.set()

        with pytest.raises(HTTPException) as exc_info:
            await asyncio.wait_for(scope_task, timeout=5)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "对话线程不存在"
    finally:
        allow_scope_lock.set()
        if not scope_task.done():
            scope_task.cancel()
        await asyncio.gather(scope_task, return_exceptions=True)
