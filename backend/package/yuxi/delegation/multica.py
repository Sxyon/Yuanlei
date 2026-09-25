"""Multica 渠道适配器：出向委派与标记核对（yuanlei 域）。

Multica 侧没有调用方幂等键，元垒用稳定 `operation_id` 与描述标记
`Yuanlei-Delegation-Operation: <operation_id>` 做 search-before-create：
重投时先核对标记，命中则采纳已有工作项，不再创建第二个。远端状态只作为只读投影读取，
不反向写元垒 canonical 状态。HTTP 传输收敛在 `HttpMulticaClient` 内。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from yuxi.delegation.contracts import (
    DelegationError,
    DelegationHandle,
    DelegationRequest,
    DelegationResult,
)

OPERATION_MARKER_PREFIX = "Yuanlei-Delegation-Operation:"
MULTICA_EXECUTOR_KEY = "multica"


@dataclass(frozen=True, slots=True)
class MulticaIssue:
    """Multica 工作项的归一化投影。"""

    id: str
    identifier: str
    title: str
    description: str
    status: str
    url: str | None = None
    updated_at: str | None = None


@runtime_checkable
class MulticaClient(Protocol):
    """Multica 创建/查询契约的窄客户端；实际认证与分页由实现承担。"""

    async def create_issue(self, *, title: str, description: str) -> MulticaIssue: ...

    async def get_issue(self, *, issue_ref: str) -> MulticaIssue: ...

    async def search_issues(self, *, query: str, limit: int = 20) -> list[MulticaIssue]: ...

    async def list_issues(
        self,
        *,
        updated_after: str | None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MulticaIssue]: ...


def operation_marker(operation_id: str) -> str:
    """生成绑定稳定操作标识的描述标记。"""
    return f"{OPERATION_MARKER_PREFIX} {operation_id}"


def _matches_marker(issue: MulticaIssue, operation_id: str) -> bool:
    """只在描述里出现精确标记时采纳，避免同名字段误命中。"""
    return operation_marker(operation_id) in (issue.description or "")


def _title_from_task(task: str) -> str:
    """从委派任务取单行标题，限制远端标题长度。"""
    first_line = next((line.strip() for line in str(task).splitlines() if line.strip()), "")
    return (first_line or "元垒委派任务")[:120]


def _description_for(request: DelegationRequest) -> str:
    """构造写一次的委派描述，内嵌稳定操作标记。"""
    lines = [operation_marker(request.operation_id), "", str(request.task).strip()]
    if request.context_refs:
        lines.extend(["", "来源引用："])
        for ref in request.context_refs:
            lines.append(f"- {ref}")
    return "\n".join(lines)


class MulticaExecutor:
    """把 Multica 工作项套进统一可委派接口。"""

    key = MULTICA_EXECUTOR_KEY

    def __init__(self, client: MulticaClient):
        self.client = client

    def capabilities(self) -> dict[str, bool]:
        """Multica 无沙盒多轮续接入口，结果只以远端 URL 暴露。"""
        return {"multi_turn": False, "remote_artifacts": True}

    async def dispatch(self, request: DelegationRequest) -> DelegationHandle:
        """先按标记核对，命中采纳；未命中才创建，保证同一操作不产生第二个工作项。"""
        existing = await self._find_by_operation(request.operation_id)
        if existing is not None:
            return self._handle(request.operation_id, existing)
        issue = await self.client.create_issue(
            title=_title_from_task(request.task),
            description=_description_for(request),
        )
        return self._handle(request.operation_id, issue)

    async def status(self, handle: DelegationHandle) -> str | None:
        """读取远端工作项状态的只读投影。"""
        if not handle.external_ref:
            return None
        issue = await self.client.get_issue(issue_ref=handle.external_ref)
        return issue.status

    async def collect(self, handle: DelegationHandle) -> DelegationResult:
        """回收远端工作项摘要；产物仅能作为远端 URL 引用。"""
        if not handle.external_ref:
            raise DelegationError("Multica 委派句柄缺少 external_ref", error_code="delegation_handle_invalid")
        issue = await self.client.get_issue(issue_ref=handle.external_ref)
        artifacts: tuple[dict[str, Any], ...] = ()
        if issue.url:
            artifacts = ({"kind": "url", "url": issue.url},)
        text = f"# {issue.title}\n\n{issue.description}\n\n状态: {issue.status}\n"
        return DelegationResult(
            summary=f"{issue.title}（{issue.status}）",
            text=text,
            artifacts=artifacts,
            usage={},
            remote_status=issue.status,
        )

    async def _find_by_operation(self, operation_id: str) -> MulticaIssue | None:
        """按标记精确核对已存在的远端工作项。"""
        candidates = await self.client.search_issues(query=operation_id, limit=20)
        for issue in candidates:
            if _matches_marker(issue, operation_id):
                return issue
        return None

    def _handle(self, operation_id: str, issue: MulticaIssue) -> DelegationHandle:
        return DelegationHandle(
            operation_id=operation_id,
            executor_key=self.key,
            external_ref=issue.identifier,
            external_url=issue.url,
            remote_status=issue.status,
        )


class HttpMulticaClient:
    """基于 aiohttp 的 Multica 客户端；端点以配置表达，认证头收敛在此。"""

    def __init__(self, *, base_url: str, token: str, project_ref: str | None = None, timeout: float = 20.0):
        self.base_url = str(base_url).rstrip("/")
        self.token = str(token)
        self.project_ref = project_ref
        self.timeout = float(timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> MulticaIssue:
        return MulticaIssue(
            id=str(payload.get("id") or ""),
            identifier=str(payload.get("identifier") or payload.get("id") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or ""),
            url=payload.get("url") or payload.get("html_url"),
            updated_at=payload.get("updated_at"),
        )

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(headers=self._headers(), timeout=timeout) as session:
            async with session.request(method, f"{self.base_url}{path}", **kwargs) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise DelegationError(
                        f"multica request failed: {method} {path} -> {response.status}: {body[:500]}",
                        error_code="multica_request_failed",
                    )
                return await response.json()

    async def create_issue(self, *, title: str, description: str) -> MulticaIssue:
        payload: dict[str, Any] = {"title": title, "description": description}
        if self.project_ref:
            payload["project_id"] = self.project_ref
        data = await self._request("POST", "/api/issues", json=payload)
        return self._normalize(data.get("issue", data))

    async def get_issue(self, *, issue_ref: str) -> MulticaIssue:
        data = await self._request("GET", f"/api/issues/{issue_ref}")
        return self._normalize(data.get("issue", data))

    async def search_issues(self, *, query: str, limit: int = 20) -> list[MulticaIssue]:
        data = await self._request("GET", "/api/issues", params={"query": query, "limit": int(limit)})
        items = data.get("issues", data) if isinstance(data, dict) else data
        return [self._normalize(item) for item in (items or [])]

    async def list_issues(self, *, updated_after: str | None, limit: int = 50, offset: int = 0) -> list[MulticaIssue]:
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if self.project_ref:
            params["project_id"] = self.project_ref
        if updated_after:
            params["updated_after"] = updated_after
        data = await self._request("GET", "/api/issues", params=params)
        items = data.get("issues", data) if isinstance(data, dict) else data
        return [self._normalize(item) for item in (items or [])]


def build_multica_client_from_env() -> HttpMulticaClient | None:
    """按环境配置装配 Multica 客户端；凭据缺失时返回 None，适配器不注册。"""
    base_url = os.getenv("YUANLEI_MULTICA_BASE_URL", "").strip()
    token = os.getenv("YUANLEI_MULTICA_TOKEN", "").strip()
    if not base_url or not token:
        return None
    project_ref = os.getenv("YUANLEI_MULTICA_PROJECT_ID", "").strip() or None
    return HttpMulticaClient(base_url=base_url, token=token, project_ref=project_ref)
