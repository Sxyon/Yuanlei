from __future__ import annotations

from types import SimpleNamespace

import pytest

from yuxi.repositories.agent_state_repository import AgentStateRepository


class _Graph:
    def __init__(self):
        self.checkpointer = object()
        self.events: list[tuple] = []

    async def aget_state(self, config):
        self.events.append(("read", config))
        return SimpleNamespace(values={"messages": ["hello"]})

    async def aupdate_state(self, config, values):
        self.events.append(("write", config, values))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reads_and_updates_through_canonical_graph() -> None:
    graph = _Graph()
    repository = AgentStateRepository(graph, uid="user-1", thread_id="thread-1")

    values = await repository.get_values()

    await repository.update({"token_usage": {"summary_active": True}})

    config = {"configurable": {"uid": "user-1", "thread_id": "thread-1"}}
    assert values == {"messages": ["hello"]}
    assert graph.events == [
        ("read", config),
        ("write", config, {"token_usage": {"summary_active": True}}),
    ]


@pytest.mark.unit
def test_rejects_graph_without_checkpointer() -> None:
    graph = SimpleNamespace(checkpointer=None)

    with pytest.raises(ValueError, match="requires a graph with checkpointer"):
        AgentStateRepository(graph, uid="user-1", thread_id="thread-1")
