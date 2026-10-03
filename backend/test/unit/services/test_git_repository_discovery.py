"""Gitea 仓库候选分页与最小元数据投影。"""

from unittest.mock import AsyncMock

import pytest

from yuxi.git.gitea import GiteaProvider


@pytest.mark.asyncio
async def test_repository_discovery_reads_all_pages_and_omits_remote_secrets(monkeypatch):
    """下一页仓库仍可选择，远端附带字段不会泄露到候选 API。"""
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "http://test.invalid")
    provider = GiteaProvider(api_origin="http://test.invalid", api_token="test", ssh_host="test.invalid", ssh_port=22)
    first = [
        {
            "id": index,
            "owner": {"login": "team"},
            "name": f"repo-{index}",
            "default_branch": "main",
            "token": "must-not-return",
        }
        for index in range(50)
    ]
    last = [
        {"id": 50, "owner": {"login": "other"}, "name": "last", "default_branch": "develop", "description": "last repo"}
    ]
    request = AsyncMock(side_effect=[first, last])
    monkeypatch.setattr(provider, "_request", request)
    result = await provider.list_repositories()
    assert len(result) == 51
    assert result[-1] == {
        "id": "50",
        "owner": "other",
        "name": "last",
        "default_branch": "develop",
        "description": "last repo",
    }
    assert all("token" not in value for value in result)
    assert request.await_args_list[1].kwargs["params"] == {"page": 2, "limit": 50}


@pytest.mark.asyncio
async def test_repository_discovery_rejects_invalid_remote_list(monkeypatch):
    """远端错误结构不能伪装成空仓库列表。"""
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "http://test.invalid")
    provider = GiteaProvider(api_origin="http://test.invalid", api_token="test", ssh_host="test.invalid", ssh_port=22)
    monkeypatch.setattr(provider, "_request", AsyncMock(return_value={"message": "denied"}))
    with pytest.raises(ValueError, match="repository list"):
        await provider.list_repositories()
