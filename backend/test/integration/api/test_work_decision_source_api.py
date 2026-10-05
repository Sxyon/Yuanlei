"""P02 正式工作来源的真实 HTTP、PostgreSQL 回读与并发证据。"""

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
async def work_source_context(test_client):
    """隔离真实项目，保留环境原有用户及数据。"""
    marker = uuid.uuid4().hex[:12]
    uid, pid = f"pytest-work-source-{marker}", f"pytest-work-source-project-{marker}"
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


async def setup_sources(context):
    """建立明确的批准依据和可独立编号的工作项目。"""
    client, root, headers, outsider, engine, pid = context
    work = f"/api/projects/{pid}/work"
    assert (
        await client.put(f"{work}/code", headers=headers, json={"code": "W" + uuid.uuid4().hex[:8].upper()})
    ).status_code == 200
    topic = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "来源议题", "source_channel": "project"})
    ).json()
    other = (
        await client.post(f"{root}/topics", headers=headers, json={"title": "不一致议题", "source_channel": "project"})
    ).json()
    assert (
        await client.put(f"{work}/topics/{topic['id']}/code", headers=headers, json={"code": "SRC"})
    ).status_code == 200
    draft = (
        await client.post(
            f"{root}/decisions",
            headers=headers,
            json={"title": "正式依据", "conclusion": "原批准结论", "topic_id": topic["id"]},
        )
    ).json()
    approved = await client.post(
        f"{root}/decisions/{draft['id']}/operations",
        headers=headers,
        json={"action": "approve", "expected_revision": 1, "reason": "明确批准"},
    )
    assert approved.status_code == 200, approved.text
    return work, topic, other, approved.json()


