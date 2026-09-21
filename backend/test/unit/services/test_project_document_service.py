"""项目文档 key 与 content 约束的纯单元测试。"""

from __future__ import annotations

import pytest

from yuxi.services.project_document_service import (
    MAX_DOCUMENT_CONTENT_BYTES,
    encode_document_content,
    validate_document_key,
)

pytestmark = pytest.mark.unit


def test_document_key_accepts_normalized_names():
    for key in ("dashboard.config", "profile", "data.customer-segments", "a_b-1", "a" * 120):
        assert validate_document_key(key) == key


def test_document_key_rejects_invalid_names():
    for key in ("", ".config", "-config", "_config", "Data", "data/../x", "data/x", "\\x", "a" * 121, "中文"):
        with pytest.raises(ValueError):
            validate_document_key(key)


def test_document_content_size_limit_is_measured_in_utf8_bytes():
    accepted = "a" * (MAX_DOCUMENT_CONTENT_BYTES - 2)
    assert len(encode_document_content(accepted)) <= MAX_DOCUMENT_CONTENT_BYTES

    with pytest.raises(ValueError):
        encode_document_content("a" * MAX_DOCUMENT_CONTENT_BYTES)


def test_document_content_rejects_non_json_values():
    with pytest.raises(ValueError):
        encode_document_content({1, 2, 3})

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            encode_document_content(value)
