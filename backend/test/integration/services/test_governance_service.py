"""元垒项目治理域用例的真实 PostgreSQL 集成测试。

覆盖多来源归一化写读、重复外部标识拒绝、无来源输入拒绝，以及
proposed 未经审核不得成为 canonical 的数据库与用例双层约束。
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yuxi.services.governance_service import (
    create_governance_decision,
    operate_governance_decision,
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
            assert by_channel["multica"]["admission_status"] == "proposed"
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
            assert topic["admission_status"] == "proposed"
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
            assert reviewed["admission_status"] == "canonical"
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
                db=session,
                user=user,
            )
            assert decision["status"] == "draft"
            decision = await operate_governance_decision(
                project_id="project-owner",
                decision_id=decision["id"],
                action="approve",
                expected_revision=decision["revision_number"],
                reason="批准",
                db=session,
                user=user,
            )
            assert decision["status"] == "approved"
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

            with pytest.raises(HTTPException) as approval:
                await review_governance_task(project_id="project-owner", task_id=task["id"], approve=True,
                                             review_note=None, db=session, user=user)
            assert approval.value.detail["code"] == "admission_required"
            reviewed = await review_governance_task(project_id="project-owner", task_id=task["id"], approve=False,
                                                    review_note="保留来源", db=session, user=user)
            assert reviewed["status"] == "rejected"
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


async def test_topic_revision_lifecycle_and_protected_deletion():
    """持续研讨保留快照，显式重开不改正式决策，引用保护软删除。"""
    from yuxi.services.governance_service import (
        update_governance_topic,
        create_governance_topic_comment,
        operate_governance_topic,
        get_governance_topic_timeline,
    )

    async with _scoped_database("pytest_topic_lifecycle") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as db:
            user = await _load_user(db, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="原题",
                summary="原文",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            context = dict(project_id="project-owner", topic_id=topic["id"], db=db, user=user)

            async def operation(action, **kwargs):
                return await operate_governance_topic(
                    **context,
                    action=action,
                    reason="核对原因",
                    execution_hint=kwargs.get("execution_hint"),
                    decision_id=kwargs.get("decision_id"),
                )

            await review_governance_topic(**context, approve=False, review_note="暂不纳入")
            revised = await update_governance_topic(
                **context, title="修订题", summary="修订文", expected_revision=1, reason="补充事实"
            )
            assert revised["admission_status"] == "rejected" and revised["revision_number"] == 2
            for kind in ("discussion", "reconsideration", "correction"):
                comment = await create_governance_topic_comment(**context, content=kind, discussion_type=kind)
                assert comment["revision_number"] == 2
            assert (await get_governance_topic(**context))["progress"] == "open"
            with pytest.raises(HTTPException) as conflict:
                await update_governance_topic(
                    **context, title="覆盖", summary="覆盖", expected_revision=1, reason="并发"
                )
            assert conflict.value.detail["code"] == "revision_conflict"
            await operation("resubmit")
            with pytest.raises(HTTPException):
                await operation("resubmit")
            await review_governance_topic(**context, approve=True, review_note="纳入管理")
            decision = await create_governance_decision(
                project_id="project-owner",
                topic_id=topic["id"],
                title="决策",
                conclusion="保留原方案",
                rationale="理由",
                db=db,
                user=user,
            )
            decision = await operate_governance_decision(
                project_id="project-owner",
                decision_id=decision["id"],
                action="approve",
                expected_revision=decision["revision_number"],
                reason="批准",
                db=db,
                user=user,
            )
            assert decision["topic_revision_number"] == 2
            assert (await get_governance_topic(**context))["progress"] == "open"
            with pytest.raises(HTTPException) as missing:
                await operation("decide", decision_id="missing")
            assert missing.value.detail["code"] == "decision_required"
            assert (await operation("decide", decision_id=decision["id"]))["progress"] == "decided"
            await operation("reopen", execution_hint="pause_recommended")
            await update_governance_topic(
                **context, title="新方向", summary="新正文", expected_revision=2, reason="实践反馈"
            )
            saved = (
                await db.execute(
                    text("SELECT conclusion,topic_revision_number FROM governance_decisions WHERE id=:id"),
                    {"id": decision["id"]},
                )
            ).one()
            assert tuple(saved) == ("保留原方案", 2)
            assert (await get_governance_topic(**context))["execution_hint"] == "pause_recommended"
            with pytest.raises(HTTPException) as protected:
                await operation("delete")
            assert protected.value.detail["references"] == ["关联决策"]
            await operation("archive")
            assert await list_governance_topics(project_id="project-owner", db=db, user=user) == []
            assert (
                len(await list_governance_topics(project_id="project-owner", include_archived=True, db=db, user=user))
                == 1
            )
            with pytest.raises(HTTPException):
                await create_governance_topic_comment(**context, content="归档不写")
            await operation("restore")
            timeline = await get_governance_topic_timeline(**context, before=None, limit=3)
            sequences = [e["sequence"] for e in timeline["items"]]
            assert sequences == sorted(sequences, reverse=True)
            older = await get_governance_topic_timeline(**context, before=timeline["next_before"], limit=100)
            assert not set(sequences).intersection(e["sequence"] for e in older["items"])
            assert any(e["revision"] and e["revision"]["summary"] == "原文" for e in older["items"])
            assert (
                await db.execute(
                    text("SELECT count(*) FROM governance_topic_revisions WHERE topic_id=:id"), {"id": topic["id"]}
                )
            ).scalar() == 3
            empty = await create_governance_topic(
                project_id="project-owner",
                title="误建",
                summary=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            await operate_governance_topic(
                project_id="project-owner",
                topic_id=empty["id"],
                action="delete",
                reason="误建",
                execution_hint=None,
                decision_id=None,
                db=db,
                user=user,
            )
            assert (
                await db.execute(text("SELECT deleted_at FROM governance_topics WHERE id=:id"), {"id": empty["id"]})
            ).scalar() is not None
            with pytest.raises(HTTPException) as deleted:
                await get_governance_topic(project_id="project-owner", topic_id=empty["id"], db=db, user=user)
            assert deleted.value.status_code == 404


@pytest.mark.parametrize("migration_entry", ["versioned", "unversioned"])
async def test_topic_v27_migration_preserves_unknown_history(migration_entry, monkeypatch):
    """真实旧列结构升级两次，旧审核评论不伪造正文版本。"""
    from yuxi.services.governance_service import get_governance_topic_timeline

    async with _scoped_database("pytest_topic_migration") as (manager, sessions):
        await _seed_scope(manager)
        async with manager.async_engine.begin() as conn:
            await conn.execute(text("DROP TABLE governance_topic_events, governance_topic_revisions CASCADE"))
            for column in (
                "progress",
                "execution_hint",
                "archived_at",
                "deleted_at",
                "revision_number",
                "history_sequence",
            ):
                await conn.execute(text(f"ALTER TABLE governance_topics DROP COLUMN {column} CASCADE"))
            await conn.execute(
                text("ALTER TABLE governance_topic_comments DROP COLUMN revision_number, DROP COLUMN discussion_type")
            )
            await conn.execute(text("ALTER TABLE governance_decisions DROP COLUMN topic_revision_number"))
            await conn.execute(
                text(
                    "INSERT INTO governance_topics (id,project_id,title,summary,status,source_channel,review_owner_uid,reviewed_at,created_at,updated_at) VALUES ('old','project-owner','旧题','仅存正文','canonical','project','uid-owner','2026-01-02','2026-01-01','2026-01-03')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO governance_topic_comments(id,topic_id,content,author_name,created_at) VALUES ('old-comment','old','旧评论','旧作者','2026-01-03')"
                )
            )
        if migration_entry == "unversioned":
            from yuxi import storage_migration

            monkeypatch.setattr(storage_migration, "pg_manager", manager)
            await storage_migration._ensure_yuanlei_schema()
        else:
            await manager.upgrade_yuanlei_schema_v27_to_v28()
        await manager.upgrade_yuanlei_schema_v27_to_v28()
        async with sessions() as db:
            user = await _load_user(db, "uid-owner")
            topic = await get_governance_topic(project_id="project-owner", topic_id="old", db=db, user=user)
            assert (topic["admission_status"], topic["progress"]) == ("canonical", "open")
            line = await get_governance_topic_timeline(
                project_id="project-owner", topic_id="old", before=None, limit=100, db=db, user=user
            )
            assert [e["kind"] for e in line["items"]] == ["migration_baseline", "comment", "admitted", "created"]
            assert line["items"][1]["revision"] is None
            assert line["items"][0]["revision"]["origin"] == "migration"
            assert line["items"][1]["comment"]["author_name"] == "旧作者"


async def test_topic_concurrent_edit_and_reference_deletion_lock():
    """双会话竞争同一修订只成功一次，引用提交与删除按同一行锁串行。"""
    import asyncio
    from yuxi.repositories.governance_repository import GovernanceRepository
    from yuxi.services.governance_service import update_governance_topic, operate_governance_topic

    async with _scoped_database("pytest_topic_concurrency") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as db:
            user = await _load_user(db, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="并发题",
                summary="原文",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )

        async def edit(title):
            async with sessions() as db:
                user = await _load_user(db, "uid-owner")
                try:
                    return await update_governance_topic(
                        project_id="project-owner",
                        topic_id=topic["id"],
                        title=title,
                        summary=title,
                        expected_revision=1,
                        reason="并发编辑",
                        db=db,
                        user=user,
                    )
                except HTTPException as error:
                    return error

        outcomes = await asyncio.gather(edit("甲"), edit("乙"))
        assert sum(isinstance(result, dict) for result in outcomes) == 1
        assert [result.detail["code"] for result in outcomes if isinstance(result, HTTPException)] == [
            "revision_conflict"
        ]
        async with sessions() as reference_db:
            repo = GovernanceRepository(reference_db)
            await repo.get_topic_for_update(topic_id=topic["id"])
            await repo.add_decision(
                project_id="project-owner",
                topic_id=topic["id"],
                title="引用",
                conclusion="正式依据",
                rationale=None,
                operator="uid-owner",
                topic_revision_number=2,
            )
            started = asyncio.Event()

            async def delete():
                async with sessions() as db:
                    user = await _load_user(db, "uid-owner")
                    started.set()
                    try:
                        await operate_governance_topic(
                            project_id="project-owner",
                            topic_id=topic["id"],
                            action="delete",
                            reason="并发删除",
                            execution_hint=None,
                            decision_id=None,
                            db=db,
                            user=user,
                        )
                    except HTTPException as error:
                        return error

            pending = asyncio.create_task(delete())
            await started.wait()
            await reference_db.commit()
            refused = await pending
            assert refused.detail["code"] == "topic_referenced"
        async with sessions() as db:
            assert (
                await db.execute(
                    text("SELECT deleted_at,revision_number FROM governance_topics WHERE id=:id"), {"id": topic["id"]}
                )
            ).one() == (None, 2)


@pytest.mark.parametrize("reference_kind", ["governance", "work"])
async def test_topic_task_references_block_delete_and_reopen_preserves_run(reference_kind):
    """两类任务保护引用；议题建议暂停不改任务、执行及 Run 快照。"""
    from yuxi.services.governance_service import operate_governance_topic
    from yuxi.storage.postgres.models_business import ProjectWorkTask, ProjectWorkExecution, AgentRun

    async with _scoped_database("pytest_topic_task_refs") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as db:
            user = await _load_user(db, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="有关联任务",
                summary="背景",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            context = dict(project_id="project-owner", topic_id=topic["id"], db=db, user=user)

            async def op(action, **kwargs):
                return await operate_governance_topic(
                    **context,
                    action=action,
                    reason="实践反馈",
                    execution_hint=kwargs.get("execution_hint"),
                    decision_id=None,
                )

            if reference_kind == "governance":
                task = await create_governance_task(
                    project_id="project-owner",
                    topic_id=topic["id"],
                    title="治理任务",
                    description="原任务说明",
                    decision_id=None,
                    assignee_agent_slug=None,
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=db,
                    user=user,
                )
                label = "治理任务及其执行依据"
            else:
                db.add(
                    ProjectWorkTask(
                        id="work",
                        project_id="project-owner",
                        topic_id=topic["id"],
                        number="TEST-001",
                        title="正式工作",
                        status="in_progress",
                        created_by="uid-owner",
                    )
                )
                db.add(
                    AgentRun(
                        id="run",
                        uid="uid-owner",
                        agent_slug="employee",
                        conversation_thread_id="thread",
                        runtime_scope_id="thread",
                        request_id="request",
                        status="interrupted",
                        input_payload={"task": "原输入"},
                    )
                )
                await db.flush()
                db.add(
                    ProjectWorkExecution(
                        id="execution",
                        task_id="work",
                        project_id="project-owner",
                        uid="uid-owner",
                        agent_slug="employee",
                        status="interrupted",
                        prompt="原执行输入",
                        request_id="work-request",
                        thread_id="work-thread",
                        current_run_id="run",
                    )
                )
                await db.commit()
                label = "正式工作及其执行依据"
            with pytest.raises(HTTPException) as protected:
                await op("delete")
            assert protected.value.detail["references"] == [label]
            await op("close")
            await op("reopen", execution_hint="pause_recommended")
            if reference_kind == "governance":
                assert (
                    await db.execute(
                        text("SELECT status,description FROM governance_tasks WHERE id=:id"), {"id": task["id"]}
                    )
                ).one() == ("proposed", "原任务说明")
            else:
                assert (
                    await db.execute(text("SELECT status FROM project_work_tasks WHERE id='work'"))
                ).scalar() == "in_progress"
                assert (
                    await db.execute(text("SELECT status,prompt FROM project_work_executions WHERE id='execution'"))
                ).one() == ("interrupted", "原执行输入")
                assert (await db.execute(text("SELECT status,input_payload FROM agent_runs WHERE id='run'"))).one() == (
                    "interrupted",
                    {"task": "原输入"},
                )


async def test_decision_v28_migration_preserves_original_approval_and_is_reentrant():
    """旧记录只建立一次基线，不虚构批准时间或过往修订。"""
    async with _scoped_database("pytest_decision_migration") as (manager, _):
        await _seed_user(manager.async_engine, uid="uid-owner")
        await _seed_project(manager.async_engine, project_id="project-owner", uid="uid-owner")
        async with manager.async_engine.begin() as conn:
            for table in ("governance_decision_errata", "governance_decision_events", "governance_decision_revisions"):
                await conn.execute(text(f"DROP TABLE {table} CASCADE"))
            for name in (
                "ck_governance_decisions_status",
                "ck_governance_decisions_decision_shape",
                "fk_decision_target_project",
                "ck_decision_relation_shape",
                "ck_decision_revision_sequence",
            ):
                await conn.execute(text(f"ALTER TABLE governance_decisions DROP CONSTRAINT {name}"))
            for column in ("relation_type", "target_decision_id", "revision_number", "history_sequence", "deleted_at"):
                await conn.execute(text(f"ALTER TABLE governance_decisions DROP COLUMN {column}"))
            await conn.execute(
                text(
                    "INSERT INTO "
                    "governance_decisions(id,project_id,title,conclusion,status,created_by,created_at,updated_at,decided_by,decided_at) "
                    "VALUES "
                    "('legacy-draft','project-owner','旧草案','未知前文','proposed','uid-owner','2025-01-01','2025-01-02',NULL,NULL),"
                    "('legacy-approved','project-owner','旧正式决策','旧批准原文','implemented','uid-owner','2025-01-01','2025-01-02','原拍板者','2025-02-03')"
                )
            )
        await manager.upgrade_yuanlei_schema_v28_to_v29()
        async with manager.async_engine.connect() as conn:
            baseline = (
                await conn.execute(
                    text(
                        "SELECT decision_id,created_at,snapshot,origin FROM "
                        "governance_decision_revisions ORDER BY decision_id"
                    )
                )
            ).all()
            assert len(baseline) == 2 and all(row.origin == "migration" for row in baseline)
            assert (
                await conn.execute(
                    text(
                        "SELECT status,decided_by,decided_at::date FROM governance_decisions WHERE id='legacy-approved'"
                    )
                )
            ).one() == ("approved", "原拍板者", date(2025, 2, 3))
            assert (
                await conn.execute(
                    text("SELECT status,decided_by,decided_at FROM governance_decisions WHERE id='legacy-draft'")
                )
            ).one() == ("draft", None, None)
        await manager.upgrade_yuanlei_schema_v28_to_v29()
        async with manager.async_engine.connect() as conn:
            assert (
                await conn.execute(
                    text(
                        "SELECT decision_id,created_at,snapshot,origin FROM "
                        "governance_decision_revisions ORDER BY decision_id"
                    )
                )
            ).all() == baseline
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM governance_decision_events WHERE kind='migration_baseline'")
                )
            ).scalar() == 2
            assert (
                await conn.execute(text("SELECT min(history_sequence),max(history_sequence) FROM governance_decisions"))
            ).one() == (1, 1)
