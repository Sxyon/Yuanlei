"""项目蓝图名称与正文约束的纯单元测试。"""

from __future__ import annotations

import pytest

from yuxi.services.project_blueprint_service import (
    MAX_BLUEPRINT_BYTES,
    encode_blueprint_content,
    validate_blueprint_name,
)

pytestmark = pytest.mark.unit


def test_blueprint_name_accepts_normalized_markdown_files():
    for name in ("product-vision.md", "design.md", "a_b-1.md", "项目蓝图.md", "a" * 117 + ".md"):
        assert validate_blueprint_name(name) == name


def test_blueprint_name_rejects_paths_and_non_markdown():
    for name in (
        "",
        ".md",
        "Vision.md",
        "vision",
        "vision.txt",
        "vision.md.exe",
        "sub/vision.md",
        "../vision.md",
        "vision/../evil.md",
        "\\vision.md",
        "a" * 118 + ".md",
    ):
        with pytest.raises(ValueError):
            validate_blueprint_name(name)


def test_blueprint_content_size_limit_is_measured_in_utf8_bytes():
    assert encode_blueprint_content("a" * (MAX_BLUEPRINT_BYTES - 1)) == b"a" * (MAX_BLUEPRINT_BYTES - 1)

    with pytest.raises(ValueError):
        encode_blueprint_content("中" * (MAX_BLUEPRINT_BYTES // 3 + 1))


def test_blueprint_content_rejects_non_text():
    with pytest.raises(ValueError):
        encode_blueprint_content(b"bytes")
