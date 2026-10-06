"""P03 工作建议纳入的真实 HTTP、PostgreSQL 回读与并发证据。"""

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
async def suggestion_context(test_client):
    """隔离真实项目，保留环境原有用户及数据。"""
    marker = uuid.uuid4().hex[:12]
    uid, pid = f"pytest-suggestion-{marker}", f"pytest-suggestion-project-{marker}"
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


async def suggestion(client, root, headers, **values):
    """通过公开入口记录待处理建议。"""
    response = await client.post(f"{root}/tasks", headers=headers, json={"title": "待处理建议", **values})
    assert response.status_code == 200, response.text
    return response.json()


async def test_admission_concurrency_link_and_database_guards(suggestion_context):
    """同建议并发只创建一次，多建议可关联同工作且不同目标拒绝。"""
    client, root, headers, outsider, engine, pid = suggestion_context
    work = f"/api/projects/{pid}/work"
    item = await suggestion(client, root, headers)
    assert (
        await client.post(f"{root}/tasks/{item['id']}/review", headers=headers, json={"approve": True})
    ).status_code == 409
    missing = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    assert missing.status_code == 409 and "缩写" in missing.text
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text("SELECT status FROM governance_tasks WHERE id=:id"), {"id": item["id"]})
            == "proposed"
        )
        assert await conn.scalar(text("SELECT count(*) FROM project_work_tasks WHERE project_id=:p"), {"p": pid}) == 0
    assert (
        await client.put(f"{work}/code", headers=headers, json={"code": "S" + uuid.uuid4().hex[:8].upper()})
    ).status_code == 200
    answers = await asyncio.gather(
        *[
            client.post(
                f"{root}/tasks/{item['id']}/admit",
                headers=headers,
                json={"mode": "create", "title": "正式工作", "review_note": "确认纳入"},
            )
            for _ in range(4)
        ]
    )
    assert all(r.status_code == 200 for r in answers), [r.text for r in answers]
    ids = {r.json()["work"]["id"] for r in answers}
    assert len(ids) == 1
    work_id = ids.pop()
    detail = (await client.get(f"{work}/tasks/{work_id}", headers=headers)).json()
    second = await suggestion(client, root, headers, title="第二项来源建议")
    linked = await client.post(
        f"{root}/tasks/{second['id']}/admit", headers=headers, json={"mode": "link", "work_task_id": work_id}
    )
    assert linked.status_code == 200, linked.text
    after = (await client.get(f"{work}/tasks/{work_id}", headers=headers)).json()
    assert (after["title"], after["status"], after["number"], after["source_decision_id"]) == (
        detail["title"],
        detail["status"],
        detail["number"],
        detail["source_decision_id"],
    )
    other_work = (await client.post(f"{work}/tasks", headers=headers, json={"title": "其他工作"})).json()
    conflict = await client.post(
        f"{root}/tasks/{second['id']}/admit", headers=headers, json={"mode": "link", "work_task_id": other_work["id"]}
    )
    assert conflict.status_code == 409 and "已纳入" in conflict.text
    assert (
        await client.post(f"{root}/tasks/{item['id']}/admit", headers=outsider, json={"mode": "create"})
    ).status_code == 404
    denied = await suggestion(client, root, headers, title="拒绝建议")
    assert (
        await client.post(
            f"{root}/tasks/{denied['id']}/review", headers=headers, json={"approve": False, "review_note": "无价值"}
        )
    ).status_code == 200
    assert (
        await client.post(f"{root}/tasks/{denied['id']}/admit", headers=headers, json={"mode": "create"})
    ).status_code == 409
    async with engine.begin() as conn:
        assert (
            await conn.scalar(text("SELECT count(*) FROM work_suggestion_admissions WHERE project_id=:p"), {"p": pid})
            == 2
        )
        assert await conn.scalar(text("SELECT count(*) FROM project_work_tasks WHERE project_id=:p"), {"p": pid}) == 2
        assert (
            await conn.scalar(text("SELECT review_note FROM governance_tasks WHERE id=:id"), {"id": item["id"]})
            == "确认纳入"
        )
        # 同用户另一个项目也不能建立跨项目映射。
        other = pid + "-other"
        await conn.execute(
            text(
                "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                "SELECT :id,uid,'Other','selectable',:id,'linked' FROM projects WHERE id=:p"
            ),
            {"id": other, "p": pid},
        )
    try:
        third = await suggestion(client, root, headers, title="不能跨项目")
        remote = await client.put(
            f"/api/projects/{other}/work/code", headers=headers, json={"code": "R" + uuid.uuid4().hex[:8].upper()}
        )
        assert remote.status_code == 200
        target = (
            await client.post(f"/api/projects/{other}/work/tasks", headers=headers, json={"title": "其他项目工作"})
        ).json()
        assert (
            await client.post(
                f"{root}/tasks/{third['id']}/admit",
                headers=headers,
                json={"mode": "link", "work_task_id": target["id"]},
            )
        ).status_code == 404
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO work_suggestion_admissions "
                        "(suggestion_id,project_id,work_task_id,mode,created_by,created_at) "
                        "VALUES (:s,:p,:w,'link','test',NOW())"
                    ),
                    {"s": third["id"], "p": pid, "w": target["id"]},
                )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": other})


