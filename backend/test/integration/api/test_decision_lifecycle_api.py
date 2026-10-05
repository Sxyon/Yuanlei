"""P01 决策生命周期的真实 HTTP、PostgreSQL 回读与并发证据。"""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def decision_context(test_client):
    """隔离真实项目，保留环境原有用户及数据。"""
    marker = uuid.uuid4().hex[:12]
    uid, pid = f"pytest-decision-{marker}", f"pytest-decision-project-{marker}"
    engine = create_async_engine(os.environ["POSTGRES_URL"])
    async with engine.begin() as conn:
        department = await conn.scalar(text("INSERT INTO departments(name) VALUES (:name) RETURNING id"), {"name": uid})
        users = []
        for suffix in ("", "-other"):
            users.append(
                await conn.scalar(
                    text(
                        "INSERT INTO "
                        "users(username,uid,password_hash,role,department_id,login_failed_count,is_deleted) "
                        "VALUES (:uid,:uid,'x','user',:department,0,0) RETURNING id"
                    ),
                    {"uid": uid + suffix, "department": department},
                )
            )
        await conn.execute(
            text(
                "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                "VALUES (:id,:uid,'Pytest decision','selectable',:path,'linked')"
            ),
            {"id": pid, "uid": uid, "path": f"projects/{pid}"},
        )
    headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(users[0])})}"}
    outsider = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(users[1])})}"}
    root = f"/api/projects/{pid}/governance"
    try:
        yield test_client, root, headers, outsider, engine, pid
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": pid})
            await conn.execute(text("DELETE FROM users WHERE department_id=:id"), {"id": department})
            await conn.execute(text("DELETE FROM departments WHERE id=:id"), {"id": department})
        await engine.dispose()


