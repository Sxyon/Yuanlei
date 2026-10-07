"""P09回复、处置与实际确认的真实数据库边界。"""

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from test.integration.services.test_governance_service import _scoped_database, _seed_user, _seed_project
from yuxi.services import governance_service as service
from yuxi.storage.postgres.models_business import User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """隔离数据库不依赖运行API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离数据库不创建知识资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离数据库不创建沙盒。"""
    yield


async def seed(manager, factory):
    """建立同用户两个项目与两条真实议题。"""
    await _seed_user(manager.async_engine, uid="p09")
    for pid in ("project-a", "project-b"):
        await _seed_project(manager.async_engine, project_id=pid, uid="p09")
    topics = []
    async with factory() as db:
        user = await db.scalar(select(User).where(User.uid == "p09"))
        for pid in ("project-a", "project-b"):
            topics.append(
                await service.create_governance_topic(
                    project_id=pid,
                    title=pid,
                    summary="原始内容",
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=db,
                    user=user,
                )
            )
    return user, topics


async def rejected(call, db, code, status=422):
    """失败必须来自目标守卫并回滚当前用例。"""
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == status
    assert exc.value.detail["code"] == code
    await db.rollback()


async def test_reply_current_revision_single_layer_and_original_location():
    """回复用当前修订，事件只定位原讨论，拒绝跨议题和二层。"""
    async with _scoped_database("p09_reply") as (manager, factory):
        user, topics = await seed(manager, factory)
        tid = topics[0]["id"]
        async with factory() as db:
            root = await service.create_governance_topic_comment(
                project_id="project-a", topic_id=tid, content="原讨论", db=db, user=user
            )
            await service.update_governance_topic(
                project_id="project-a",
                topic_id=tid,
                title="更新后",
                summary="新正文",
                expected_revision=1,
                reason="补充",
                db=db,
                user=user,
            )
            kwargs = dict(
                project_id="project-a",
                topic_id=tid,
                content="回复",
                parent_comment_id=root["id"],
                operation_id="reply-one",
                db=db,
                user=user,
            )
            await rejected(
                service.create_governance_topic_comment(**{**kwargs, "operation_id": None}),
                db,
                "reply_operation_required",
            )
            reply = await service.create_governance_topic_comment(**kwargs)
            assert reply["revision_number"] == 2 and root["revision_number"] == 1
            assert (await service.create_governance_topic_comment(**kwargs))["id"] == reply["id"]
            await rejected(
                service.create_governance_topic_comment(**{**kwargs, "content": "另一意图"}),
                db,
                "operation_conflict",
                409,
            )
            await rejected(
                service.create_governance_topic_comment(
                    **{**kwargs, "parent_comment_id": reply["id"], "operation_id": "nested"}
                ),
                db,
                "invalid_reply_parent",
            )
            foreign = await service.create_governance_topic_comment(
                project_id="project-b", topic_id=topics[1]["id"], content="跨议题", db=db, user=user
            )
            await rejected(
                service.create_governance_topic_comment(
                    **{**kwargs, "parent_comment_id": foreign["id"], "operation_id": "foreign"}
                ),
                db,
                "invalid_reply_parent",
            )
            page = await service.get_governance_topic_timeline(
                project_id="project-a", topic_id=tid, before=None, limit=1, db=db, user=user
            )
            assert page["items"][0]["kind"] == "reply" and page["items"][0]["comment"] is None
            assert page["items"][0]["details"]["parent_comment_id"] == root["id"]
            detail = await service.get_topic_discussion(
                project_id="project-a", topic_id=tid, comment_id=root["id"], db=db, user=user
            )
            assert [row["id"] for row in detail["replies"]] == [reply["id"]]
            await service.operate_governance_topic(
                project_id="project-a",
                topic_id=tid,
                action="archive",
                reason=None,
                execution_hint=None,
                decision_id=None,
                db=db,
                user=user,
            )
            await rejected(
                service.create_governance_topic_comment(**{**kwargs, "operation_id": "archived"}),
                db,
                "topic_read_only",
                409,
            )


