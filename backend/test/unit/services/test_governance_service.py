"""元垒项目治理来源归一化与标题校验的纯逻辑单测。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from yuxi.services.governance_service import (
    normalize_governance_source,
    normalize_title,
)


def test_normalize_governance_source_accepts_project_and_external_channels() -> None:
    assert normalize_governance_source(
        source_channel="project", source_external_id=None, source_url=None
    ) == ("project", None, None)
    assert normalize_governance_source(
        source_channel="github",
        source_external_id=" owner/repo#1 ",
        source_url="https://github.com/owner/repo/issues/1",
    ) == ("github", "owner/repo#1", "https://github.com/owner/repo/issues/1")


@pytest.mark.parametrize("channel", [None, "", "slack"])
def test_normalize_governance_source_rejects_missing_or_unknown_channel(channel) -> None:
    with pytest.raises(HTTPException) as error:
        normalize_governance_source(source_channel=channel, source_external_id=None, source_url=None)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "invalid_source"


def test_normalize_governance_source_requires_external_id_for_channels() -> None:
    with pytest.raises(HTTPException) as error:
        normalize_governance_source(source_channel="multica", source_external_id=None, source_url=None)
    assert error.value.detail["code"] == "invalid_source"


def test_normalize_governance_source_rejects_external_fields_for_project() -> None:
    with pytest.raises(HTTPException) as error:
        normalize_governance_source(
            source_channel="project", source_external_id="x", source_url="https://x.invalid"
        )
    assert error.value.detail["code"] == "invalid_source"


def test_normalize_title_trims_and_rejects_empty_or_overlong() -> None:
    assert normalize_title("  议题  ") == "议题"
    for bad in ("", "   ", "x" * 513):
        with pytest.raises(HTTPException) as error:
            normalize_title(bad)
        assert error.value.detail["code"] == "invalid_title"
