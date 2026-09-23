from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from yuxi.agents.middlewares.model_input import (
    ImageInputCompatibilityMiddleware,
    ModelInputCapabilityError,
    ModelImagePayloadError,
    ModelToolCallingCapabilityError,
)
from yuxi.agents.middlewares.network_retry import NetworkRetryMiddleware

pytestmark = pytest.mark.unit
_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"


def _request(model, messages, tools=None) -> ModelRequest:
    """构造可控制能力 metadata 的模型请求。"""
    return ModelRequest(model=model, messages=messages, tools=tools)


def _model(
    *,
    image_input="supported",
    tool_image_result="lift_to_user",
    chat_tool_calling="unknown",
    request_body_overrides=None,
):
    """创建带模型能力档案的轻量模型。"""
    protocol = "openai_chat_completions"
    spec = "openai:gpt-6-sol"
    return SimpleNamespace(
        metadata={
            "yuxi_model_spec": spec,
            "yuxi_protocol": protocol,
            "yuxi_capabilities": {
                "protocol": protocol,
                "input": {"image": image_input},
                "image": {"tool_result": tool_image_result},
                "tool_calling": {"chat_completions": chat_tool_calling},
                "provenance": {"source": "test", "matched_key": spec},
            },
            "yuxi_request_body_overrides": request_body_overrides or {},
        }
    )


def _tool_image_message(path: str = "/user-data/image.png") -> ToolMessage:
    """构造带文件来源的图片工具结果。"""
    return ToolMessage(
        content_blocks=[{"type": "image", "base64": _PNG_BASE64, "mime_type": "image/png"}],
        name="read_file",
        tool_call_id="call_image",
        additional_kwargs={"read_file_path": path, "read_file_media_type": "image/png"},
    )


def test_bridges_supported_tool_images_after_parallel_results_without_mutating_state():
    middleware = ImageInputCompatibilityMiddleware()
    original_messages = [
        HumanMessage("读图并列目录"),
        _tool_image_message(),
        ToolMessage(content="['a.png']", name="ls", tool_call_id="call_ls"),
    ]
    seen = {}

    def handler(request):
        seen["messages"] = request.messages
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(_request(_model(), original_messages), handler)

    messages = seen["messages"]
    assert original_messages[1].content_blocks[0]["type"] == "image"
    assert [message.type for message in messages] == ["human", "tool", "tool", "human"]
    assert messages[1].tool_call_id == "call_image"
    assert isinstance(messages[1].content, str)
    assert messages[2].tool_call_id == "call_ls"
    assert messages[3].content_blocks[1] == {
        "type": "image",
        "base64": _PNG_BASE64,
        "mime_type": "image/png",
    }
    assert messages[3].content_blocks[0]["text"] == (
        "Images returned by read_file are attached below. Inspect them when answering."
    )


@pytest.mark.parametrize("tool_image_result", ["unknown", "native"])
def test_rejects_unverified_tool_image_result_before_provider_call(tool_image_result):
    middleware = ImageInputCompatibilityMiddleware()
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(content="should not run")])

    request = _request(_model(tool_image_result=tool_image_result), [_tool_image_message()])
    with pytest.raises(ModelInputCapabilityError) as raised:
        middleware.wrap_model_call(request, handler)

    assert raised.value.code == "tool_image_result_unknown"
    assert raised.value.origin == "tool"
    assert calls == 0


@pytest.mark.parametrize("status", ["unknown", "unsupported"])
def test_rejects_unconfirmed_or_unsupported_user_image_before_provider_call(status):
    middleware = ImageInputCompatibilityMiddleware()
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(content="should not run")])

    request = _request(
        _model(image_input=status),
        [HumanMessage(content=[{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_BASE64}"}}])],
    )
    with pytest.raises(ModelInputCapabilityError) as raised:
        middleware.wrap_model_call(request, handler)

    assert raised.value.code == f"image_input_{status}"
    assert raised.value.model_spec == "openai:gpt-6-sol"
    assert raised.value.protocol == "openai_chat_completions"
    assert raised.value.modality == "image"
    assert raised.value.origin == "user"
    assert raised.value.provenance["source"] == "test"
    assert calls == 0


def test_passes_user_image_and_preserves_unrelated_provider_errors():
    middleware = ImageInputCompatibilityMiddleware()
    request = _request(
        _model(),
        [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}])],
    )

    def handler(_request):
        error = RuntimeError("invalid tool schema")
        error.status_code = 400
        raise error

    with pytest.raises(RuntimeError, match="invalid tool schema"):
        middleware.wrap_model_call(request, handler)


