"""使用真实 SDK 与 LangGraph 验证供应商推理协议边界。"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from yuxi.models.chat import load_chat_model
from yuxi.models.utils import parse_assistant_message_body
from yuxi.models.providers.cache import ModelInfo
from yuxi.services.chat_service import _protocol_event_yuxi_event

REASONING = " First\nthen check. "
TOOL = {"type": "function", "function": {"name": "inspect_code", "parameters": {"type": "object", "properties": {}}}}


def make_model(monkeypatch, provider, field="reasoning_content", *, enabled=True):
    """以 SDK 的真实 JSON/SSE 解析覆盖模型工厂。"""
    requests = []

    def respond(request):
        """工具结果后的请求必须携带原始推理，而非格式化后的展示文本。"""
        body = json.loads(request.content)
        requests.append(body)
        resumed = body["messages"][-1]["role"] == "tool"
        if resumed:
            if enabled:
                assert body["messages"][-2]["reasoning_content"] == REASONING
            else:
                assert "reasoning_content" not in body["messages"][-2]
        base = {"id": "chat-test", "object": "chat.completion", "created": 1, "model": "test"}
        reasoning = {field: REASONING} if enabled and not resumed else {}
        tool = {"id": "call-test", "type": "function", "function": {"name": "inspect_code", "arguments": "{}"}}
        message = {"role": "assistant", "content": "OK" if resumed else "", **reasoning}
        if not resumed:
            message["tool_calls"] = [tool]
        finish = "stop" if resumed else "tool_calls"
        if body.get("stream"):
            delta = {**message}
            if not resumed:
                delta["tool_calls"] = [{"index": 0, **tool}]
            events = [
                {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                {**base, "choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}},
            ]
            if reasoning:
                delta[field] = REASONING[8:]
                events.insert(
                    0,
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "", field: REASONING[:8]},
                                "finish_reason": None,
                            }
                        ],
                    },
                )
            if not resumed:
                events.insert(
                    -2,
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "",
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                text="".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200, json={**base, "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
        )

    info = ModelInfo(provider, "test", "chat", "Test", "test-key", "https://example.com/v1", "openai")
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda _: info)
    transport = httpx.MockTransport(respond)
    model = load_chat_model(
        info.spec,
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
    )
    return model, requests


@pytest.mark.parametrize("provider", ["siliconflow-cn", "opencode-go", "zhipuai-coding-plan"])
@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("output_version", ["v0", "v1"])
async def test_provider_reasoning_and_tool_roundtrip(monkeypatch, provider, field, stream, output_version):
    """三家均保留推理、工具 ID 与续答原文，异步和同步路径一致。"""
    model, requests = make_model(monkeypatch, provider, field)
    model.output_version = output_version
    bound = model.bind_tools([TOOL])
    for asynchronous in (False, True):
        inputs = [HumanMessage("Inspect this function.")]
        if stream:
            chunks = [chunk async for chunk in bound.astream(inputs)] if asynchronous else list(bound.stream(inputs))
            result = chunks[0]
            for chunk in chunks[1:]:
                result += chunk
            assert result.usage_metadata["total_tokens"] == 5
        else:
            result = await bound.ainvoke(inputs) if asynchronous else bound.invoke(inputs)
        assert "reasoning_content" not in result.additional_kwargs
        assert result.response_metadata["model_provider"] == "openai"
        assert result.response_metadata["output_version"] == "v1"
        assert isinstance(result.content, list)
        assert next(b for b in result.content_blocks if b["type"] == "reasoning")["reasoning"] == REASONING
        assert result.tool_calls[0]["id"] == "call-test"
        inputs.extend([result, ToolMessage("valid", tool_call_id="call-test")])
        answer = await bound.ainvoke(inputs) if asynchronous else bound.invoke(inputs)
        assert answer.text == "OK"
    assert len(requests) == 4


async def test_real_v3_reasoning_projection_and_checkpoint(monkeypatch):
    """真实 v3 事件经服务层投影后与 checkpoint 的历史推理一致。"""
    model, _ = make_model(monkeypatch, "opencode-go")

    async def node(state):
        """执行真实模型流桥接。"""
        return {"messages": [await model.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", node)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "reasoning-test"}}
    run = await compiled.astream_events({"messages": [HumanMessage("Inspect code")]}, config, version="v3")
    emitted = []
    async for event in run:
        if event["method"] == "messages":
            raw, metadata = event["params"]["data"]
            projected = _protocol_event_yuxi_event(raw, message_id="m", thread_id="t", namespace=[])
            if projected:
                emitted.append(projected)
    assert "".join(e.get("reasoning_content", "") for e in emitted) == REASONING
    assert any(e["type"] == "tool_call" and e["tool_call_id"] == "call-test" for e in emitted)
    state = await compiled.aget_state(config)
    persisted = state.values["messages"][-1].model_dump()
    assert parse_assistant_message_body(persisted["content"], persisted)["reasoning_content"] == REASONING


def test_non_reasoning_provider_is_unchanged(monkeypatch):
    """普通 OpenAI 请求不添加第三方字段。"""
    model, _ = make_model(monkeypatch, "openai", enabled=False)
    payload = model._get_request_payload([AIMessage("OK", additional_kwargs={"reasoning_content": "private"})])
    assert "reasoning_content" not in payload["messages"][0]


async def test_disabling_adapter_reproduces_upstream_reasoning_loss(monkeypatch):
    """负向对照：同一真实 SDK 响应在关闭适配后只保留工具，丢失推理。"""
    model, _ = make_model(monkeypatch, "opencode-go")
    model.preserve_reasoning = False
    result = await model.ainvoke("Inspect code")
    assert result.tool_calls[0]["id"] == "call-test"
    assert "reasoning_content" not in result.additional_kwargs
    assert not any(block["type"] == "reasoning" for block in result.content_blocks)


@pytest.mark.parametrize("provider", ["siliconflow-cn", "opencode-go", "zhipuai-coding-plan"])
async def test_missing_reasoning_still_completes_tool_roundtrip(monkeypatch, provider):
    """供应商没有输出推理时，不伪造字段、不妨碍工具及续答。"""
    model, _ = make_model(monkeypatch, provider, enabled=False)
    inputs = [HumanMessage("Inspect code")]
    chunks = [chunk async for chunk in model.bind_tools([TOOL]).astream(inputs)]
    result = chunks[0]
    for chunk in chunks[1:]:
        result += chunk
    assert not any(block["type"] == "reasoning" for block in result.content_blocks)
    assert result.tool_calls[0]["id"] == "call-test"
    inputs.extend([result, ToolMessage("valid", tool_call_id="call-test")])
    answer = await model.ainvoke(inputs)
    assert answer.text == "OK"
    assert not any(block["type"] == "reasoning" for block in answer.content_blocks)


@pytest.mark.parametrize(
    "content,metadata,expected",
    [
        (
            [
                None,
                "ignored",
                {"type": "text", "text": 42},
                {"type": "reasoning", "reasoning": None},
                {"type": "text", "text": " first "},
                {"type": "reasoning", "reasoning": " thought "},
                {"type": "text", "text": "second"},
                {"type": "reasoning", "reasoning": "next"},
                {"type": "tool_call", "name": "inspect_code"},
            ],
            None,
            {"content": " first second", "reasoning_content": " thought next"},
        ),
        (
            "stored answer",
            {"content": [{"type": "text", "text": "metadata text"}]},
            {"content": "stored answer", "reasoning_content": ""},
        ),
        (
            "answer",
            {"content": "invalid blocks", "additional_kwargs": {"reasoning_content": "saved thought"}},
            {"content": "answer", "reasoning_content": "saved thought"},
        ),
        ("answer", {}, {"content": "answer", "reasoning_content": ""}),
        ("answer", {"additional_kwargs": None}, {"content": "answer", "reasoning_content": ""}),
        (
            "answer",
            {"additional_kwargs": {"reasoning_content": {"bad": True}}},
            {"content": "answer", "reasoning_content": ""},
        ),
        ("<think> old thought </think>answer", {}, {"content": "answer", "reasoning_content": " old thought "}),
        ("<think>partial", {}, {"content": "", "reasoning_content": "partial"}),
        (
            "example: <think>literal</think>",
            {},
            {"content": "example: <think>literal</think>", "reasoning_content": ""},
        ),
        (
            "answer",
            {
                "content": [{"type": "reasoning", "reasoning": "canonical"}],
                "additional_kwargs": {"reasoning_content": "duplicate"},
            },
            {"content": "answer", "reasoning_content": "canonical"},
        ),
    ],
)
def test_history_recovery_is_best_effort(content, metadata, expected):
    """旧历史只恢复真实已有内容；缺失或畸形推理不影响正文。"""
    assert parse_assistant_message_body(content, metadata) == expected


def test_standard_blocks_encode_history_once(monkeypatch):
    """下一轮将标准文本和推理各编码一次，工具结构不泄漏到正文。"""
    model, _ = make_model(monkeypatch, "zhipuai-coding-plan")
    message = AIMessage(
        content_blocks=[
            {"type": "reasoning", "reasoning": REASONING},
            {"type": "text", "text": "answer"},
            {"type": "tool_call", "id": "call-test", "name": "inspect_code", "args": {}},
        ],
        response_metadata={"output_version": "v1"},
    )
    wire = model._get_request_payload([message])["messages"][0]
    assert wire["content"] == "answer"
    assert wire["reasoning_content"] == REASONING
    assert len(wire["tool_calls"]) == 1
    assert wire["tool_calls"][0]["id"] == "call-test"
