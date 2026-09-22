"""Dashboard 页面内容校验的纯单元测试。"""

from __future__ import annotations

import pytest

from yuxi.services.project_dashboard_service import MAX_PAGE_BYTES, _encode_page_html

pytestmark = pytest.mark.unit


def test_page_html_requires_utf8_document():
    assert _encode_page_html("<html><body>ok</body></html>").startswith(b"<html")
    assert _encode_page_html("<!DOCTYPE html><p>ok</p>").startswith(b"<!DOCTYPE")


def test_page_html_rejects_empty_or_non_document():
    for html in ("", "   ", "<div>fragment</div>"):
        with pytest.raises(ValueError):
            _encode_page_html(html)


def test_page_html_rejects_oversized_content():
    with pytest.raises(ValueError):
        _encode_page_html("<html>" + "a" * MAX_PAGE_BYTES + "</html>")
