from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture()
async def scheduled_project_directory(test_client, standard_user):
    """为定时任务 API 用例创建并清理真实 linked Project 目录。"""
    headers = standard_user["headers"]
    directory_name = f"pytest-scheduled-{uuid.uuid4().hex[:10]}"
    response = await test_client.post(
        "/api/workspace/directory",
        headers=headers,
        json={"parent_path": "/", "name": directory_name},
    )
    assert response.status_code == 200, response.text
    try:
        yield directory_name
    finally:
        response = await test_client.request(
            "DELETE",
            "/api/workspace/file",
            headers=headers,
            params={"path": directory_name},
        )
        assert response.status_code in {200, 404}, response.text


async def test_scheduled_task_crud_persists_and_enforces_owner_scope(
    test_client,
    admin_headers,
    standard_user,
    scheduled_project_directory,
):
    """真实 HTTP CRUD 持久化配置，并对其他用户隐藏任务。"""
    owner_headers = standard_user["headers"]
    agent_response = await test_client.get("/api/agent/default", headers=owner_headers)
    assert agent_response.status_code == 200, agent_response.text
    agent = agent_response.json()["agent"]
    agent_slug = str(agent.get("slug") or agent["agent_id"])

    project_response = await test_client.post(
        "/api/projects",
        headers=owner_headers,
        json={
            "request_id": f"pytest-scheduled-project-{uuid.uuid4()}",
            "name": "Scheduled API Project",
            "workdir": {"mode": "linked", "path": scheduled_project_directory},
        },
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]

    create_response = await test_client.post(
        "/api/scheduled-tasks",
        headers=owner_headers,
        json={
            "request_id": f"pytest-scheduled-create-{uuid.uuid4()}",
            "name": "Daily review",
            "project_id": project_id,
            "agent_slug": agent_slug,
            "prompt": "Review today's work",
            "cron_expression": "0 9 * * *",
            "timezone": "Asia/Shanghai",
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    job_id = created["id"]
    assert created["tool_approval_mode"] == "default"

    replay_payload = {
        "request_id": f"pytest-scheduled-replay-{uuid.uuid4()}",
        "name": "Replay-safe review",
        "project_id": project_id,
        "agent_slug": agent_slug,
        "prompt": "Review replay safety",
        "cron_expression": "0 10 * * *",
        "timezone": "Asia/Shanghai",
    }
    first_replay = await test_client.post("/api/scheduled-tasks", headers=owner_headers, json=replay_payload)
    second_replay = await test_client.post("/api/scheduled-tasks", headers=owner_headers, json=replay_payload)
    assert first_replay.status_code == 200, first_replay.text
    assert second_replay.status_code == 200, second_replay.text
    assert second_replay.json()["id"] == first_replay.json()["id"]
    conflicting_replay = await test_client.post(
        "/api/scheduled-tasks",
        headers=owner_headers,
        json={**replay_payload, "prompt": "Different intent"},
    )
    assert conflicting_replay.status_code == 409, conflicting_replay.text

    update_response = await test_client.patch(
        f"/api/scheduled-tasks/{job_id}",
        headers=owner_headers,
        json={"name": "Daily review updated", "cron_expression": "30 9 * * *"},
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["name"] == "Daily review updated"
    assert update_response.json()["cron_expression"] == "30 9 * * *"

    owner_list = await test_client.get("/api/scheduled-tasks", headers=owner_headers)
    assert owner_list.status_code == 200, owner_list.text
    persisted = next(job for job in owner_list.json()["jobs"] if job["id"] == job_id)
    assert persisted["name"] == "Daily review updated"
    assert persisted["cron_expression"] == "30 9 * * *"

    other_user_list = await test_client.get("/api/scheduled-tasks", headers=admin_headers)
    assert other_user_list.status_code == 200, other_user_list.text
    assert job_id not in {job["id"] for job in other_user_list.json()["jobs"]}
    assert (
        await test_client.patch(
            f"/api/scheduled-tasks/{job_id}",
            headers=admin_headers,
            json={"name": "Forbidden"},
        )
    ).status_code == 404
    assert (
        await test_client.post(
            f"/api/scheduled-tasks/{job_id}/run-now",
            headers=admin_headers,
            json={"request_id": f"pytest-admin-run-{uuid.uuid4()}"},
        )
    ).status_code == 404
    assert (
        await test_client.delete(
            f"/api/scheduled-tasks/{job_id}",
            headers=admin_headers,
        )
    ).status_code == 404

    run_request_id = f"pytest-owner-run-{uuid.uuid4()}"
    first_run = await test_client.post(
        f"/api/scheduled-tasks/{job_id}/run-now",
        headers=owner_headers,
        json={"request_id": run_request_id},
    )
    second_run = await test_client.post(
        f"/api/scheduled-tasks/{job_id}/run-now",
        headers=owner_headers,
        json={"request_id": run_request_id},
    )
    assert first_run.status_code == 200, first_run.text
    assert second_run.status_code == 200, second_run.text
    assert second_run.json()["id"] == first_run.json()["id"]

    project_delete = await test_client.delete(f"/api/projects/{project_id}", headers=owner_headers)
    assert project_delete.status_code == 200, project_delete.text
    deleted_project_run = await test_client.post(
        f"/api/scheduled-tasks/{job_id}/run-now",
        headers=owner_headers,
        json={"request_id": f"pytest-deleted-project-run-{uuid.uuid4()}"},
    )
    assert deleted_project_run.status_code == 404, deleted_project_run.text

    delete_response = await test_client.delete(
        f"/api/scheduled-tasks/{job_id}",
        headers=owner_headers,
    )
    assert delete_response.status_code == 200, delete_response.text
    assert (
        await test_client.patch(
            f"/api/scheduled-tasks/{job_id}",
            headers=owner_headers,
            json={"name": "Deleted"},
        )
    ).status_code == 404
