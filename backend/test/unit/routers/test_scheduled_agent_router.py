from __future__ import annotations

import importlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.utils.auth_middleware import get_db, get_required_user

router_module = importlib.import_module("server.routers.scheduled_agent_router")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.scheduled_agents, prefix="/api")

    async def fake_db():
        return object()

    async def fake_user():
        return SimpleNamespace(uid="user-1", role="user")

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_required_user] = fake_user
    return TestClient(app)


def test_scheduled_task_api_uses_proposal_paths_and_forbids_unknown_fields(monkeypatch):
    async def fake_create_scheduled_job(*, data, **_kwargs):
        return data

    monkeypatch.setattr(router_module, "create_scheduled_job", fake_create_scheduled_job)
    response = _client().post(
        "/api/scheduled-tasks",
        json={
            "request_id": "create-request-1",
            "name": "Daily",
            "project_id": "project-1",
            "agent_slug": "chatbot",
            "prompt": "hello",
            "cron_expression": "0 9 * * *",
            "timezone": "Asia/Shanghai",
            "model_spec": "provider:model",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == "project-1"
    assert response.json()["tool_approval_mode"] == "default"
    assert _client().get("/api/scheduled-agents").status_code == 404

    invalid = _client().post(
        "/api/scheduled-tasks",
        json={
            "request_id": "create-request-2",
            "name": "Daily",
            "project_id": "project-1",
            "agent_slug": "chatbot",
            "prompt": "hello",
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
            "unknown": True,
        },
    )
    assert invalid.status_code == 422


def test_run_now_and_delete_keep_owner_scope(monkeypatch):
    calls = []

    async def fake_run_now(*, job_id, request_id, user, **_kwargs):
        calls.append(("run-now", job_id, request_id, user.uid))
        return {"id": "execution-1", "thread_id": "thread-1"}

    async def fake_delete(*, job_id, user, **_kwargs):
        calls.append(("delete", job_id, user.uid))
        return True

    monkeypatch.setattr(router_module, "run_scheduled_job_now", fake_run_now)
    monkeypatch.setattr(router_module, "delete_scheduled_job", fake_delete)
    client = _client()

    assert (
        client.post(
            "/api/scheduled-tasks/job-1/run-now",
            json={"request_id": "manual-request-1"},
        ).json()["thread_id"]
        == "thread-1"
    )
    assert client.delete("/api/scheduled-tasks/job-1").json()["deleted"] is True
    assert calls == [
        ("run-now", "job-1", "manual-request-1", "user-1"),
        ("delete", "job-1", "user-1"),
    ]


def test_update_rejects_explicit_null_enabled(monkeypatch):
    async def forbidden_update(**_kwargs):
        raise AssertionError("无效 enabled 不应进入 service")

    monkeypatch.setattr(router_module, "update_scheduled_job", forbidden_update)

    response = _client().patch("/api/scheduled-tasks/job-1", json={"enabled": None})

    assert response.status_code == 422