async def test_work_optional_source_history_and_review(work_source_context):
    """真实来源约束、复核确认、历史读取和旧尝试不被调整覆盖。"""
    client, root, headers, outsider, engine, pid = work_source_context
    work, topic, other, decision = await setup_sources(work_source_context)
    direct = await client.post(f"{work}/tasks", headers=headers, json={"title": "独立工作"})
    assert direct.status_code == 200, direct.text
    assert direct.json()["source_decision_id"] is None and "-GEN-" in direct.json()["number"]
    assert (await client.get(f"{root}/decisions", headers=outsider)).status_code == 404
    assert (
        await client.post(
            f"{work}/tasks", headers=outsider, json={"title": "越权", "source_decision_id": decision["id"]}
        )
    ).status_code == 404
    bad = await client.post(
        f"{work}/tasks",
        headers=headers,
        json={"title": "不一致", "topic_id": other["id"], "source_decision_id": decision["id"]},
    )
    assert bad.status_code == 422 and "一致" in bad.text
    created = await client.post(
        f"{work}/tasks",
        headers=headers,
        json={"title": "按依据执行", "topic_id": topic["id"], "source_decision_id": decision["id"]},
    )
    assert created.status_code == 200, created.text
    task = created.json()
    assert task["source_decision_revision"] == 2
    draft = (
        await client.post(f"{root}/decisions", headers=headers, json={"title": "仅草案", "conclusion": "待核对"})
    ).json()
    assert (
        await client.post(
            f"{work}/tasks", headers=headers, json={"title": "草案不是依据", "source_decision_id": draft["id"]}
        )
    ).status_code == 409
    slug = f"pytest-source-agent-{uuid.uuid4().hex[:12]}"
    async with engine.begin() as conn:
        uid = await conn.scalar(text("SELECT uid FROM projects WHERE id=:pid"), {"pid": pid})
        await conn.execute(
            text(
                "INSERT INTO agents(slug,backend_id,name,pics,config_json,share_config,"
                "is_default,is_subagent,created_by) VALUES (:slug,'ChatbotAgent','Source agent','[]'::jsonb,"
                "'{}'::jsonb,'{}'::jsonb,FALSE,FALSE,:uid)"
            ),
            {"slug": slug, "uid": uid},
        )
        await conn.execute(
            text(
                "INSERT INTO project_agents(id,project_id,agent_slug,config_overrides) "
                "VALUES (:slug,:pid,:slug,'{}'::jsonb)"
            ),
            {"slug": slug, "pid": pid},
        )
    try:
        assignment = await client.post(
            f"{work}/tasks/{task['id']}/executions", headers=headers, json={"agent_slug": slug}
        )
        assert assignment.status_code == 200, assignment.text
        execution = assignment.json()
        assert (
            execution["source_topic_id"],
            execution["source_decision_id"],
            execution["source_decision_revision"],
        ) == (topic["id"], decision["id"], 2)
        async with engine.connect() as conn:
            original = (
                await conn.execute(
                    text(
                        "SELECT prompt, request_id, source_decision_id, source_decision_revision "
                        "FROM project_work_executions WHERE id=:id"
                    ),
                    {"id": execution["id"]},
                )
            ).one()
        payload = {
            "topic_id": None,
            "source_decision_id": None,
            "expected_topic_id": topic["id"],
            "expected_decision_id": decision["id"],
            "expected_decision_revision": 2,
        }
        changed = await client.put(f"{work}/tasks/{task['id']}/source", headers=headers, json=payload)
        assert changed.status_code == 200, changed.text
        assert changed.json()["number"] == task["number"] and changed.json()["source_decision_id"] is None
        assert (await client.put(f"{work}/tasks/{task['id']}/source", headers=headers, json=payload)).status_code == 409
        async with engine.connect() as conn:
            preserved = (
                await conn.execute(
                    text(
                        "SELECT prompt, request_id, source_decision_id, source_decision_revision "
                        "FROM project_work_executions WHERE id=:id"
                    ),
                    {"id": execution["id"]},
                )
            ).one()
            assert preserved == original
        assert (
            await client.post(f"{work}/tasks/{task['id']}/executions/{execution['id']}/cancel", headers=headers)
        ).status_code == 200
        next_attempt = (
            await client.post(f"{work}/tasks/{task['id']}/executions", headers=headers, json={"agent_slug": slug})
        ).json()
        assert next_attempt["source_decision_id"] is None
        await client.post(f"{work}/tasks/{task['id']}/executions/{next_attempt['id']}/cancel", headers=headers)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM project_agents WHERE agent_slug=:slug"), {"slug": slug})
            await conn.execute(text("DELETE FROM agents WHERE slug=:slug"), {"slug": slug})
    source_detail = (await client.get(f"{root}/decisions/{decision['id']}", headers=headers)).json()
    assert "正式工作及其历史执行依据" in source_detail["references"]
    historical_work = await client.post(f"{work}/tasks", headers=headers,
        json={"title": "保留旧依据的工作", "source_decision_id": decision["id"]})
    assert historical_work.status_code == 200, historical_work.text
    # 补充的原依据退出有效集合后，已批准与需复核并存。
    supplement = (
        await client.post(
            f"{root}/decisions",
            headers=headers,
            json={
                "title": "补充",
                "conclusion": "补充条件",
                "relation_type": "supplement",
                "target_decision_id": decision["id"],
            },
        )
    ).json()
    assert (
        await client.post(
            f"{root}/decisions/{supplement['id']}/operations",
            headers=headers,
            json={"action": "approve", "expected_revision": 1, "reason": "补充批准"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{root}/decisions/{decision['id']}/operations",
            headers=headers,
            json={"action": "revoke", "expected_revision": 2, "reason": "依据变化"},
        )
    ).status_code == 200
    historical_detail = (await client.get(f"{work}/tasks/{historical_work.json()['id']}", headers=headers)).json()
    assert historical_detail["source"]["decision"]["status"] == "revoked"
    assert historical_detail["source"]["decision"]["snapshot"]["conclusion"] == "原批准结论"
    assert historical_detail["status"] == "todo"
    history = await client.get(f"{work}/tasks/{task['id']}/executions", headers=headers)
    assert any(item["source_decision_id"] == decision["id"] for item in history.json())
    ref_work = await client.post(
        f"{work}/tasks", headers=headers, json={"title": "补充工作", "source_decision_id": supplement["id"]}
    )
    assert ref_work.status_code == 409 and "复核" in ref_work.text
    reviewed = await client.post(
        f"{work}/tasks",
        headers=headers,
        json={"title": "已核对补充", "source_decision_id": supplement["id"], "review_confirmed": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    detail = (await client.get(f"{work}/tasks/{reviewed.json()['id']}", headers=headers)).json()
    assert detail["source"]["decision"]["requires_review"] is True
    assert detail["source"]["decision"]["status"] == "approved"
    assert detail["source"]["decision"]["snapshot"]["conclusion"] == "补充条件"
    historical = await client.post(
        f"{work}/tasks", headers=headers, json={"title": "不能新选撤销", "source_decision_id": decision["id"]}
    )
    assert historical.status_code == 409
    archive = await client.post(f"{root}/topics/{topic['id']}/operations", headers=headers, json={"action": "archive"})
    assert archive.status_code == 200, archive.text
    archived = await client.post(f"{work}/tasks", headers=headers, json={"title": "归档来源", "topic_id": topic["id"]})
    assert archived.status_code == 404
    assert (
        await client.post(f"{root}/topics/{topic['id']}/operations", headers=headers, json={"action": "restore"})
    ).status_code == 200
    delete = await client.post(
        f"{root}/topics/{topic['id']}/operations", headers=headers, json={"action": "delete", "reason": "测试保护"}
    )
    assert delete.status_code == 409 and "历史执行依据" in delete.text
    async with engine.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM project_work_tasks WHERE project_id=:pid AND source_decision_id IS NULL"),
                {"pid": pid},
            )
            == 2
        )


async def test_work_reference_delete_race_and_cross_project(work_source_context):
    """真实竞争共享议题锁；数据库拒绝跨项目决策和版本引用。"""
    client, root, headers, outsider, engine, pid = work_source_context
    work, topic, other, decision = await setup_sources(work_source_context)
    for _ in range(3):
        new_topic = (
            await client.post(
                f"{root}/topics", headers=headers, json={"title": "竞争来源", "source_channel": "project"}
            )
        ).json()
        assert (
            await client.put(
                f"{work}/topics/{new_topic['id']}/code",
                headers=headers,
                json={"code": "T" + uuid.uuid4().hex[:6].upper()},
            )
        ).status_code == 200
        ref, deleted = await asyncio.gather(
            client.post(f"{work}/tasks", headers=headers, json={"title": "竞争工作", "topic_id": new_topic["id"]}),
            client.post(
                f"{root}/topics/{new_topic['id']}/operations",
                headers=headers,
                json={"action": "delete", "reason": "竞争删除"},
            ),
        )
        assert (ref.status_code, deleted.status_code) in {(200, 409), (404, 200)}, (ref.text, deleted.text)
        async with engine.connect() as conn:
            assert not await conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM project_work_tasks w JOIN governance_topics t "
                    "ON w.topic_id=t.id WHERE t.id=:id AND t.deleted_at IS NOT NULL)"
                ),
                {"id": new_topic["id"]},
            )
    other_pid = f"pytest-other-source-{uuid.uuid4().hex[:12]}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                "SELECT :id,uid,'Other source','selectable',:id,'linked' FROM projects WHERE id=:pid"
            ),
            {"id": other_pid, "pid": pid},
        )
    try:
        other_work = f"/api/projects/{other_pid}/work"
        assert (
            await client.put(f"{other_work}/code", headers=headers, json={"code": "X" + uuid.uuid4().hex[:8].upper()})
        ).status_code == 200
        denied = await client.post(
            f"{other_work}/tasks", headers=headers, json={"title": "跨项目", "source_decision_id": decision["id"]}
        )
        assert denied.status_code == 404
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO project_work_tasks(id,project_id,number,title,status,created_by,"
                        "source_decision_id,source_decision_revision) "
                        "VALUES (:id,:pid,'X-GEN-000001','invalid','todo','pytest',:decision,2)"
                    ),
                    {"id": str(uuid.uuid4()), "pid": other_pid, "decision": decision["id"]},
                )
        async with engine.connect() as conn:
            assert (
                await conn.scalar(
                    text("SELECT count(*) FROM project_work_tasks WHERE project_id=:pid"), {"pid": other_pid}
                )
                == 0
            )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": other_pid})


