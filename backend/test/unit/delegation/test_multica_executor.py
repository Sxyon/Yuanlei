"""Multica 适配器的单元测试：标记核对、能力声明与凭据装配边界。"""

from __future__ import annotations

import pytest

from yuxi.delegation.contracts import DelegationHandle, DelegationRequest
from yuxi.delegation.multica import (
    HttpMulticaClient,
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

    async def list_issues(self, *, limit: int = 50, offset: int = 0) -> list[MulticaIssue]:
        return self.issues[offset : offset + limit]


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
    monkeypatch.delenv("YUANLEI_MULTICA_WORKSPACE_ID", raising=False)
    assert build_multica_client_from_env() is None

    # base_url + token 齐备但缺 workspace 作用域仍 fail-closed，不装配客户端。
    monkeypatch.setenv("YUANLEI_MULTICA_BASE_URL", "http://multica.invalid")
    monkeypatch.setenv("YUANLEI_MULTICA_TOKEN", "secret-token")
    assert build_multica_client_from_env() is None

    monkeypatch.setenv("YUANLEI_MULTICA_WORKSPACE_ID", "ws-1")
    client = build_multica_client_from_env()
    assert client is not None
    assert client.base_url == "http://multica.invalid"
    assert client.workspace_ref == "ws-1"


@pytest.mark.asyncio
async def test_http_client_scopes_every_issue_request_by_workspace(monkeypatch) -> None:
    """四个 issues 出入口都带 workspace 作用域，列表固定 updated_at 倒序。

    workspace 作用域统一放查询参数：真实实例 `POST /api/issues` 请求体带
    `workspace_id` 返回 400，查询参数带则 2xx（见 Decision 受控写实测）。断言 create
    的请求体不含 `workspace_id`，回退到请求体形状时该用例失败。
    """
    client = HttpMulticaClient(base_url="http://multica.invalid", token="t", workspace_ref="ws-1")
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            return {
                "id": "i",
                "identifier": "YL-1",
                "title": "t",
                "description": "d",
                "updated_at": "2026-09-25T00:00:00Z",
            }
        return {"issues": []}

    monkeypatch.setattr(HttpMulticaClient, "_request", fake_request)

    await client.create_issue(title="t", description="d")
    await client.get_issue(issue_ref="i")
    await client.search_issues(query="q")
    await client.list_issues(limit=5)

    assert calls[0][2]["params"]["workspace_id"] == "ws-1"
    assert "workspace_id" not in calls[0][2]["json"]
    assert calls[1][2]["params"]["workspace_id"] == "ws-1"
    assert calls[2][2]["params"]["workspace_id"] == "ws-1"
    assert calls[3][2]["params"]["workspace_id"] == "ws-1"
    assert calls[3][2]["params"]["sort"] == "updated_at"
    assert calls[3][2]["params"]["direction"] == "desc"
    assert "updated_after" not in calls[3][2]["params"]