async def test_disposition_history_reference_guards_retry_and_concurrency():
    """处置真实引用与追加版本，竞争者只有一次成功且不会生成半条历史。"""
    async with _scoped_database("p09_disposition") as (manager, factory):
        user, topics = await seed(manager, factory)
        tid = topics[0]["id"]
        async with factory() as db:
            root = await service.create_governance_topic_comment(
                project_id="project-a", topic_id=tid, content="建议", db=db, user=user
            )
            base = dict(project_id="project-a", topic_id=tid, comment_id=root["id"], db=db, user=user)
            payload = dict(
                operation_id="first",
                expected_version=0,
                disposition="partial",
                explanation="落实一部分",
                reference={"kind": "revision", "id": tid, "version": 1},
            )
            first = await service.record_topic_disposition(**base, payload=payload)
            assert first["reference_snapshot"]["snapshot"]["summary"] == "原始内容"
            assert (await service.record_topic_disposition(**base, payload=payload))["id"] == first["id"]
            for reference in (
                {"kind": "revision", "id": tid, "version": 99},
                {"kind": "revision", "id": topics[1]["id"], "version": 1},
            ):
                await rejected(
                    service.record_topic_disposition(
                        **base,
                        payload={
                            **payload,
                            "expected_version": 1,
                            "operation_id": uuid.uuid4().hex,
                            "reference": reference,
                        },
                    ),
                    db,
                    "invalid_reference",
                )

        async def contender(op):
            async with factory() as db:
                try:
                    return await service.record_topic_disposition(
                        project_id="project-a",
                        topic_id=tid,
                        comment_id=root["id"],
                        db=db,
                        user=user,
                        payload={
                            **payload,
                            "operation_id": op,
                            "expected_version": 1,
                            "disposition": "rejected",
                            "explanation": "新证据",
                            "reference": None,
                        },
                    )
                except HTTPException as exc:
                    await db.rollback()
                    return exc

        outcomes = await asyncio.gather(contender("second"), contender("third"))
        assert sum(isinstance(value, dict) for value in outcomes) == 1
        failure = next(value for value in outcomes if isinstance(value, HTTPException))
        assert failure.detail["code"] == "disposition_conflict"
        async with factory() as db:
            detail = await service.get_topic_discussion(
                project_id="project-a", topic_id=tid, comment_id=root["id"], db=db, user=user
            )
            assert [row["version"] for row in detail["dispositions"]] == [2, 1]
            assert detail["content"] == "建议" and detail["dispositions"][0]["reference_snapshot"] is None
            await rejected(
                service.operate_governance_topic(
                    project_id="project-a",
                    topic_id=tid,
                    action="delete",
                    reason="删除",
                    execution_hint=None,
                    decision_id=None,
                    db=db,
                    user=user,
                ),
                db,
                "topic_referenced",
                409,
            )