async def test_admission_mapping_failure_rolls_back_all_writes(suggestion_context):
    """数据库拒绝映射后，工作、编号与审核都不留下半成品。"""
    client, root, headers, _, engine, pid = suggestion_context
    work = f"/api/projects/{pid}/work"
    await client.put(f"{work}/code", headers=headers, json={"code": "F" + uuid.uuid4().hex[:8].upper()})
    item = await suggestion(client, root, headers)
    name = "pytest_reject_admission_" + uuid.uuid4().hex[:10]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                f"IF NEW.suggestion_id = '{item['id']}' THEN RAISE EXCEPTION 'isolated admission rejection'; "
                "END IF; RETURN NEW; END $$"
            )
        )
        await conn.execute(
            text(
                f"CREATE TRIGGER {name} BEFORE INSERT ON work_suggestion_admissions "
                f"FOR EACH ROW EXECUTE FUNCTION {name}()"
            )
        )
    try:
        failure = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
        assert failure.status_code == 500
        async with engine.connect() as conn:
            assert (
                await conn.scalar(text("SELECT status FROM governance_tasks WHERE id=:id"), {"id": item["id"]})
                == "proposed"
            )
            assert (
                await conn.scalar(text("SELECT count(*) FROM project_work_tasks WHERE project_id=:p"), {"p": pid}) == 0
            )
            assert (
                await conn.scalar(
                    text("SELECT count(*) FROM work_suggestion_admissions WHERE project_id=:p"), {"p": pid}
                )
                == 0
            )
            assert (
                await conn.scalar(text("SELECT next_number FROM project_work_codes WHERE project_id=:p"), {"p": pid})
                == 1
            )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TRIGGER {name} ON work_suggestion_admissions"))
            await conn.execute(text(f"DROP FUNCTION {name}()"))
    recovery = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    assert recovery.status_code == 200 and recovery.json()["work"]["number"].endswith("000001")


async def test_admission_inherits_source_and_legacy_new_execution_rejected(suggestion_context):
    """继承来源复核和编号；旧建议不再新建执行，历史行不被改写。"""
    client, root, headers, _, engine, pid = suggestion_context
    work = f"/api/projects/{pid}/work"
    await client.put(f"{work}/code", headers=headers, json={"code": "D" + uuid.uuid4().hex[:8].upper()})
    topic = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "方向", "source_channel": "project"})
    ).json()
    draft = (
        await client.post(
            f"{root}/decisions",
            headers=headers,
            json={"title": "依据", "conclusion": "具体要求", "topic_id": topic["id"]},
        )
    ).json()
    item = await suggestion(client, root, headers, topic_id=topic["id"], decision_id=draft["id"])
    assert (
        await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    ).status_code == 409
    await client.post(
        f"{root}/decisions/{draft['id']}/operations",
        headers=headers,
        json={"action": "approve", "reason": "批准", "expected_revision": 1},
    )
    missing_code = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    assert missing_code.status_code == 409 and "议题" in missing_code.text
    await client.put(f"{work}/topics/{topic['id']}/code", headers=headers, json={"code": "DIR"})
    created = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    assert created.status_code == 200, created.text
    detail = (await client.get(f"{work}/tasks/{created.json()['work']['id']}", headers=headers)).json()
    assert (
        detail["topic_id"] == topic["id"]
        and detail["source_decision_id"] == draft["id"]
        and detail["source_decision_revision"] == 2
    )
    assert "-DIR-" in detail["number"]
    old_endpoint = await client.post(
        f"{root}/tasks/{item['id']}/delegations", headers=headers, json={"executor_key": "codex"}
    )
    assert old_endpoint.status_code == 409 and "正式工作" in old_endpoint.text
    no_work = await client.post(
        f"/api/projects/{pid}/delegations", headers=headers, json={"executor_key": "multica", "task": "旁路"}
    )
    assert no_work.status_code == 422


