"""模拟公开Gateway配合真实HTTP/PG，证明C1本地工程链。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager

import httpx
import pytest
from aiohttp import web
from sqlalchemy import select, text

from test.integration.services.test_delegation_service import _scoped_database, _seed_scope
from yuxi.storage.postgres.models_business import (
    APIKey,
    Department,
    User,
    ProjectWorkResult,
    DelegationAttempt,
    ChannelDelegation,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """测试只拥有隔离schema，不使用日常API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """测试不产生知识资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """测试只产生自有Workdir与模拟session。"""
    yield


class GatewayOracle:
    """独立固定文本oracle和可故障注入的公开RPC服务。"""

    def __init__(self, factory):
        self.factory = factory
        self.sessions = {}
        self.dispatch_count = 0
        self.wrong_run = False
        self.not_ready = False
        self.fault = None
        self.lose_acceptance = False
        self.pause_wait = None

    async def websocket(self, request):
        """通过真实WebSocket回执，不patch产品Adapter。"""
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "event", "event": "connect.challenge", "payload": {"nonce": "synthetic"}})
        async for message in socket:
            value = json.loads(message.data)
            payload = await self.rpc(value["method"], value["params"])
            if value["method"] == "agent" and self.lose_acceptance:
                self.lose_acceptance = False
                # 原生接受已发生，但WS不回执也不主动关闭；产品总超时须结束。
                continue
            await socket.send_json({"type": "res", "id": value["id"], "ok": True, "payload": payload})
        return socket

    async def rpc(self, method, params):
        """固定数据证明来源和提交点，模型不参与生成oracle。"""
        if method == "connect":
            return {
                "protocol": 4,
                "server": {"version": "2026.9.8"},
                "auth": {"scopes": ["operator.read", "operator.write"]},
            }
        if method == "agents.list":
            return {"agents": [{"id": "isolated-c"}]}
        if method == "config.get":
            return {
                "config": {
                    "agents": {
                        "entries": {
                            "isolated-c": {
                                "tools": {"deny": ["*"]},
                                "skills": ["unexpected"] if self.fault == "skills" else [],
                                "memory": {"search": {"enabled": False}},
                                "model": {"primary": "test/model", "fallbacks": []},
                            }
                        }
                    }
                }
            }
        if method == "tools.effective":
            return {
                "agentId": "isolated-c",
                "groups": [],
                "toolAccess": {
                    "checked": "live-session" if params.get("sessionKey") else "local-config",
                    "tools": [{"id": "read", "status": "excluded"}],
                },
            }
        if method == "sessions.create":
            # 独立事务回读，session副作用之前intent已经提交。
            async with self.factory() as db:
                attempt = await db.scalar(
                    select(DelegationAttempt).where(
                        DelegationAttempt.remote_binding["session_key"].as_string() == params["key"]
                    )
                )
                assert attempt is not None
            identifier = "session-" + str(len(self.sessions))
            self.sessions[params["key"]] = {"id": identifier, "revision": "lifecycle-1"}
            return {
                "key": params["key"],
                "sessionId": identifier,
                "entry": {"lifecycleRevision": "lifecycle-1"},
                "runStarted": False,
            }
        if method == "agent":
            self.dispatch_count += 1
            async with self.factory() as db:
                attempt = await db.scalar(
                    select(DelegationAttempt).where(
                        DelegationAttempt.remote_binding["run_id"].as_string() == params["idempotencyKey"]
                    )
                )
                assert attempt is not None and attempt.remote_binding["dispatch_started"]
            assert params["deliver"] is False and params["disableMessageTool"] is True and params["timeout"] == 60
            session = self.sessions[params["sessionKey"]]
            assert params["sessionId"] == params["expectedExistingSessionId"] == session["id"]
            assert params["expectedExistingSessionLifecycleRevision"] == session["revision"]
            package = json.loads(params["message"].splitlines()[1])
            supplement_text = "独立加法核算记录"
            output = {
                "protocol": "yuanlei.collaboration/1.0",
                "kind": "return",
                "operation_id": package["operation_id"],
                "attempt_id": package["attempt_id"],
                "outcome": "completed",
                "formal_delivery": {
                    "text": "A=330；B=330；C=300；最低C。",
                    "artifact_refs": [],
                    "unresolved": [],
                    "notices": [{"kind": "observation", "text": "给定数据仅为合成示例", "blocking": False}],
                    "criteria_revision": package["work"]["criteria_revision"],
                    "context_snapshot_id": package["context"]["snapshot_id"],
                },
                "questions": [],
                "supplement": {
                    "revision": 1,
                    "summary": "字" * 201,
                    "assertion_level": "agent-report",
                    "complete": False,
                    "details_ref": {
                        "kind": "inline-text",
                        "text": supplement_text,
                        "size_bytes": len(supplement_text.encode()),
                        "sha256": hashlib.sha256(supplement_text.encode()).hexdigest(),
                    },
                },
                "error": None,
            }
            if self.fault == "blocked":
                output.update(
                    outcome="blocked",
                    formal_delivery=None,
                    questions=[
                        {
                            "client_question_key": "missing-input",
                            "revision": 1,
                            "title": "缺少资料",
                            "missing": "合成数据",
                            "impact": "不能核算",
                            "checked_refs": [package["context"]["snapshot_id"]],
                            "requested_answer": "请补数据",
                        }
                    ],
                )
            session.update(
                run=params["idempotencyKey"], input=params["message"], output=json.dumps(output, ensure_ascii=False)
            )
            return {
                "runId": session["run"],
                "sessionKey": params["sessionKey"],
                "agentId": params["agentId"],
                "status": "accepted",
            }
        if method == "agent.wait":
            if self.pause_wait is not None:
                entered, release = self.pause_wait
                entered.set()
                await release.wait()
            session = next(x for x in self.sessions.values() if x.get("run") == params["runId"])
            return {
                "runId": "other" if self.fault == "wait-run" else session["run"],
                "status": "timeout" if self.not_ready else "ok",
                "terminalReceipt": {
                    "runId": session["run"],
                    "sessionId": "other" if self.fault == "receipt-session" else session["id"],
                    "turnId": None if self.fault == "receipt-turn" else "turn-" + session["id"],
                    "terminalDisposition": "visible",
                    "successfulToolNames": None if self.fault == "receipt-tools" else [],
                    "rerouted": False,
                    "requested": {"provider": "test", "model": "model"},
                    "effective": {"provider": "test", "model": "other" if self.fault == "model" else "model"},
                },
                "terminalReply": {"disposition": "visible", "text": session["output"]},
            }
        if method == "chat.history":
            session = self.sessions[params["sessionKey"]]
            cap = 8000 if self.fault == "history-truncated" else params.get("maxChars", 8000)
            data = session["input"].encode("utf-16-le")
            visible_input = data[: cap * 2].decode("utf-16-le", errors="ignore")
            if len(data) // 2 > cap:
                visible_input += "\n...(truncated)..."
            if self.fault in {"owner", "permission"}:
                async with self.factory() as db:
                    attempt = await db.scalar(
                        select(DelegationAttempt).where(
                            DelegationAttempt.remote_binding["session_key"].as_string() == params["sessionKey"]
                        )
                    )
                    row = await db.get(ChannelDelegation, attempt.delegation_id)
                    if self.fault == "owner":
                        row.owner_token = "concurrent-owner"
                    else:
                        from yuxi.storage.postgres.models_business import CollaboratorConnectionProject

                        permission = await db.get(
                            CollaboratorConnectionProject, (attempt.connection_id, attempt.project_id)
                        )
                        permission.enabled = False
                    await db.commit()
            return {
                "sessionKey": params["sessionKey"],
                "sessionId": session["id"],
                "hasMore": self.fault == "history-incomplete",
                "messages": [
                    {
                        "role": "user",
                        "content": 123 if self.fault == "input-shape" else visible_input,
                        "idempotencyKey": session["run"] + ":user",
                    },
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": session["output"]}],
                        "stopReason": "length" if self.fault == "truncated" else "stop",
                        "__openclaw": {
                            "runId": "wrong" if self.wrong_run else session["run"],
                            "id": "message-" + session["id"],
                        },
                    },
                ],
            }
        raise AssertionError(method)


@asynccontextmanager
async def local_http(manager, factory):
    """创建精确自有HTTP进程和模拟Gateway，退出仅清理本卡资源。"""
    async with manager.async_engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()"))
    gateway = GatewayOracle(factory)
    application = web.Application()
    application.router.add_get("/", gateway.websocket)
    runner = web.AppRunner(application)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 18890).start()
    env = {**os.environ, "C1_TEST_SCHEMA": schema}
    errors = tempfile.TemporaryFile(mode="w+b")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "test.integration.services.collaboration_http_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18891",
            "--log-level",
            "error",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=errors,
    )
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18891", timeout=60) as client:
            for _ in range(600):
                try:
                    await client.get("/openapi.json")
                    break
                except httpx.ConnectError:
                    if process.poll() is not None:
                        errors.seek(0)
                        raise AssertionError(errors.read().decode()[-6000:])
                    await asyncio.sleep(0.1)
            else:
                errors.seek(0)
                raise AssertionError("isolated HTTP failed to start: " + errors.read().decode()[-6000:])
            yield client, gateway
    finally:
        process.terminate()
        process.wait(timeout=15)
        errors.close()
        await runner.cleanup()


async def seed_api_key(factory, uid="uid-owner"):
    """使用实际APIKey认证，秘密只用于隔离HTTP调用。"""
    token = "yxkey_c1-" + uid
    async with factory() as db:
        user = await db.scalar(select(User).where(User.uid == uid))
        department = Department(name="c1-" + uid)
        db.add(department)
        await db.flush()
        user.department_id = department.id
        db.add(
            APIKey(
                key_hash=hashlib.sha256(token.encode()).hexdigest(),
                key_prefix="yxkey_c1",
                name="c1",
                user_id=user.id,
                created_by=uid,
                is_enabled=True,
            )
        )
        await db.commit()
    return {"Authorization": "Bearer " + token}


async def test_two_http_entries_accurate_result_and_separate_supplement(tmp_path, monkeypatch):
    """两个真实HTTP入口均形成准确pending结果，补充独立回读。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    (tmp_path / "shared/uid-owner/workspace/projects/project-owner").mkdir(parents=True)
    async with _scoped_database("c1_delivery") as (manager, factory):
        await _seed_scope(manager.async_engine)
        headers = await seed_api_key(factory)
        await _seed_scope(manager.async_engine, uid="uid-other", project_id="project-other")
        other_headers = await seed_api_key(factory, "uid-other")
        async with local_http(manager, factory) as (client, gateway):
            connection = await client.post(
                "/api/collaborators/connections",
                headers=headers,
                json={
                    "label": "isolated",
                    "endpoint": "ws://127.0.0.1:18890",
                    "project_ids": ["project-owner"],
                    "token": "synthetic-gateway-token",
                },
            )
            assert connection.status_code == 200, connection.text
            assert "synthetic-gateway-token" not in connection.text
            target = await client.post(
                "/api/collaborators/targets",
                headers=headers,
                json={"connection_id": connection.json()["id"], "remote_identity": "isolated-c", "label": "C"},
            )
            assert target.status_code == 200, target.text
            checked = await client.post(f"/api/collaborators/targets/{target.json()['id']}/check", headers=headers)
            assert checked.status_code == 200, checked.text
            for path in [
                "/api/projects/project-owner/delegations",
                "/api/projects/project-owner/work/tasks/project-owner-work/delegations",
            ]:
                body = {
                    "executor_key": "openclaw",
                    "target_id": target.json()["id"],
                    "target_revision": 1,
                    "summary_budget": 200,
                }
                if path.endswith("owner/delegations"):
                    body.update(work_task_id="project-owner-work", task="只算给定合成数据")
                dispatched = await client.post(path, headers=headers, json=body)
                assert dispatched.status_code == 200, dispatched.text
                op = dispatched.json()["operation_id"]
                gateway.wrong_run = True
                entered, release = asyncio.Event(), asyncio.Event()
                gateway.pause_wait = (entered, release)
                first = asyncio.create_task(
                    client.post(f"/api/projects/project-owner/delegations/{op}/collect", headers=headers)
                )
                await asyncio.wait_for(entered.wait(), 10)
                concurrent = await client.post(f"/api/projects/project-owner/delegations/{op}/collect", headers=headers)
                assert concurrent.status_code == 409 and concurrent.json()["detail"]["code"] == "delegation_collecting"
                release.set()
                refused = await first
                gateway.pause_wait = None
                assert refused.status_code == 409, refused.text
                assert refused.json()["detail"]["code"] == "delivery_source_unverified"
                async with factory() as db:
                    row = await db.scalar(select(ChannelDelegation).where(ChannelDelegation.operation_id == op))
                    assert (
                        row.dispatch_state == "dispatched" and row.owner_token is None and row.lease_expires_at is None
                    )
                    assert (
                        await db.scalar(
                            select(ProjectWorkResult).where(ProjectWorkResult.source_delegation_id == row.id)
                        )
                        is None
                    )
                gateway.wrong_run = False
                for fault in [
                    "wait-run",
                    "receipt-session",
                    "model",
                    "history-incomplete",
                    "input-shape",
                    "receipt-turn",
                    "history-truncated",
                    "receipt-tools",
                    "truncated",
                    "not-ready",
                    "owner",
                    "permission",
                ]:
                    gateway.fault = fault
                    gateway.not_ready = fault == "not-ready"
                    refused = await client.post(
                        f"/api/projects/project-owner/delegations/{op}/collect", headers=headers
                    )
                    assert refused.status_code == 409, (fault, refused.text)
                    assert refused.json()["detail"]["code"] == (
                        "delivery_not_ready"
                        if fault == "not-ready"
                        else "delegation_owner_changed"
                        if fault == "owner"
                        else "target_unavailable"
                        if fault == "permission"
                        else "delivery_source_unverified"
                    )
                    async with factory() as db:
                        row = await db.scalar(select(ChannelDelegation).where(ChannelDelegation.operation_id == op))
                        assert (
                            await db.scalar(
                                select(ProjectWorkResult).where(ProjectWorkResult.source_delegation_id == row.id)
                            )
                            is None
                        )
                        if fault == "owner":
                            assert row.owner_token == "concurrent-owner" and row.dispatch_state == "collecting"
                            row.dispatch_state, row.owner_token, row.lease_expires_at = "dispatched", None, None
                            await db.commit()
                        else:
                            assert (
                                row.dispatch_state == "dispatched"
                                and row.owner_token is None
                                and row.lease_expires_at is None
                            )
                from yuxi.storage.postgres.models_business import CollaboratorConnectionProject

                async with factory() as db:
                    permission = await db.get(CollaboratorConnectionProject, (connection.json()["id"], "project-owner"))
                    permission.enabled = True
                    await db.commit()
                gateway.fault, gateway.not_ready = None, False
                collected = await client.post(f"/api/projects/project-owner/delegations/{op}/collect", headers=headers)
                assert collected.status_code == 200, collected.text
                from yuxi.workspace.workdir import Workdir

                workdir = Workdir.open_existing("uid-owner", "projects/project-owner")
                assert (
                    workdir.read_file("/" + collected.json()["artifact_path"], 1024).decode()
                    == "A=330；B=330；C=300；最低C。"
                )
                supplement = await client.get(
                    f"/api/projects/project-owner/delegations/{op}/supplement", headers=headers
                )
                assert supplement.status_code == 200, supplement.text
                assert supplement.json()["attempt_id"] == dispatched.json()["attempt_id"]
                assert supplement.json()["supplement"]["summary_conforming"] is False
                assert supplement.json()["supplement"]["complete"] is False
                async with factory() as db:
                    row = await db.scalar(select(ChannelDelegation).where(ChannelDelegation.operation_id == op))
                    result = await db.scalar(
                        select(ProjectWorkResult).where(ProjectWorkResult.source_delegation_id == row.id)
                    )
                    assert result.summary == "A=330；B=330；C=300；最低C。" and result.status == "pending"
                    assert result.unresolved == "非阻塞事项：给定数据仅为合成示例"
                    assert result.source_output["source"]["run_id"] == row.external_ref
                from yuxi.delegation.protocol import validate_contract

                projection = await client.get(
                    f"/api/projects/project-owner/collaboration/attempts/{dispatched.json()['attempt_id']}",
                    headers=headers,
                )
                assert projection.status_code == 200, projection.text
                validate_contract("collaboration-read", projection.json())
                assert projection.json()["result"]["id"] == result.id
                assert projection.json()["allowed_actions"][0]["result_id"] == result.id
                repeated = await client.post(f"/api/projects/project-owner/delegations/{op}/collect", headers=headers)
                assert repeated.status_code == 200 and repeated.json()["attempt_id"] == dispatched.json()["attempt_id"]
            assert gateway.dispatch_count == 2
            # 接受回执丢失后由真实收敛Owner只读核对，不产生第二次agent动作。
            gateway.lose_acceptance = True
            body = {
                "executor_key": "openclaw",
                "target_id": target.json()["id"],
                "target_revision": 1,
                "work_task_id": "project-owner-work",
                "task": "接受丢失核对",
            }
            lost = await client.post("/api/projects/project-owner/delegations", headers=headers, json=body)
            assert lost.status_code == 409, lost.text
            assert lost.json()["detail"]["code"] == "delivery_outcome_unknown"
            async with factory() as db:
                pending = await db.scalar(
                    select(ChannelDelegation).where(ChannelDelegation.dispatch_state == "pending")
                )
                assert pending.owner_token is None and pending.lease_expires_at is None
                assert pending.error_code == "delivery_outcome_unknown"
            from yuxi.services.delegation_service import reconcile_delegations
            from yuxi.storage.postgres import manager as manager_module

            manager.AsyncSession = factory
            monkeypatch.setattr(manager_module, "pg_manager", manager)
            counts = await reconcile_delegations()
            assert counts["redispatched"] == 1, counts
            assert gateway.dispatch_count == 3
            async with factory() as db:
                rows = list((await db.scalars(select(ChannelDelegation))).all())
                assert len(rows) == 3 and all(r.dispatch_state in {"dispatched", "reclaimed"} for r in rows)
                recovered = next(r for r in rows if r.dispatch_state == "dispatched")
                assert recovered.owner_token is None and recovered.external_ref
            recovered_collect = await client.post(
                f"/api/projects/project-owner/delegations/{recovered.operation_id}/collect", headers=headers
            )
            assert recovered_collect.status_code == 200, recovered_collect.text
            # 已核对来源的非成功输出持久保存，但零成功结果与artifact。
            gateway.fault = "blocked"
            blocked = await client.post("/api/projects/project-owner/delegations", headers=headers, json=body)
            assert blocked.status_code == 200, blocked.text
            blocked_op = blocked.json()["operation_id"]
            refused = await client.post(
                f"/api/projects/project-owner/delegations/{blocked_op}/collect", headers=headers
            )
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "delivery_not_completed"
            observation = await client.get(
                f"/api/projects/project-owner/delegations/{blocked_op}/supplement", headers=headers
            )
            assert observation.status_code == 200
            raw = observation.json()["observation"]
            assert json.loads(raw["text"])["outcome"] == "blocked"
            assert raw["source"]["attempt_id"] == blocked.json()["attempt_id"]
            async with factory() as db:
                row = await db.scalar(select(ChannelDelegation).where(ChannelDelegation.operation_id == blocked_op))
                assert row.artifact_path is None and row.owner_token is None
                assert (
                    await db.scalar(select(ProjectWorkResult).where(ProjectWorkResult.source_delegation_id == row.id))
                    is None
                )
            gateway.fault = "skills"
            drift = await client.post("/api/projects/project-owner/delegations", headers=headers, json=body)
            assert drift.status_code == 409 and drift.json()["detail"]["code"] == "target_policy_unverified"
            assert gateway.dispatch_count == 4
            gateway.fault = None
            # 本人连接不可跨用户读取、使用或伪造核验；当前项目许可是实际副作用门。
            for url in [
                f"/api/collaborators/connections/{connection.json()['id']}/targets",
                f"/api/projects/project-owner/delegations/{op}/supplement",
            ]:
                assert (await client.get(url, headers=other_headers)).status_code == 404
            assert (
                await client.post(f"/api/collaborators/targets/{target.json()['id']}/check", headers=other_headers)
            ).status_code == 404
            assert (
                await client.post(
                    "/api/projects/project-other/delegations",
                    headers=other_headers,
                    json={**body, "work_task_id": "project-other-work"},
                )
            ).status_code == 404
            stale = await client.post(
                "/api/projects/project-owner/delegations", headers=headers, json={**body, "target_revision": 99}
            )
            assert stale.status_code == 409 and stale.json()["detail"]["code"] == "target_unavailable"
            changed = await client.put(
                f"/api/collaborators/connections/{connection.json()['id']}",
                headers=headers,
                json={
                    "label": "revoked",
                    "endpoint": "ws://127.0.0.1:18890",
                    "project_ids": [],
                    "expected_revision": 1,
                },
            )
            assert changed.status_code == 200, changed.text
            for path in [
                "/api/projects/project-owner/delegations",
                "/api/projects/project-owner/work/tasks/project-owner-work/delegations",
            ]:
                refused = await client.post(
                    path,
                    headers=headers,
                    json=body
                    if path.endswith("owner/delegations")
                    else {k: v for k, v in body.items() if k not in {"task", "work_task_id"}},
                )
                assert refused.status_code == 409 and refused.json()["detail"]["code"] == "target_unavailable"
            conflict = await client.put(
                f"/api/collaborators/connections/{connection.json()['id']}",
                headers=headers,
                json={
                    "label": "old",
                    "endpoint": "ws://127.0.0.1:18890",
                    "project_ids": ["project-owner"],
                    "expected_revision": 1,
                },
            )
            assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "connection_revision_conflict"
            assert gateway.dispatch_count == 4
            from yuxi.storage.postgres.models_business import CollaboratorConnection

            async with factory() as db:
                stored = await db.get(CollaboratorConnection, connection.json()["id"])
                assert b"synthetic-gateway-token" not in bytes(stored.ciphertext)
                assert "token" not in stored.config_json


