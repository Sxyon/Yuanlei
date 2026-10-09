"""输出额度与截断边界的正负向回归。"""

from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AIMessageChunk

from yuxi.agents.middlewares.output_limit import OutputLimitMiddleware
from yuxi.agents.middlewares.network_retry import NetworkRetryMiddleware
from yuxi.models.chat import LangChainChatAdapter, load_chat_model, select_model
from yuxi.models.output import ModelOutputTruncated, check_output_complete
from yuxi.models.providers.cache import ModelInfo
from yuxi.models.providers.service import _normalize_model_item

pytestmark = pytest.mark.unit


def _info(**kwargs):
    """提供没有 SDK profile 的 Anthropic 兼容模型。"""
    return ModelInfo(
        provider_id="test",
        model_id="deepseek-flash",
        model_type="chat",
        display_name="test",
        provider_type="anthropic",
        api_key="test-key",
        base_url="http://localhost:9999",
        **kwargs,
    )


@pytest.mark.parametrize("loader", [load_chat_model, select_model])
@pytest.mark.parametrize(
    "override, expected",
    [({}, 65536), ({"max_tokens": 32}, 32), ({"max_completion_tokens": 32}, 32), ({"max_tokens": None}, 65536)],
)
def test_output_configuration_reaches_both_entrypoints(monkeypatch, loader, override, expected):
    """两个加载入口使用同一配置与调用优先级。"""
    info = ModelInfo.from_dict(_info(default_output_tokens=65536, max_output_tokens=393216).to_dict())
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda spec: info)
    loaded = loader(info.spec, **override)
    model = loaded.model if isinstance(loaded, LangChainChatAdapter) else loaded
    payload = model._get_request_payload("test")
    assert payload["max_tokens"] == expected
    assert "max_completion_tokens" not in payload
    assert "max_output_tokens" not in payload


def test_unknown_old_model_sdk_fallback_is_explicitly_identified(monkeypatch):
    """未知旧模型保留 SDK 默认，并明确复现短输出来源。"""
    info = _info()
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda spec: info)
    assert load_chat_model(info.spec)._get_request_payload("test")["max_tokens"] == 4096


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "65536", []])
def test_invalid_config_or_call_rejected(monkeypatch, value):
    """配置与调用都拒绝非法额度类型。"""
    with pytest.raises(ValueError, match="正整数"):
        _normalize_model_item({"id": "test", "type": "chat", "default_output_tokens": value})
    info = _info(default_output_tokens=65536)
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda spec: info)
    with pytest.raises(ValueError, match="正整数"):
        load_chat_model(info.spec, max_tokens=value)


def test_known_maximum_and_conflicting_aliases_rejected(monkeypatch):
    """能力约束与同层别名冲突在请求前失败。"""
    info = _info(default_output_tokens=65536, max_output_tokens=65536)
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda spec: info)
    with pytest.raises(ValueError, match="超过模型最大输出"):
        load_chat_model(info.spec, max_tokens=65537)
    with pytest.raises(ValueError, match="冲突"):
        load_chat_model(info.spec, max_tokens=32, max_completion_tokens=64)
    with pytest.raises(ValueError, match="超过模型最大输出"):
        _normalize_model_item({"id": "test", "type": "chat", "default_output_tokens": 64, "max_output_tokens": 32})


@pytest.mark.parametrize("reason", ["end_turn", "tool_use", "stop", "stop_sequence"])
def test_normal_stop_and_tool_use_are_accepted(reason):
    """正常结束及工具调用不被误判为截断。"""
    check_output_complete(AIMessage("complete", response_metadata={"stop_reason": reason}))


@pytest.mark.parametrize("reason", ["max_tokens", "length", "model_context_window_exceeded", "MAX_TOKENS"])
def test_truncated_tool_response_never_leaves_model_boundary(reason):
    """截断事实阻止工具执行，且不会进入网络重试。"""
    message = AIMessage(
        "partial",
        response_metadata={"stop_reason": reason},
        tool_calls=[{"name": "side_effect", "args": {}, "id": "t"}],
        invalid_tool_calls=[{"name": "side_effect", "args": '{"x":', "id": "bad", "error": "partial"}],
    )
    request = ModelRequest(model=SimpleNamespace(), messages=[], tools=[])
    attempts = []

    def handler(request):
        """返回截断响应，计数仅证明不会重试；核心断言是响应无法进入工具节点。"""
        attempts.append(1)
        return OutputLimitMiddleware().wrap_model_call(request, lambda _: ModelResponse(result=[message]))

    with pytest.raises(ModelOutputTruncated) as error:
        NetworkRetryMiddleware(max_retries=2).wrap_model_call(request, handler)
    assert error.value.message is message
    assert error.value.reason == reason
    assert len(attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["end_turn", "max_tokens"])
