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
    _seed_user,
    _seed_project,
)
from yuxi.services.governance_service import (
    create_governance_decision,
    update_governance_decision,
    operate_governance_decision,
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
                "blockers": 0,
                "pending_topics": 2,
                "overdue_work": 0,
                "pending_results": 0,
                "pending_result_work": 0,
                "current_exceptions": 0,
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


async def test_formal_overview_counts_pages_and_current_anomalies_from_database() -> None:
    """建议、验收与历史失败不能冒充当前业务进展，分页统计保持一致。"""
    from datetime import timedelta

    import httpx
    from fastapi import FastAPI

    from server.routers.governance_router import governance
    from server.utils.auth_middleware import get_db, get_required_user
    from yuxi.storage.postgres.models_business import (
        ProjectWorkTask,
        ProjectWorkResult,
        ProjectWorkExecution,
        ChannelDelegation,
        WorkSuggestionAdmission,
    )
    from yuxi.utils.datetime_utils import utc_now_naive

    async with _scoped_database("pytest_p08_overview") as (manager, sessions):
        await _seed_scope(manager)
        await _seed_user(manager.async_engine, uid="uid-other")
        await _seed_project(manager.async_engine, project_id="project-other", uid="uid-other")
        now = utc_now_naive()
        async with sessions() as db:
            db.add(
                ProjectWorkTask(
                    id="foreign-work",
                    project_id="project-other",
                    number="OTHER-1",
                    title="不可见工作",
                    status="blocked",
                    created_by="uid-other",
                )
            )
            await db.flush()
            db.add(
                ProjectWorkResult(
                    id="foreign-result",
                    project_id="project-other",
                    task_id="foreign-work",
                    request_id="foreign-result",
                    request_hash="h",
                    summary="不可见结果",
                    criteria_snapshot="条件",
                    criteria_revision=1,
                    submitted_by="uid-other",
                    status="pending",
                    evidence=[],
                )
            )
            user = await _load_user(db, "uid-owner")
            for i in range(12):
                status = {0: "blocked", 1: "done", 2: "cancelled", 3: "in_progress"}.get(i, "todo")
                db.add(
                    ProjectWorkTask(
                        id=f"w-{i:02}",
                        project_id="project-owner",
                        number=f"W-{i}",
                        title=f"正式工作{i}",
                        status=status,
                        created_by="uid-owner",
                        due_date=now.date() - timedelta(days=1),
                        updated_at=now + timedelta(seconds=i),
                    )
                )
            await db.commit()
            await create_governance_topic(
                project_id="project-owner",
                title="待纳入",
                summary=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            archived = await create_governance_topic(
                project_id="project-owner",
                title="归档后不待处理",
                summary=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            await db.execute(
                text("UPDATE governance_topics SET archived_at=now() WHERE id=:id"), {"id": archived["id"]}
            )
            suggestion = await create_governance_task(
                project_id="project-owner",
                title="已纳入建议",
                description=None,
                topic_id=None,
                decision_id=None,
                assignee_agent_slug=None,
                source_channel="project",
                source_external_id=None,
                source_url=None,
                db=db,
                user=user,
            )
            db.add(
                WorkSuggestionAdmission(
                    mode="link",
                    project_id="project-owner",
                    suggestion_id=suggestion["id"],
                    work_task_id="w-00",
                    created_by="uid-owner",
                )
            )
            for i in range(2):
                db.add(
                    ProjectWorkResult(
                        id=f"r-{i}",
                        project_id="project-owner",
                        task_id="w-03",
                        request_id=f"r-{i}",
                        request_hash="h",
                        summary=f"待验收{i}",
                        criteria_snapshot="条件",
                        criteria_revision=1,
                        submitted_by="uid-owner",
                        status="pending",
                        evidence=[],
                    )
                )
            for name, task_id, status, seconds in (
                ("old-fail", "w-03", "failed", 0),
                ("new-success", "w-03", "completed", 1),
                ("current-fail", "w-00", "failed", 2),
                ("done-fail", "w-01", "failed", 3),
                ("interrupt", "w-04", "interrupted", 4),
            ):
                db.add(
                    ProjectWorkExecution(
                        id=name,
                        project_id="project-owner",
                        task_id=task_id,
                        uid="uid-owner",
                        agent_slug="employee",
                        status=status,
                        prompt="p",
                        request_id=name,
                        thread_id=name,
                        created_at=now + timedelta(seconds=seconds),
                    )
                )
            db.add(
                ChannelDelegation(
                    id="delegated-fail",
                    project_id="project-owner",
                    work_task_id="w-05",
                    operation_id="delegated-fail",
                    executor_key="codex",
                    task="本次委派",
                    dispatch_state="failed",
                )
            )
            db.add(
                ChannelDelegation(
                    id="remote-fail",
                    project_id="project-owner",
                    work_task_id="w-06",
                    operation_id="remote-fail",
                    executor_key="codex",
                    task="远端异常",
                    dispatch_state="dispatched",
                    remote_status="failed",
                )
            )
            await db.commit()
            decision = await create_governance_decision(
                project_id="project-owner",
                title="来源决策",
                conclusion="新版依据",
                rationale=None,
                topic_id=None,
                db=db,
                user=user,
            )
            await operate_governance_decision(
                project_id="project-owner",
                decision_id=decision["id"],
                action="approve",
                expected_revision=1,
                reason="形成旧依据",
                db=db,
                user=user,
            )
            current_decision = await create_governance_decision(
                project_id="project-owner",
                title="当前来源",
                conclusion="新依据",
                rationale=None,
                topic_id=None,
                db=db,
                user=user,
            )
            await update_governance_decision(
                project_id="project-owner",
                decision_id=current_decision["id"],
                title="当前来源",
                conclusion="修订后的依据",
                rationale=None,
                topic_id=None,
                relation_type="ordinary",
                target_decision_id=None,
                expected_revision=1,
                reason="完善草案",
                db=db,
                user=user,
            )
            await operate_governance_decision(
                project_id="project-owner",
                decision_id=current_decision["id"],
                action="approve",
                expected_revision=2,
                reason="形成新依据",
                db=db,
                user=user,
            )
            await db.execute(
                text(
                    "UPDATE project_work_tasks SET source_decision_id=:id, source_decision_revision=3 WHERE id='w-03'"
                ),
                {"id": current_decision["id"]},
            )
            await db.execute(
                text(
                    "UPDATE project_work_executions SET source_decision_id=:id, source_decision_revision=2 "
                    "WHERE id='new-success'"
                ),
                {"id": decision["id"]},
            )
            await db.execute(text("UPDATE project_work_results SET source_execution_id='new-success' WHERE id='r-1'"))
            await db.commit()

        app = FastAPI()
        app.include_router(governance, prefix="/api")

        async def db_scope():
            """HTTP读取真实隔离数据库。"""
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_scope
        app.dependency_overrides[get_required_user] = lambda: user
        root = "/api/projects/project-owner/governance"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(root + "/board")
            assert response.status_code == 200, response.text
            board = response.json()
            overview = board["overview"]
            assert overview["pending"]["counts"]["pending_topics"] == 1
            assert overview["pending"]["counts"]["pending_tasks"] == 0
            assert overview["work"]["total"] == 12 and len(overview["work"]["items"]) == 5
            assert overview["work"]["blocked_count"] == 1 and overview["work"]["overdue_count"] == 10
            assert overview["results"]["total"] == 2 and overview["results"]["work_count"] == 1
            assert {r["id"] for r in overview["exceptions"]["items"]} == {
                "current-fail",
                "interrupt",
                "delegated-fail",
                "remote-fail",
            }
            assert {r["id"] for r in overview["historical_exceptions"]["items"]} == {"old-fail", "done-fail"}
            assert board["graph"]["work"]["total"] == 12 and len(board["graph"]["work"]["items"]) == 10
            current_work = next(
                row
                for row in (await client.get(root + "/overview", params={"section": "work", "limit": 100})).json()[
                    "items"
                ]
                if row["id"] == "w-03"
            )
            frozen_result = next(row for row in board["graph"]["results"]["items"] if row["id"] == "r-1")
            assert current_work["source_decision_id"] == current_decision["id"]
            assert current_work["source_decision_revision"] == 3
            assert frozen_result["frozen_decision_revision"] == 2
            assert frozen_result["frozen_decision_id"] == decision["id"]
            assert frozen_result["history_url"].endswith("#work-execution-new-success")
            pages = []
            for offset in (0, 5, 10):
                page = (
                    await client.get(root + "/overview", params={"section": "work", "offset": offset, "limit": 5})
                ).json()
                assert page["total"] == 12
                pages.extend(page["items"])
            assert len({r["id"] for r in pages}) == 12
            assert next(r for r in pages if r["id"] == "w-01")["overdue"] is False
            assert next(r for r in pages if r["id"] == "w-02")["overdue"] is False
            assert all(r["url"].endswith(r["id"]) for r in pages)
            assert all("#work-result-" in r["url"] for r in overview["results"]["items"])
            assert (
                await client.get("/api/projects/missing/governance/overview", params={"section": "work"})
            ).status_code == 404
            assert (
                await client.get("/api/projects/project-other/governance/overview", params={"section": "results"})
            ).status_code == 404
            assert (await client.get(root + "/overview", params={"section": "wrong"})).status_code == 422
            assert (await client.get(root + "/overview", params={"section": "work", "offset": -1})).status_code == 422
            async with sessions() as db:
                await db.execute(text("UPDATE project_work_tasks SET status='done' WHERE id='w-00'"))
                await db.execute(text("UPDATE project_work_results SET status='not_accepted' WHERE id='r-0'"))
                await db.commit()
            updated = (await client.get(root + "/board")).json()["overview"]
            assert updated["work"]["blocked_count"] == 0 and updated["results"]["total"] == 1
            assert updated["exceptions"]["total"] == 3
