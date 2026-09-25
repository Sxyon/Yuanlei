"""Multica 适配器的单元测试：标记核对、能力声明与凭据装配边界。"""

from __future__ import annotations

import pytest

from yuxi.delegation.contracts import DelegationHandle, DelegationRequest
from yuxi.delegation.multica import (
    MulticaExecutor,
    MulticaIssue,
    build_multica_client_from_env,
    operation_marker,
)


class _FakeClient:
    def __init__(self, *, issues: list[MulticaIssue] | None = None):
        self.issues = list(issues or [])
        self.create_calls = 0
        self.last_description = ""

    async def create_issue(self, *, title: str, description: str) -> MulticaIssue:
        self.create_calls += 1
        self.last_description = description
        issue = MulticaIssue(
            id=f"id-{self.create_calls}",
            identifier=f"YL-{self.create_calls}",
            title=title,
            description=description,
            status="todo",
            url=f"https://multica.invalid/issues/YL-{self.create_calls}",
            updated_at="2026-09-25T00:00:00Z",
        )
        self.issues.append(issue)
        return issue

    async def get_issue(self, *, issue_ref: str) -> MulticaIssue:
        return next(issue for issue in self.issues if issue.identifier == issue_ref)

    async def search_issues(self, *, query: str, limit: int = 20) -> list[MulticaIssue]:
        return [issue for issue in self.issues if query in issue.description][:limit]

    async def list_issues(self, *, updated_after: str | None, limit: int = 50) -> list[MulticaIssue]:
        return self.issues[:limit]


def _request(operation_id: str = "op-123") -> DelegationRequest:
    return DelegationRequest(
        operation_id=operation_id,
        project_id="project-1",
        task="实现一件事",
        initiator_run_id="run-1",
    )


def test_capabilities_declare_only_consumed_abilities() -> None:
    executor = MulticaExecutor(_FakeClient())
    assert executor.capabilities() == {"multi_turn": False, "remote_artifacts": True}


@pytest.mark.asyncio
async def test_dispatch_creates_and_embeds_stable_marker() -> None:
    client = _FakeClient()
    handle = await MulticaExecutor(client).dispatch(_request())
    assert client.create_calls == 1
    assert operation_marker("op-123") in client.last_description
    assert handle.external_ref == "YL-1"
    assert handle.remote_status == "todo"


@pytest.mark.asyncio
async def test_dispatch_adopts_existing_issue_by_exact_marker() -> None:
    existing = MulticaIssue(
        id="id-existing",
        identifier="YL-9",
        title="实现一件事",
        description=f"{operation_marker('op-123')}\n\n实现一件事",
        status="in_progress",
        url="https://multica.invalid/issues/YL-9",
    )
    client = _FakeClient(issues=[existing])
    handle = await MulticaExecutor(client).dispatch(_request())
    assert client.create_calls == 0
    assert handle.external_ref == "YL-9"
    assert handle.remote_status == "in_progress"


@pytest.mark.asyncio
async def test_dispatch_does_not_adopt_lookalike_without_marker() -> None:
    lookalike = MulticaIssue(
        id="id-x",
        identifier="YL-7",
        title="实现一件事",
        description="提到了 op-123 但没有精确标记",
        status="todo",
    )
    client = _FakeClient(issues=[lookalike])
    handle = await MulticaExecutor(client).dispatch(_request())
    assert client.create_calls == 1
    assert handle.external_ref == "YL-1"


@pytest.mark.asyncio
async def test_status_and_collect_expose_remote_projection() -> None:
    client = _FakeClient(
        issues=[MulticaIssue(id="i", identifier="YL-1", title="T", description="D", status="done", url="u")]
    )
    executor = MulticaExecutor(client)
    handle = DelegationHandle(operation_id="op-123", executor_key="multica", external_ref="YL-1")
    assert await executor.status(handle) == "done"
    result = await executor.collect(handle)
    assert result.remote_status == "done"
    assert result.artifacts == ({"kind": "url", "url": "u"},)
    assert "done" in (result.text or "")


def test_build_multica_client_from_env_fails_closed_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("YUANLEI_MULTICA_BASE_URL", raising=False)
    monkeypatch.delenv("YUANLEI_MULTICA_TOKEN", raising=False)
    assert build_multica_client_from_env() is None

    monkeypatch.setenv("YUANLEI_MULTICA_BASE_URL", "http://multica.invalid")
    monkeypatch.setenv("YUANLEI_MULTICA_TOKEN", "secret-token")
    client = build_multica_client_from_env()
    assert client is not None
    assert client.base_url == "http://multica.invalid"
