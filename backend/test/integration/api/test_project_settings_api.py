"""项目设置真实 PostgreSQL 与 HTTP 协议集成证据。"""

import os
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.agent_router import agent_router
from server.routers.project_router import projects
from server.utils.auth_middleware import get_db, get_required_user
from yuxi.storage.postgres.manager import PROJECT_SETTINGS_SCHEMA_STATEMENTS, PostgresManager
from yuxi.storage.postgres.models_business import Agent, Project, ProjectAgent, ProjectSettings, User
from yuxi.storage.postgres.models_knowledge import KnowledgeBase

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离数据库验证不要求迁移运行中的服务。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """所有测试资源由隔离 schema 清理。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """本文件不创建沙盒。"""
    yield


@pytest_asyncio.fixture
async def settings_api():
    """装配真实路由与独立 PostgreSQL schema，仅注入测试用户身份。"""
    schema = f"project_settings_{uuid.uuid4().hex[:16]}"
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid = f"test-{uuid.uuid4().hex}"
    project_id = str(uuid.uuid4())
    user = User(uid=uid, username=uid, password_hash="test", role="user", is_deleted=0)
    app = FastAPI()
    app.include_router(projects, prefix="/api")
    app.include_router(agent_router, prefix="/api")

    async def session_dependency():
        """每次请求使用独立真实数据库事务。"""
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_required_user] = lambda: user
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = object.__new__(PostgresManager)
        PostgresManager.__init__(manager)
        manager.async_engine = engine
        manager._initialized = True
        await manager.create_business_tables()
        await manager.create_knowledge_tables()
        async with factory() as db:
            db.add(user)
            await db.flush()
            db.add(
                Project(
                    id=project_id,
                    uid=uid,
                    name="原名称",
                    selection_status="selectable",
                    directory_mode="managed",
                    workdir_path=f"projects/{project_id}",
                )
            )
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory, manager, app, user, project_id
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def test_defaults_and_atomic_settings_persistence(settings_api):
    client, factory, _, _, user, project_id = settings_api
    response = await client.get(f"/api/projects/{project_id}/settings")
    assert response.status_code == 200, response.text
    values = response.json()["settings"]
    assert values == {
        "work_status": "planned",
        "priority": "none",
        "owner_type": "member",
        "owner_id": user.uid,
        "description": "",
        "start_date": None,
        "due_date": None,
    }
    response = await client.put(
        f"/api/projects/{project_id}/settings",
        json={
            "name": "新名称",
            **values,
            "work_status": "paused",
            "description": "描" * 255,
            "start_date": "2026-10-03",
            "due_date": "2026-10-04",
        },
    )
    assert response.status_code == 200, response.text
    async with factory() as db:
        project = await db.get(Project, project_id)
        setting = await db.get(ProjectSettings, project_id)
        assert project.name == "新名称" and project.status == "active" and project.uid == user.uid
        assert setting.work_status == "paused" and setting.start_date.isoformat() == "2026-10-03"
        assert setting.description == "描" * 255
    readback = (await client.get(f"/api/projects/{project_id}/settings")).json()
    assert readback["settings"] == response.json()["settings"]


async def test_bad_date_and_foreign_agent_do_not_rename(settings_api):
    client, factory, _, _, user, project_id = settings_api
    values = (await client.get(f"/api/projects/{project_id}/settings")).json()["settings"]
    for changes, code in [
        ({"start_date": "2026-10-04", "due_date": "2026-10-03"}, 422),
        ({"owner_type": "agent", "owner_id": "foreign-agent"}, 422),
        ({"description": "x" * 256}, 422),
    ]:
        result = await client.put(
            f"/api/projects/{project_id}/settings", json={"name": "不能保存", **values, **changes}
        )
        assert result.status_code == code, result.text
    async with factory() as db:
        assert (await db.get(Project, project_id)).name == "原名称"
        assert await db.get(ProjectSettings, project_id) is None


async def test_responsibility_does_not_authorize_and_private_kb_not_linkable(settings_api):
    client, factory, _, app, user, project_id = settings_api
    other = User(uid="other", username="other", password_hash="test", role="user", is_deleted=0)
    async with factory() as db:
        db.add(other)
        db.add(
            KnowledgeBase(
                kb_id="private",
                name="秘密知识库",
                kb_type="milvus",
                created_by="other",
                share_config={"version": 2, "read_scope": None, "manage_scope": None},
            )
        )
        await db.commit()
    result = await client.put(f"/api/projects/{project_id}/knowledge-links", json={"kb_ids": ["private"]})
    assert result.status_code == 403, result.text
    values = (await client.get(f"/api/projects/{project_id}/settings")).json()["settings"]
    result = await client.put(
        f"/api/projects/{project_id}/settings", json={"name": "原名称", **values, "owner_id": other.uid}
    )
    assert result.status_code == 200, result.text
    app.dependency_overrides[get_required_user] = lambda: other
    assert (await client.get(f"/api/projects/{project_id}/settings")).status_code == 404
    assert (await client.put(f"/api/projects/{project_id}/knowledge-links", json={"kb_ids": []})).status_code == 404


async def test_migration_backfills_creator_and_is_idempotent(settings_api):
    _, factory, manager, _, user, project_id = settings_api
    async with manager.async_engine.begin() as conn:
        await conn.execute(text("DROP TABLE project_settings"))
        await conn.execute(text("DROP TABLE project_knowledge_links"))
    await manager.upgrade_yuanlei_schema_v21_to_v22()
    await manager.upgrade_yuanlei_schema_v21_to_v22()
    async with factory() as db:
        rows = list((await db.scalars(select(ProjectSettings))).all())
        assert len(rows) == 1
        assert rows[0].project_id == project_id and rows[0].owner_id == user.uid
        assert rows[0].work_status == "planned" and rows[0].priority == "none"
    assert "UPDATE projects" not in " ".join(PROJECT_SETTINGS_SCHEMA_STATEMENTS)


async def test_knowledge_link_does_not_restore_revoked_read_access(settings_api):
    client, factory, _, _, user, project_id = settings_api
    async with factory() as db:
        db.add(
            KnowledgeBase(
                kb_id="shared",
                name="共享知识库",
                kb_type="milvus",
                created_by="external",
                share_config={
                    "version": 2,
                    "read_scope": {"access_level": "user", "user_uids": [user.uid]},
                    "manage_scope": None,
                },
            )
        )
        await db.commit()
    response = await client.put(f"/api/projects/{project_id}/knowledge-links", json={"kb_ids": ["shared"]})
    assert response.status_code == 200, response.text
    assert response.json()["knowledge_links"] == [{"kb_id": "shared", "name": "共享知识库", "accessible": True}]
    async with factory() as db:
        kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == "shared"))
        kb.share_config = {"version": 2, "read_scope": None, "manage_scope": None}
        await db.commit()
    response = await client.get(f"/api/projects/{project_id}/settings")
    assert response.json()["knowledge_candidates"] == []
    assert response.json()["knowledge_links"] == [{"kb_id": "shared", "name": None, "accessible": False}]
    response = await client.put(f"/api/projects/{project_id}/knowledge-links", json={"kb_ids": []})
    assert response.status_code == 200 and response.json()["knowledge_links"] == []
    async with factory() as db:
        assert await db.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == "shared")) is not None


async def test_project_agent_owner_must_be_transferred_before_unbinding(settings_api):
    from yuxi.services.project_agent_service import unbind_project_agent_view
    from fastapi import HTTPException

    client, factory, _, _, user, project_id = settings_api
    async with factory() as db:
        db.add(
            Agent(
                slug="project-owner",
                name="项目负责人",
                backend_id="chatbot",
                created_by=user.uid,
                share_config={"version": 2, "read_scope": None, "manage_scope": None},
            )
        )
        await db.flush()
        db.add(
            ProjectAgent(id=str(uuid.uuid4()), project_id=project_id, agent_slug="project-owner", config_overrides={})
        )
        await db.commit()
    values = (await client.get(f"/api/projects/{project_id}/settings")).json()["settings"]
    response = await client.put(
        f"/api/projects/{project_id}/settings",
        json={"name": "原名称", **values, "owner_type": "agent", "owner_id": "project-owner"},
    )
    assert response.status_code == 200, response.text
    response = await client.delete("/api/agent/project-owner")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "该智能体仍是项目负责人，请先转移责任"
    async with factory() as db:
        assert await db.scalar(select(Agent).where(Agent.slug == "project-owner")) is not None
        assert await db.scalar(select(ProjectAgent).where(ProjectAgent.project_id == project_id)) is not None
        assert (await db.get(ProjectSettings, project_id)).owner_id == "project-owner"
    async with factory() as db:
        with pytest.raises(HTTPException) as error:
            await unbind_project_agent_view(
                project_id=project_id, agent_slug="project-owner", delete_agent=False, db=db, user=user
            )
        assert error.value.status_code == 409 and error.value.detail == "该智能体仍是项目负责人，请先转移责任"
        await db.rollback()
    async with factory() as db:
        assert await db.scalar(select(ProjectAgent).where(ProjectAgent.project_id == project_id)) is not None
        assert (await db.get(ProjectSettings, project_id)).owner_id == "project-owner"
    response = await client.put(f"/api/projects/{project_id}/settings", json={"name": "原名称", **values})
    assert response.status_code == 200, response.text
    async with factory() as db:
        await unbind_project_agent_view(
            project_id=project_id, agent_slug="project-owner", delete_agent=False, db=db, user=user
        )
    async with factory() as db:
        assert await db.scalar(select(ProjectAgent).where(ProjectAgent.project_id == project_id)) is None
        assert (await db.get(ProjectSettings, project_id)).owner_id == user.uid


@pytest.mark.parametrize("yuanlei_version", [None, 21])
async def test_real_migration_entry_initializes_or_upgrades_yuanlei(
    settings_api, monkeypatch, tmp_path, yuanlei_version
):
    from yuxi import storage_migration
    from yuxi.storage.postgres.manager import BUSINESS_SCHEMA_VERSION, KNOWLEDGE_SCHEMA_VERSION, YUANLEI_SCHEMA_VERSION
    from yuxi.storage_migrations.v071_workdirs import V071WorkdirMigrationPlan

    _, factory, manager, _, user, project_id = settings_api
    manager.AsyncSession = factory
    async with manager.async_engine.begin() as conn:
        await conn.execute(text("DROP TABLE project_settings"))
        await conn.execute(text("DROP TABLE project_knowledge_links"))
    await manager.create_schema_version_table()
    await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION)
    await manager.record_schema_version("knowledge", KNOWLEDGE_SCHEMA_VERSION)
    if yuanlei_version is not None:
        await manager.record_schema_version("yuanlei", yuanlei_version)

    async def no_side_effect(*args, **kwargs):
        """本用例只隔离无关的文件迁移与配置初始化。"""

    async def empty_workdir_plan(db):
        """独立 schema 没有旧版文件需要迁移。"""
        return V071WorkdirMigrationPlan(False, (), ())

    monkeypatch.setattr(storage_migration, "pg_manager", manager)
    monkeypatch.setattr(manager, "initialize", lambda: None)
    monkeypatch.setattr(manager, "close", no_side_effect)
    monkeypatch.setattr(storage_migration, "read_v071_workdir_plan", empty_workdir_plan)
    monkeypatch.setattr(storage_migration, "_legacy_skill_roots_exist", lambda: False)
    monkeypatch.setattr(storage_migration, "_legacy_system_config_exists", lambda: False)
    monkeypatch.setattr(storage_migration, "runtime_storage_requires_quiescence", lambda: False)
    monkeypatch.setattr(storage_migration, "_converge_database_state", no_side_effect)
    monkeypatch.setattr(storage_migration, "migrate_shared_skills", no_side_effect)
    monkeypatch.setattr(storage_migration, "mark_v071_skills_migrated", lambda: None)
    monkeypatch.setattr(storage_migration, "migrate_runtime_storage_identity", lambda: None)
    monkeypatch.setattr(storage_migration, "get_legacy_storage_dir", lambda: tmp_path)
    await storage_migration.main()
    assert await manager.get_schema_versions() == {
        "business": BUSINESS_SCHEMA_VERSION,
        "knowledge": KNOWLEDGE_SCHEMA_VERSION,
        "yuanlei": YUANLEI_SCHEMA_VERSION,
    }
    await manager.require_current_schema()
    async with factory() as db:
        settings = await db.get(ProjectSettings, project_id)
        assert settings.owner_id == user.uid and settings.work_status == "planned"
        assert await db.scalar(text("SELECT COUNT(*) FROM project_knowledge_links")) == 0


async def test_owner_candidates_expose_profile_images_without_account_secrets(settings_api):
    client, factory, _, _, user, project_id = settings_api
    async with factory() as db:
        member = await db.scalar(select(User).where(User.uid == user.uid))
        member.avatar = "https://example.com/member.png"
        db.add(
            Agent(
                slug="pictured-agent",
                name="有头像的智能体",
                backend_id="chatbot",
                created_by=user.uid,
                icon="https://example.com/agent.png",
                share_config={"version": 2, "read_scope": None, "manage_scope": None},
            )
        )
        await db.flush()
        db.add(
            ProjectAgent(
                id=str(uuid.uuid4()),
                project_id=project_id,
                agent_slug="pictured-agent",
                config_overrides={},
            )
        )
        await db.commit()
    response = await client.get(f"/api/projects/{project_id}/settings")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["members"] == [{"id": user.uid, "name": user.username, "avatar": "https://example.com/member.png"}]
    assert result["agents"] == [
        {"id": "pictured-agent", "name": "有头像的智能体", "icon": "https://example.com/agent.png"}
    ]


async def test_task_knowledge_selection_requires_link_and_access(settings_api):
    """实际 HTTP/PG 验证任务选择不授权、活动执行拒绝变更、迁移幂等。"""
    from server.routers.project_work_router import project_work
    from yuxi.storage.postgres.models_business import ProjectWorkTask, ProjectWorkExecution

    client, factory, manager, app, user, project_id = settings_api
    app.include_router(project_work, prefix="/api")
    async with factory() as db:
        for identity, owner in [("task-readable", user.uid), ("task-unlinked", user.uid), ("task-private", "other")]:
            db.add(
                KnowledgeBase(
                    kb_id=identity,
                    name=identity,
                    kb_type="milvus",
                    created_by=owner,
                    share_config={"version": 2, "read_scope": None, "manage_scope": None},
                )
            )
        await db.commit()
    assert (
        await client.put(f"/api/projects/{project_id}/knowledge-links", json={"kb_ids": ["task-readable"]})
    ).status_code == 200
    root = f"/api/projects/{project_id}/work"
    assert (await client.put(f"{root}/code", json={"code": "TEST"})).status_code == 200
    response = await client.post(f"{root}/tasks", json={"title": "显式知识库选择"})
    assert response.status_code == 200, response.text
    task_id = response.json()["id"]
    assert response.json()["knowledge_ids"] == []
    path = f"{root}/tasks/{task_id}"
    for denied in ["task-private", "task-unlinked"]:
        assert (await client.patch(path, json={"knowledge_ids": [denied]})).status_code == 403
    response = await client.patch(path, json={"knowledge_ids": ["task-readable"]})
    assert response.status_code == 200, response.text
    read = (await client.get(path)).json()
    assert read["knowledge_ids"] == ["task-readable"]
    assert read["knowledge_candidates"] == [{"kb_id": "task-readable", "name": "task-readable"}]
    async with factory() as db:
        assert (await db.get(ProjectWorkTask, task_id)).knowledge_ids == ["task-readable"]
        db.add(
            ProjectWorkExecution(
                id="knowledge-execution",
                task_id=task_id,
                project_id=project_id,
                uid=user.uid,
                agent_slug="employee",
                status="queued",
                prompt="test",
                request_id="knowledge-request",
                thread_id="knowledge-thread",
            )
        )
        await db.commit()
    from types import SimpleNamespace
    from yuxi.services.project_agent_service import load_task_knowledge_selection

    async with factory() as db:
        continuation = SimpleNamespace(run_type="chat", source="chat", conversation_thread_id="knowledge-thread")
        assert await load_task_knowledge_selection(db=db, uid=user.uid, project_id=project_id, run=continuation) == [
            "task-readable"
        ]
        assert (
            await load_task_knowledge_selection(db=db, uid="other-user", project_id=project_id, run=continuation) == []
        )
        assert (
            await load_task_knowledge_selection(db=db, uid=user.uid, project_id="other-project", run=continuation) == []
        )
    assert (await client.patch(path, json={"knowledge_ids": []})).status_code == 409
    await manager.upgrade_yuanlei_schema_v26_to_v27()
    await manager.upgrade_yuanlei_schema_v26_to_v27()
    async with factory() as db:
        assert (await db.get(ProjectWorkTask, task_id)).knowledge_ids == ["task-readable"]
