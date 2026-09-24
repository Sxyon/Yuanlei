"""校验跨模型协议共用的图片输入内容。"""

from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image

_IMAGE_MIME_TYPE = re.compile(r"^image/[a-zA-Z0-9][a-zA-Z0-9.+-]*$")
_DATA_IMAGE_URL = re.compile(r"^data:(image/[a-zA-Z0-9][a-zA-Z0-9.+-]*);base64,([A-Za-z0-9+/]*={0,2})$", re.IGNORECASE)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BASE64_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3)


def validate_image_mime_type(mime_type: object) -> str:
    """校验图片 MIME 类型并返回规范化值。"""
    if not isinstance(mime_type, str) or not _IMAGE_MIME_TYPE.fullmatch(mime_type):
        raise ValueError("图片 MIME 类型无效")
    return mime_type.lower()


def validate_image_base64(content: object, mime_type: object) -> None:
    """校验非空 Base64、真实图片格式及其 MIME 一致性。"""
    validate_image_mime_type(mime_type)
    decoded = _decode_image_base64(content)
    validate_image_bytes(decoded, mime_type)


def image_mime_type_from_base64(content: object) -> str:
    """从有效图片 Base64 中识别真实 MIME 类型。"""
    return _image_mime_type(_decode_image_base64(content))


def validate_image_bytes(content: bytes, mime_type: object) -> None:
    """校验图片字节可解码且实际格式与声明 MIME 一致。"""
    normalized_mime = validate_image_mime_type(mime_type)
    if not isinstance(content, bytes) or not content:
        raise ValueError("图片内容不能为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片内容超过 5 MiB 限制")
    actual_mime = _image_mime_type(content)
    if actual_mime != normalized_mime:
        raise ValueError("图片 MIME 类型与实际内容不匹配")


def _decode_image_base64(content: object) -> bytes:
    if not isinstance(content, str) or not content:
        raise ValueError("图片内容不能为空")
    if len(content) > MAX_IMAGE_BASE64_LENGTH:
        raise ValueError("图片内容超过 5 MiB 限制")
    try:
        decoded = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 Base64 内容无效") from exc
    if not decoded:
        raise ValueError("图片内容不能为空")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("图片内容超过 5 MiB 限制")
    return decoded


def _image_mime_type(content: bytes) -> str:
    try:
        with Image.open(BytesIO(content)) as image:
            image_format = image.format
            image.verify()
    except (Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ValueError("图片字节无效") from exc
    mime_type = Image.MIME.get(image_format)
    if not mime_type:
        raise ValueError("图片格式不受支持")
    return mime_type


def validate_image_url(url: object) -> None:
    """只接受有效图片 data URL 或带主机名的 HTTP(S) URL。"""
    if not isinstance(url, str) or not url:
        raise ValueError("图片 URL 无效")

    if url.lower().startswith("data:"):
        if len(url) > MAX_IMAGE_BASE64_LENGTH + 128:
            raise ValueError("图片内容超过 5 MiB 限制")
        match = _DATA_IMAGE_URL.fullmatch(url)
        if not match:
            raise ValueError("图片 data URL 无效")
        validate_image_base64(match.group(2), match.group(1))
        return

    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port not in (0,)
        )
    except ValueError as exc:
        raise ValueError("图片 URL 无效") from exc
    if not valid_url:
        raise ValueError("图片 URL 无效")


def validate_image_content_block(block: dict) -> None:
    """校验 LangChain 标准图片内容块，不暴露图片字节或 URL。"""
    block_type = block.get("type")
    if block_type == "image_url":
        image_url = block.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        validate_image_url(url)
        return

    if block_type not in {"image", "input_image"}:
        raise ValueError("图片内容块类型无效")

    mime_type = block.get("mime_type") or block.get("media_type")
    if isinstance(block.get("base64"), str):
        validate_image_base64(block["base64"], mime_type)
        return

    url = block.get("url") or block.get("image_url")
    if url is not None:
        if isinstance(url, dict):
            url = url.get("url")
        validate_image_url(url)
        return

    data = block.get("data")
    if isinstance(data, bytes):
        if not data:
            raise ValueError("图片内容不能为空")
        validate_image_bytes(data, mime_type)
        return
    if isinstance(data, str):
        if data.lower().startswith("data:"):
            validate_image_url(data)
        else:
            validate_image_base64(data, mime_type)
        return

    raise ValueError("图片内容无效")
