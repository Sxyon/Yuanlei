"""督查板只读聚合的真实 PostgreSQL 集成测试。

覆盖治理事实与执行事实从唯一事实源读取、跨项目待决策队列与阻塞项汇总，以及
汇报只引用产出 Run、不改写 Run 终态。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from test.integration.services.test_governance_service import (
    _load_user,
    _scoped_database,
    _seed_scope,
)
from yuxi.services.governance_service import (
    create_governance_decision,
    create_governance_report,
    create_governance_task,
    create_governance_topic,
    list_governance_decisions,
    list_governance_reports,
    list_governance_tasks,
    list_governance_topics,
)
from yuxi.services.inspection_board_service import (
    get_project_inspection_board,
    get_user_inspection_board,
)

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


async def _seed_conversation(engine, *, thread_id: str, uid: str, project_id: str, agent_slug: str) -> int:
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "INSERT INTO conversations (thread_id, uid, agent_id, project_id, status, is_pinned) "
                "VALUES (:thread_id, :uid, :agent_slug, :project_id, 'active', FALSE) RETURNING id"
            ),
            {"thread_id": thread_id, "uid": uid, "agent_slug": agent_slug, "project_id": project_id},
        )
        return int(result.scalar_one())


async def _seed_run(
    engine,
    *,
    run_id: str,
    thread_id: str,
    uid: str,
    agent_slug: str,
    status: str,
    conversation_id: int,
    error_type: str | None = None,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO agent_runs (id, conversation_thread_id, runtime_scope_id, agent_slug, uid, status, "
                "request_id, source, channel, run_type, conversation_id, origin_metadata, input_payload, "
                "token_usage, error_type, created_at, updated_at) "
                "VALUES (:id, :thread_id, :runtime_scope, :agent_slug, :uid, :status, :request_id, 'scheduled', "
                "'worker', 'chat', :conversation_id, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, :error_type, now(), now())"
            ),
            {
                "id": run_id,
                "thread_id": thread_id,
                "runtime_scope": thread_id,
                "agent_slug": agent_slug,
                "uid": uid,
                "status": status,
                "request_id": f"req-{run_id}",
                "conversation_id": conversation_id,
                "error_type": error_type,
            },
        )


async def test_project_board_reads_governance_and_run_facts_from_source() -> None:
    """督查板展示的议题/任务/决策与执行事实与唯一事实源逐项一致。"""
    async with _scoped_database("pytest_board_source") as (manager, sessions):
        await _seed_scope(manager)
        thread_id = str(uuid.uuid4())
        conversation_id = await _seed_conversation(
            manager.async_engine,
            thread_id=thread_id,
            uid="uid-owner",
            project_id="project-owner",
            agent_slug="employee",
        )
        await _seed_run(
            manager.async_engine,
            run_id="run-failed",
            thread_id=thread_id,
            uid="uid-owner",
            agent_slug="employee",
            status="failed",
            conversation_id=conversation_id,
            error_type="ModelTimeout",
        )
        await _seed_run(
            manager.async_engine,
            run_id="run-completed",
            thread_id=thread_id,
            uid="uid-owner",
            agent_slug="employee",
            status="completed",
            conversation_id=conversation_id,
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            topic = await create_governance_topic(
                project_id="project-owner",
                title="督查发现",
                summary="来源归一化",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=session,
                user=user,
            )
            decision = await create_governance_decision(
                project_id="project-owner",
                title="采纳议题",
                conclusion="进入实施",
                rationale=None,
                topic_id=topic["id"],
                db=session,
                user=user,
            )
            task = await create_governance_task(
                project_id="project-owner",
                title="落实任务",
                description=None,
                topic_id=topic["id"],
                decision_id=None,
                assignee_agent_slug="employee",
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=session,
                user=user,
            )
            report = await create_governance_report(
                project_id="project-owner",
                title="周期汇报",
                summary="本周",
                content={"completed": 1},
                source_run_id="run-completed",
                artifact_path="reports/weekly.md",
                db=session,
                user=user,
            )

            board = await get_project_inspection_board(project_id="project-owner", db=session, user=user)
            assert board["governance"]["topics"] == await list_governance_topics(
                project_id="project-owner", db=session, user=user
            )
            assert board["governance"]["tasks"] == await list_governance_tasks(
                project_id="project-owner", db=session, user=user
            )
            assert board["governance"]["decisions"] == await list_governance_decisions(
                project_id="project-owner", db=session, user=user
            )
            assert board["governance"]["reports"] == await list_governance_reports(
                project_id="project-owner", db=session, user=user
            )
            assert [item["id"] for item in board["governance"]["pending_topics"]] == [topic["id"]]
            assert [item["id"] for item in board["governance"]["pending_tasks"]] == [task["id"]]
            assert [item["id"] for item in board["governance"]["pending_decisions"]] == [decision["id"]]
            assert [item["id"] for item in board["governance"]["reports"]] == [report["id"]]
            assert board["governance"]["pending_topics"][0]["admission_status"] == "proposed"

            execution = board["execution"]
            assert execution["run_status_counts"] == {"completed": 1, "failed": 1}
            assert {item["id"] for item in execution["recent_runs"]} == {"run-completed", "run-failed"}
            assert [item["id"] for item in execution["blocked_runs"]] == ["run-failed"]
            assert execution["blocked_runs"][0]["error_type"] == "ModelTimeout"


async def test_board_rejects_invisible_or_unknown_project() -> None:
    """不可见或未知 Project 的督查板返回 404，不泄漏他人事实。"""
    async with _scoped_database("pytest_board_scope") as (manager, sessions):
        await _seed_scope(manager)
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            with pytest.raises(HTTPException) as missing:
                await get_project_inspection_board(project_id="missing-project", db=session, user=user)
            assert missing.value.status_code == 404


async def test_cross_project_board_aggregates_pending_and_blockers() -> None:
    """跨项目督查板汇总多个 Project 的 open 议题与阻塞项。"""
    async with _scoped_database("pytest_board_cross") as (manager, sessions):
        await _seed_scope(manager)
        async with manager.async_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                    "VALUES ('project-secondary', 'uid-owner', 'Second', 'selectable', "
                    "'projects/project-secondary', 'linked')"
                )
            )
        for project_id, run_id in (
            ("project-owner", "run-a"),
            ("project-secondary", "run-b"),
        ):
            thread_id = str(uuid.uuid4())
            conversation_id = await _seed_conversation(
                manager.async_engine,
                thread_id=thread_id,
                uid="uid-owner",
                project_id=project_id,
                agent_slug="employee",
            )
            await _seed_run(
                manager.async_engine,
                run_id=run_id,
                thread_id=thread_id,
                uid="uid-owner",
                agent_slug="employee",
                status="interrupted",
                conversation_id=conversation_id,
            )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            for project_id in ("project-owner", "project-secondary"):
                await create_governance_topic(
                    project_id=project_id,
                    title=f"{project_id} 议题",
                    summary=None,
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=session,
                    user=user,
                )
            board = await get_user_inspection_board(db=session, user=user)
            assert board["summary"] == {
                "projects": 2,
                "open_topics": 2,
                "pending_tasks": 0,
                "pending_decisions": 0,
                "blockers": 2,
            }
            assert {item["project"]["id"] for item in board["projects"]} == {
                "project-owner",
                "project-secondary",
            }


async def test_report_write_references_run_without_changing_run_status() -> None:
    """汇报写入只引用产出 Run，运行中的 Run 终态不被终结或改写。"""
    async with _scoped_database("pytest_board_report") as (manager, sessions):
        await _seed_scope(manager)
        thread_id = str(uuid.uuid4())
        conversation_id = await _seed_conversation(
            manager.async_engine,
            thread_id=thread_id,
            uid="uid-owner",
            project_id="project-owner",
            agent_slug="employee",
        )
        await _seed_run(
            manager.async_engine,
            run_id="run-running",
            thread_id=thread_id,
            uid="uid-owner",
            agent_slug="employee",
            status="running",
            conversation_id=conversation_id,
        )
        async with sessions() as session:
            user = await _load_user(session, "uid-owner")
            report = await create_governance_report(
                project_id="project-owner",
                title="定时汇报",
                summary="汇总",
                content={"open_topics": 0},
                source_run_id="run-running",
                artifact_path="reports/periodic.md",
                db=session,
                user=user,
            )
            assert report["source_run_id"] == "run-running"
            run_status = await session.scalar(text("SELECT status FROM agent_runs WHERE id = 'run-running'"))
            assert run_status == "running"
            assert "status" not in report
