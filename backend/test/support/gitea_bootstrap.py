"""为 git-integration profile 创建隔离 Gitea 测试身份与仓库。"""

from __future__ import annotations

import os
import subprocess
import uuid

import httpx


def bootstrap_gitea_repository() -> dict[str, str]:
    """创建一次性测试用户、Token 和非空仓库；仅用于本地 integration。"""
    host_origin = os.getenv("YUXI_TEST_GITEA_ORIGIN", "http://127.0.0.1:3300").rstrip("/")
    keyscan_host = os.getenv("YUXI_TEST_GITEA_KEYSCAN_HOST", "127.0.0.1")
    keyscan_port = os.getenv("YUXI_TEST_GITEA_KEYSCAN_PORT", os.getenv("YUXI_GITEA_SSH_PORT", "2222"))
    suffix = uuid.uuid4().hex[:12]
    username = os.getenv("YUXI_TEST_GITEA_USERNAME", "") or f"yuxi-test-{suffix}"
    password = os.getenv("YUXI_TEST_GITEA_PASSWORD", "") or f"test-only-{uuid.uuid4().hex}"
    configured_token = os.getenv("YUXI_TEST_GITEA_API_TOKEN", "").strip()
    repository = f"repository-{suffix}"
    email = f"{username}@example.invalid"
    if not os.getenv("YUXI_TEST_GITEA_USERNAME"):
        subprocess.run(
            [
                "docker", "compose", "exec", "-T", "gitea", "gitea", "admin", "user", "create",
                "--username", username, "--password", password, "--email", email, "--must-change-password=false",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    auth = None if configured_token else (username, password)
    with httpx.Client(base_url=host_origin, auth=auth, timeout=20) as client:
        if configured_token:
            token = configured_token
        else:
            token_response = client.post(
                f"/api/v1/users/{username}/tokens",
                json={"name": f"test-{suffix}", "scopes": ["all"]},
            )
            token_response.raise_for_status()
            token = token_response.json()["sha1"]
        response = client.post(
            "/api/v1/user/repos",
            headers={"Authorization": f"token {token}"},
            json={"name": repository, "auto_init": True, "default_branch": "main", "private": True},
        )
        response.raise_for_status()
    keyscan = subprocess.run(
        ["ssh-keyscan", "-p", keyscan_port, keyscan_host],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout
    return {
        "api_origin": os.getenv("YUXI_TEST_GITEA_API_ORIGIN", "http://gitea:3000").rstrip("/"),
        "username": username,
        "repository": repository,
        "api_token": token,
        "known_hosts": keyscan,
    }
