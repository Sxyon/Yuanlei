from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.exceptions import ModelError
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from yuxi.models.image_input import validate_image_content_block

from yuxi.agents.toolkits.buildin.tools import ocr_parse_file

_TOOL_IMAGE_USER_TEXT = "Images returned by read_file are attached below. Inspect them when answering."


class ModelInputCapabilityError(ModelError):
    """携带稳定字段说明模型图片输入能力拒绝原因。"""

    def __init__(self, request: ModelRequest, origin: str, profile: dict, status: str) -> None:
        metadata = _model_metadata(request.model)
        capability_name = {
            "user": "image_input",
            "tool": "tool_image_result",
            "assistant": "image_input_role",
        }.get(origin, "image_input")
        self.code = f"{capability_name}_{status}"
        self.model_spec = metadata.get("yuxi_model_spec", "unknown")
        self.protocol = profile.get("protocol", metadata.get("yuxi_protocol", "unknown"))
        self.modality = "image"
        self.origin = origin
        self.provenance = profile.get("provenance", {})
        super().__init__(f"模型 {self.model_spec} 的图片输入能力为 {status}，来源：{origin}。")


class ModelToolCallingCapabilityError(ModelError):
    """在当前协议不满足模型工具调用约束时提供结构化拒绝信息。"""

    def __init__(self, request: ModelRequest, status: str, profile: dict) -> None:
        metadata = _model_metadata(request.model)
        self.code = f"chat_tool_calling_{status}"
        self.model_spec = metadata.get("yuxi_model_spec", "unknown")
        self.protocol = profile.get("protocol", metadata.get("yuxi_protocol", "unknown"))
        self.provenance = profile.get("provenance", {})
        super().__init__(f"模型 {self.model_spec} 在当前协议下不能按要求调用工具：{status}。")


class ModelImagePayloadError(ModelError):
    """在发起模型请求前拒绝结构无效的图片内容。"""

    def __init__(self, request: ModelRequest, origin: str, profile: dict) -> None:
        metadata = _model_metadata(request.model)
        self.code = "image_payload_invalid"
        self.model_spec = metadata.get("yuxi_model_spec", "unknown")
        self.protocol = profile.get("protocol", metadata.get("yuxi_protocol", "unknown"))
        self.modality = "image"
        self.origin = origin
        self.provenance = profile.get("provenance", {})
        super().__init__(f"模型 {self.model_spec} 的图片输入内容无效，来源：{origin}。")


