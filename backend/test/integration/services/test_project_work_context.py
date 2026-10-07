"""执行资料通过真实 PostgreSQL、HTTP 和执行器协议保持版本事实。"""

import os
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from server.routers.project_work_execution_router import project_work_executions
from server.utils.auth_middleware import get_db, get_required_user
from yuxi.delegation.contracts import DelegationRequest, DelegationHandle
from yuxi.services.delegation_service import DelegationService
from yuxi.services import project_work_execution_service as execution
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import (
    User,
    Project,
    Agent,
    ProjectAgent,
    ProjectWorkTask,
    ProjectWorkExecution,
    GovernanceDecision,
    GovernanceDecisionRevision,
    ChannelDelegation,
)
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workspace.paths import ensure_bound_user_workdir
from yuxi.workspace.workdir import Workdir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """独立 Schema 不依赖常驻 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """本集合不创建知识库。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """协议测试不启动外部沙盒。"""
    yield


@asynccontextmanager
async def context_database():
    """隔离 Schema 和项目文件，保留现有数据库。"""
    marker = uuid.uuid4().hex[:16]
    schema = "p06_" + marker
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    async with admin.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    await manager.create_business_tables()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            user = User(username=marker, uid=marker, password_hash="x", role="user", is_deleted=0, login_failed_count=0)
            db.add(user)
            await db.flush()
            project = Project(
                id="p",
                uid=marker,
                name="P06",
                selection_status="selectable",
                workdir_path="projects/" + str(uuid.uuid4()),
                directory_mode="managed",
            )
            db.add(project)
            await db.flush()
            db.add(
                Agent(
                    slug="agent",
                    backend_id="ChatbotAgent",
                    name="Test",
                    pics=[],
                    config_json={},
                    share_config={},
                    is_default=False,
                    is_subagent=False,
                )
            )
            await db.flush()
            db.add(
                ProjectAgent(
                    id="binding", project_id="p", agent_slug="agent", config_overrides={}, auto_accept_work=False
                )
            )
            decision = GovernanceDecision(
                id="decision",
                project_id="p",
                title="批准依据",
                conclusion="后来的结论",
                status="superseded",
                decided_by=marker,
                decided_at=utc_now_naive(),
                revision_number=3,
            )
            db.add(decision)
            await db.flush()
            db.add(
                GovernanceDecisionRevision(
                    decision_id="decision", number=2, snapshot={"title": "批准依据", "conclusion": "选定的批准正文"}
                )
            )
            db.add(
                ProjectWorkTask(
                    id="t",
                    project_id="p",
                    number="C-GEN-000001",
                    title="目标甲",
                    description="原描述",
                    acceptance_criteria="# 原条件",
                    source_decision_id="decision",
                    source_decision_revision=2,
                    created_by=marker,
                )
            )
            await db.commit()
        ensure_bound_user_workdir(marker, project.workdir_path)
        workdir = Workdir.open_existing(marker, project.workdir_path)
        workdir.create_directory("/", ".yuanlei")
        workdir.create_directory("/.yuanlei", "blueprint")
        workdir.replace_file("/.yuanlei/blueprint/依据.md", "# 蓝图初版".encode())
        yield manager, sessions, user, project, workdir
    finally:
        # 仅清理本集合创建的目录字节。
        import shutil
        from yuxi.workspace.paths import user_workspace_dir

        shutil.rmtree(user_workspace_dir(marker), ignore_errors=True)
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_context_preview_conflict_immutable_history_and_delegation_protocol(monkeypatch):
    """预览变化拒绝；排队和协议重投复用正文，蓝图更名不改历史。"""
    async with context_database() as (manager, sessions, user, project, workdir):
        app = FastAPI()
        app.include_router(project_work_executions, prefix="/api")

        async def session_dep():
            """HTTP 请求使用真实隔离事务。"""
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = session_dep
        app.dependency_overrides[get_required_user] = lambda: user
        monkeypatch.setattr(execution, "dispatch_agent_queue", lambda slug: async_zero())

        async def snapshot_model(db, binding):
            """接受只验证队列事务，不调用外部模型。"""
            return "test:model"

        monkeypatch.setattr(execution, "_snapshot_work_model", snapshot_model)
        root = "/api/projects/p/work/tasks/t"
        selection = {"blueprints": ["依据.md"], "files": ["/missing.md"]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            preview = await client.post(root + "/context/preview", json={"selection": selection})
            assert preview.status_code == 200, preview.text
            old = preview.json()
            assert "选定的批准正文" in old["input_text"] and "后来的结论" not in old["input_text"]
            assert old["items"][-1]["mode"] == "missing"
            workdir.replace_file("/.yuanlei/blueprint/依据.md", "# 蓝图第二版".encode())
            blocked = await client.post(
                root + "/executions",
                json={
                    "agent_slug": "agent",
                    "context": {"selection": selection, "expected_fingerprint": old["fingerprint"]},
                },
            )
            assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "context_changed"
            refreshed = (await client.post(root + "/context/preview", json={"selection": selection})).json()
            created = await client.post(
                root + "/executions",
                json={
                    "agent_slug": "agent",
                    "context": {"selection": selection, "expected_fingerprint": refreshed["fingerprint"]},
                },
            )
            assert created.status_code == 200, created.text
            attempt = created.json()["id"]
            async with sessions() as db:
                row = await db.get(ProjectWorkExecution, attempt)
                original = row.context_snapshot
                assert original["input_text"] in row.prompt
                assert "# 原条件" in row.prompt and "# 蓝图第二版" in row.prompt
                assert original["items"][2]["original_text"] == "# 蓝图第二版"
                task = await db.get(ProjectWorkTask, "t")
                task.acceptance_criteria = "# 新条件"
                task.criteria_revision = 2
                await db.commit()
            workdir.move_file("/.yuanlei/blueprint/依据.md", "/.yuanlei/blueprint/更名.md")
            accepted = await client.post(f"/api/projects/p/agents/agent/workbench/{attempt}/accept")
            assert accepted.status_code == 200 and accepted.json()["status"] == "queued", accepted.text
            history = await client.get(root + f"/context/execution/{attempt}")
            assert history.status_code == 200 and history.json()["snapshot"] == original
            assert "# 新条件" not in history.json()["snapshot"]["input_text"]
            invalid = await client.post(root + "/context/preview", json={"selection": {"files": ["/../secret"]}})
            assert invalid.status_code == 422
            foreign = await client.post(root + "/context/preview", json={"selection": {"attachments": ["not-owned"]}})
            assert foreign.status_code == 404
            legacy = await client.get(root + "/context/execution/missing")
            assert legacy.status_code == 404

        class CaptureExecutor:
            """捕获真实协议对象，不声称外部产品执行成功。"""

            key = "multica"

            def __init__(self):
                self.requests = []

            def capabilities(self):
                return {}

            async def dispatch(self, request):
                """保存实际传给执行器的正文。"""
                self.requests.append(request)
                return DelegationHandle(
                    operation_id=request.operation_id, executor_key=self.key, external_ref="received"
                )

        adapter = CaptureExecutor()
        async with sessions() as db:
            service = DelegationService(db, executors=[adapter])
            result = await service.dispatch(
                executor_key="multica",
                uid=user.uid,
                request=DelegationRequest(
                    operation_id="child",
                    project_id="p",
                    task="执行子工作",
                    metadata={"work_task_id": "t", "project_work_execution_id": attempt},
                ),
            )
            row = await db.scalar(
                select(ChannelDelegation).where(ChannelDelegation.operation_id == result["operation_id"])
            )
            assert row.context_snapshot == original
            assert adapter.requests[0].task == row.task and original["input_text"] in adapter.requests[0].task
            assert "# 新条件" not in adapter.requests[0].task
            assert service._request_from_row(row).task == adapter.requests[0].task
            fresh = await service.dispatch(
                executor_key="multica",
                uid=user.uid,
                request=DelegationRequest(
                    operation_id="fresh", project_id="p", task="新工作依据", metadata={"work_task_id": "t"}
                ),
            )
            assert "# 新条件" in fresh["task"] and "# 原条件" not in fresh["task"]
            assert await db.scalar(text("SELECT count(*) FROM agent_runs")) == 0


async def async_zero():
    """接受测试不触发外部模型队列。"""
    return 0


async def test_actual_input_budget_controlled_utf8_prefix_and_legacy_migration():
    """引用也占正文预算，UTF-8 前缀不误判，迁移重入不猜测旧资料。"""
    from yuxi.storage.postgres.models_business import ProjectWorkReference
    from yuxi.services.project_work_context_service import assemble_context, TEXT_BUDGET

    async with context_database() as (manager, sessions, user, project, workdir):
        workdir.replace_file("/长文本.md", ("甲" * 30000).encode())
        async with sessions() as db:
            task = await db.get(ProjectWorkTask, "t")
            for index in range(150):
                db.add(
                    ProjectWorkReference(
                        id=str(index),
                        task_id="t",
                        title="长引用",
                        url="https://example.invalid/" + "x" * 2000,
                        created_by=user.uid,
                    )
                )
            old = ProjectWorkExecution(
                id="legacy",
                task_id="t",
                project_id="p",
                uid=user.uid,
                agent_slug="agent",
                prompt="旧输入",
                request_id="legacy-request",
                thread_id="legacy-thread",
            )
            db.add(old)
            await db.commit()
            snapshot = await assemble_context(
                db=db, user=user, project=project, task=task, selection={"files": ["/长文本.md"]}
            )
            assert len(snapshot["input_text"]) <= TEXT_BUDGET
            assert "# 原条件" in snapshot["input_text"]
            prefix = next(item for item in snapshot["items"] if item["kind"] == "file")
            assert prefix["mode"] == "direct" and prefix["truncated"] and prefix["hash_scope"] == "prefix"
            assert any(item.get("truncated") for item in snapshot["items"] if item["kind"] == "url")
        async with sessions() as db:
            db.add(
                ChannelDelegation(
                    id="legacy-delegation",
                    operation_id="legacy-operation",
                    project_id="p",
                    work_task_id="t",
                    executor_key="multica",
                    task="旧委派正文",
                    request_json={},
                    created_by=user.uid,
                )
            )
            await db.commit()
        async with manager.async_engine.begin() as db:
            await db.execute(text("ALTER TABLE project_work_executions DROP COLUMN context_snapshot"))
            await db.execute(text("ALTER TABLE channel_delegations DROP COLUMN context_snapshot"))
        await manager.upgrade_yuanlei_schema_v33_to_v34()
        await manager.upgrade_yuanlei_schema_v33_to_v34()
        async with sessions() as db:
            assert (await db.get(ProjectWorkExecution, "legacy")).context_snapshot is None
            old_delegation = await db.get(ChannelDelegation, "legacy-delegation")
            assert old_delegation.context_snapshot is None and old_delegation.task == "旧委派正文"
            assert (await db.get(ProjectWorkExecution, "legacy")).prompt == "旧输入"
            assert (await db.get(ProjectWorkTask, "t")).acceptance_criteria == "# 原条件"


async def test_context_attachment_reads_owned_object_and_reports_missing_bytes():
    """真实对象存储前缀进入输入，删除对象不改已读资料且新预览显示缺失。"""
    from yuxi.storage.minio import get_minio_client
    from yuxi.storage.postgres.models_business import ProjectWorkAttachment
    from yuxi.services.project_work_context_service import assemble_context

    client = get_minio_client()
    bucket = client.KB_BUCKETS["documents"]
    object_name = f"project_work/p06-tests/{uuid.uuid4()}/text.md"
    content = ("附件甲" * 30000).encode()
    await client.aupload_file(bucket_name=bucket, object_name=object_name, data=content, content_type="text/markdown")
    try:
        async with context_database() as (_, sessions, user, project, _):
            async with sessions() as db:
                db.add(
                    ProjectWorkAttachment(
                        id="attachment",
                        task_id="t",
                        project_id="p",
                        file_name="text.md",
                        content_type="text/markdown",
                        file_size=len(content),
                        object_name=object_name,
                        created_by=user.uid,
                    )
                )
                await db.commit()
                task = await db.get(ProjectWorkTask, "t")
                snapshot = await assemble_context(
                    db=db, user=user, project=project, task=task, selection={"attachments": ["attachment"]}
                )
                item = next(x for x in snapshot["items"] if x["kind"] == "attachment")
                assert item["truncated"] and item["hash_scope"] == "full" and item["mode"] == "direct"
                assert "附件甲" in snapshot["input_text"] and "不是内容备份" in item["note"]
                await client.adelete_file(bucket_name=bucket, object_name=object_name)
                missing = await assemble_context(
                    db=db, user=user, project=project, task=task, selection={"attachments": ["attachment"]}
                )
                assert next(x for x in missing["items"] if x["kind"] == "attachment")["mode"] == "missing"
                assert "附件甲" in snapshot["input_text"]
    finally:
        await client.adelete_file(bucket_name=bucket, object_name=object_name)


async def test_automatic_results_feedback_and_blueprint_conflicts():
    """真实事务保存旧依据、幂等反馈及外部文件修改冲突。"""
    from server.routers.project_work_router import project_work
    from yuxi.services.project_work_result_service import import_execution_result
    from yuxi.storage.postgres.models_business import GovernanceTopic, GovernanceTopicRevision, ProjectWorkResult

    async with context_database() as (_, sessions, user, project, workdir):
        app = FastAPI()
        app.include_router(project_work, prefix="/api")

        async def session_dep():
            """反馈用例使用隔离 PostgreSQL。"""
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = session_dep
        app.dependency_overrides[get_required_user] = lambda: user
        async with sessions() as db:
            topic = GovernanceTopic(id="feedback-topic", project_id="p", title="原议题", status="canonical",
                                    created_by=user.uid, source_channel="project", review_owner_uid=user.uid,
                                    reviewed_at=utc_now_naive(), revision_number=1)
            db.add(topic)
            await db.flush()
            db.add(GovernanceTopicRevision(topic_id=topic.id, number=1, title=topic.title, created_by=user.uid))
            attempt = ProjectWorkExecution(id="feedback-exec", task_id="t", project_id="p", uid=user.uid,
                                          agent_slug="agent", status="completed", prompt="当次输入",
                                          request_id="feedback-request", thread_id="feedback-thread",
                                          context_snapshot={"items": [{"kind": "requirements", "revision": 1,
                                              "description": "原描述", "acceptance_criteria": "# 原条件"}]})
            db.add(attempt)
            await db.flush()
            result = await import_execution_result(db=db, project=project, source=attempt, summary="本次输出",
                                                   output_fact={"run_id": "owned-run"}, evidence=[])
            rid = result.id
            assert (await import_execution_result(db=db, project=project, source=attempt, summary="重复",
                                                  output_fact={}, evidence=[])).id == rid
            task = await db.get(ProjectWorkTask, "t")
            task.criteria_revision = 2
            task.acceptance_criteria = "# 新条件"
            await db.commit()
        root = "/api/projects/p/work/tasks/t"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            blocked = await client.post(root + f"/results/{rid}/review", json={"status": "accepted",
                "expected_version": 1, "expected_revision": 2, "complete": True})
            assert blocked.status_code == 409, blocked.text
            missing = await client.post(root + f"/results/{rid}/review", json={"status": "not_accepted",
                "expected_version": 1, "expected_revision": 2})
            assert missing.status_code == 422
            rejected = await client.post(root + f"/results/{rid}/review", json={"status": "not_accepted",
                "comment": "需要追加证据", "expected_version": 1, "expected_revision": 2})
            assert rejected.status_code == 200, rejected.text
            payload = {"topic_id": "feedback-topic", "content": "结果反馈", "discussion_type": "correction",
                       "request_id": "one-feedback", "expected_result_version": 2, "expected_topic_revision": 1}
            assert (await client.post(root + f"/results/{rid}/topic-feedback",
                json={**payload, "topic_id": "missing", "request_id": "cross-project"})).status_code == 404
            assert (await client.post(root + f"/results/{rid}/topic-feedback",
                json={**payload, "expected_topic_revision": 2, "request_id": "stale-topic"})).status_code == 409
            async with sessions() as db:
                topic = await db.get(GovernanceTopic, "feedback-topic")
                topic.archived_at = utc_now_naive()
                await db.commit()
            assert (await client.post(root + f"/results/{rid}/topic-feedback",
                json={**payload, "request_id": "archived"})).status_code == 409
            async with sessions() as db:
                topic = await db.get(GovernanceTopic, "feedback-topic")
                topic.archived_at = None
                await db.commit()
            assert (await client.get(root + f"/results/{rid}/blueprint-preview",
                                    params={"name": "../invalid.md"})).status_code == 422
            first = await client.post(root + f"/results/{rid}/topic-feedback", json=payload)
            assert first.status_code == 200, first.text
            assert (await client.post(root + f"/results/{rid}/topic-feedback", json=payload)).json() == first.json()
            assert (await client.post(root + f"/results/{rid}/topic-feedback",
                                     json={**payload, "content": "不同意图"})).status_code == 409
            preview = await client.get(root + f"/results/{rid}/blueprint-preview", params={"name": "依据.md"})
            assert preview.status_code == 200, preview.text
            data = preview.json()
            assert "需要追加证据" in data["content"]
            workdir.replace_file("/.yuanlei/blueprint/依据.md", "外部修改".encode())
            save = {"name": "依据.md", "content": data["content"], "expected_hash": data["content_hash"],
                    "expected_result_version": 2, "expected_identity": data["file_identity"]}
            conflict_response = await client.put(root + f"/results/{rid}/blueprint-feedback", json=save)
            assert conflict_response.status_code == 409, conflict_response.text
            assert workdir.read_file("/.yuanlei/blueprint/依据.md", 256_000).decode() == "外部修改"
            fresh = (await client.get(root + f"/results/{rid}/blueprint-preview",
                                     params={"name": "依据.md"})).json()
            save.update(
                content=fresh["content"], expected_hash=fresh["content_hash"],
                expected_identity=fresh["file_identity"],
            )
            assert (await client.put(root + f"/results/{rid}/blueprint-feedback", json=save)).status_code == 200
            assert (await client.put(root + f"/results/{rid}/blueprint-feedback", json=save)).status_code == 200
            assert workdir.read_file("/.yuanlei/blueprint/依据.md", 256_000).decode() == fresh["content"]
        async with sessions() as db:
            persisted = await db.get(ProjectWorkResult, rid)
            assert persisted.criteria_snapshot == "# 原条件" and persisted.criteria_revision == 1
            assert persisted.status == "not_accepted" and persisted.review_comment == "需要追加证据"
            assert (await db.get(ProjectWorkTask, "t")).status == "todo"
            assert await db.scalar(text("SELECT count(*) FROM project_work_result_topic_feedback")) == 1
            assert (await db.get(GovernanceTopic, "feedback-topic")).status == "canonical"
            from sqlalchemy.exc import IntegrityError
            db.add(ProjectWorkResult(id="duplicate-auto", project_id="p", task_id="t", request_id="duplicate",
                request_hash="x", summary="重复", submitted_by=user.uid, origin_kind="automatic",
                source_execution_id="feedback-exec", criteria_revision=1, criteria_snapshot="原条件"))
            with pytest.raises(IntegrityError) as duplicate:
                await db.flush()
            assert "uq_auto_result_execution" in str(duplicate.value)
            await db.rollback()
            auto_count = await db.scalar(
                text("SELECT count(*) FROM project_work_results WHERE source_execution_id='feedback-exec'")
            )
            assert auto_count == 1


async def test_v35_migration_preserves_manual_result_and_old_missing_basis():
    """真实旧表升级可重入，已有结果与旧执行不推断改写。"""
    from yuxi.storage.postgres.models_business import ProjectWorkResult
    async with context_database() as (manager, sessions, user, _, _):
        async with sessions() as db:
            db.add(ProjectWorkResult(id="manual", project_id="p", task_id="t", request_id="manual-intent",
                                     request_hash="x", summary="人工历史", criteria_snapshot="原要求",
                                     criteria_revision=1, status="accepted", version=2, submitted_by=user.uid))
            await db.commit()
            await db.execute(text("DROP TABLE project_work_result_topic_feedback"))
            await db.execute(text("ALTER TABLE project_work_results DROP COLUMN origin_kind CASCADE"))
            await db.execute(text("ALTER TABLE project_work_results DROP COLUMN source_output"))
            await db.execute(text("ALTER TABLE project_work_results DROP COLUMN requirements_snapshot"))
            await db.execute(text("ALTER TABLE project_work_results ALTER COLUMN criteria_snapshot SET NOT NULL"))
            await db.execute(text("ALTER TABLE project_work_results ALTER COLUMN criteria_revision SET NOT NULL"))
            await db.commit()
        await manager.upgrade_yuanlei_schema_v34_to_v35()
        await manager.upgrade_yuanlei_schema_v34_to_v35()
        async with sessions() as db:
            row = await db.get(ProjectWorkResult, "manual")
            assert (row.summary, row.criteria_snapshot, row.status, row.version) == (
                "人工历史", "原要求", "accepted", 2)
            assert row.origin_kind == "manual" and row.requirements_snapshot is None and row.source_output is None


async def test_legacy_automatic_result_cannot_infer_current_requirements():
    """旧组合正文只保留原值，不能用当前条件验收或冒充新执行。"""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    from yuxi.services.project_work_result_service import import_execution_result, review_result
    from yuxi.storage.postgres.models_business import ProjectWorkResult

    async with context_database() as (_, sessions, user, project, _):
        async with sessions() as db:
            attempt = ProjectWorkExecution(id="old-attempt", task_id="t", project_id="p", uid=user.uid,
                agent_slug="agent", status="completed", prompt="旧输入",
                request_id="old-request", thread_id="old-thread",
                context_snapshot={"items": [{"kind": "requirements", "revision": 1, "text": "旧组合正文"}]})
            db.add(attempt)
            await db.flush()
            row = await import_execution_result(db=db, project=project, source=attempt,
                summary="旧尝试输出", output_fact={"run_id": "old-run"}, evidence=[])
            rid = row.id
            await db.commit()
            assert row.criteria_snapshot is None and row.requirements_snapshot["text"] == "旧组合正文"
        async with sessions() as db:
            with pytest.raises(HTTPException) as refused:
                await review_result(db=db, user=user, project_id="p", task_id="t", result_id=rid,
                    status="accepted", comment="", expected_version=1, expected_revision=1, complete=False)
            assert refused.value.status_code == 409
            assert "未记录可核对" in refused.value.detail["message"]
            await db.rollback()
            row = await db.get(ProjectWorkResult, rid)
            assert row.status == "pending" and row.criteria_snapshot is None
            db.add(ProjectWorkResult(id="unowned-auto", project_id="p", task_id="t", request_id="no-source",
                request_hash="x", summary="没有当次来源", submitted_by=user.uid, origin_kind="automatic"))
            with pytest.raises(IntegrityError) as shape:
                await db.flush()
            assert "ck_auto_result_source" in str(shape.value)
async def test_topic_selected_outcome_conditions_freeze_and_budget(monkeypatch):
    """选定历史目标仅在目标字段，冻结输入保留它且预算不足明确失败。"""
    from fastapi import HTTPException
    from yuxi.services.project_work_context_service import assemble_context, TEXT_BUDGET
    from yuxi.storage.postgres.models_business import GovernanceTopic, GovernanceTopicRevision

    async with context_database() as (manager, sessions, user, project, workdir):
        async with sessions() as db:
            topic = GovernanceTopic(
                id="topic",
                project_id="p",
                title="当前标题",
                summary="普通正文",
                revision_number=2,
                expected_outcome="当前目标",
                verification_conditions="当前条件",
                source_channel="project",
                created_by=user.uid,
            )
            db.add(topic)
            await db.flush()
            db.add_all(
                [
                    GovernanceTopicRevision(
                        topic_id="topic",
                        number=1,
                        title="旧标题",
                        summary="普通正文",
                        expected_outcome="独有旧目标甲",
                        verification_conditions="独有旧条件乙",
                    ),
                    GovernanceTopicRevision(
                        topic_id="topic",
                        number=2,
                        title="当前标题",
                        summary="普通正文",
                        expected_outcome="当前目标",
                        verification_conditions="当前条件",
                    ),
                ]
            )
            task = await db.get(ProjectWorkTask, "t")
            task.topic_id = "topic"
            await db.commit()
            selected = {"topic_revision": 1}
            preview = await assemble_context(db=db, user=user, project=project, task=task, selection=selected)
            assert "独有旧目标甲" in preview["input_text"] and "独有旧条件乙" in preview["input_text"]
            assert "当前目标" not in preview["input_text"] and "当前条件" not in preview["input_text"]
            monkeypatch.setattr(execution, "dispatch_agent_queue", async_zero)
            created = await execution.assign_task(
                db=db,
                user=user,
                project_id="p",
                task_id="t",
                agent_slug="agent",
                context={"selection": selected, "expected_fingerprint": preview["fingerprint"]},
            )
            row = await db.get(ProjectWorkExecution, created["id"])
            original = row.context_snapshot
            assert preview["input_text"] == original["input_text"] and original["input_text"] in row.prompt
            topic.revision_number = 3
            topic.expected_outcome = None
            topic.verification_conditions = None
            db.add(GovernanceTopicRevision(topic_id="topic", number=3, title="新标题", summary="新正文"))
            await db.flush()
            empty = await assemble_context(
                db=db, user=user, project=project, task=task, selection={"topic_revision": 3}
            )
            topic_item = next(i for i in empty["items"] if i["kind"] == "topic")
            assert "预期结果" not in topic_item["text"] and "验证条件" not in topic_item["text"]
            assert row.context_snapshot == original
            db.add(
                GovernanceTopicRevision(
                    topic_id="topic", number=4, title="过长目标", expected_outcome="甲" * TEXT_BUDGET
                )
            )
            await db.flush()
            with pytest.raises(HTTPException) as error:
                await assemble_context(db=db, user=user, project=project, task=task, selection={"topic_revision": 4})
            assert error.value.status_code == 422 and "不会截断目标" in error.value.detail
            await db.rollback()