async def test_decision_draft_approval_errata_relations_and_history(decision_context):
    """独立读取状态、原文及历史，确认不联动任务与议题进度。"""
    client, root, headers, outsider, engine, pid = decision_context

    async def create(**changes):
        response = await client.post(
            f"{root}/decisions",
            headers=headers,
            json={"title": "基础决策", "conclusion": "先补充证剧", "rationale": "原始依据", **changes},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "draft"
        return response.json()

    async def read(row):
        response = await client.get(f"{root}/decisions/{row['id']}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    async def operate(row, action, revision=None):
        return await client.post(
            f"{root}/decisions/{row['id']}/operations",
            headers=headers,
            json={"action": action, "expected_revision": revision or row["revision_number"], "reason": "明确操作原因"},
        )

    topic = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "未纳入来源", "source_channel": "project"})
    ).json()
    other_topic = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "另一来源", "source_channel": "project"})
    ).json()
    base = await create(topic_id=topic["id"])
    assert (await client.get(f"{root}/decisions/{base['id']}", headers=outsider)).status_code == 404
    assert (
        await client.post(
            f"{root}/decisions/{base['id']}/operations",
            headers=outsider,
            json={"action": "delete", "expected_revision": 1, "reason": "越权"},
        )
    ).status_code == 404
    # 原有隐式批准字段被拒绝，不能绕过显式批准。
    assert (
        await client.post(
            f"{root}/decisions", headers=headers, json={"title": "绕过", "conclusion": "不应批准", "decided": True}
        )
    ).status_code == 422
    update = {
        "title": "基础决策修订",
        "conclusion": "先补充证剧",
        "rationale": "草案理由",
        "topic_id": topic["id"],
        "expected_revision": 1,
        "reason": "补充说明",
    }
    edited = await client.put(f"{root}/decisions/{base['id']}", headers=headers, json=update)
    assert edited.status_code == 200, edited.text
    base = edited.json()
    stale = await client.put(f"{root}/decisions/{base['id']}", headers=headers, json={**update, "conclusion": "覆盖"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "revision_conflict"
    assert (await read(base))["conclusion"] == "先补充证剧"
    # 未纳入只是提示，批准可以发生；批准不改变议题进度。
    approved = await operate(base, "approve")
    assert approved.status_code == 200, approved.text
    base = approved.json()
    assert base["status"] == "approved" and base["revision_number"] == 3
    assert (await client.get(f"{root}/topics/{topic['id']}", headers=headers)).json()["progress"] == "open"
    before_retry = await read(base)
    assert (await operate(base, "approve", revision=2)).status_code == 200
    assert (await read(base))["timeline"] == before_retry["timeline"]
    assert (
        await client.put(
            f"{root}/decisions/{base['id']}",
            headers=headers,
            json={**update, "expected_revision": 3, "conclusion": "覆盖批准原文"},
        )
    ).status_code == 409
    assert (await operate(base, "delete")).status_code == 409
    erratum = {
        "field": "conclusion",
        "original_text": "证剧",
        "corrected_text": "证据",
        "reason": "文字勘误",
        "meaning_unchanged": True,
        "expected_revision": 3,
    }
    assert (
        await client.post(
            f"{root}/decisions/{base['id']}/errata", headers=headers, json={**erratum, "meaning_unchanged": False}
        )
    ).status_code == 422
    assert (
        await client.post(f"{root}/decisions/{base['id']}/errata", headers=headers, json=erratum)
    ).status_code == 200
    annotated = await read(base)
    assert annotated["conclusion"] == "先补充证剧" and annotated["errata"][0]["corrected_text"] == "证据"
    supplement = await create(
        title="跨议题补充", topic_id=other_topic["id"], relation_type="supplement", target_decision_id=base["id"]
    )
    assert (await operate(supplement, "approve")).status_code == 200
    assert (await read(base))["status"] == "approved"
    replacement = await create(title="整条替代", relation_type="replacement", target_decision_id=base["id"])
    replacement = (await operate(replacement, "approve")).json()
    assert replacement["status"] == "approved"
    assert (await read(base))["status"] == "superseded"
    assert (await read(supplement))["requires_review"] is True
    assert (await read(replacement))["target"]["id"] == base["id"]
    assert {d["id"] for d in (await read(base))["related_decisions"]} == {supplement["id"], replacement["id"]}
    assert (await operate(replacement, "revoke")).status_code == 200
    assert (await read(base))["status"] == "superseded"  # 撤销新决策不复活旧决策。
    assert (await operate(supplement, "revoke")).status_code == 409  # 当前版本仍是草案版本，须重新读取。
    supplement = await read(supplement)
    assert (await operate(supplement, "revoke")).status_code == 200
    first = (await client.get(f"{root}/decisions/{base['id']}?limit=2", headers=headers)).json()
    older = (await client.get(f"{root}/decisions/{base['id']}?before={first['next_before']}", headers=headers)).json()
    assert all(e["sequence"] < first["next_before"] for e in older["timeline"])
    assert any(e["snapshot"]["title"] == "基础决策" for e in older["timeline"])
    topic_events = (await client.get(f"{root}/topics/{topic['id']}/timeline", headers=headers)).json()["items"]
    assert {"decision_created", "decision_revised", "decision_approved", "decision_erratum", "decision_superseded"} <= {
        e["kind"] for e in topic_events
    }
    draft = await create(title="无引用误建")
    assert (await operate(draft, "delete")).status_code == 200
    assert (await client.get(f"{root}/decisions/{draft['id']}", headers=headers)).status_code == 404
    referenced = await create(title="受引用保护")
    task_response = await client.post(
        f"{root}/tasks", headers=headers, json={"title": "保持待审核", "decision_id": referenced["id"]}
    )
    assert task_response.status_code == 200, task_response.text
    refused = await operate(referenced, "delete")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "decision_referenced"
    # 归档只阻止新建/批准；历史原文和撤销保留可用。
    blocked = await create(topic_id=topic["id"])
    assert (
        await client.post(f"{root}/topics/{topic['id']}/operations", headers=headers, json={"action": "archive"})
    ).status_code == 200
    assert (await operate(blocked, "approve")).status_code == 409
    assert (await read(base))["status"] == "superseded"
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("SELECT conclusion,status,revision_number FROM governance_decisions WHERE id=:id"),
                {"id": base["id"]},
            )
        ).one() == ("先补充证剧", "superseded", 3)
        assert (
            await conn.execute(text("SELECT deleted_at FROM governance_decisions WHERE id=:id"), {"id": draft["id"]})
        ).scalar() is not None
        assert (
            await conn.execute(text("SELECT status FROM governance_tasks WHERE project_id=:id"), {"id": pid})
        ).scalar() == "proposed"


async def test_decision_concurrent_edit_and_replacement_approval(decision_context):
    """两个真实请求并发，只有一个修订和一个整体替代获胜。"""
    client, root, headers, _, engine, _ = decision_context
    base = (
        await client.post(f"{root}/decisions", headers=headers, json={"title": "初稿", "conclusion": "初始"})
    ).json()
    edits = await asyncio.gather(
        *[
            client.put(
                f"{root}/decisions/{base['id']}",
                headers=headers,
                json={"title": title, "conclusion": title, "expected_revision": 1, "reason": "修改"},
            )
            for title in ("甲", "乙")
        ]
    )
    assert sorted(r.status_code for r in edits) == [200, 409]
    assert next(r for r in edits if r.status_code == 409).json()["detail"]["code"] == "revision_conflict"
    assert (
        await client.post(
            f"{root}/decisions/{base['id']}/operations",
            headers=headers,
            json={"action": "approve", "expected_revision": 2, "reason": "批准"},
        )
    ).status_code == 200
    drafts = [
        (
            await client.post(
                f"{root}/decisions",
                headers=headers,
                json={
                    "title": title,
                    "conclusion": title,
                    "relation_type": "replacement",
                    "target_decision_id": base["id"],
                },
            )
        ).json()
        for title in ("替代甲", "替代乙")
    ]
    outcomes = await asyncio.gather(
        *[
            client.post(
                f"{root}/decisions/{draft['id']}/operations",
                headers=headers,
                json={"action": "approve", "expected_revision": 1, "reason": "替代"},
            )
            for draft in drafts
        ]
    )
    assert sorted(r.status_code for r in outcomes) == [200, 409]
    assert next(r for r in outcomes if r.status_code == 409).json()["detail"]["code"] == "target_not_approved"
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("SELECT count(*) FROM governance_decisions WHERE target_decision_id=:id AND status='approved'"),
                {"id": base["id"]},
            )
        ).scalar() == 1
        assert (
            await conn.execute(
                text("SELECT count(*) FROM governance_decision_events WHERE decision_id=:id AND kind='superseded'"),
                {"id": base["id"]},
            )
        ).scalar() == 1


