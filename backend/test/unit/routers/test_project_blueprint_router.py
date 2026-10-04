"""项目蓝图路由的 HTTP 契约单元测试。"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.utils.auth_middleware import get_db, get_required_user

router_module = importlib.import_module("server.routers.project_blueprint_router")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.project_blueprints, prefix="/api")

    async def fake_db():
        return object()

    async def fake_user():
        return SimpleNamespace(uid="user-1", role="user")

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_required_user] = fake_user
    return TestClient(app)


def test_blueprint_router_exposes_list_get_and_put(monkeypatch):
    async def fake_list(*, project_id, db, user):
        return {"project_id": project_id, "directory": ".yuanlei/blueprint", "documents": []}

    async def fake_get(*, project_id, name, db, user):
        return {"name": name, "content": "# Vision", "size": 8, "modified_at": 1.0}

    async def fake_put(*, project_id, name, content, db, user):
        return {"name": name, "content": content, "size": len(content), "modified_at": 2.0}

    monkeypatch.setattr(router_module, "list_project_blueprint_view", fake_list)
    monkeypatch.setattr(router_module, "get_project_blueprint_view", fake_get)
    monkeypatch.setattr(router_module, "put_project_blueprint_view", fake_put)
    client = _client()

    listed = client.get("/api/projects/project-1/blueprint")
    assert listed.status_code == 200, listed.text
    assert listed.json()["project_id"] == "project-1"

    read = client.get("/api/projects/project-1/blueprint/product-vision.md")
    assert read.status_code == 200, read.text
    assert read.json()["content"] == "# Vision"

    written = client.put(
        "/api/projects/project-1/blueprint/product-vision.md",
        json={"content": "# Vision\n"},
    )
    assert written.status_code == 200, written.text
    assert written.json()["size"] == len("# Vision\n")


def test_blueprint_router_rejects_unknown_fields(monkeypatch):
    async def fail_put(*, project_id, name, content, db, user):
        raise AssertionError("非法 payload 不应进入 service")

    monkeypatch.setattr(router_module, "put_project_blueprint_view", fail_put)

    forbidden = _client().put(
        "/api/projects/project-1/blueprint/product-vision.md",
        json={"content": "# Vision", "expected_version": 1},
    )
    assert forbidden.status_code == 422


def test_blueprint_router_maps_value_error_to_422_and_missing_to_404(monkeypatch):
    async def raising_value(*, project_id, name, db, user):
        raise ValueError("蓝图文档名不允许空格")

    monkeypatch.setattr(router_module, "get_project_blueprint_view", raising_value)
    invalid = _client().get("/api/projects/project-1/blueprint/bad%20name.md")
    assert invalid.status_code == 422, invalid.text

    async def raising_missing(*, project_id, name, db, user):
        raise HTTPException(status_code=404, detail="蓝图文档不存在")

    monkeypatch.setattr(router_module, "get_project_blueprint_view", raising_missing)
    missing = _client().get("/api/projects/project-1/blueprint/missing.md")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "蓝图文档不存在"
