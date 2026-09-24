"""模型协议与输入能力解析。"""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

ImageSupport = Literal["supported", "unsupported", "unknown"]
InputModalitySupport = Literal["supported", "unsupported", "unknown"]
ToolImageResult = Literal["lift_to_user", "unsupported", "unknown"]
ChatToolCalling = Literal["responses_required", "reasoning_effort_none", "unknown"]

KNOWN_INPUT_MODALITIES = ("text", "image", "audio", "video", "file", "pdf")
_INPUT_MODALITY_ALIASES = {
    "document": "file",
    "documents": "file",
    "image_url": "image",
    "input_image": "image",
    "speech": "audio",
    "visual": "image",
    "vision": "image",
}
_CURATED_IMAGE_INPUT: dict[tuple[str, str, str], tuple[ImageSupport, str]] = {
    ("openai", "openai_chat_completions", "gpt-6-astra"): ("supported", "openai_model_docs"),
    ("openai", "openai_chat_completions", "gpt-6-sol"): ("supported", "openai_model_docs"),
    ("openai", "openai_chat_completions", "gpt-6-luna"): ("supported", "openai_model_docs"),
    ("deepseek", "openai_chat_completions", "deepseek-flash"): ("supported", "deepseek_vision_docs"),
    ("deepseek", "openai_chat_completions", "deepseek-v4-flash"): ("supported", "deepseek_vision_docs"),
    ("deepseek", "openai_chat_completions", "deepseek-v4-flash-vision-exp"): ("supported", "deepseek_vision_docs"),
    ("deepseek", "openai_chat_completions", "deepseek-v4-pro"): ("unsupported", "deepseek_models_docs"),
}
_OFFICIAL_PROVIDER_HOSTS = {"openai": "api.openai.com", "deepseek": "api.deepseek.com"}
_CURATED_CHAT_TOOL_CALLING: dict[tuple[str, str, str], ChatToolCalling] = {
    ("openai", "openai_chat_completions", "gpt-6-astra"): "responses_required",
    ("openai", "openai_chat_completions", "gpt-6-sol"): "reasoning_effort_none",
    ("openai", "openai_chat_completions", "gpt-6-luna"): "reasoning_effort_none",
}


def normalize_input_modality(value: str) -> str:
    """把常见模态别名归一成稳定名称。"""
    normalized = value.strip().lower().replace("-", "_")
    return _INPUT_MODALITY_ALIASES.get(normalized, normalized)


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """描述当前真实调用协议下的输入模态与工具能力及其证据来源。"""

    protocol: str
    input_modalities: dict[str, InputModalitySupport]
    input_sources: dict[str, str]
    tool_image_result: ToolImageResult
    chat_tool_calling: ChatToolCalling
    source: str
    matched_key: str

    @property
    def image_input(self) -> ImageSupport:
        """兼容既有图片专用调用方。"""
        return self.input_modalities.get("image", "unknown")

    def to_dict(self) -> dict:
        """返回可安全写入 Redis 与模型 metadata 的结构。"""
        return {
            "protocol": self.protocol,
            "input": dict(self.input_modalities),
            "image": {"tool_result": self.tool_image_result},
            "tool_calling": {"chat_completions": self.chat_tool_calling},
            "provenance": {
                "source": self.source,
                "matched_key": self.matched_key,
                "input_sources": dict(self.input_sources),
            },
        }


def resolve_model_capabilities(
    provider_id: str,
    provider_type: str,
    model: dict,
    base_url: str = "",
) -> ModelCapabilityProfile:
    """按精确渠道、协议和模型 ID 解析输入模态能力。"""
    if provider_type == "anthropic":
        protocol = "anthropic_messages"
    elif provider_type == "gemini":
        protocol = "gemini_generate_content"
    else:
        protocol = "openai_chat_completions"

    model_id = model["id"]
    matched_key = f"{provider_id}:{protocol}:{model_id}"
    try:
        provider_url = urlsplit(base_url)
        provider_host = provider_url.hostname
        provider_port = provider_url.port
    except ValueError:
        provider_host = None
        provider_port = None
        provider_scheme = None
    else:
        provider_scheme = provider_url.scheme
    is_official_channel = (
        provider_scheme == "https"
        and provider_host == _OFFICIAL_PROVIDER_HOSTS.get(provider_id)
        and provider_port in (None, 443)
    )
    configured_capabilities = model.get("capabilities")
    input_config = configured_capabilities.get("input") if isinstance(configured_capabilities, dict) else None
    configured_image = input_config.get("image") if isinstance(input_config, dict) else None
    image_config = configured_capabilities.get("image") if isinstance(configured_capabilities, dict) else None
    configured_tool_image = image_config.get("tool_result") if isinstance(image_config, dict) else None
    declared_modalities = model.get("input_modalities")
    input_modalities: dict[str, InputModalitySupport] = {"image": "unknown"}
    input_sources = {"image": "unknown"}
    if isinstance(declared_modalities, list):
        normalized_modalities = {
            normalize_input_modality(item) for item in declared_modalities if isinstance(item, str) and item.strip()
        }
        input_modalities = {
            modality: "supported" if modality in normalized_modalities else "unsupported"
            for modality in KNOWN_INPUT_MODALITIES
        }
        source = "provider_models_endpoint"
        input_sources = {modality: source for modality in KNOWN_INPUT_MODALITIES}
    elif is_official_channel and (provider_id, protocol, model_id) in _CURATED_IMAGE_INPUT:
        image_input, source = _CURATED_IMAGE_INPUT[(provider_id, protocol, model_id)]
        input_modalities["image"] = image_input
        input_sources["image"] = source
    else:
        source = "unknown"

    if configured_image in {"supported", "unsupported"}:
        input_modalities["image"] = configured_image
        source = "admin_override"
        input_sources["image"] = source
    image_input = input_modalities.get("image", "unknown")

    if configured_tool_image == "native":
        # 当前没有 adapter 证明可将图片保留在 tool result 中。
        tool_image_result: ToolImageResult = "unknown"
    elif configured_tool_image in {"lift_to_user", "unsupported", "unknown"}:
        tool_image_result: ToolImageResult = configured_tool_image
    elif protocol == "openai_chat_completions":
        tool_image_result: ToolImageResult = {
            "supported": "lift_to_user",
            "unsupported": "unsupported",
            "unknown": "unknown",
        }[image_input]
    else:
        tool_image_result = "unknown"

    chat_tool_calling = (
        _CURATED_CHAT_TOOL_CALLING.get((provider_id, protocol, model_id), "unknown")
        if is_official_channel
        else "unknown"
    )

    return ModelCapabilityProfile(
        protocol=protocol,
        input_modalities=input_modalities,
        input_sources=input_sources,
        tool_image_result=tool_image_result,
        chat_tool_calling=chat_tool_calling,
        source=source,
        matched_key=matched_key,
    )
