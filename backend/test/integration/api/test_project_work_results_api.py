"""人工结果通过真实 HTTP 与 PostgreSQL 闭合验收和完成边界。"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_manual_results_versions_transactions_and_execution_guards(test_client):
    """重复验收、两类活跃执行、旧条件和越权证据均有持久结果证据。"""
    marker = uuid.uuid4().hex[:12]
    uid, project = f"p05-test-{marker}", f"p05-project-{marker}"
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with engine.begin() as db:
        dep = await db.scalar(text("INSERT INTO departments(name) VALUES (:uid) RETURNING id"), {"uid": uid})
        user = await db.scalar(
            text(
                "INSERT INTO "
                """
                users(username,uid,password_hash,role,department_id,is_deleted,login_failed_count)
                VALUES (:uid,:uid,'x','user',:dep,0,0) RETURNING id
                """
            ),
            {"uid": uid, "dep": dep},
        )
        outsider = await db.scalar(
            text(
                "INSERT INTO "
                """
                users(username,uid,password_hash,role,department_id,is_deleted,login_failed_count)
                VALUES (:uid,:uid,'x','user',:dep,0,0) RETURNING id
                """
            ),
            {"uid": uid + "-other", "dep": dep},
        )
        for pid in (project, project + "-other"):
            await db.execute(
                text(
                    "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                    "VALUES (:pid,:uid,'P05','selectable',:path,'managed')"
                ),
                {"pid": pid, "uid": uid, "path": f"projects/{pid}"},
            )
    headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user)})}
    foreign = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(outsider)})}
    root = f"/api/projects/{project}/work"
    try:
        response = await test_client.put(root + "/code", headers=headers, json={"code": "Q" + marker.upper()[:10]})
        assert response.status_code == 200, response.text
        created = await test_client.post(
            root + "/tasks", headers=headers, json={"title": "人工工作", "acceptance_criteria": "# 条件一"}
        )
        assert created.status_code == 200, created.text
        task = created.json()["id"]
        base = root + "/tasks/" + task
        other = (await test_client.post(root + "/tasks", headers=headers, json={"title": "另一工作"})).json()["id"]
        assert (await test_client.patch(base, headers=headers, json={"status": "done"})).status_code == 409
        assert (await test_client.get(base, headers=foreign)).status_code == 404
        async with engine.connect() as db:
            runs_before = await db.scalar(text("SELECT count(*) FROM agent_runs"))
        payload = {
            "request_id": "first",
            "summary": "人工结果",
            "expected_revision": 1,
            "evidence": [{"kind": "url", "value": "https://example.com/result"}],
        }
        responses = await asyncio.gather(
            *(test_client.post(base + "/results", headers=headers, json=payload) for _ in range(2))
        )
        assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
        data = responses[-1].json()
        result = data["results"][0]
        assert len(data["results"]) == 1 and result["criteria_snapshot"] == "# 条件一"
        assert result["evidence"][0]["availability"] == "reference_only"
        assert data["status"] == "todo"
        assert (
            await test_client.post(base + "/results", headers=headers, json={**payload, "summary": "异值重复"})
        ).status_code == 409
        assert (
            await test_client.post(
                base + "/results",
                headers=headers,
                json={
                    **payload,
                    "request_id": "bad-url",
                    "evidence": [{"kind": "url", "value": "javascript:alert(1)"}],
                },
            )
        ).status_code == 422
        assert (
            await test_client.post(
                base + "/results",
                headers=headers,
                json={**payload, "request_id": "bad-file", "evidence": [{"kind": "file", "value": "/../secret"}]},
            )
        ).status_code == 422
        review = {"status": "not_accepted", "comment": "请补证据", "expected_version": 1, "expected_revision": 1}
        response = await test_client.post(base + "/results/" + result["id"] + "/review", headers=headers, json=review)
        assert response.status_code == 200 and response.json()["status"] == "todo"
        assert response.json()["results"][0]["status"] == "not_accepted"
        assert (
            await test_client.post(
                base + "/results/" + result["id"] + "/review", headers=headers, json={**review, "status": "accepted"}
            )
        ).status_code == 409
        result = (
            await test_client.post(base + "/results", headers=headers, json={**payload, "request_id": "second"})
        ).json()["results"][0]
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    project_work_executions(id,task_id,project_id,uid,agent_slug,status,
                    prompt,request_id,thread_id) VALUES (:id,:task,:project,:uid,'qa',
                    'queued','qa',:request,:thread)
                    """
                ),
                {
                    "id": "e-" + marker,
                    "task": task,
                    "project": project,
                    "uid": uid,
                    "request": "req-" + marker,
                    "thread": "thread-" + marker,
                },
            )
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    project_work_executions(id,task_id,project_id,uid,agent_slug,status,
                    prompt,request_id,thread_id) VALUES (:id,:task,:project,:uid,'qa2',
                    'completed','qa',:request,:thread)
                    """
                ),
                {
                    "id": "wrong-" + marker,
                    "task": other,
                    "project": project,
                    "uid": uid,
                    "request": "wrong-req-" + marker,
                    "thread": "wrong-thread-" + marker,
                },
            )
        assert (
            await test_client.post(
                base + "/results",
                headers=headers,
                json={**payload, "request_id": "wrong-source", "source_execution_id": "wrong-" + marker},
            )
        ).status_code == 404
        combo = {**payload, "request_id": "combo-active", "complete": True}
        response = await test_client.post(base + "/results", headers=headers, json=combo)
        assert response.status_code == 409, response.text
        async with engine.connect() as db:
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM project_work_results WHERE task_id=:id AND request_id='combo-active'"),
                    {"id": task},
                )
                == 0
            )
            assert await db.scalar(text("SELECT status FROM project_work_tasks WHERE id=:id"), {"id": task}) == "todo"
        accept = {"status": "accepted", "comment": "按条件核对", "expected_version": 1, "expected_revision": 1}
        response = await test_client.post(base + "/results/" + result["id"] + "/review", headers=headers, json=accept)
        assert response.status_code == 200 and response.json()["status"] == "todo"
        assert (await test_client.patch(base, headers=headers, json={"status": "done"})).status_code == 409
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE project_work_executions SET status='completed' WHERE id=:id"), {"id": "e-" + marker}
            )
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    channel_delegations(id,operation_id,project_id,work_task_id,executor_key,
                    task,request_json,dispatch_state,attempts,result_json,created_at,updated_at)
                    VALUES (:id,:id,:project,:task,'multica','qa','{}','pending',0,'{}',
                    NOW(),NOW())
                    """
                ),
                {"id": "d-" + marker, "project": project, "task": task},
            )
        # 回收事务先改为活跃但尚未提交，完成必须等锁后读取新状态。
        async with engine.connect() as collector:
            transaction = await collector.begin()
            await collector.execute(
                text("UPDATE channel_delegations SET dispatch_state='collecting',remote_status='done' WHERE id=:id"),
                {"id": "d-" + marker},
            )
            completing = asyncio.create_task(
                test_client.post(base + "/results", headers=headers, json={**combo, "request_id": "collect-race"})
            )
            try:
                waiting = False
                for _ in range(100):
                    async with engine.connect() as observer:
                        waiting = bool(
                            await observer.scalar(
                                text(
                                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND "
                                    "query LIKE '%channel_delegations%' AND query LIKE '%FOR UPDATE%')"
                                )
                            )
                        )
                    if waiting:
                        break
                    await asyncio.sleep(0.02)
                assert waiting and not completing.done(), "完成未等待正在回收的委派锁"
            finally:
                await transaction.commit()
                response = await completing
            assert response.status_code == 409, response.text
        async with engine.connect() as db:
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM project_work_results WHERE task_id=:task AND request_id='collect-race'"),
                    {"task": task},
                )
                == 0
            )
        for dispatch, remote, blocked in [
            ("pending", None, True),
            ("dispatched", "in_progress", True),
            ("collecting", "done", True),
            ("dispatched", "done", False),
            ("dispatched", None, True),
            ("failed", None, False),
            ("reclaimed", "in_progress", True),
            ("reclaimed", "done", False),
        ]:
            async with engine.begin() as db:
                await db.execute(
                    text("UPDATE channel_delegations SET dispatch_state=:dispatch,remote_status=:remote WHERE id=:id"),
                    {"id": "d-" + marker, "dispatch": dispatch, "remote": remote},
                )
            response = await test_client.post(
                base + "/results",
                headers=headers,
                json={**combo, "request_id": "matrix-" + dispatch + "-" + str(remote)},
            )
            assert response.status_code == (409 if blocked else 200), response.text
            if not blocked:
                assert response.json()["status"] == "done"
                await test_client.patch(base, headers=headers, json={"status": "todo"})
        # 非终态编码 turn 优先于旧远端投影；实际 turn 结束可完成。
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    coding_sessions(id,uid,project_id,runtime_scope_id,executor,mode,status,
                    workdir_path,policy_json,budget_json,usage_json,created_at,updated_at)
                    VALUES (:id,:uid,:project,'qa','codex','headless','running',:path,
                    '{}','{}','{}',NOW(),NOW())
                    """
                ),
                {"id": "s-" + marker, "uid": uid, "project": project, "path": f"projects/{project}"},
            )
            await db.execute(
                text(
                    "INSERT INTO "
                    """
                    coding_session_turns(id,session_id,seq,request_text,status,usage_json,
                    created_at) VALUES (:id,:session,1,'qa','running','{}',NOW())
                    """
                ),
                {"id": "t-" + marker, "session": "s-" + marker},
            )
            await db.execute(
                text(
                    "UPDATE channel_delegations SET "
                    """
                    executor_key='codex',dispatch_state='dispatched',remote_status='completed',
                    turn_id=:turn WHERE id=:id
                    """
                ),
                {"turn": "t-" + marker, "id": "d-" + marker},
            )
        assert (await test_client.patch(base, headers=headers, json={"status": "done"})).status_code == 409
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE channel_delegations SET dispatch_state='failed' WHERE id=:id"), {"id": "d-" + marker}
            )
        assert (await test_client.patch(base, headers=headers, json={"status": "done"})).status_code == 409
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE coding_session_turns SET status='completed' WHERE id=:id"), {"id": "t-" + marker}
            )
        # 条件变化不能重用已接受旧结果；结果快照与已验收正文保持不变。
        response = await test_client.put(
            base + "/requirements",
            headers=headers,
            json={"description": "新描述", "acceptance_criteria": "# 条件二", "expected_revision": 1},
        )
        assert response.status_code == 200, response.text
        assert not response.json()["acceptance_current"]
        assert (
            await test_client.put(
                base + "/requirements",
                headers=headers,
                json={"acceptance_criteria": "错误覆盖", "expected_revision": 1},
            )
        ).status_code == 409
        assert (await test_client.patch(base, headers=headers, json={"status": "done"})).status_code == 409
        fresh = {"request_id": "current", "summary": "按新条件完成", "expected_revision": 2}
        result = (await test_client.post(base + "/results", headers=headers, json=fresh)).json()["results"][0]
        accept.update(expected_revision=2, complete=True)
        responses = await asyncio.gather(
            *(
                test_client.post(base + "/results/" + result["id"] + "/review", headers=headers, json=accept)
                for _ in range(2)
            )
        )
        assert all(r.status_code == 200 and r.json()["status"] == "done" for r in responses), [
            r.text for r in responses
        ]
        assert (
            await test_client.post(
                base + "/results/" + result["id"] + "/review", headers=headers, json={**accept, "comment": "覆盖"}
            )
        ).status_code == 409
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT count(*) FROM agent_runs")) == runs_before
            assert (
                await db.scalar(
                    text("SELECT criteria_snapshot FROM project_work_results WHERE task_id=:id AND request_id='first'"),
                    {"id": task},
                )
                == "# 条件一"
            )
            notices = await db.scalar(
                text("SELECT occurrences FROM user_inbox_items WHERE source_id=:id AND kind='task_completed'"),
                {"id": task},
            )
            assert len(notices) == 4  # 三次独立完成矩阵 + 当前验收完成；重复请求不追加。
            assert (
                await db.scalar(text("SELECT summary FROM project_work_results WHERE id=:id"), {"id": result["id"]})
                == "按新条件完成"
            )
        response = await test_client.put(
            base + "/requirements",
            headers=headers,
            json={"description": "新描述", "acceptance_criteria": "# 条件三", "expected_revision": 2},
        )
        assert response.json()["status"] == "done" and not response.json()["acceptance_current"]
        other_base = root + "/tasks/" + other
        upload = await test_client.post(
            other_base + "/attachments", headers=headers, files={"file": ("proof.txt", b"manual proof", "text/plain")}
        )
        assert upload.status_code == 200, upload.text
        attachment = upload.json()["id"]
        proof = {
            "request_id": "proof",
            "summary": "附件证据",
            "expected_revision": 1,
            "evidence": [{"kind": "attachment", "value": attachment}],
        }
        assert (
            await test_client.post(
                base + "/results",
                headers=headers,
                json={**proof, "request_id": "foreign-proof", "expected_revision": 3},
            )
        ).status_code == 422
        response = await test_client.post(other_base + "/results", headers=headers, json=proof)
        assert response.status_code == 200, response.text
        proof_result = response.json()["results"][0]
        assert proof_result["evidence"][0]["availability"] == "available"
        response = await test_client.post(
            other_base + "/results/" + proof_result["id"] + "/review",
            headers=headers,
            json={"status": "accepted", "comment": "附件核对", "expected_version": 1, "expected_revision": 1},
        )
        assert response.status_code == 200, response.text
        assert (await test_client.delete(other_base + "/attachments/" + attachment, headers=headers)).status_code == 200
        reread = (await test_client.get(other_base, headers=headers)).json()
        assert reread["results"][0]["evidence"][0]["availability"] == "unavailable"
        assert (await test_client.patch(other_base, headers=headers, json={"status": "done"})).status_code == 422
        legacy_id = (await test_client.post(root + "/tasks", headers=headers, json={"title": "历史工作"})).json()["id"]
        async with engine.begin() as db:
            await db.execute(text("UPDATE project_work_tasks SET status='done' WHERE id=:id"), {"id": legacy_id})
        legacy = (await test_client.get(root + "/tasks/" + legacy_id, headers=headers)).json()
        assert legacy["legacy_completion"] and legacy["status"] == "done" and not legacy["results"]
    finally:
        async with engine.begin() as db:
            await db.execute(text("DELETE FROM project_work_results WHERE project_id=:id"), {"id": project})
            await db.execute(
                text("DELETE FROM projects WHERE id IN (:id,:other)"), {"id": project, "other": project + "-other"}
            )
            await db.execute(text("DELETE FROM user_inbox_items WHERE uid=:uid"), {"uid": uid})
            await db.execute(
                text("DELETE FROM users WHERE uid IN (:uid,:other)"), {"uid": uid, "other": uid + "-other"}
            )
            await db.execute(text("DELETE FROM departments WHERE id=:id"), {"id": dep})
        await engine.dispose()
