from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from yuxi.models import image_input
from yuxi.services.input_message_service import (
    build_chat_input_message,
    build_chat_input_message_from_openai_content,
    restore_chat_input_message,
)

pytestmark = pytest.mark.unit


def _image_base64(image_format):
    """生成有效的小型图片内容供入口校验测试使用。"""
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "red").save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


_PNG_BASE64 = _image_base64("PNG")


def test_build_chat_input_message_preserves_explicit_image_mime_type():
    message = build_chat_input_message("看图", _PNG_BASE64, "image/png")

    assert message.require_langchain_message().content[1]["image_url"]["url"] == f"data:image/png;base64,{_PNG_BASE64}"


@pytest.mark.parametrize(
    ("image_content", "mime_type"),
    [("", "image/png"), ("not base64", "image/png"), (_PNG_BASE64, "text/plain"), ("YWJj", "image/png")],
)
def test_build_chat_input_message_rejects_invalid_image_data(image_content, mime_type):
    with pytest.raises(ValueError):
        build_chat_input_message("看图", image_content, mime_type)


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,not base64",
        "data:text/plain;base64,YWJj",
        "file:///tmp/image.png",
        "javascript:alert(1)",
    ],
)
def test_openai_image_url_input_rejects_invalid_urls(url):
    with pytest.raises(ValueError):
        build_chat_input_message_from_openai_content([{"type": "image_url", "image_url": {"url": url}}])


def test_legacy_image_input_defaults_to_jpeg():
    jpeg_base64 = _image_base64("JPEG")
    message = build_chat_input_message("看图", jpeg_base64)

    assert message.require_langchain_message().content[1]["image_url"]["url"] == f"data:image/jpeg;base64,{jpeg_base64}"


def test_legacy_empty_image_content_remains_a_text_request():
    message = build_chat_input_message("hello", "")

    assert message.message_type == "text"
    assert message.require_langchain_message().content == "hello"


def test_rejects_oversize_image_before_base64_decode(monkeypatch):
    def fail_if_decoded(*_args, **_kwargs):
        pytest.fail("oversize image reached Base64 decoder")

    monkeypatch.setattr(image_input.base64, "b64decode", fail_if_decoded)
    oversized = "A" * (image_input.MAX_IMAGE_BASE64_LENGTH + 1)

    with pytest.raises(ValueError, match="超过 5 MiB"):
        build_chat_input_message("看图", oversized, "image/png")


def test_restore_repairs_legacy_png_mislabeled_as_jpeg_without_mutating_metadata():
    from langchain.messages import HumanMessage

    raw_message = HumanMessage(
        content=[
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_PNG_BASE64}", "detail": "high"}},
        ]
    ).model_dump()
    metadata = {"raw_message": raw_message}

    restored = restore_chat_input_message(content="看图", image_content=_PNG_BASE64, metadata=metadata)

    restored_url = restored.require_langchain_message().content[1]["image_url"]
    assert restored_url == {"url": f"data:image/png;base64,{_PNG_BASE64}", "detail": "high"}
    assert metadata["raw_message"]["content"][1]["image_url"]["url"] == f"data:image/jpeg;base64,{_PNG_BASE64}"
    assert restored.extra_metadata["raw_message"]["content"][1]["image_url"]["url"] == (
        f"data:image/png;base64,{_PNG_BASE64}"
    )