async def test_actual_confirmation_conditions_correction_evidence_and_archive():
    """条件冻结、人工更正和撤回独立于生命周期；坏证据不产生记录。"""
    async with _scoped_database("p09_confirmation") as (manager, factory):
        user, topics = await seed(manager, factory)
        tid = topics[0]["id"]
        async with factory() as db:
            await service.update_governance_topic(
                project_id="project-a",
                topic_id=tid,
                title="目标",
                summary="正文",
                expected_outcome="达到10",
                verification_conditions="手工核对",
                expected_revision=1,
                reason="明确目标",
                db=db,
                user=user,
            )
            base = dict(project_id="project-a", topic_id=tid, db=db, user=user)
            payload = dict(
                operation_id="confirm",
                expected_version=0,
                expected_revision=2,
                action="confirm",
                explanation="人工确认",
                reference=None,
                evidence=[{"kind": "url", "value": "https://example.com/evidence"}],
            )
            await rejected(
                service.record_topic_confirmation(
                    **base, payload={**payload, "operation_id": "no-evidence", "evidence": []}
                ),
                db,
                "evidence_required",
            )
            await rejected(
                service.record_topic_confirmation(
                    **base, payload={**payload, "operation_id": "no-history", "action": "correct"}
                ),
                db,
                "invalid_confirmation",
            )
            await rejected(
                service.record_topic_confirmation(
                    **base,
                    payload={
                        **payload,
                        "operation_id": "wrong-type",
                        "reference": {"kind": "revision", "id": tid, "version": 2},
                    },
                ),
                db,
                "invalid_reference",
            )
            first = await service.record_topic_confirmation(**base, payload=payload)
            assert first["expected_outcome"] == "达到10"
            assert first["evidence"][0]["availability"] == "reference_only"
            assert (await service.record_topic_confirmation(**base, payload=payload))["id"] == first["id"]
            await service.update_governance_topic(
                project_id="project-a",
                topic_id=tid,
                title="目标",
                summary="正文",
                expected_outcome="达到20",
                verification_conditions="新条件",
                expected_revision=2,
                reason="条件改变",
                db=db,
                user=user,
            )
            await rejected(
                service.record_topic_confirmation(
                    **base, payload={**payload, "operation_id": "stale", "expected_version": 1}
                ),
                db,
                "confirmation_conflict",
                409,
            )
            bad = {
                **payload,
                "operation_id": "bad",
                "expected_version": 1,
                "expected_revision": 3,
                "action": "correct",
                "evidence": [{"kind": "file", "value": "../../forbidden"}],
            }
            await rejected(service.record_topic_confirmation(**base, payload=bad), db, "topic_evidence_unavailable")
            correction = await service.record_topic_confirmation(
                **base,
                payload={
                    **payload,
                    "operation_id": "correct",
                    "expected_version": 1,
                    "expected_revision": 3,
                    "action": "correct",
                    "explanation": "重新核对达到20",
                },
            )
            assert correction["version"] == 2 and correction["expected_outcome"] == "达到20"
            await service.record_topic_confirmation(
                **base,
                payload={
                    **payload,
                    "operation_id": "withdraw",
                    "expected_version": 2,
                    "expected_revision": 3,
                    "action": "withdraw",
                    "evidence": [],
                    "explanation": "撤回判断",
                },
            )
            current = await service.get_governance_topic(**base)
            assert current["admission_status"] == "proposed" and current["progress"] == "open"
            followup = await service.get_topic_followup(**base)
            assert [row["action"] for row in followup["confirmations"]] == ["withdraw", "correct", "confirm"]
            assert followup["confirmations"][-1]["expected_outcome"] == "达到10"
            await service.operate_governance_topic(
                **base, action="archive", reason=None, execution_hint=None, decision_id=None
            )
            await rejected(
                service.record_topic_confirmation(
                    **base,
                    payload={**payload, "operation_id": "readonly", "expected_version": 3, "expected_revision": 3},
                ),
                db,
                "topic_read_only",
                409,
            )
            assert len((await service.get_topic_followup(**base))["confirmations"]) == 3