@pytest.mark.parametrize(
    "image_block",
    [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,not base64"}},
        {"type": "image_url", "image_url": {"url": "file:///etc/passwd"}},
        {"type": "image", "base64": "YWJj", "mime_type": "text/plain"},
        {"type": "image", "base64": "YWJj", "mime_type": "image/png"},
        {"type": "image", "base64": "", "mime_type": "image/png"},
    ],
)
def test_rejects_malformed_image_payload_before_provider_call(image_block):
    middleware = ImageInputCompatibilityMiddleware()
    request = _request(_model(), [HumanMessage(content_blocks=[image_block])])

    with pytest.raises(ModelImagePayloadError) as raised:
        middleware.wrap_model_call(request, lambda _request: pytest.fail("provider must not be called"))

    assert raised.value.code == "image_payload_invalid"
    assert raised.value.origin == "user"


def test_text_request_does_not_require_known_image_capability():
    middleware = ImageInputCompatibilityMiddleware()
    request = _request(_model(image_input="unknown", tool_image_result="unknown"), [HumanMessage("hello")])
    seen = {}

    def handler(model_request):
        seen["request"] = model_request
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request, handler)

    assert seen["request"] is request


def test_does_not_relift_historical_tool_image_after_explicit_ocr_call():
    middleware = ImageInputCompatibilityMiddleware()
    path = "/user-data/image.png"
    messages = [
        _tool_image_message(path),
        AIMessage(
            content="OCRを明示的に実行します。",
            tool_calls=[{"name": "ocr_parse_file", "args": {"file_path": path}, "id": "call_ocr"}],
        ),
        ToolMessage(content="OCR result", tool_call_id="call_ocr"),
    ]
    seen = {}

    def handler(request):
        seen["messages"] = request.messages
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(_request(_model(), messages), handler)

    assert [message.type for message in seen["messages"]] == ["tool", "ai", "tool"]
    assert "OCR was explicitly requested" in seen["messages"][0].content


def test_gpt6_astra_tool_calling_requires_responses_before_provider_call():
    middleware = ImageInputCompatibilityMiddleware()
    request = _request(
        _model(chat_tool_calling="responses_required"),
        [HumanMessage("hello")],
        tools=[{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}],
    )

    with pytest.raises(ModelToolCallingCapabilityError) as raised:
        middleware.wrap_model_call(request, lambda _request: pytest.fail("provider must not be called"))

    assert raised.value.code == "chat_tool_calling_requires_responses"


@pytest.mark.asyncio
async def test_capability_errors_escape_network_retry_instead_of_becoming_assistant_text():
    image_middleware = ImageInputCompatibilityMiddleware()
    retry_middleware = NetworkRetryMiddleware(max_retries=2, initial_delay=0, jitter=False)
    request = _request(
        _model(image_input="unknown"),
        [HumanMessage(content=[{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_BASE64}"}}])],
    )

    async def provider_handler(_request):
        pytest.fail("capability preflight must run before the provider")

    async def image_guard(inner_request):
        return await image_middleware.awrap_model_call(inner_request, provider_handler)

    with pytest.raises(ModelInputCapabilityError) as raised:
        await retry_middleware.awrap_model_call(request, image_guard)

    assert raised.value.code == "image_input_unknown"
    assert not raised.value.is_retryable


def test_gpt6_sol_tool_calling_requires_explicit_none_reasoning_effort():
    middleware = ImageInputCompatibilityMiddleware()
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    request = _request(_model(chat_tool_calling="reasoning_effort_none"), [HumanMessage("hello")], tools=tools)

    with pytest.raises(ModelToolCallingCapabilityError) as raised:
        middleware.wrap_model_call(request, lambda _request: pytest.fail("provider must not be called"))
    assert raised.value.code == "chat_tool_calling_requires_reasoning_effort_none"

    model = _model(chat_tool_calling="reasoning_effort_none", request_body_overrides={"reasoning_effort": "none"})
    response = middleware.wrap_model_call(
        _request(model, [HumanMessage("hello")], tools=tools),
        lambda _request: ModelResponse(result=[AIMessage(content="ok")]),
    )
    assert response.result[0].content == "ok"


def test_ocr_remains_an_explicit_tool_not_an_automatic_fallback():
    assert [tool.name for tool in ImageInputCompatibilityMiddleware.tools] == ["ocr_parse_file"]