async def test_v37_migration_idempotence_and_owner_constraints():
    """真实PG重复升级保留旧委派，跨用户/项目关联由数据库拒绝。"""
    from sqlalchemy.exc import IntegrityError
    from yuxi.storage.postgres.models_business import CollaboratorConnection, CollaboratorConnectionProject

    async with _scoped_database("c1_migration") as (manager, factory):
        await _seed_scope(manager.async_engine)
        await _seed_scope(manager.async_engine, uid="uid-other", project_id="project-other")
        async with manager.async_engine.begin() as db:
            for table in [
                "delegation_attempts",
                "collaborator_targets",
                "collaborator_connection_projects",
                "collaborator_connections",
            ]:
                await db.execute(text(f"DROP TABLE {table} CASCADE"))
            await db.execute(
                text("ALTER TABLE channel_delegations DROP CONSTRAINT ck_channel_delegations_executor_key")
            )
            await db.execute(
                text(
                    "ALTER TABLE channel_delegations ADD CONSTRAINT ck_channel_delegations_executor_key "
                    "CHECK (executor_key IN ('codex','opencode','multica'))"
                )
            )
            await db.execute(
                text(
                    "INSERT INTO channel_delegations(id,operation_id,project_id,executor_key,task,request_json,"
                    "dispatch_state,attempts,result_json,created_at,updated_at) "
                    "VALUES('old','old','project-owner','multica','旧输入','{}','dispatched',1,'{}',NOW(),NOW())"
                )
            )
        await manager.upgrade_yuanlei_schema_v36_to_v37()
        await manager.upgrade_yuanlei_schema_v36_to_v37()
        async with factory() as db:
            old = await db.get(ChannelDelegation, "old")
            assert old.task == "旧输入" and old.dispatch_state == "dispatched" and old.executor_key == "multica"
            assert not list((await db.scalars(select(DelegationAttempt))).all())
            db.add(
                CollaboratorConnection(
                    id="conn",
                    uid="uid-owner",
                    label="C",
                    provider_key="openclaw",
                    revision=1,
                    config_json={},
                    ciphertext=b"cipher",
                    nonce=b"nonce",
                )
            )
            await db.commit()
            db.add(CollaboratorConnectionProject(connection_id="conn", project_id="project-other", uid="uid-owner"))
            with pytest.raises(IntegrityError) as caught:
                await db.commit()
            assert "foreign key" in str(caught.value).lower()
            await db.rollback()
            db.add(CollaboratorConnectionProject(connection_id="conn", project_id="project-owner", uid="uid-other"))
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()
            old = await db.get(ChannelDelegation, "old")
            old.executor_key = "made-up"
            with pytest.raises(IntegrityError) as caught:
                await db.commit()
            assert "ck_channel_delegations_executor_key" in str(caught.value)
            await db.rollback()

            from yuxi.storage.postgres.models_business import CollaboratorTarget

            db.add(
                CollaboratorTarget(
                    id="wrong-target", connection_id="conn", uid="uid-other", revision=1, remote_identity="C", label="C"
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()
            db.add(
                CollaboratorConnection(
                    id="other-conn",
                    uid="uid-other",
                    label="D",
                    provider_key="openclaw",
                    revision=1,
                    config_json={},
                    ciphertext=b"cipher",
                    nonce=b"nonce",
                )
            )
            await db.flush()
            for connection_id, project_id, uid in [
                ("conn", "project-owner", "uid-owner"),
                ("other-conn", "project-other", "uid-other"),
            ]:
                db.add(CollaboratorConnectionProject(connection_id=connection_id, project_id=project_id, uid=uid))
                db.add(
                    CollaboratorTarget(
                        id=connection_id + "-target",
                        connection_id=connection_id,
                        uid=uid,
                        revision=1,
                        remote_identity="C",
                        label="C",
                    )
                )
            db.add(
                ChannelDelegation(
                    id="other-delegation",
                    operation_id="other-root",
                    project_id="project-other",
                    executor_key="openclaw",
                    task="other",
                    request_json={},
                    dispatch_state="pending",
                    attempts=0,
                    result_json={},
                )
            )
            await db.commit()
            db.add(
                ChannelDelegation(
                    id="other-unused",
                    operation_id="other-unused-root",
                    project_id="project-other",
                    executor_key="openclaw",
                    task="other",
                    request_json={},
                    dispatch_state="pending",
                    attempts=0,
                    result_json={},
                )
            )
            await db.commit()
            other_values = dict(
                id="other-attempt",
                delegation_id="other-delegation",
                project_id="project-other",
                uid="uid-other",
                connection_id="other-conn",
                target_id="other-conn-target",
                root_operation_id="other-root",
                snapshot_json={},
                task_package={},
                rendered_input_hash="0" * 64,
                remote_binding={},
            )
            db.add(DelegationAttempt(**other_values))
            await db.commit()
            values = dict(
                id="owner-attempt",
                delegation_id="old",
                project_id="project-owner",
                uid="uid-owner",
                connection_id="conn",
                target_id="conn-target",
                root_operation_id="old",
                snapshot_json={},
                task_package={},
                rendered_input_hash="0" * 64,
                remote_binding={},
            )
            for field, wrong in [
                ("target_id", "other-conn-target"),
                ("connection_id", "other-conn"),
                ("uid", "uid-other"),
                ("delegation_id", "other-unused"),
                ("root_operation_id", "other-root"),
                ("predecessor_id", "other-attempt"),
            ]:
                db.add(DelegationAttempt(**{**values, field: wrong}))
                with pytest.raises(IntegrityError) as caught:
                    await db.commit()
                assert "foreign key" in str(caught.value).lower(), field
                await db.rollback()
            db.add(DelegationAttempt(**values))
            await db.commit()
            db.add(DelegationAttempt(**{**values, "id": "duplicate-attempt"}))
            with pytest.raises(IntegrityError) as caught:
                await db.commit()
            assert "uq_delegation_attempt_source" in str(caught.value)
            await db.rollback()


async def test_real_tool_entry_reuses_owner_and_refuses_stale_run(tmp_path, monkeypatch):
    """真实根Run工具通过共同入口，过期owner不能制造远端动作。"""
    from types import SimpleNamespace
    from datetime import timedelta
    from test.integration.services.test_project_dashboard_tool import _seed_run
    from yuxi.agents.toolkits.buildin import delegation_tools
    from yuxi.services.collaborator_service import CollaboratorService
    from yuxi.storage.postgres.models_business import AgentRun, ProjectWorkTask
    from yuxi.utils.datetime_utils import utc_now_naive

    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    (tmp_path / "shared/uid-tool/workspace/projects/p1").mkdir(parents=True)
    async with _scoped_database("c1_tool") as (manager, factory):
        manager.AsyncSession = factory
        await _seed_run(factory, uid="uid-tool", project_id="project-tool", thread_id="thread-tool", run_id="run-tool")
        async with factory() as db:
            db.add(
                ProjectWorkTask(
                    id="work-tool",
                    project_id="project-tool",
                    number="TEST-000001",
                    title="合成工作",
                    created_by="uid-tool",
                )
            )
            await db.commit()
        monkeypatch.setattr(delegation_tools, "pg_manager", manager)
        async with local_http(manager, factory) as (_, gateway):
            async with factory() as db:
                service = CollaboratorService(db)
                connection = await service.save_connection(
                    uid="uid-tool",
                    label="tool",
                    endpoint="ws://127.0.0.1:18890",
                    project_ids=["project-tool"],
                    token="synthetic",
                )
                target = await service.save_target(
                    uid="uid-tool", connection_id=connection["id"], remote_identity="isolated-c", label="C"
                )
                await service.check_target(target["id"], "uid-tool")
            runtime = SimpleNamespace(
                context=SimpleNamespace(
                    uid="uid-tool", run_id="run-tool", worker_id="worker-current", thread_id="thread-tool"
                )
            )
            dispatched = json.loads(
                await delegation_tools.delegation_dispatch.coroutine(
                    executor_key="openclaw",
                    task="合成核算",
                    work_task_id="work-tool",
                    target_id=target["id"],
                    target_revision=1,
                    runtime=runtime,
                )
            )
            assert dispatched.get("error_code") is None and dispatched["dispatch_state"] == "dispatched", dispatched
            async with factory() as db:
                row = await db.scalar(
                    select(ChannelDelegation).where(ChannelDelegation.operation_id == dispatched["operation_id"])
                )
                assert row.initiator_run_id == "run-tool" and row.work_task_id == "work-tool"
                run = await db.get(AgentRun, "run-tool")
                run.lease_expires_at = utc_now_naive() - timedelta(seconds=1)
                await db.commit()
            refused = json.loads(
                await delegation_tools.delegation_dispatch.coroutine(
                    executor_key="openclaw",
                    task="过期运行",
                    work_task_id="work-tool",
                    target_id=target["id"],
                    target_revision=1,
                    runtime=runtime,
                )
            )
            assert refused["error_code"] == "invalid_request"
            assert gateway.dispatch_count == 1
