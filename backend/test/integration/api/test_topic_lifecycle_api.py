"""议题持续研讨的真实 HTTP 生命周期与归属回读。"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_topic_http_revision_reopen_archive_and_delete(test_client):
    """通过真实路由验证修订、提示、引用拒删及软删除最终事实。"""
    marker = uuid.uuid4().hex[:12]
    uid = f"pytest-topic-{marker}"
    pid = f"pytest-topic-project-{marker}"
    engine = create_async_engine(os.environ["POSTGRES_URL"])
    async with engine.begin() as conn:
        department = await conn.scalar(text("INSERT INTO departments(name) VALUES (:name) RETURNING id"), {"name": uid})
        users = []
        for suffix in ("", "-other"):
            users.append(
                await conn.scalar(
                    text(
                        "INSERT INTO users(username,uid,password_hash,role,department_id,"
                        "login_failed_count,is_deleted) "
                        "VALUES (:uid,:uid,'x','user',:department,0,0) RETURNING id"
                    ),
                    {"uid": uid + suffix, "department": department},
                )
            )
        await conn.execute(
            text(
                "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                "VALUES (:id,:uid,'Pytest topic','selectable',:path,'linked')"
            ),
            {"id": pid, "uid": uid, "path": f"projects/{pid}"},
        )
    headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(users[0])})}"}
    outsider = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(users[1])})}"}
    root = f"/api/projects/{pid}/governance"
    try:
        response = await test_client.post(
            f"{root}/topics",
            headers=headers,
            json={"title": "最初议题", "summary": "最初正文", "source_channel": "project"},
        )
        assert response.status_code == 200, response.text
        tid = response.json()["id"]
        path = f"{root}/topics/{tid}"
        missing_reason = await test_client.post(f"{path}/operations", headers=headers, json={"action": "close"})
        assert missing_reason.status_code == 422
        assert missing_reason.json()["detail"]["code"] == "reason_required"
        blank_reason = await test_client.put(
            path, headers=headers, json={"title": "不应保存", "expected_revision": 1, "reason": " "}
        )
        assert blank_reason.status_code == 422
        assert (await test_client.get(path, headers=headers)).json()["revision_number"] == 1
        assert (await test_client.get(path, headers=outsider)).status_code == 404
        assert (await test_client.get(f"{path}/timeline", headers=outsider)).status_code == 404
        assert (
            await test_client.post(f"{path}/operations", headers=outsider, json={"action": "delete", "reason": "越权"})
        ).status_code == 404
        assert (
            await test_client.post(
                f"{path}/review", headers=headers, json={"approve": False, "review_note": "信息不足"}
            )
        ).status_code == 200
        edited = await test_client.put(
            path,
            headers=headers,
            json={"title": "补充议题", "summary": "补充正文", "expected_revision": 1, "reason": "补充证据"},
        )
        assert edited.status_code == 200 and edited.json()["admission_status"] == "rejected"
        conflict = await test_client.put(
            path, headers=headers, json={"title": "覆盖", "expected_revision": 1, "reason": "过期"}
        )
        assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "revision_conflict"
        assert (
            await test_client.post(
                f"{path}/comments", headers=headers, json={"content": "重新考虑", "discussion_type": "reconsideration"}
            )
        ).status_code == 200
        assert (await test_client.get(path, headers=headers)).json()["progress"] == "open"
        assert (
            await test_client.post(
                f"{path}/operations", headers=headers, json={"action": "resubmit", "reason": "资料已补齐"}
            )
        ).status_code == 200
        assert (await test_client.post(f"{path}/review", headers=headers, json={"approve": True})).status_code == 200
        decided = await test_client.post(
            f"{root}/decisions", headers=headers, json={"topic_id": tid, "title": "正式决策", "conclusion": "原结论"}
        )
        assert decided.status_code == 200, decided.text
        did = decided.json()["id"]
        assert decided.json()["status"] == "draft"
        assert (
            await test_client.post(
                f"{root}/decisions/{did}/operations",
                headers=headers,
                json={"action": "approve", "expected_revision": 1, "reason": "批准依据"},
            )
        ).status_code == 200
        assert (await test_client.get(path, headers=headers)).json()["progress"] == "open"
        assert (
            await test_client.post(f"{path}/operations", headers=headers, json={"action": "decide", "decision_id": did})
        ).status_code == 200
        missing_hint = await test_client.post(
            f"{path}/operations", headers=headers, json={"action": "reopen", "reason": "反馈"}
        )
        assert missing_hint.status_code == 422
        reopened = await test_client.post(
            f"{path}/operations",
            headers=headers,
            json={"action": "reopen", "reason": "实践有问题", "execution_hint": "pause_recommended"},
        )
        assert reopened.status_code == 200 and reopened.json()["execution_hint"] == "pause_recommended"
        board = (await test_client.get(f"{root}/board", headers=headers)).json()
        assert (
            next(d for d in board["governance"]["decisions"] if d["id"] == did)["topic_execution_hint"]
            == "pause_recommended"
        )
        protected = await test_client.post(
            f"{path}/operations", headers=headers, json={"action": "delete", "reason": "不再关注"}
        )
        assert protected.status_code == 409 and protected.json()["detail"]["references"] == ["关联决策"]
        assert "关联决策" in protected.json()["detail"]["message"]
        assert (
            await test_client.post(f"{path}/operations", headers=headers, json={"action": "archive"})
        ).status_code == 200
        assert (await test_client.get(f"{root}/topics", headers=headers)).json() == []
        assert (await test_client.get(f"/api/projects/{pid}/work/topics", headers=headers)).json() == []
        assert (await test_client.get(path, headers=headers)).json()["archived_at"]
        assert (
            await test_client.post(f"{path}/operations", headers=headers, json={"action": "restore"})
        ).status_code == 200
        first = (await test_client.get(f"{path}/timeline?limit=2", headers=headers)).json()
        older = (await test_client.get(f"{path}/timeline?before={first['next_before']}", headers=headers)).json()
        assert all(e["sequence"] < first["next_before"] for e in older["items"])
        assert any(e["revision"] and e["revision"]["summary"] == "最初正文" for e in older["items"])
        empty = (
            await test_client.post(
                f"{root}/topics", headers=headers, json={"title": "误建", "source_channel": "project"}
            )
        ).json()
        assert (
            await test_client.post(
                f"{root}/topics/{empty['id']}/operations", headers=headers, json={"action": "delete", "reason": "误建"}
            )
        ).status_code == 200
        assert (await test_client.get(f"{root}/topics/{empty['id']}", headers=headers)).status_code == 404
        async with engine.connect() as conn:
            assert (
                await conn.execute(
                    text("SELECT title,revision_number,status,progress FROM governance_topics WHERE id=:id"),
                    {"id": tid},
                )
            ).one() == ("补充议题", 2, "canonical", "open")
            assert (
                await conn.execute(
                    text("SELECT conclusion,topic_revision_number FROM governance_decisions WHERE id=:id"), {"id": did}
                )
            ).one() == ("原结论", 2)
            assert (
                await conn.execute(text("SELECT deleted_at FROM governance_topics WHERE id=:id"), {"id": empty["id"]})
            ).scalar() is not None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": pid})
            await conn.execute(text("DELETE FROM users WHERE department_id=:id"), {"id": department})
            await conn.execute(text("DELETE FROM departments WHERE id=:id"), {"id": department})
        await engine.dispose()
