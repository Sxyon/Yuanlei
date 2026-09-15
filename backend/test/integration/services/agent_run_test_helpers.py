"""AgentRun 集成测试共享的数据工厂。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from yuxi.storage.postgres.models_business import AgentRun, Conversation, Message, Project, User
from yuxi.utils.datetime_utils import utc_now_naive


async def create_agent_run(
    session_factory,
    *,
    prefix: str,
    message_content: str,
    input_payload: dict[str, Any],
    status: str = "pending",
    worker_id: str | None = None,
    lease_expires_at: datetime | None = None,
) -> tuple[str, str, int]:
    """创建供 AgentRun 集成测试使用的最小持久化链路。"""
    run_id = str(uuid.uuid4())
    request_id = f"{prefix}-{uuid.uuid4()}"
    thread_id = f"pytest-{prefix}-{uuid.uuid4()}"
    uid = f"pytest-user-{uuid.uuid4()}"
    project_id = str(uuid.uuid4())

    async with session_factory() as db:
        db.add(User(username=uid, uid=uid, password_hash="test"))
        await db.flush()
        db.add(
            Project(
                id=project_id,
                uid=uid,
                selection_status="implicit",
                workdir_path=f"projects/{project_id}",
                directory_mode="managed",
            )
        )
        await db.flush()
        conversation = Conversation(
            thread_id=thread_id,
            uid=uid,
            project_id=project_id,
            agent_id="main",
            status="active",
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content=message_content,
            request_id=request_id,
            delivery_status="dispatched",
        )
        db.add(message)
        await db.flush()
        db.add(
            AgentRun(
                id=run_id,
                conversation_thread_id=thread_id,
                runtime_scope_id=thread_id,
                agent_slug="main",
                uid=uid,
                request_id=request_id,
                conversation_id=conversation.id,
                input_message_id=message.id,
                input_payload=dict(input_payload),
                status=status,
                run_type="chat",
                worker_id=worker_id,
                heartbeat_at=utc_now_naive() if worker_id else None,
                lease_expires_at=lease_expires_at,
            )
        )
        await db.commit()
        return run_id, thread_id, message.id