async def test_v35_migration_reentry_preserves_legacy_comments_and_revisions():
    """真实PostgreSQL模拟35结构，重复升级保持旧正文和未知值。"""
    async with _scoped_database("p09_migration") as (manager, factory):
        user, topics = await seed(manager, factory)
        async with factory() as db:
            root = await service.create_governance_topic_comment(
                project_id="project-a", topic_id=topics[0]["id"], content="旧评论", db=db, user=user
            )
        async with manager.async_engine.begin() as conn:
            for table in ("governance_topic_dispositions", "governance_topic_confirmations"):
                await conn.execute(text(f"DROP TABLE {table}"))
            for table in ("governance_topics", "governance_topic_revisions"):
                for column in ("expected_outcome", "verification_conditions"):
                    await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            for column in ("parent_comment_id", "operation_id", "intent_fingerprint"):
                await conn.execute(text(f"ALTER TABLE governance_topic_comments DROP COLUMN {column} CASCADE"))
        await manager.upgrade_yuanlei_schema_v35_to_v36()
        await manager.upgrade_yuanlei_schema_v35_to_v36()
        async with manager.async_engine.connect() as conn:
            values = (
                await conn.execute(
                    text(
                        "SELECT content,parent_comment_id,revision_number FROM governance_topic_comments WHERE id=:id"
                    ),
                    {"id": root["id"]},
                )
            ).one()
            assert values == ("旧评论", None, 1)
            assert await conn.scalar(text("SELECT expected_outcome FROM governance_topics LIMIT 1")) is None
            assert await conn.scalar(text("SELECT count(*) FROM governance_topic_events")) == 3


async def test_referenced_revision_and_target_delete_share_project_lock(monkeypatch):
    """引用先提交则拒删，删除先提交则拒引用，持久数据库验证真实阻塞。"""
    async with _scoped_database("p09_reference_delete") as (manager, factory):
        user, topics = await seed(manager, factory)
        source = topics[0]["id"]
        async with factory() as db:
            root = await service.create_governance_topic_comment(
                project_id="project-a", topic_id=source, content="关联修订", db=db, user=user
            )
        for deletion_first in (False, True):
            async with factory() as db:
                target = await service.create_governance_topic(
                    project_id="project-a",
                    title="待关联目标",
                    summary="目标正文",
                    source_channel="project",
                    source_external_id=None,
                    source_url=None,
                    db=db,
                    user=user,
                )
            ready, release = asyncio.Event(), asyncio.Event()
            async with factory() as first, factory() as second:
                commit = first.commit

                async def gated_commit():
                    ready.set()
                    await release.wait()
                    await commit()

                monkeypatch.setattr(first, "commit", gated_commit)
                pid = await second.scalar(text("SELECT pg_backend_pid()"))

                async def write_reference(db, expected):
                    return await service.record_topic_disposition(
                        project_id="project-a",
                        topic_id=source,
                        comment_id=root["id"],
                        payload={
                            "operation_id": uuid.uuid4().hex,
                            "expected_version": expected,
                            "disposition": "adopted",
                            "explanation": "保存真实目标",
                            "reference": {"kind": "revision", "id": target["id"], "version": 1},
                        },
                        db=db,
                        user=user,
                    )

                async def delete_target(db):
                    return await service.operate_governance_topic(
                        project_id="project-a",
                        topic_id=target["id"],
                        action="delete",
                        reason="无价值",
                        execution_hint=None,
                        decision_id=None,
                        db=db,
                        user=user,
                    )

                primary = asyncio.create_task(delete_target(first) if deletion_first else write_reference(first, 0))
                await asyncio.wait_for(ready.wait(), 10)
                competing = asyncio.create_task(write_reference(second, 1) if deletion_first else delete_target(second))
                try:
                    blocked = False
                    for _ in range(20):
                        async with manager.async_engine.connect() as observer:
                            blocked = bool(
                                await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid})
                            )
                        if blocked:
                            break
                        await asyncio.sleep(0.05)
                    assert blocked, "竞争操作必须等待项目锁，而不是通过引用检查后删除目标"
                finally:
                    release.set()
                await primary
                with pytest.raises(HTTPException) as exc:
                    await competing
                assert exc.value.detail["code"] == ("invalid_reference" if deletion_first else "topic_referenced")
                await second.rollback()
            async with factory() as db:
                history = await service.get_topic_discussion(
                    project_id="project-a", topic_id=source, comment_id=root["id"], db=db, user=user
                )
                assert len(history["dispositions"]) == 1
                assert (
                    history["dispositions"][0]["target_topic_id"] != target["id"]
                    if deletion_first
                    else history["dispositions"][0]["target_topic_id"] == target["id"]
                )
