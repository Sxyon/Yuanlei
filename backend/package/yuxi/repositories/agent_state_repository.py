"""LangGraph Agent state persistence boundary."""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph


class AgentStateRepository:
    """通过 canonical graph 读写 checkpoint，保留 reducer 与版本语义。"""

    def __init__(self, graph: CompiledStateGraph, *, uid: str, thread_id: str):
        if getattr(graph, "checkpointer", None) is None:
            raise ValueError("Agent state repository requires a graph with checkpointer")
        self._graph = graph
        self._config = {"configurable": {"uid": str(uid), "thread_id": str(thread_id)}}

    async def get_values(self) -> dict[str, Any]:
        """读取当前 checkpoint 的 state values。"""
        state = await self._graph.aget_state(self._config)
        return dict(getattr(state, "values", {}) or {})

    async def update(self, values: dict[str, Any]) -> None:
        """通过 canonical graph 追加一个 state checkpoint。"""
        if not values:
            return
        await self._graph.aupdate_state(self._config, values)