class ImageInputCompatibilityMiddleware(AgentMiddleware[Any, Any, Any]):
    """按模型能力预检图片输入并转换 Chat Completions 的 tool 图片角色。"""

    tools = [ocr_parse_file]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(_prepare_image_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(_prepare_image_request(request))


def _prepare_image_request(request: ModelRequest) -> ModelRequest:
    """在调用 Provider 前校验模型的图片与工具协议能力。"""
    profile = _model_capabilities(request.model)
    for message in request.messages:
        for block in getattr(message, "content_blocks", []):
            if not isinstance(block, dict) or block.get("type") not in {"image", "image_url", "input_image"}:
                continue
            try:
                validate_image_content_block(block)
            except ValueError as exc:
                origin = "tool" if isinstance(message, ToolMessage) else "user"
                raise ModelImagePayloadError(request, origin, profile) from exc

    tool_calling = profile.get("tool_calling", {}).get("chat_completions", "unknown")
    if request.tools and tool_calling == "responses_required":
        raise ModelToolCallingCapabilityError(request, "requires_responses", profile)
    if request.tools and tool_calling == "reasoning_effort_none":
        overrides = _model_metadata(request.model).get("yuxi_request_body_overrides", {})
        if not isinstance(overrides, dict) or overrides.get("reasoning_effort") != "none":
            raise ModelToolCallingCapabilityError(request, "requires_reasoning_effort_none", profile)

    image_input = profile.get("input", {}).get("image", "unknown")
    user_has_image = any(
        isinstance(message, HumanMessage) and _message_has_image(message) for message in request.messages
    )
    tool_has_image = any(
        isinstance(message, ToolMessage) and _message_has_image(message) for message in request.messages
    )
    unsupported_role_has_image = any(
        not isinstance(message, (HumanMessage, ToolMessage)) and _message_has_image(message)
        for message in request.messages
    )

    if unsupported_role_has_image:
        raise ModelInputCapabilityError(request, "assistant", profile, "unsupported")

    if user_has_image and image_input != "supported":
        raise ModelInputCapabilityError(request, "user", profile, image_input)

    tool_image_result = profile.get("image", {}).get("tool_result", "unknown")
    if tool_has_image and tool_image_result == "lift_to_user" and image_input == "supported":
        return _lift_tool_images_to_user(request)
    if tool_has_image:
        tool_status = tool_image_result if tool_image_result in {"unsupported", "unknown"} else "unknown"
        raise ModelInputCapabilityError(request, "tool", profile, tool_status)
    return request


def _model_metadata(model: Any) -> dict:
    """从模型或绑定 Runnable 读取已缓存的 Yuanlei metadata。"""
    for candidate in (model, getattr(model, "bound", None), getattr(model, "model", None)):
        metadata = getattr(candidate, "metadata", None)
        if isinstance(metadata, dict):
            return metadata
    return {}


def _model_capabilities(model: Any) -> dict:
    """读取模型缓存建立的能力档案；旧缓存按 unknown 处理。"""
    metadata = _model_metadata(model)
    profile = metadata.get("yuxi_capabilities")
    return profile if isinstance(profile, dict) else {"protocol": metadata.get("yuxi_protocol", "unknown")}


def _message_has_image(message: Any) -> bool:
    """判断 LangChain 消息是否含有标准图片内容块。"""
    return any(
        isinstance(block, dict) and block.get("type") in {"image", "image_url", "input_image"}
        for block in getattr(message, "content_blocks", [])
    )


def _lift_tool_images_to_user(request: ModelRequest) -> ModelRequest:
    """将 Chat Completions 不承载的 tool 图片紧随 tool 结果提升为 user 图片。"""
    if not any(isinstance(message, ToolMessage) and _message_has_image(message) for message in request.messages):
        return request

    bridged_messages = []
    pending_images: list[dict[str, Any]] = []
    latest_ocr_call_by_path: dict[str, int] = {}

    for index, message in enumerate(request.messages):
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls:
            if tool_call.get("name") == "ocr_parse_file":
                file_path = tool_call.get("args", {}).get("file_path")
                if isinstance(file_path, str) and file_path:
                    latest_ocr_call_by_path[file_path] = index

    def flush_pending_images() -> None:
        if not pending_images:
            return
        bridged_messages.append(
            HumanMessage(
                content_blocks=[{"type": "text", "text": _TOOL_IMAGE_USER_TEXT}, *pending_images],
            )
        )
        pending_images.clear()

    for index, message in enumerate(request.messages):
        if not isinstance(message, ToolMessage):
            flush_pending_images()
            bridged_messages.append(message)
            continue

        image_blocks = [
            block for block in message.content_blocks if block.get("type") in {"image", "image_url", "input_image"}
        ]
        if not image_blocks:
            bridged_messages.append(message)
            continue

        image_path = message.additional_kwargs.get("read_file_path")
        ocr_explicitly_requested = isinstance(image_path, str) and latest_ocr_call_by_path.get(image_path, -1) > index
        if not ocr_explicitly_requested:
            pending_images.extend(image_blocks)
        text = "\n".join(
            block["text"]
            for block in message.content_blocks
            if block.get("type") == "text" and isinstance(block.get("text"), str)
        )
        bridged_messages.append(
            message.model_copy(
                update={
                    "content": text
                    or (
                        f"read_file returned {len(image_blocks)} image(s). "
                        + (
                            "OCR was explicitly requested for this image."
                            if ocr_explicitly_requested
                            else "The image content is attached in the following user message for visual inspection."
                        )
                    )
                }
            )
        )

    flush_pending_images()
    if bridged_messages == request.messages:
        return request
    return request.override(messages=bridged_messages)
