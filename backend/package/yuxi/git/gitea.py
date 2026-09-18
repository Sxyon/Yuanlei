"""Gitea 托管商 API 实现。"""

from __future__ import annotations

import os
from fnmatch import fnmatchcase
from urllib.parse import quote, urlsplit

import httpx

from yuxi.git.hosting import DeployKey, HostedBranch, HostedRepository


class GiteaProvider:
    """访问一个经过 allowlist 校验的 Gitea 实例。"""

    def __init__(self, *, api_origin: str, api_token: str, ssh_host: str, ssh_port: int):
        self.api_origin = validate_gitea_origin(api_origin)
        self.ssh_host = str(ssh_host).strip()
        self.ssh_port = int(ssh_port)
        if not self.ssh_host or not 1 <= self.ssh_port <= 65535:
            raise ValueError("invalid Gitea SSH endpoint")
        self._headers = {"Authorization": f"token {api_token}", "Accept": "application/json"}

    async def verify_connection(self) -> None:
        """验证 Token 可访问当前 Gitea 用户 API。"""
        await self._request("GET", "/api/v1/user")

    async def get_repository(self, owner: str, name: str) -> HostedRepository:
        """读取仓库并校验 canonical SSH endpoint。"""
        data = await self._request("GET", f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}")
        default_branch = str(data.get("default_branch") or "").strip()
        ssh_url = str(data.get("ssh_url") or "").strip()
        parsed_owner, parsed_name = _parse_canonical_ssh_url(ssh_url, self.ssh_host, self.ssh_port)
        if parsed_owner != owner or parsed_name != name or not default_branch:
            raise ValueError("Gitea repository metadata does not match the requested repository")
        return HostedRepository(str(data["id"]), parsed_owner, parsed_name, ssh_url, default_branch)

    async def get_branch(self, owner: str, name: str, branch: str) -> HostedBranch:
        """精确读取一个分支，不接受 tag 或完整 ref。"""
        normalized = str(branch or "").strip()
        if not normalized or normalized.startswith("refs/"):
            raise ValueError("invalid Gitea branch name")
        data = await self._request(
            "GET",
            f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/branches/{quote(normalized, safe='')}",
        )
        returned_name = str(data.get("name") or "").strip()
        commit = data.get("commit") if isinstance(data, dict) else None
        commit_sha = str(commit.get("id") or "").strip() if isinstance(commit, dict) else ""
        if returned_name != normalized or not commit_sha:
            raise ValueError("Gitea branch metadata does not match the requested branch")
        return HostedBranch(returned_name, commit_sha)

    async def list_deploy_keys(self, owner: str, name: str) -> list[DeployKey]:
        """分页列出仓库的全部 deploy key。"""
        path = f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/keys"
        result: list[DeployKey] = []
        seen_ids: set[str] = set()
        page = 1
        limit = 50
        while True:
            response = await self._raw_request("GET", path, params={"page": page, "limit": limit})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError("invalid Gitea deploy key response")
            for item in data:
                key_id = str(item["id"])
                if key_id in seen_ids:
                    raise ValueError("Gitea deploy key pagination repeated an item")
                seen_ids.add(key_id)
                result.append(
                    DeployKey(key_id, str(item["title"]), str(item["key"]), bool(item.get("read_only", True)))
                )
            total_header = response.headers.get("x-total-count")
            total = int(total_header) if total_header else None
            if not data or (total is not None and len(result) >= total) or (total is None and len(data) < limit):
                return result
            page += 1
            if page > 10_000:
                raise ValueError("Gitea deploy key pagination did not terminate")

    async def create_deploy_key(self, owner: str, name: str, *, title: str, public_key: str) -> DeployKey:
        """创建仓库可写 deploy key。"""
        data = await self._request(
            "POST",
            f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/keys",
            json={"title": title, "key": public_key, "read_only": False},
        )
        return DeployKey(str(data["id"]), str(data["title"]), str(data["key"]), bool(data.get("read_only", True)))

    async def delete_deploy_key(self, owner: str, name: str, key_id: str) -> None:
        """撤销 deploy key；远端已不存在时视为完成。"""
        response = await self._raw_request(
            "DELETE", f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/keys/{quote(str(key_id), safe='')}"
        )
        if response.status_code not in {204, 404}:
            response.raise_for_status()

    async def is_branch_protected(self, owner: str, name: str, branch: str) -> bool:
        """列出并匹配全部保护规则，包含 Gitea 支持的 glob 规则。"""
        data = await self._request(
            "GET", f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/branch_protections"
        )
        if not isinstance(data, list):
            raise ValueError("invalid Gitea branch protection response")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("invalid Gitea branch protection rule")
            rule_name = str(item.get("rule_name") or item.get("branch_name") or "").strip()
            if not rule_name:
                raise ValueError("Gitea branch protection rule has no name")
            if _matches_gitea_rule(branch, rule_name):
                return True
        return False

    async def _request(self, method: str, path: str, **kwargs):
        """发送不跟随重定向的 Gitea API 请求。"""
        response = await self._raw_request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    async def _raw_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """在短生命周期客户端中发送请求，避免凭据进入 URL。"""
        async with httpx.AsyncClient(
            base_url=self.api_origin,
            headers=self._headers,
            follow_redirects=False,
            timeout=20,
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.is_redirect:
            raise ValueError("Gitea redirects are not allowed")
        return response


def validate_gitea_origin(value: str) -> str:
    """要求 origin 精确命中运维 allowlist。"""
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid Gitea API origin")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Gitea API origin must not contain path, query or fragment")
    allowed = {
        item.strip().rstrip("/") for item in os.getenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "").split(",") if item.strip()
    }
    if raw not in allowed:
        raise ValueError("Gitea API origin is not allowed")
    return raw


def _matches_gitea_rule(branch: str, rule_name: str) -> bool:
    """匹配已验证子集；扩展 glob 保守视为命中，避免错误放行。"""
    glob_markers = "*?[{\\"
    if not any(marker in rule_name for marker in glob_markers):
        return branch.casefold() == rule_name.casefold()
    if any(marker in rule_name for marker in "{}\\"):
        return True
    if rule_name.count("[") != rule_name.count("]"):
        return True
    # fnmatch 的 `*` 可跨 `/`，范围比 Gitea separator-aware glob 更宽，只会保守拒绝更多分支。
    return fnmatchcase(branch, rule_name)


def _parse_canonical_ssh_url(ssh_url: str, expected_host: str, expected_port: int) -> tuple[str, str]:
    """校验 Gitea SSH URL 的 endpoint 和 owner/name。"""
    if ssh_url.startswith("ssh://"):
        parsed = urlsplit(ssh_url)
        host, port, path = parsed.hostname, parsed.port or 22, parsed.path
    else:
        user_host, separator, path = ssh_url.partition(":")
        host = user_host.rsplit("@", 1)[-1] if separator else ""
        port = 22
        path = f"/{path}"
    parts = [part for part in path.strip("/").split("/") if part]
    if host != expected_host or port != expected_port or len(parts) != 2:
        raise ValueError("Gitea SSH URL does not match configured endpoint")
    return parts[0], parts[1].removesuffix(".git")
