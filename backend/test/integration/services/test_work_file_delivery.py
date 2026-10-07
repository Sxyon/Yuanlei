"""文件交付只采信同次成功展示的持久调用。"""

import pytest

from test.integration.services.test_project_work_context import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    context_database,
    ensure_live_api_schema as ensure_live_api_schema,
)
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.storage.postgres.models_business import AgentRun, Conversation, Message, ToolCall

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_file_registration_does_not_take_sibling_or_failed_calls():
    """同线程相邻运行、失败展示和普通写文件都不冒充当次交付物。"""
    async with context_database() as (_, sessions, user, _, _):
        async with sessions() as db:
            conversation = Conversation(thread_id="thread", uid=user.uid, agent_id="agent", project_id="p")
            db.add(conversation)
            await db.flush()
            for name in ("selected", "sibling"):
                db.add(AgentRun(id=name, conversation_thread_id="thread", runtime_scope_id="thread",
                               agent_slug="agent", uid=user.uid, request_id=name, status="completed",
                               conversation_id=conversation.id))
            await db.flush()
            for run, tool, status, path in (
                ("selected", "present_artifacts", "success", "/delivered.md"),
                ("selected", "present_artifacts", "error", "/failed.md"),
                ("selected", "write_file", "success", "/unregistered.md"),
                ("sibling", "present_artifacts", "success", "/sibling.md"),
            ):
                message = Message(conversation_id=conversation.id, run_id=run, role="tool", content="合成工具记录")
                db.add(message)
                await db.flush()
                db.add(ToolCall(message_id=message.id, tool_name=tool, status=status,
                                tool_input={"filepaths": [path]}))
            await db.commit()
        async with sessions() as db:
            repo = ProjectWorkRepository(db, project_id="p", uid=user.uid)
            assert await repo.run_artifact_paths("selected") == ["/delivered.md"]
            assert await repo.run_artifact_paths("sibling") == ["/sibling.md"]
