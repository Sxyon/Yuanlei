"""项目工作任务执行队列的真实 PostgreSQL 事务测试。"""

from __future__ import annotations

import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
from yuxi.services import project_work_execution_service as work
from yuxi.services import agent_run_service
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import ProjectWorkExecution, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离 Schema 不依赖运行中 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 不创建知识库资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 不创建沙盒。"""
    yield


async def test_assignment_acceptance_and_agent_fifo(monkeypatch):
    """接受后进入持久队列，重复接受拒绝，Agent 只认领最早队头。"""
    schema = f"pytest_work_queue_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"], pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        manager = PostgresManager()
        manager.async_engine = scoped_engine
        manager._initialized = True
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO users (username, uid, password_hash, role, login_failed_count, is_deleted) "
                "VALUES ('queue-user', 'queue-user', 'x', 'user', 0, 0)"
            ))
            await connection.execute(text(
                "INSERT INTO projects (id, uid, name, selection_status, workdir_path, directory_mode) "
                "VALUES ('queue-project', 'queue-user', 'Queue', 'selectable', 'projects/queue', 'managed')"
            ))
            await connection.execute(text(
                "INSERT INTO agents (slug, backend_id, name, pics, config_json, share_config, is_default, is_subagent) "
                "VALUES ('queue-agent', 'ChatbotAgent', 'Queue', '[]'::jsonb, '{}'::jsonb, "
                "'{}'::jsonb, FALSE, FALSE)"
            ))
            await connection.execute(text(
                "INSERT INTO project_agents (id, project_id, agent_slug, config_overrides) "
                "VALUES ('queue-binding', 'queue-project', 'queue-agent', "
                "'{\"context\": {\"model\": \"project:model\"}}'::jsonb)"
            ))
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-1', 'queue-project', 'QUEUE-GEN-000001', 'First', 'todo', 'queue-user', NOW(), NOW()), "
                "('queue-task-2', 'queue-project', 'QUEUE-GEN-000002', 'Second', 'todo', 'queue-user', NOW(), NOW())"
            ))
        sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
        user = User(uid="queue-user", username="queue-user")
        monkeypatch.setattr(work, "dispatch_agent_queue", AsyncMock(return_value=0))
        monkeypatch.setattr(
            agent_run_service.model_cache, "get_model_info",
            lambda spec: SimpleNamespace(model_type="chat") if spec in {
                "project:model", "system:model", "provider:first", "provider:second", "provider:third"
            } else None,
        )
        monkeypatch.setattr(
            agent_run_service, "system_options",
            SimpleNamespace(get=AsyncMock(return_value={"default_model": "system:model"})),
        )
        async with sessions() as db:
            first = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-1", agent_slug="queue-agent"
            )
        async with sessions() as db:
            second = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-2", agent_slug="queue-agent"
            )
        async with sessions() as db:
            await work.accept_task(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent", execution_id=first["id"]
            )
            assert (await db.get(ProjectWorkExecution, first["id"])).model_spec == "project:model"
            with pytest.raises(HTTPException) as repeated:
                await work.accept_task(
                    db=db, user=user, project_id="queue-project", agent_slug="queue-agent", execution_id=first["id"]
                )
            assert repeated.value.status_code == 409
        async with sessions() as db:
            await work.accept_task(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent", execution_id=second["id"]
            )
            board = await work.get_agent_workbench(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent"
            )
            assert [item["id"] for item in board["queued"]] == [first["id"], second["id"]]
            cancelled = await work.cancel_assignment(
                db=db, user=user, project_id="queue-project", task_id="queue-task-2", execution_id=second["id"]
            )
            assert cancelled["status"] == "cancelled"
        async with sessions() as db:
            second = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-2", agent_slug="queue-agent"
            )
        async with sessions() as db:
            await work.accept_task(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent", execution_id=second["id"]
            )
        async with sessions() as lock_db:
            await lock_db.scalar(
                select(ProjectWorkExecution)
                .where(ProjectWorkExecution.id == first["id"])
                .with_for_update()
            )
            claim_pid = asyncio.get_running_loop().create_future()

            async def claim_while_head_locked():
                """在独立事务中尝试认领队头。"""
                async with sessions() as claim_db:
                    claim_pid.set_result(await claim_db.scalar(text("SELECT pg_backend_pid()")))
                    row = await ProjectWorkExecutionRepository(claim_db).claim_agent_head("queue-agent")
                    return row.id if row else None

            claim = asyncio.create_task(claim_while_head_locked())
            pid = await asyncio.wait_for(claim_pid, timeout=3)
            for _ in range(50):
                async with admin_engine.connect() as observer:
                    waiting = await observer.scalar(text(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": pid})
                if waiting == "Lock":
                    break
                await asyncio.sleep(0.02)
            assert waiting == "Lock", "认领事务应先等待真正队头的行锁"
            assert not claim.done(), "不能跳过被撤回事务锁住的 FIFO 队头"
            await lock_db.rollback()
            assert await claim == first["id"]
        async with sessions() as db:
            row = await ProjectWorkExecutionRepository(db).claim_agent_head("queue-agent")
            assert row.id == first["id"]
            row.status = "dispatching"
            await db.commit()
        async with sessions() as db:
            assert await ProjectWorkExecutionRepository(db).claim_agent_head("queue-agent") is None

        async with scoped_engine.begin() as connection:
            first_request_id, first_thread_id = (await connection.execute(text(
                "SELECT request_id, thread_id FROM project_work_executions WHERE id = :id"
            ), {"id": first["id"]})).one()
            await connection.execute(text(
                "INSERT INTO conversations (thread_id, uid, agent_id, project_id, is_pinned) "
                "VALUES (:thread_id, 'queue-user', 'queue-agent', 'queue-project', FALSE)"
            ), {"thread_id": first_thread_id})
            await connection.execute(text(
                "INSERT INTO agent_runs (id, conversation_thread_id, runtime_scope_id, agent_slug, uid, "
                "status, request_id, source, channel, external_id, run_type, origin_metadata, input_payload, token_usage) "
                "VALUES ('queue-run', :thread_id, :thread_id, 'queue-agent', 'queue-user', "
                "'completed', :request_id, 'project_work', 'worker', :execution_id, 'chat', "
                "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ), {"request_id": first_request_id, "thread_id": first_thread_id, "execution_id": first["id"]})
            message_id = await connection.scalar(text(
                "INSERT INTO messages (conversation_id, role, content, run_id, delivery_status) "
                "SELECT id, 'assistant', 'Only this run result', 'queue-run', 'complete' "
                "FROM conversations WHERE thread_id = :thread_id RETURNING id"
            ), {"thread_id": first_thread_id})
            await connection.execute(text(
                "UPDATE agent_runs SET output_message_id = :message_id WHERE id = 'queue-run'"
            ), {"message_id": message_id})
            await connection.execute(text(
                "UPDATE project_work_executions SET status = 'submitted', current_run_id = 'queue-run', "
                "updated_at = NOW() - INTERVAL '1 minute' WHERE id = :id"
            ), {"id": first["id"]})

        @asynccontextmanager
        async def scoped_context():
            """将收敛器限定到测试 schema。"""
            async with sessions() as db:
                yield db

        monkeypatch.setattr(work.pg_manager, "get_async_session_context", scoped_context)
        assert await work.reconcile_project_work_executions() >= 1
        assert await work.reconcile_project_work_executions() >= 0
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT status FROM project_work_executions WHERE id = :id"
            ), {"id": first["id"]}) == "completed"
            assert await connection.scalar(text(
                "SELECT count(*) FROM project_work_comments WHERE source_run_id = 'queue-run' "
                "AND content LIKE '%Only this run result%'"
            )) == 1

        async with scoped_engine.begin() as connection:
            request_id = await connection.scalar(text(
                "SELECT request_id FROM project_work_executions WHERE id = :id"
            ), {"id": second["id"]})
            input_id = await connection.scalar(text(
                "INSERT INTO messages (conversation_id, role, content, delivery_status) "
                "SELECT id, 'user', 'Rejected request', 'complete' FROM conversations "
                "WHERE thread_id = :thread_id RETURNING id"
            ), {"thread_id": first_thread_id})
            await connection.execute(text(
                "INSERT INTO agent_run_requests (request_id, uid, agent_slug, conversation_thread_id, "
                "source, channel, queue_policy, status, input_message_id, input_payload, origin_metadata, created_at, updated_at) "
                "VALUES (:request_id, 'queue-user', 'queue-agent', :thread_id, 'project_work', 'worker', "
                "'enqueue', 'rejected', :input_id, '{}'::json, '{}'::json, NOW(), NOW())"
            ), {"request_id": request_id, "input_id": input_id, "thread_id": first_thread_id})
            await connection.execute(text(
                "UPDATE project_work_executions SET status = 'submitted', updated_at = NOW() - INTERVAL '1 minute' "
                "WHERE id = :id"
            ), {"id": second["id"]})
        assert await work.reconcile_project_work_executions() >= 1
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT status FROM project_work_executions WHERE id = :id"
            ), {"id": second["id"]}) == "failed"

        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-3', 'queue-project', 'QUEUE-GEN-000003', 'Third', 'todo', 'queue-user', NOW(), NOW())"
            ))
            await connection.execute(text(
                "INSERT INTO agent_runs (id, conversation_thread_id, runtime_scope_id, agent_slug, uid, "
                "status, request_id, source, channel, external_id, run_type, origin_metadata, input_payload, token_usage) "
                "VALUES ('queue-run-empty', 'queue-thread-empty', 'queue-thread-empty', 'queue-agent', 'queue-user', "
                "'completed', 'queue-request-empty', 'project_work', 'worker', 'queue-execution-empty', 'chat', "
                "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb)"
            ))
            await connection.execute(text(
                "INSERT INTO project_work_executions (id, task_id, project_id, uid, agent_slug, status, "
                "prompt, request_id, thread_id, current_run_id, created_at, updated_at) "
                "VALUES ('queue-execution-empty', 'queue-task-3', 'queue-project', 'queue-user', 'queue-agent', "
                "'submitted', 'Do work', 'queue-request-empty', 'queue-thread-empty', 'queue-run-empty', "
                "NOW(), NOW() - INTERVAL '1 minute')"
            ))
        assert await work.reconcile_project_work_executions() >= 1
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT status FROM project_work_executions WHERE id = 'queue-execution-empty'"
            )) == "failed"
            assert await connection.scalar(text(
                "SELECT count(*) FROM project_work_comments WHERE source_run_id = 'queue-run-empty'"
            )) == 0

        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-4', 'queue-project', 'QUEUE-GEN-000004', 'Fourth', 'todo', 'queue-user', NOW(), NOW())"
            ))
            await connection.execute(text(
                "INSERT INTO project_work_executions (id, task_id, project_id, uid, agent_slug, status, "
                "prompt, request_id, thread_id, current_run_id, created_at, updated_at) "
                "VALUES ('queue-execution-wrong', 'queue-task-4', 'queue-project', 'queue-user', 'queue-agent', "
                "'submitted', 'Do work', 'queue-request-wrong', 'queue-thread-wrong', 'queue-run', "
                "NOW(), NOW() - INTERVAL '1 minute')"
            ))
        assert await work.reconcile_project_work_executions() >= 1
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT status FROM project_work_executions WHERE id = 'queue-execution-wrong'"
            )) == "failed"
            assert await connection.scalar(text(
                "SELECT count(*) FROM project_work_comments WHERE task_id = 'queue-task-4'"
            )) == 0

        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-5', 'queue-project', 'QUEUE-GEN-000005', 'Auto', 'todo', 'queue-user', NOW(), NOW())"
            ))
        async with sessions() as db:
            configured = await work.update_work_queue_config(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent",
                auto_accept_work=True, work_default_model_spec="provider:first",
            )
            assert configured == {"auto_accept_work": True, "work_default_model_spec": "provider:first"}
        async with sessions() as db:
            automatic = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-5", agent_slug="queue-agent"
            )
            assert automatic["status"] == "queued"
            assert automatic["model_spec"] == "provider:first"
            assert automatic["accepted_at"] is not None
        async with sessions() as db:
            await work.update_work_queue_config(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent",
                auto_accept_work=False, work_default_model_spec="provider:second",
            )
            row = await db.get(ProjectWorkExecution, automatic["id"])
            assert row.model_spec == "provider:first"
            board = await work.get_agent_workbench(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent"
            )
            assert board["auto_accept_work"] is False
            assert board["work_default_model_spec"] == "provider:second"
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-6', 'queue-project', 'QUEUE-GEN-000006', 'Manual', 'todo', 'queue-user', NOW(), NOW())"
            ))
        async with sessions() as db:
            pending = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-6", agent_slug="queue-agent"
            )
            assert pending["status"] == "pending_acceptance" and pending["model_spec"] is None
        async with sessions() as db:
            await work.update_work_queue_config(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent",
                auto_accept_work=False, work_default_model_spec="provider:third",
            )
            accepted = await work.accept_task(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent", execution_id=pending["id"]
            )
            assert accepted["model_spec"] == "provider:third"

        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO project_work_tasks (id, project_id, number, title, status, created_by, created_at, updated_at) "
                "VALUES ('queue-task-7', 'queue-project', 'QUEUE-GEN-000007', 'Inherited', 'todo', 'queue-user', NOW(), NOW()), "
                "('queue-task-8', 'queue-project', 'QUEUE-GEN-000008', 'System', 'todo', 'queue-user', NOW(), NOW())"
            ))
        async with sessions() as db:
            await work.update_work_queue_config(
                db=db, user=user, project_id="queue-project", agent_slug="queue-agent",
                auto_accept_work=True, work_default_model_spec=None,
            )
            inherited = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-7", agent_slug="queue-agent"
            )
            assert inherited["model_spec"] == "project:model"
        async with scoped_engine.begin() as connection:
            await connection.execute(text(
                "UPDATE project_agents SET config_overrides = '{}'::jsonb WHERE id = 'queue-binding'"
            ))
        async with sessions() as db:
            system = await work.assign_task(
                db=db, user=user, project_id="queue-project", task_id="queue-task-8", agent_slug="queue-agent"
            )
            assert system["model_spec"] == "system:model"
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
