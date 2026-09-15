"""Git 托管商 API 的最小抽象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class UnsupportedGitProviderError(ValueError):
    """请求了尚未支持的 Git 托管商。"""


@dataclass(frozen=True)
class HostedRepository:
    """托管商返回的 canonical 仓库元数据。"""

    id: str
    owner: str
    name: str
    ssh_url: str
    default_branch: str


@dataclass(frozen=True)
class DeployKey:
    """远端 deploy key 的最小投影。"""

    id: str
    title: str
    key: str
    read_only: bool


class GitHostingProvider(Protocol):
    """托管商元数据和 deploy key 操作契约。"""

    async def verify_connection(self) -> None: ...

    async def get_repository(self, owner: str, name: str) -> HostedRepository: ...

    async def list_deploy_keys(self, owner: str, name: str) -> list[DeployKey]: ...

    async def create_deploy_key(self, owner: str, name: str, *, title: str, public_key: str) -> DeployKey: ...

    async def delete_deploy_key(self, owner: str, name: str, key_id: str) -> None: ...

    async def is_branch_protected(self, owner: str, name: str, branch: str) -> bool: ...


def create_git_hosting_provider(*, provider: str, **kwargs) -> GitHostingProvider:
    """只创建已实现的托管商，其他类型集中 fail-closed。"""
    normalized = str(provider or "").strip().lower()
    if normalized == "gitea":
        from yuxi.git.gitea import GiteaProvider

        return GiteaProvider(**kwargs)
    if normalized in {"github", "gitlab"}:
        # TODO: 有真实 consumer 和集成测试时，在此接入 GitHub/GitLab provider。
        raise UnsupportedGitProviderError(f"Git provider '{normalized}' is not implemented")
    raise UnsupportedGitProviderError(f"Unsupported Git provider '{normalized}'")
