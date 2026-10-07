"""P09真实HTTP场景与最终持久事实，不以请求成功替代结果。"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yuxi.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_reply_disposition_actual_confirmation_real_http(test_client):
    """回复→真实修订处置→结果依据→更正→归档→恢复全链，保留各自Owner。"""
    marker = uuid.uuid4().hex[:12]
    uid, pid = f"p09-test-{marker}", f"p09-project-{marker}"
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with engine.begin() as conn:
        dep = await conn.scalar(text("INSERT INTO departments(name) VALUES (:uid) RETURNING id"), {"uid": uid})
        users = []
        for suffix in ("", "-other"):
            users.append(
                await conn.scalar(
                    text(
                        "INSERT INTO users(username,uid,password_hash,role,department_id,"
                        "is_deleted,login_failed_count) "
                        "VALUES (:uid,:uid,'x','user',:dep,0,0) RETURNING id"
                    ),
                    {"uid": uid + suffix, "dep": dep},
                )
            )
        for project in (pid, pid + "-other"):
            await conn.execute(
                text(
                    "INSERT INTO projects(id,uid,name,selection_status,workdir_path,directory_mode) "
                    "VALUES (:pid,:uid,'P09HTTP','selectable',:path,'linked')"
                ),
                {"pid": project, "uid": uid, "path": f"projects/{project}"},
            )
    headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(users[0])})}
    foreign = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(users[1])})}
    root = f"/api/projects/{pid}/governance"
    work = f"/api/projects/{pid}/work"

    async def post(url, payload, expected=200):
        response = await test_client.post(url, headers=headers, json=payload)
        assert response.status_code == expected, response.text
        return response.json()

    try:
        topic = await post(root + "/topics", {"title": "预期核对", "summary": "原正文", "source_channel": "project"})
        path = root + "/topics/" + topic["id"]
        initial = await test_client.get(path + "/followup", headers=headers)
        assert initial.json()["confirmations"] == []
        assert (await test_client.get(path + "/followup", headers=foreign)).status_code == 404
        comment = await post(path + "/comments", {"content": "建议明确范围", "operation_id": "comment"})
        changed = await test_client.put(
            path,
            headers=headers,
            json={
                "title": "预期核对",
                "summary": "修订正文",
                "expected_outcome": "达到目标",
                "verification_conditions": "按记录核对",
                "expected_revision": 1,
                "reason": "采纳范围建议",
            },
        )
        assert changed.json()["revision_number"] == 2
        reply_payload = {"content": "回应范围", "parent_comment_id": comment["id"], "operation_id": "reply"}
        repeated = await asyncio.gather(*(post(path + "/comments", reply_payload) for _ in range(2)))
        assert repeated[0]["id"] == repeated[1]["id"] and repeated[0]["revision_number"] == 2
        disposition = {
            "operation_id": "partial",
            "expected_version": 0,
            "disposition": "partial",
            "explanation": "实际修改范围",
            "reference": {"kind": "revision", "id": topic["id"], "version": 2},
        }
        record = await post(path + "/comments/" + comment["id"] + "/dispositions", disposition)
        assert record["reference_snapshot"]["snapshot"]["summary"] == "修订正文"
        assert (await post(path + "/comments/" + comment["id"] + "/dispositions", disposition))["id"] == record["id"]
        edited = await post(
            path + "/comments/" + comment["id"] + "/dispositions",
            {
                **disposition,
                "operation_id": "adopted",
                "expected_version": 1,
                "disposition": "adopted",
                "explanation": "完整处理",
            },
        )
        assert edited["version"] == 2
        await post(
            path + "/comments/" + comment["id"] + "/dispositions", {**disposition, "operation_id": "conflict"}, 409
        )
        decision = await post(root + "/decisions", {"title": "草案依据", "conclusion": "暂定", "topic_id": None})
        dec_reference = {
            **disposition,
            "operation_id": "decision",
            "expected_version": 2,
            "reference": {"kind": "decision", "id": decision["id"], "version": 1},
        }
        await post(path + "/comments/" + comment["id"] + "/dispositions", dec_reference)
        denied = await post(
            root + "/decisions/" + decision["id"] + "/operations",
            {"action": "delete", "expected_revision": 1, "reason": "删草案"},
            409,
        )
        assert denied["detail"]["code"] == "decision_referenced"
        assert (await test_client.get(root + "/decisions/" + decision["id"], headers=headers)).json()[
            "status"
        ] == "draft"
        for revision in range(1, 33):
            response = await test_client.put(
                root + "/decisions/" + decision["id"],
                headers=headers,
                json={
                    "title": "草案依据",
                    "conclusion": f"新结论{revision}",
                    "rationale": "",
                    "expected_revision": revision,
                    "reason": "追加修订",
                },
            )
            assert response.status_code == 200, response.text
        exact = root + "/decisions/" + decision["id"] + "/revisions/1"
        old = await test_client.get(exact, headers=headers)
        assert old.status_code == 200, old.text
        assert old.json()["number"] == 1 and old.json()["snapshot"]["conclusion"] == "暂定"
        assert (await test_client.get(exact, headers=foreign)).status_code == 404
        assert (await test_client.get(exact.replace(pid, pid + "-other"), headers=headers)).status_code == 404
        latest = (await test_client.get(root + "/decisions/" + decision["id"], headers=headers)).json()
        assert latest["revision_number"] == 33
        assert all(e.get("revision_number") != 1 for e in latest["timeline"])
        configured = await test_client.put(work + "/code", headers=headers, json={"code": "P" + marker.upper()[:10]})
        assert configured.status_code == 200, configured.text
        task = await post(work + "/tasks", {"title": "人工工作", "acceptance_criteria": "有证据"})
        task_path = work + "/tasks/" + task["id"]
        data = await post(
            task_path + "/results",
            {
                "request_id": "result",
                "summary": "人工业务结果",
                "expected_revision": 1,
                "evidence": [{"kind": "url", "value": "https://example.com/result"}],
            },
        )
        result = data["results"][0]
        accepted = await post(
            task_path + "/results/" + result["id"] + "/review",
            {"status": "accepted", "comment": "人工接受", "expected_version": 1, "expected_revision": 1},
        )
        result = accepted["results"][0]
        assert (await test_client.get(path + "/followup", headers=headers)).json()["confirmations"] == []
        feedback_payload = {
            "topic_id": topic["id"],
            "content": "P07结果反馈仍可研讨",
            "discussion_type": "correction",
            "request_id": "feedback",
            "expected_result_version": result["version"],
            "expected_topic_revision": 2,
        }
        feedback_path = task_path + "/results/" + result["id"] + "/topic-feedback"
        feedback = await post(feedback_path, feedback_payload)
        assert (await post(feedback_path, feedback_payload))["comment_id"] == feedback["comment_id"]
        await post(
            path + "/comments",
            {
                "content": "回复反馈",
                "parent_comment_id": feedback["comment_id"],
                "operation_id": "feedback-reply",
            },
        )
        await post(
            path + "/comments/" + feedback["comment_id"] + "/dispositions",
            {
                "operation_id": "feedback-adopt",
                "expected_version": 0,
                "disposition": "adopted",
                "explanation": "将结果作为核对依据",
                "reference": {"kind": "result", "id": result["id"], "version": result["version"]},
            },
        )
        feedback_detail = (await test_client.get(path + "/comments/" + feedback["comment_id"], headers=headers)).json()
        assert feedback_detail["discussion_type"] == "correction" and len(feedback_detail["replies"]) == 1
        feedback_disposition = feedback_detail["dispositions"][0]
        assert feedback_disposition["disposition"] == "adopted" and feedback_disposition["version"] == 1
        assert feedback_disposition["result_id"] == result["id"]
        frozen = feedback_disposition["reference_snapshot"]
        assert frozen["kind"] == "result" and frozen["id"] == result["id"] and frozen["version"] == result["version"]
        assert frozen["snapshot"]["review_status"] == "accepted"
        feedback_timeline = (await test_client.get(path + "/timeline", headers=headers)).json()["items"]
        feedback_event = next(
            e for e in feedback_timeline if e["kind"] == "comment" and e["comment"]["id"] == feedback["comment_id"]
        )
        assert feedback_event["details"]["result_id"] == result["id"]
        assert feedback_event["details"]["result_version"] == result["version"]
        assert (await test_client.get(path + "/followup", headers=headers)).json()["confirmations"] == []
        payload = {
            "operation_id": "actual",
            "expected_version": 0,
            "expected_revision": 2,
            "action": "confirm",
            "explanation": "人工核对现实已达成",
            "reference": {"kind": "result", "id": result["id"], "version": result["version"]},
        }
        actual = await post(path + "/confirmations", payload)
        assert actual["verification_conditions"] == "按记录核对"
        assert actual["reference_snapshot"]["snapshot"]["review_status"] == "accepted"
        assert (await post(path + "/confirmations", payload))["id"] == actual["id"]
        await post(
            path + "/confirmations",
            {
                **payload,
                "operation_id": "stale-result",
                "expected_version": 1,
                "reference": {"kind": "result", "id": result["id"], "version": 1},
            },
            409,
        )
        correction = await post(
            path + "/confirmations",
            {
                **payload,
                "operation_id": "correct",
                "expected_version": 1,
                "action": "correct",
                "explanation": "补充确认适用范围",
            },
        )
        assert correction["version"] == 2
        foreign_topic = await post(
            f"/api/projects/{pid}-other/governance/topics", {"title": "其他项目", "source_channel": "project"}
        )
        bad = await post(
            path + "/comments/" + comment["id"] + "/dispositions",
            {
                **disposition,
                "operation_id": "foreign",
                "expected_version": 3,
                "reference": {"kind": "revision", "id": foreign_topic["id"], "version": 1},
            },
            422,
        )
        assert bad["detail"]["code"] == "invalid_reference"
        for action in ("archive", "restore"):
            await post(path + "/operations", {"action": action})
            if action == "archive":
                rejected = await post(
                    path + "/confirmations", {**payload, "operation_id": "archived", "expected_version": 2}, 409
                )
                assert rejected["detail"]["code"] == "topic_read_only"
        detail = (await test_client.get(path + "/comments/" + comment["id"], headers=headers)).json()
        assert len(detail["replies"]) == 1 and [r["version"] for r in detail["dispositions"]] == [3, 2, 1]
        page = (await test_client.get(path + "/timeline?limit=2", headers=headers)).json()
        sequences = [r["sequence"] for r in page["items"]]
        while page["next_before"]:
            page = (
                await test_client.get(path + f"/timeline?limit=2&before={page['next_before']}", headers=headers)
            ).json()
            sequences.extend(r["sequence"] for r in page["items"])
        assert sequences == sorted(set(sequences), reverse=True)
        current = (await test_client.get(path, headers=headers)).json()
        assert current["admission_status"] == "proposed" and current["progress"] == "open"
        async with engine.connect() as conn:
            assert (
                await conn.scalar(
                    text("SELECT count(*) FROM governance_topic_confirmations WHERE topic_id=:tid"),
                    {"tid": topic["id"]},
                )
                == 2
            )
            assert (
                await conn.scalar(text("SELECT status FROM project_work_tasks WHERE id=:id"), {"id": task["id"]})
                == "todo"
            )
            assert (
                await conn.scalar(
                    text(
                        "SELECT count(*) FROM agent_runs r JOIN conversations c ON c.id=r.conversation_id "
                        "WHERE c.project_id=:pid"
                    ),
                    {"pid": pid},
                )
                == 0
            )
    finally:
        async with engine.begin() as conn:
            # 精确清理本测试创建的引用，避免影响共享用户项目。
            for table in ("governance_topic_dispositions", "governance_topic_confirmations"):
                await conn.execute(
                    text(
                        f"DELETE FROM {table} WHERE topic_id IN "
                        "(SELECT id FROM governance_topics WHERE project_id IN (:pid,:other))"
                    ),
                    {"pid": pid, "other": pid + "-other"},
                )
            await conn.execute(
                text("DELETE FROM project_work_result_topic_feedback WHERE project_id=:pid"), {"pid": pid}
            )
            await conn.execute(text("DELETE FROM project_work_results WHERE project_id=:pid"), {"pid": pid})
            await conn.execute(text("DELETE FROM user_inbox_items WHERE uid=:uid"), {"uid": uid})
            await conn.execute(
                text("DELETE FROM projects WHERE id IN (:pid,:other)"), {"pid": pid, "other": pid + "-other"}
            )
            await conn.execute(text("DELETE FROM users WHERE id IN (:a,:b)"), {"a": users[0], "b": users[1]})
            await conn.execute(text("DELETE FROM departments WHERE id=:id"), {"id": dep})
        await engine.dispose()