async def test_topic_number_configuration_locks_project_before_topic(work_source_context):
    """项目被占用时编号配置不先占议题，避免与新建工作反向等待。"""
    client, root, headers, _, engine, pid = work_source_context
    work = f"/api/projects/{pid}/work"
    topic = (await client.post(f"{root}/topics", headers=headers,
                              json={"title": "锁顺序议题", "source_channel": "project"})).json()
    async with engine.connect() as holder:
        await holder.execute(text("SELECT id FROM projects WHERE id=:id FOR UPDATE"), {"id": pid})
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        configuring = asyncio.create_task(client.put(f"{work}/topics/{topic['id']}/code", headers=headers,
                                                     json={"code": "LOCK"}))
        try:
            async with engine.connect() as observer:
                for _ in range(100):
                    waiting = await observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                        "AND :holder = ANY(pg_blocking_pids(pid)) AND query LIKE '%projects%' "
                        "AND query LIKE '%FOR UPDATE%')"
                    ), {"holder": holder_pid})
                    if waiting:
                        break
                    await asyncio.sleep(0.02)
                assert waiting, "编号配置必须进入项目锁等待后再验证议题锁"
                # 旧议题优先路径会在此处因已持有议题行锁失败。
                assert await observer.scalar(text("SELECT id FROM governance_topics WHERE id=:id FOR UPDATE NOWAIT"),
                                             {"id": topic['id']}) == topic['id']
                await observer.rollback()
        finally:
            await holder.commit()
        result = await asyncio.wait_for(configuring, timeout=10)
        assert result.status_code == 200, result.text
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT code FROM project_topic_codes WHERE topic_id=:id"),
                                     {"id": topic['id']}) == "LOCK"