async def test_decision_save_approve_reference_delete_races_and_invalid_targets(decision_context):
    """竞争失败必须对应版本或真实引用；跨项目和撤销依据不能批准。"""
    client, root, headers, _, engine, pid = decision_context
    draft = (
        await client.post(f"{root}/decisions", headers=headers, json={"title": "竞争草案", "conclusion": "初稿"})
    ).json()
    outcomes = await asyncio.gather(
        client.put(
            f"{root}/decisions/{draft['id']}",
            headers=headers,
            json={"title": "新稿", "conclusion": "新稿", "expected_revision": 1, "reason": "修订"},
        ),
        client.post(
            f"{root}/decisions/{draft['id']}/operations",
            headers=headers,
            json={"action": "approve", "expected_revision": 1, "reason": "批准"},
        ),
    )
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    assert (
        next(response for response in outcomes if response.status_code == 409).json()["detail"]["code"]
        == "revision_conflict"
    )
    current = (await client.get(f"{root}/decisions/{draft['id']}", headers=headers)).json()
    if current["status"] == "draft":
        assert (
            await client.post(
                f"{root}/decisions/{draft['id']}/operations",
                headers=headers,
                json={"action": "approve", "expected_revision": current["revision_number"], "reason": "批准新稿"},
            )
        ).status_code == 200
    current = (await client.get(f"{root}/decisions/{draft['id']}", headers=headers)).json()
    pending = (
        await client.post(
            f"{root}/decisions",
            headers=headers,
            json={
                "title": "待批准补充",
                "conclusion": "补充",
                "relation_type": "supplement",
                "target_decision_id": draft["id"],
            },
        )
    ).json()
    assert (
        await client.post(
            f"{root}/decisions/{draft['id']}/operations",
            headers=headers,
            json={"action": "revoke", "expected_revision": current["revision_number"], "reason": "依据失效"},
        )
    ).status_code == 200
    invalid = await client.post(
        f"{root}/decisions/{pending['id']}/operations",
        headers=headers,
        json={"action": "approve", "expected_revision": 1, "reason": "不应批准"},
    )
    assert invalid.status_code == 409 and invalid.json()["detail"]["code"] == "target_not_approved"
    other_pid = f"{pid}-other"
    async with engine.begin() as conn:
        uid = await conn.scalar(text("SELECT uid FROM projects WHERE id=:id"), {"id": pid})
        await conn.execute(
            text(
                "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                "VALUES (:id,:uid,'Other','selectable',:path,'linked')"
            ),
            {"id": other_pid, "uid": uid, "path": f"projects/{other_pid}"},
        )
    try:
        other_root = f"/api/projects/{other_pid}/governance"
        target = (
            await client.post(
                f"{other_root}/decisions", headers=headers, json={"title": "跨项目", "conclusion": "原依据"}
            )
        ).json()
        assert (
            await client.post(
                f"{other_root}/decisions/{target['id']}/operations",
                headers=headers,
                json={"action": "approve", "expected_revision": 1, "reason": "批准"},
            )
        ).status_code == 200
        denied = await client.post(
            f"{root}/decisions",
            headers=headers,
            json={
                "title": "非法跨项目关系",
                "conclusion": "补充",
                "relation_type": "supplement",
                "target_decision_id": target["id"],
            },
        )
        assert denied.status_code == 404
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": other_pid})
    referenced = (
        await client.post(f"{root}/decisions", headers=headers, json={"title": "引用删除竞争", "conclusion": "草案"})
    ).json()
    deletion, reference = await asyncio.gather(
        client.post(
            f"{root}/decisions/{referenced['id']}/operations",
            headers=headers,
            json={"action": "delete", "expected_revision": 1, "reason": "删除"},
        ),
        client.post(f"{root}/tasks", headers=headers, json={"title": "竞争引用", "decision_id": referenced["id"]}),
    )
    assert (deletion.status_code, reference.status_code) in ((200, 404), (409, 200))
    async with engine.connect() as conn:
        deleted = await conn.scalar(
            text("SELECT deleted_at FROM governance_decisions WHERE id=:id"), {"id": referenced["id"]}
        )
        count = await conn.scalar(
            text("SELECT count(*) FROM governance_tasks WHERE decision_id=:id"), {"id": referenced["id"]}
        )
        assert (deleted is not None, count) in ((True, 0), (False, 1))