async def test_admission_requires_review_and_rejects_archived_source(suggestion_context):
    """纳入复用正式工作的复核与归档约束，拒绝时不留下审核或映射。"""
    client, root, headers, _, engine, pid = suggestion_context
    work = f"/api/projects/{pid}/work"
    await client.put(f"{work}/code", headers=headers, json={"code": "R" + uuid.uuid4().hex[:8].upper()})
    base = (
        await client.post(f"{root}/decisions", headers=headers, json={"title": "原依据", "conclusion": "原方案"})
    ).json()
    await client.post(
        f"{root}/decisions/{base['id']}/operations",
        headers=headers,
        json={"action": "approve", "expected_revision": 1, "reason": "批准"},
    )
    extra = (
        await client.post(
            f"{root}/decisions",
            headers=headers,
            json={
                "title": "补充依据",
                "conclusion": "补充",
                "relation_type": "supplement",
                "target_decision_id": base["id"],
            },
        )
    ).json()
    await client.post(
        f"{root}/decisions/{extra['id']}/operations",
        headers=headers,
        json={"action": "approve", "expected_revision": 1, "reason": "批准补充"},
    )
    await client.post(
        f"{root}/decisions/{base['id']}/operations",
        headers=headers,
        json={"action": "revoke", "expected_revision": 2, "reason": "原依据变化"},
    )
    item = await suggestion(client, root, headers, decision_id=extra["id"])
    rejected = await client.post(f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create"})
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "source_review_required"
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text("SELECT status FROM governance_tasks WHERE id=:id"), {"id": item["id"]})
            == "proposed"
        )
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM work_suggestion_admissions WHERE suggestion_id=:id"), {"id": item["id"]}
            )
            == 0
        )
    accepted = await client.post(
        f"{root}/tasks/{item['id']}/admit", headers=headers, json={"mode": "create", "review_confirmed": True}
    )
    assert accepted.status_code == 200, accepted.text
    detail = (await client.get(f"{work}/tasks/{accepted.json()['work']['id']}", headers=headers)).json()
    assert detail["source"]["decision"]["requires_review"] is True
    topic = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "待归档来源", "source_channel": "project"})
    ).json()
    archived_item = await suggestion(client, root, headers, topic_id=topic["id"])
    archive = await client.post(f"{root}/topics/{topic['id']}/operations", headers=headers, json={"action": "archive"})
    assert archive.status_code == 200, archive.text
    invalid = await client.post(f"{root}/tasks/{archived_item['id']}/admit", headers=headers, json={"mode": "create"})
    assert invalid.status_code == 404, invalid.text
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text("SELECT status FROM governance_tasks WHERE id=:id"), {"id": archived_item["id"]})
            == "proposed"
        )


async def test_legacy_canonical_suggestion_links_without_rewriting_review(suggestion_context):
    """历史已审核建议补充关联保留原审核责任人、时间和说明。"""
    client, root, headers, _, engine, pid = suggestion_context
    work = f"/api/projects/{pid}/work"
    await client.put(f"{work}/code", headers=headers, json={"code": "L" + uuid.uuid4().hex[:8].upper()})
    formal = (await client.post(f"{work}/tasks", headers=headers, json={"title": "既有独立工作"})).json()
    legacy = await suggestion(client, root, headers, title="历史已审核建议")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE governance_tasks SET status='canonical',review_owner_uid=(SELECT uid FROM projects WHERE id=:p), "
                "reviewed_at=NOW(),review_note='历史审定' WHERE id=:id"
            ),
            {"p": pid, "id": legacy["id"]},
        )
        before = (
            await conn.execute(
                text("SELECT review_owner_uid,reviewed_at,review_note FROM governance_tasks WHERE id=:id"),
                {"id": legacy["id"]},
            )
        ).one()
    response = await client.post(
        f"{root}/tasks/{legacy['id']}/admit",
        headers=headers,
        json={"mode": "link", "work_task_id": formal["id"], "review_note": "补充关联"},
    )
    assert response.status_code == 200, response.text
    async with engine.connect() as conn:
        after = (
            await conn.execute(
                text("SELECT review_owner_uid,reviewed_at,review_note FROM governance_tasks WHERE id=:id"),
                {"id": legacy["id"]},
            )
        ).one()
        assert tuple(after) == tuple(before)
        assert (
            await conn.scalar(
                text("SELECT reason FROM work_suggestion_admissions WHERE suggestion_id=:id"), {"id": legacy["id"]}
            )
            == "补充关联"
        )
    detail = (await client.get(f"{work}/tasks/{formal['id']}", headers=headers)).json()
    assert detail["title"] == "既有独立工作" and detail["source_decision_id"] is None
    assert detail["suggestions"][0]["id"] == legacy["id"]
