"""Project Git HTTP 层的敏感输入边界。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routers.git_router as router


@pytest.mark.parametrize(
    "payload",
    [
        {"api_token": "secret-marker-missing-fields"},
        {
            "request_id": "request-1",
            "name": "Gitea",
            "provider": "gitea",
            "api_origin": "https://gitea.example.invalid",
            "ssh_host": "gitea.example.invalid",
            "ssh_port": 22,
            "ssh_known_host_key": "gitea.example.invalid ssh-ed25519 AAAA",
            "api_token": "secret-marker-" + "x" * 5000,
        },
    ],
)
def test_invalid_api_token_request_is_not_reflected(monkeypatch, caplog, payload):
    """write-only Token 在任意请求校验失败时都不进入响应或日志。"""
    marker = payload["api_token"]

    async def create_connection(**kwargs):
        raise AssertionError("非法请求不得进入 service")

    async def current_user():
        return SimpleNamespace(uid="user-1")

    async def database():
        yield SimpleNamespace()

    monkeypatch.setattr(router, "create_git_connection_view", create_connection)
    app = FastAPI()
    app.include_router(router.git, prefix="/api")
    app.dependency_overrides[router.get_required_user] = current_user
    app.dependency_overrides[router.get_db] = database

    response = TestClient(app).post(
        "/api/git/connections",
        json=payload,
    )

    assert response.status_code == 422
    assert marker not in response.text
    assert marker not in caplog.text


def test_invalid_rotated_token_request_is_not_reflected(monkeypatch, caplog):
    """Token 更新的请求校验也使用固定脱敏响应。"""
    marker = "secret-marker-rotate"

    async def rotate(**kwargs):
        raise AssertionError("非法请求不得进入 service")

    async def current_user():
        return SimpleNamespace(uid="user-1")

    async def database():
        yield SimpleNamespace()

    monkeypatch.setattr(router, "rotate_git_connection_credential_view", rotate)
    app = FastAPI()
    app.include_router(router.git, prefix="/api")
    app.dependency_overrides[router.get_required_user] = current_user
    app.dependency_overrides[router.get_db] = database

    response = TestClient(app).put(
        "/api/git/connections/connection-1/credential",
        json={"api_token": marker, "unexpected": True},
    )

    assert response.status_code == 422
    assert marker not in response.text
    assert marker not in caplog.text