async def test_general_adapter_stream_preserves_long_content_and_finish_reason(reason):
    """长文本不被应用裁剪，流式与非流式保留结束原因。"""
    text = "long output " * 6000

    class Model:
        """合成模型保留超过 4096 的文本。"""

        async def astream(self, messages):
            """流式末片带供应商结束原因。"""
            yield AIMessageChunk(text[:20000])
            yield AIMessageChunk(text[20000:])
            yield AIMessageChunk("", response_metadata={"stop_reason": reason})

        async def ainvoke(self, messages):
            """非流式使用同一长响应。"""
            return AIMessage(text, response_metadata={"stop_reason": reason})

    adapter = LangChainChatAdapter(Model(), model_name="test")
    parts = []
    try:
        async for chunk in await adapter.call("test", stream=True):
            parts.append(chunk)
    except ModelOutputTruncated as error:
        assert reason == "max_tokens"
        assert error.message.text == text
    assert "".join(chunk.content for chunk in parts) == text
    assert parts[-1].response_metadata["stop_reason"] == reason
    if reason == "max_tokens":
        with pytest.raises(ModelOutputTruncated):
            await adapter.call("test")
    else:
        response = await adapter.call("test")
        assert response.content == text
        assert response.is_full


@pytest.mark.asyncio
async def test_official_deepseek_defaults_are_narrow_idempotent_and_preserve_explicit(monkeypatch):
    """仅补官方目标模型的缺失默认，保留管理员选择。"""
    from unittest.mock import AsyncMock
    from yuxi.models.providers import service

    provider = SimpleNamespace(
        provider_id="test-official",
        provider_type="anthropic",
        base_url="https://api.deepseek.com/anthropic",
        enabled_models=[
            {"id": "deepseek-flash", "type": "chat"},
            {"id": "deepseek-v4-pro", "type": "chat", "default_output_tokens": 32},
            {"id": "unknown", "type": "chat"},
            {"id": "deepseek-flash-proxy", "type": "chat", "base_url_override": "https://proxy.example/anthropic"},
        ],
    )

    async def providers(db):
        """返回测试供应商，不访问共享运行数据。"""
        return [provider]

    monkeypatch.setattr(service, "list_model_providers", providers)
    monkeypatch.setattr(service, "BUILTIN_PROVIDERS", [])
    db = SimpleNamespace(flush=AsyncMock())
    await service.ensure_builtin_model_providers_in_db(db)
    first = provider.enabled_models
    assert first[0]["default_output_tokens"] == 65536
    assert first[0]["max_output_tokens"] == 393216
    assert first[1]["default_output_tokens"] == 32
    assert "default_output_tokens" not in first[2]
    await service.ensure_builtin_model_providers_in_db(db)
    assert provider.enabled_models is first
    provider.enabled_models = [{"id": "deepseek-flash", "type": "chat", "default_output_tokens": None}]
    await service.ensure_builtin_model_providers_in_db(db)
    assert provider.enabled_models[0]["default_output_tokens"] is None
    provider.enabled_models = [
        {"id": "deepseek-flash", "type": "chat", "base_url_override": "https://proxy.example/anthropic"}
    ]
    await service.ensure_builtin_model_providers_in_db(db)
    assert "default_output_tokens" not in provider.enabled_models[0]


def test_general_entrypoint_mixed_alias_override_and_conflict(monkeypatch):
    """顶层覆盖跨别名生效，同层冲突明确拒绝。"""
    info = _info(default_output_tokens=65536)
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda _: info)
    model = select_model(info.spec, model_params={"max_tokens": 65536}, max_completion_tokens=32)
    assert model.model._get_request_payload("test")["max_tokens"] == 32
    with pytest.raises(ValueError, match="冲突"):
        select_model(info.spec, max_tokens=32, max_completion_tokens=64)


def test_gemini_final_configuration_keeps_small_override_and_rejects_excess(monkeypatch):
    """Gemini 调用配置保留小额度并拒绝转换前的非法值。"""
    info = _info(default_output_tokens=65536, max_output_tokens=65536)
    from dataclasses import replace

    info = replace(info, provider_type="gemini", model_id="gemini-2.5-flash")
    monkeypatch.setattr("yuxi.models.chat.model_cache.get_model_info", lambda _: info)
    model = load_chat_model(info.spec)
    assert model._prepare_params(None).max_output_tokens == 65536
    assert model._prepare_params(None, max_tokens=32).max_output_tokens == 32
    with pytest.raises(ValueError, match="超过模型最大输出"):
        model._prepare_params(None, generation_config={"max_output_tokens": 65537})
    for invalid in ("32", 1.0, True):
        with pytest.raises(ValueError, match="正整数"):
            model._prepare_params(None, generation_config={"max_output_tokens": invalid})
    with pytest.raises(ValueError, match="冲突"):
        model._prepare_params(None, generation_config={"max_output_tokens": 64}, max_tokens=32)
    assert model._prepare_params(None, generation_config={"max_output_tokens": 32}).max_output_tokens == 32
