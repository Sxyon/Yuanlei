from types import SimpleNamespace

import pytest

from yuxi.repositories.tool_message_audit_repository import ToolMessageAuditRepository
from yuxi.storage.postgres.models_business import AgentRun


class _FakeDb:
    def __init__(self, runs):
        self.runs = runs

    async def get(self, model, run_id):
        assert model is AgentRun
        return self.runs.get(run_id)


@pytest.mark.asyncio
async def test_resume_source_run_ids_follow_full_same_conversation_ancestry():
    ancestor = SimpleNamespace(
        id="ancestor",
        run_type="chat",
        created_by_run_id=None,
        conversation_id=7,
    )
    parent = SimpleNamespace(
        id="parent",
        run_type="resume",
        created_by_run_id="ancestor",
        conversation_id=7,
    )
    current = SimpleNamespace(
        id="current",
        run_type="resume",
        created_by_run_id="parent",
        conversation_id=7,
    )
    repository = ToolMessageAuditRepository(_FakeDb({"parent": parent, "ancestor": ancestor}))

    assert await repository._source_run_ids(current) == ["current", "parent", "ancestor"]


@pytest.mark.asyncio
async def test_resume_source_run_ids_reject_cross_conversation_parent():
    parent = SimpleNamespace(
        id="parent",
        run_type="chat",
        created_by_run_id=None,
        conversation_id=8,
    )
    current = SimpleNamespace(
        id="current",
        run_type="resume",
        created_by_run_id="parent",
        conversation_id=7,
    )
    repository = ToolMessageAuditRepository(_FakeDb({"parent": parent}))

    with pytest.raises(ValueError, match="conversation"):
        await repository._source_run_ids(current)
