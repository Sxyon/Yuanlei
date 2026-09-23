from __future__ import annotations

import pytest

from yuxi.models.providers.capabilities import resolve_model_capabilities

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("model_id", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
def test_official_openai_gpt6_models_resolve_native_image_and_tool_constraints(model_id: str):
    profile = resolve_model_capabilities(
        "openai",
        "openai",
        {"id": model_id},
        "https://api.openai.com/v1",
    )

    assert profile.protocol == "openai_chat_completions"
    assert profile.image_input == "supported"
    assert profile.source == "openai_model_docs"
    assert profile.matched_key == f"openai:openai_chat_completions:{model_id}"
    if model_id == "gpt-6-astra":
        assert profile.chat_tool_calling == "responses_required"
    else:
        assert profile.chat_tool_calling == "reasoning_effort_none"


@pytest.mark.parametrize(
    ("provider_id", "base_url", "model_id"),
    [
        ("openai", "https://proxy.example/v1", "gpt-6-sol"),
        ("openai-compatible", "https://api.openai.com/v1", "gpt-6-sol"),
        ("openai", "http://api.openai.com/v1", "gpt-6-sol"),
        ("openai", "https://api.openai.com.evil.example/v1", "gpt-6-sol"),
        ("deepseek", "https://api.deepseek.com", "deepseek-v4.1-flash"),
    ],
)
def test_exact_provider_host_and_model_identity_prevent_capability_leakage(
    provider_id: str,
    base_url: str,
    model_id: str,
):
    profile = resolve_model_capabilities(provider_id, "openai", {"id": model_id}, base_url)

    assert profile.image_input == "unknown"
    assert profile.source == "unknown"
    assert profile.chat_tool_calling == "unknown"


@pytest.mark.parametrize(
    "model_id",
    ["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"],
)
def test_official_deepseek_v41_flash_names_resolve_native_image(model_id: str):
    profile = resolve_model_capabilities(
        "deepseek",
        "openai",
        {"id": model_id},
        "https://api.deepseek.com/v1",
    )

    assert profile.image_input == "supported"
    assert profile.source == "deepseek_vision_docs"
    assert profile.tool_image_result == "lift_to_user"


def test_provider_modalities_distinguish_absent_from_explicitly_empty():
    absent = resolve_model_capabilities("gateway", "openai", {"id": "model"}, "https://gateway.example/v1")
    explicit_empty = resolve_model_capabilities(
        "gateway",
        "openai",
        {"id": "model", "input_modalities": []},
        "https://gateway.example/v1",
    )
    image_input = resolve_model_capabilities(
        "gateway",
        "openai",
        {"id": "model", "input_modalities": ["text", "image"]},
        "https://gateway.example/v1",
    )

    assert absent.image_input == "unknown"
    assert explicit_empty.image_input == "unsupported"
    assert image_input.image_input == "supported"


def test_admin_override_precedes_official_and_channel_metadata():
    profile = resolve_model_capabilities(
        "openai",
        "openai",
        {
            "id": "gpt-6-sol",
            "input_modalities": ["text", "image"],
            "capabilities": {"input": {"image": "unsupported"}},
        },
        "https://api.openai.com/v1",
    )

    assert profile.image_input == "unsupported"
    assert profile.source == "admin_override"


def test_native_tool_result_override_stays_unknown_until_adapter_is_proven():
    profile = resolve_model_capabilities(
        "openai",
        "openai",
        {"id": "gpt-6-sol", "capabilities": {"image": {"tool_result": "native"}}},
        "https://api.openai.com/v1",
    )

    assert profile.image_input == "supported"
    assert profile.tool_image_result == "unknown"


def test_profile_serializes_protocol_status_and_provenance():
    profile = resolve_model_capabilities("gateway", "openai", {"id": "model"}, "https://gateway.example/v1")

    assert profile.to_dict() == {
        "protocol": "openai_chat_completions",
        "input": {"image": "unknown"},
        "image": {"tool_result": "unknown"},
        "tool_calling": {"chat_completions": "unknown"},
        "provenance": {
            "source": "unknown",
            "matched_key": "gateway:openai_chat_completions:model",
        },
    }
