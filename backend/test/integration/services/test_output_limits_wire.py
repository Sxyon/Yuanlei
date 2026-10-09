"""使用真实 HTTP 接收端核对两个加载入口和供应商 SDK。"""

from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from test.support.output_limit_server import LONG_OUTPUT, OutputHandler
from yuxi.models.chat import load_chat_model, select_model
from yuxi.models.providers.cache import ModelInfo

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize("protocol", ["anthropic", "openai"])
@pytest.mark.parametrize("entry", ["agent", "general"])
@pytest.mark.parametrize("stream", [False, True])
async def test_final_http_request_keeps_default_and_smaller_override(monkeypatch, protocol, entry, stream):
    """SDK 通过 TCP 发出参数，合成响应超过 4096 且无应用裁剪。"""
    monkeypatch.setenv("RUNNING_IN_DOCKER", "false")
    server = ThreadingHTTPServer(("127.0.0.1", 0), OutputHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from test.support.output_limit_server import LOCK, REQUESTS

    try:
        info = ModelInfo.from_dict(
            ModelInfo(
                provider_id="output-wire",
                model_id="output-test",
                model_type="chat",
                display_name="test",
                provider_type=protocol,
                api_key="synthetic-key",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                default_output_tokens=65536,
                max_output_tokens=393216,
            ).to_dict()
        )
        monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda _: info)
        with LOCK:
            start = len(REQUESTS)
        for value in (None, 32, 131072, 393216):
            kwargs = {} if value is None else {"max_completion_tokens": value}
            model = (
                load_chat_model(info.spec, **kwargs)
                if entry == "agent"
                else select_model(
                    info.spec, model_params={"max_tokens": 65536}, **({"max_completion_tokens": value} if value else {})
                )
            )
            if entry == "agent":
                if stream:
                    chunks = [chunk async for chunk in model.astream("OUTPUT_CASE:normal")]
                    assert "".join(chunk.text for chunk in chunks) == LONG_OUTPUT
                    assert any(chunk.response_metadata for chunk in chunks)
                else:
                    assert (await model.ainvoke("OUTPUT_CASE:normal")).text == LONG_OUTPUT
            elif stream:
                chunks = [chunk async for chunk in await model.call("OUTPUT_CASE:normal", stream=True)]
                assert "".join(chunk.content for chunk in chunks) == LONG_OUTPUT
                assert chunks[-1].is_full
            else:
                assert (await model.call("OUTPUT_CASE:normal")).content == LONG_OUTPUT
        with LOCK:
            payloads = list(REQUESTS[start:])
        assert len(payloads) == 4
        assert [p.get("max_tokens", p.get("max_completion_tokens")) for p in payloads] == [65536, 32, 131072, 393216]
        assert all(len(set(p) & {"max_tokens", "max_completion_tokens", "max_output_tokens"}) == 1 for p in payloads)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("case", ["tool", "truncated_tool", "truncated_valid_tool"])
async def test_subagent_real_graph_rejects_truncation_before_tool_node(monkeypatch, case):
    """子后端真实装配与 TCP 响应验证；不代替 worker 执行树验收。"""
    from unittest.mock import AsyncMock

    from deepagents.backends import StateBackend
    from yuxi.agents.buildin.subagent import graph as subagent_graph
    from yuxi.agents.buildin.subagent.context import SubAgentContext
    from yuxi.models.output import ModelOutputTruncated

    monkeypatch.setenv("RUNNING_IN_DOCKER", "false")
    server = ThreadingHTTPServer(("127.0.0.1", 0), OutputHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        info = ModelInfo(
            provider_id="output-wire",
            model_id="output-test",
            model_type="chat",
            display_name="test",
            provider_type="openai",
            api_key="synthetic-key",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            default_output_tokens=65536,
        )
        monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda _: info)
        context = SubAgentContext(
            thread_id="synthetic-child",
            uid="synthetic-user",
            model=info.spec,
            workdir_path="/home/gem/user-data/projects/synthetic-test",
            workdir_relative_path="projects/synthetic-test",
        )
        context._runtime_prepared = True
        monkeypatch.setattr(subagent_graph, "sync_agent_context_skills", AsyncMock())
        monkeypatch.setattr(subagent_graph, "resolve_configured_runtime_tools", AsyncMock(return_value=[]))
        monkeypatch.setattr(subagent_graph, "create_agent_composite_backend", lambda _: StateBackend())
        # 此用例仅验证真实构图和模型/工具节点，不提供运行时持久化降级。
        monkeypatch.setattr(subagent_graph.SubAgentBackend, "_get_checkpointer", AsyncMock(return_value=None))
        graph = await subagent_graph.SubAgentBackend().get_graph(context=context)
        updates = []
        try:
            async for update in graph.astream(
                {"messages": [{"role": "user", "content": f"OUTPUT_CASE:{case}"}]},
                context=context,
                stream_mode="updates",
            ):
                updates.append(update)
        except ModelOutputTruncated as error:
            assert case in {"truncated_tool", "truncated_valid_tool"}
            assert error.reason == "length"
            assert error.message.text == "partial tool"
            if case == "truncated_valid_tool":
                assert error.message.tool_calls[0]["name"] == "write_todos"
            assert not any("tools" in update for update in updates)
        else:
            assert case == "tool"
            tool_updates = [update["tools"] for update in updates if "tools" in update]
            assert len(tool_updates) == 1
            assert tool_updates[0]["todos"] == [{"content": "synthetic task", "status": "in_progress"}]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
