"""真实 Gitea deploy key、fetch、worktree、push 与撤权链路。"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test.support.gitea_bootstrap import bootstrap_gitea_repository
from yuxi.git.executor import GitExecutionError, GitExecutor
from yuxi.git.gitea import GiteaProvider


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件只访问隔离 Gitea，不依赖 Yuxi API Schema。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """本文件没有知识库资源需要清理。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """本文件没有 Sandbox 资源需要清理。"""
    yield


@pytest.mark.integration
async def test_gitea_deploy_key_fetch_push_and_revoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """通过真实 HTTP/SSH 协议验证可信 Git 主链路。"""
    host_origin = os.getenv("YUXI_TEST_GITEA_ORIGIN", "http://127.0.0.1:3300").rstrip("/")
    try:
        response = httpx.get(f"{host_origin}/api/healthz", timeout=2)
        response.raise_for_status()
    except (httpx.HTTPError, OSError):
        pytest.skip("git-integration Gitea profile is not running")

    data = bootstrap_gitea_repository()
    monkeypatch.setenv("YUXI_GIT_ALLOWED_GITEA_ORIGINS", host_origin)
    provider = GiteaProvider(
        api_origin=host_origin,
        api_token=data["api_token"],
        ssh_host="gitea",
        ssh_port=2222,
    )
    await provider.verify_connection()
    metadata = await provider.get_repository(data["username"], data["repository"])
    private_key, public_key = _generate_keypair()
    deploy_key = await provider.create_deploy_key(
        data["username"], data["repository"], title="yuxi-integration", public_key=public_key
    )
    try:
        assert deploy_key.read_only is False
        remote_host = os.getenv("YUXI_TEST_GITEA_KEYSCAN_HOST", "127.0.0.1")
        remote_port = os.getenv("YUXI_TEST_GITEA_KEYSCAN_PORT", os.getenv("YUXI_GITEA_SSH_PORT", "2222"))
        remote_url = metadata.ssh_url.replace("gitea:2222", f"{remote_host}:{remote_port}")
        known_hosts = data["known_hosts"]
        executor = GitExecutor(timeout_seconds=30)
        bare_path = tmp_path / "repository.git"
        worktree_path = tmp_path / "worktree"
        bundle = await executor.fetch_remote_bundle(
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
        )
        try:
            await executor.import_bundle(bundle_path=bundle, bare_path=bare_path)
        finally:
            bundle.unlink(missing_ok=True)
        await executor.ensure_worktree(
            bare_path=bare_path,
            worktree_path=worktree_path,
            branch="codex/task-integration",
            base_branch="main",
        )
        (worktree_path / "integration.txt").write_text("verified\n")
        executor._run(["git", "-C", str(worktree_path), "add", "integration.txt"])
        executor._run(["git", "-C", str(worktree_path), "commit", "-m", "test: verify trusted push"])
        head_sha = (await executor.inspect_worktree(worktree_path)).head_sha

        pushed_sha = await executor.push_commit(
            bare_path=bare_path,
            expected_sha=head_sha,
            branch="codex/task-integration",
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
        )

        assert pushed_sha == head_sha
        async with httpx.AsyncClient(
            base_url=host_origin,
            headers={"Authorization": f"token {data['api_token']}"},
            timeout=20,
        ) as client:
            response = await client.post(
                f"/api/v1/repos/{data['username']}/{data['repository']}/branch_protections",
                json={"rule_name": "codex/*", "enable_push": False},
            )
            response.raise_for_status()
        assert await provider.is_branch_protected(
            data["username"], data["repository"], "codex/task-integration"
        )
    finally:
        await provider.delete_deploy_key(data["username"], data["repository"], deploy_key.id)
    with pytest.raises(GitExecutionError):
        await executor.fetch_remote_bundle(
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
        )


def _generate_keypair() -> tuple[str, str]:
    """生成 integration 专用 Ed25519 keypair。"""
    key = Ed25519PrivateKey.generate()
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public_key = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode()
    return private_key, public_key
