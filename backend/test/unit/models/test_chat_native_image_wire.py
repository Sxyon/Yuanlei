from __future__ import annotations

import json
import base64
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import SecretStr

from yuxi.agents.middlewares.model_input import ImageInputCompatibilityMiddleware
from yuxi.models.chat import ChatCompletionsAdapter

pytestmark = pytest.mark.unit


def _response(request: httpx.Request, payloads: list[dict]) -> httpx.Response:
    """捕获真实 adapter 发出的请求并返回最小合法 Chat Completions 响应。"""
    payloads.append(json.loads(request.content))
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-6-sol",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _adapter(
    client: httpx.AsyncClient,
    *,
    model: str = "gpt-6-sol",
    base_url: str = "https://api.openai.com/v1",
    extra_body: dict | None = None,
) -> ChatCompletionsAdapter:
    """构造只连接本测试 MockTransport 的 Chat Completions adapter。"""
    return ChatCompletionsAdapter(
        model=model,
        api_key=SecretStr("test-key"),
        base_url=base_url,
        http_async_client=client,
        stream_usage=False,
        max_retries=0,
        extra_body=extra_body,
    )


def _image_base64(image_format: str) -> str:
    """生成有效的小型协议测试图片。"""
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "red").save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


_PNG_BASE64 = _image_base64("PNG")
_JPEG_BASE64 = _image_base64("JPEG")


@pytest.mark.parametrize(
    ("model", "base_url"),
    [
        ("gpt-6-astra", "https://api.openai.com/v1"),
        ("gpt-6-sol", "https://api.openai.com/v1"),
        ("gpt-6-luna", "https://api.openai.com/v1"),
        ("deepseek-flash", "https://api.deepseek.com/v1"),
    ],
)
@pytest.mark.asyncio
async def test_chat_completions_wire_preserves_multiple_user_images_mime_detail_and_order(model, base_url):
    payloads = []
    transport = httpx.MockTransport(lambda request: _response(request, payloads))
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = _adapter(client, model=model, base_url=base_url)
        await adapter.ainvoke(
            [
                HumanMessage(
                    content_blocks=[
                        {"type": "text", "text": "Compare these images."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{_PNG_BASE64}", "detail": "high"},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{_JPEG_BASE64}", "detail": "low"},
                        },
                    ]
                )
            ]
        )

    content = payloads[0]["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": "Compare these images."},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_PNG_BASE64}", "detail": "high"},
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{_JPEG_BASE64}", "detail": "low"},
        },
    ]


@pytest.mark.asyncio
async def test_chat_completions_wire_sends_lifted_tool_image_as_user_image():
    payloads = []
    transport = httpx.MockTransport(lambda request: _response(request, payloads))
    messages = [
        HumanMessage("Inspect the returned image."),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"file_path": "/user-data/image.png"},
                    "id": "call_image",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content_blocks=[{"type": "image", "base64": _PNG_BASE64, "mime_type": "image/png"}],
            name="read_file",
            tool_call_id="call_image",
            additional_kwargs={"read_file_path": "/user-data/image.png"},
        ),
    ]
    profile_model = SimpleNamespace(
        metadata={
            "yuxi_model_spec": "openai:gpt-6-sol",
            "yuxi_protocol": "openai_chat_completions",
            "yuxi_capabilities": {
                "protocol": "openai_chat_completions",
                "input": {"image": "supported"},
                "image": {"tool_result": "lift_to_user"},
                "tool_calling": {"chat_completions": "unknown"},
                "provenance": {"source": "test", "matched_key": "openai:gpt-6-sol"},
            },
        }
    )

    async with httpx.AsyncClient(transport=transport) as client:
        adapter = _adapter(client)

        async def invoke(prepared: ModelRequest):
            return await adapter.ainvoke(prepared.messages)

        await ImageInputCompatibilityMiddleware().awrap_model_call(
            ModelRequest(model=profile_model, messages=messages, tools=[]),
            invoke,
        )

    wire_messages = payloads[0]["messages"]
    assert [message["role"] for message in wire_messages] == ["user", "assistant", "tool", "user"]
    assert wire_messages[1]["tool_calls"][0]["id"] == "call_image"
    assert wire_messages[2]["tool_call_id"] == "call_image"
    assert wire_messages[2]["content"].startswith("read_file returned 1 image(s).")
    assert wire_messages[3]["content"] == [
        {"type": "text", "text": "Images returned by read_file are attached below. Inspect them when answering."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_BASE64}"}},
    ]


@pytest.mark.asyncio
async def test_chat_completions_wire_transmits_sol_tool_reasoning_effort_none():
    payloads = []
    transport = httpx.MockTransport(lambda request: _response(request, payloads))
    tool = {
        "name": "lookup",
        "description": "Look up a value.",
        "parameters": {"type": "object", "properties": {}},
    }
    async with httpx.AsyncClient(transport=transport) as client:
        model = _adapter(client, extra_body={"reasoning_effort": "none"}).bind_tools([tool])
        await model.ainvoke([HumanMessage("hello")])

    assert payloads[0]["reasoning_effort"] == "none"
    assert payloads[0]["tools"][0]["function"]["name"] == "lookup"
