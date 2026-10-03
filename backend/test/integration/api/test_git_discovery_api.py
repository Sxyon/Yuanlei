"""仓库候选 API 使用真实用户归属查询，远端协议独立替换。"""

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from test.integration.api import test_project_settings_api as settings_fixtures
from server.routers.git_router import git
from server.utils.auth_middleware import get_required_user
from yuxi.services import git_discovery_service as service
from yuxi.storage.postgres.models_business import GitCredential, GitConnection, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
settings_api = settings_fixtures.settings_api
ensure_live_api_schema = settings_fixtures.ensure_live_api_schema
cleanup_test_knowledge_resources = settings_fixtures.cleanup_test_knowledge_resources
cleanup_test_sandboxes = settings_fixtures.cleanup_test_sandboxes


@pytest_asyncio.fixture
async def discovery_api(settings_api, monkeypatch):
    """复用隔离 PostgreSQL 与真实 HTTP 路由，不触及开发用户连接。"""
    client, sessions, _, app, user, _ = settings_api
    app.include_router(git, prefix="/api")
    async with sessions() as db:
        db.add(
            GitCredential(
                id="secret", uid=user.uid, purpose="gitea_api_token", ciphertext=b"dummy", nonce=b"dummy", key_version=1
            )
        )
        await db.flush()
        db.add(
            GitConnection(
                id="connection",
                uid=user.uid,
                name="test",
                provider="gitea",
                api_origin="http://test.invalid",
                ssh_host="test.invalid",
                ssh_port=22,
                ssh_known_host_key="dummy",
                api_token_credential_id="secret",
                idempotency_key="connection",
            )
        )
        await db.commit()
    provider = AsyncMock()
    provider.list_repositories.return_value = [
        {"id": "7", "owner": "team", "name": "repo", "default_branch": "main", "description": ""}
    ]
    provider.list_branches.return_value = [{"name": "main", "head_sha": "a" * 40}]
    monkeypatch.setattr(service.GitCredentialOwner, "decrypt", lambda self, value: "test-secret")
    monkeypatch.setattr(service, "create_git_hosting_provider", lambda **kwargs: provider)
    yield client, app, provider, sessions, user


async def test_discovery_returns_remote_repository_and_branch_metadata(discovery_api):
    """候选值来自远端回读，响应不包含连接 Token。"""
    client, _, provider, _, _ = discovery_api
    result = await client.get("/api/git/connections/connection/repositories")
    assert result.status_code == 200
    assert result.json() == provider.list_repositories.return_value
    assert "test-secret" not in result.text
    result = await client.get("/api/git/connections/connection/branches", params={"owner": "team", "name": "repo"})
    assert result.status_code == 200
    assert result.json() == provider.list_branches.return_value
    provider.list_branches.assert_awaited_once_with("team", "repo")


async def test_discovery_denies_other_users_before_remote_calls(discovery_api):
    """猜测别人连接 ID 不能读取其私有仓库目录。"""
    client, app, provider, _, _ = discovery_api
    app.dependency_overrides[get_required_user] = lambda: User(
        uid="outsider", username="outsider", password_hash="test"
    )
    for path in ("repositories", "branches?owner=team&name=repo"):
        result = await client.get(f"/api/git/connections/connection/{path}")
        assert result.status_code == 404
    provider.list_repositories.assert_not_awaited()
    provider.list_branches.assert_not_awaited()


async def test_disabled_connection_is_not_discovered(discovery_api):
    """停用连接不能继续用持久 Token 枚举远端。"""
    client, _, provider, sessions, _ = discovery_api
    async with sessions() as db:
        connection = await db.get(GitConnection, "connection")
        connection.status = "disabled"
        await db.commit()
    result = await client.get("/api/git/connections/connection/repositories")
    assert result.status_code == 404
    provider.list_repositories.assert_not_awaited()


async def test_remote_error_has_safe_actionable_response(discovery_api):
    """远端拒绝时返回可操作错误，不返回凭据或内部异常。"""
    client, _, provider, _, _ = discovery_api
    request = httpx.Request("GET", "http://test.invalid/api/v1/user/repos")
    provider.list_repositories.side_effect = httpx.HTTPStatusError(
        "private failure", request=request, response=httpx.Response(403, request=request)
    )
    result = await client.get("/api/git/connections/connection/repositories")
    assert result.status_code == 502
    assert "读取权限" in result.json()["detail"]
    assert "private failure" not in result.text
