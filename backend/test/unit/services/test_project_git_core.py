"""Project Git 的路径、凭据和 provider 负向边界。"""

import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from yuxi.git.credentials import GitCredentialOwner, GitNotConfiguredError
from yuxi.git.gitea import GiteaProvider
from yuxi.git.hosting import UnsupportedGitProviderError, create_git_hosting_provider
from yuxi.storage.postgres.models_business import GitConnection, ProjectGitRepository
from yuxi.workspace.git_paths import (
    configured_branch_prefix,
    derive_repository_directory,
    derive_task_branch,
    derive_task_key,
    require_commit_sha,
    resolve_project_git_host_paths,
    runtime_git_worktree_path,
)


def test_credential_aad_rejects_cross_user_and_tampering():
    owner = GitCredentialOwner(b"a" * 32)
    encrypted = owner.encrypt(uid="user-a", purpose="gitea_api_token", plaintext="marker-secret")
    model = SimpleNamespace(**encrypted.__dict__, status="active")

    assert owner.decrypt(model) == "marker-secret"
    model.uid = "user-b"
    with pytest.raises(InvalidTag):
        owner.decrypt(model)


def test_missing_credential_key_fails_closed(monkeypatch):
    monkeypatch.delenv("YUXI_GIT_CREDENTIAL_KEY", raising=False)

    with pytest.raises(GitNotConfiguredError):
        GitCredentialOwner()


@pytest.mark.parametrize("provider", ["github", "gitlab", "unknown"])
def test_unimplemented_providers_fail_closed(provider):
    with pytest.raises(UnsupportedGitProviderError):
        create_git_hosting_provider(provider=provider)


def test_directory_and_task_keys_do_not_embed_hostile_input(monkeypatch):
    monkeypatch.setenv("YUXI_GIT_BRANCH_PREFIX", "codex/")
    directory = derive_repository_directory("../中文 API \\ repo", "binding-1")
    task_key = derive_task_key("uid:external", "root/conversation")

    assert "/" not in directory and "\\" not in directory and ".." not in directory
    assert directory.startswith("api-repo-")
    assert len(task_key) == 24
    assert derive_task_branch("uid:external", "root/conversation") == f"codex/task-{task_key}"


@pytest.mark.parametrize("prefix", ["", "codex", "/codex/", "codex//", "codex.lock/", "codex@{/", "../"])
def test_branch_prefix_rejects_invalid_git_refs(monkeypatch, prefix):
    monkeypatch.setenv("YUXI_GIT_BRANCH_PREFIX", prefix)

    with pytest.raises(ValueError):
        configured_branch_prefix()


@pytest.mark.parametrize("value", ["", "abc", "z" * 40, "a" * 39, "a" * 41])
def test_expected_commit_sha_requires_full_hex(value):
    with pytest.raises(ValueError):
        require_commit_sha(value)


def test_git_path_resolution_rejects_agent_created_repos_symlink(monkeypatch, tmp_path):
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    project = tmp_path / "shared" / "user" / "workspace" / "projects" / "project-id"
    project.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "repos").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        resolve_project_git_host_paths(
            "user", "projects/project-id", "repo-safe", create_parents=True
        )


def test_runtime_git_worktree_path_uses_agent_backend_runtime_root():
    assert (
        runtime_git_worktree_path("projects/project-id", "repos/api/worktrees/task-1")
        == "/home/gem/user-data/projects/project-id/repos/api/worktrees/task-1"
    )

    with pytest.raises(ValueError):
        runtime_git_worktree_path("projects/project-id", "../escape")


def test_public_git_models_never_serialize_credentials_or_trust_anchor():
    connection = GitConnection(
        id="connection-1",
        uid="user-1",
        name="Gitea",
        provider="gitea",
        api_origin="https://gitea.example.invalid",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
        ssh_known_host_key="marker-known-host",
        api_token_credential_id="marker-token-id",
        idempotency_key="request-1",
    )
    repository = ProjectGitRepository(
        id="repository-1",
        project_id="project-1",
        uid="user-1",
        connection_id="connection-1",
        alias="api",
        directory_name="api-safe",
        repository_owner="owner",
        repository_name="repo",
        canonical_ssh_url="marker-remote-url",
        deploy_public_key="marker-public-key",
        deploy_public_key_fingerprint="marker-fingerprint",
        deploy_private_credential_id="marker-private-id",
        idempotency_key="request-2",
    )

    serialized = json.dumps([connection.to_dict(), repository.to_dict()])

    assert "marker-known-host" not in serialized
    assert "marker-token-id" not in serialized
    assert "marker-remote-url" not in serialized
    assert "marker-public-key" not in serialized
    assert "marker-private-id" not in serialized


@pytest.mark.asyncio
async def test_gitea_branch_protection_matches_glob_rules(monkeypatch):
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "https://gitea.example.invalid")
    provider = GiteaProvider(
        api_origin="https://gitea.example.invalid",
        api_token="test-only",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
    )

    async def request(method, path, **kwargs):
        assert method == "GET"
        assert path.endswith("/branch_protections")
        assert not kwargs
        return [{"rule_name": "main"}, {"rule_name": "codex/*"}]

    monkeypatch.setattr(provider, "_request", request)

    assert await provider.is_branch_protected("owner", "repo", "codex/task-123") is True
    assert await provider.is_branch_protected("owner", "repo", "feature/task-123") is False


@pytest.mark.asyncio
async def test_gitea_branch_protection_fails_closed_for_unnamed_rule(monkeypatch):
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "https://gitea.example.invalid")
    provider = GiteaProvider(
        api_origin="https://gitea.example.invalid",
        api_token="test-only",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
    )

    async def request(*args, **kwargs):
        return [{}]

    monkeypatch.setattr(provider, "_request", request)

    with pytest.raises(ValueError, match="no name"):
        await provider.is_branch_protected("owner", "repo", "codex/task-123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule", "branch"),
    [("Codex/Task-123", "codex/task-123"), ("{codex,release}/*", "feature/task-123")],
)
async def test_gitea_branch_protection_plain_casefold_and_extended_glob_fail_closed(monkeypatch, rule, branch):
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "https://gitea.example.invalid")
    provider = GiteaProvider(
        api_origin="https://gitea.example.invalid",
        api_token="test-only",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
    )

    async def request(*args, **kwargs):
        return [{"rule_name": rule}]

    monkeypatch.setattr(provider, "_request", request)

    assert await provider.is_branch_protected("owner", "repo", branch) is True


@pytest.mark.asyncio
async def test_gitea_deploy_keys_reads_every_page(monkeypatch):
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", "https://gitea.example.invalid")
    provider = GiteaProvider(
        api_origin="https://gitea.example.invalid",
        api_token="test-only",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
    )
    calls = []

    async def request(method, path, **kwargs):
        calls.append(kwargs["params"]["page"])
        page = kwargs["params"]["page"]
        items = [
            {"id": index, "title": f"key-{index}", "key": f"public-{index}", "read_only": False}
            for index in range(1, 51)
        ]
        if page == 2:
            items = [{"id": 51, "title": "target", "key": "public-51", "read_only": False}]
        return httpx.Response(
            200,
            json=items,
            headers={"X-Total-Count": "51"},
            request=httpx.Request(method, f"https://gitea.example.invalid{path}"),
        )

    monkeypatch.setattr(provider, "_raw_request", request)

    keys = await provider.list_deploy_keys("owner", "repo")

    assert calls == [1, 2]
    assert len(keys) == 51
    assert keys[-1].title == "target"
