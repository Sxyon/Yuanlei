from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import yuxi.services.coding_execution_service as execution_module
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialWrite,
)
from yuxi.services.coding_execution_service import (
    _heartbeat_coding_turn_lease,
    _new_coding_turn_owner_id,
    coding_turn_owner_prefix,
    reconcile_coding_turns,
    run_coding_turn_job,
    wait_for_latest_turn,
)
from yuxi.services.coding_session_service import CodingSessionService
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

SCOPE_KEY = "agent-project:user-1:coder:project-1"
WORKDIR = "projects/11111111-1111-4111-8111-111111111111"
MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")

OPENCODE_OUTPUT = "\n".join(
    [
        json.dumps({"type": "step_start", "sessionID": "ses_job", "part": {"sessionID": "ses_job"}}),
        json.dumps({"type": "text", "sessionID": "ses_job", "part": {"text": "PONG"}}),
        json.dumps({"type": "step_finish", "sessionID": "ses_job", "part": {"tokens": {"total": 3}}}),
    ]
)


class _FakeProvider:
    def __init__(self):
        self.connections: dict[str, object] = {}

    def get_scope(self, scope, *, create_if_missing=False, **_kwargs):
        if scope.cache_key in self.connections:
            return self.connections[scope.cache_key]
        if not create_if_missing:
            return None
        connection = SimpleNamespace(
            cache_key=scope.cache_key,
            sandbox_id=scope.sandbox_id,
            generation="gen-1",
            workdir_path=_kwargs.get("workdir_path"),
        )
        self.connections[scope.cache_key] = connection
        return connection

    def release_scope(self, scope, **_kwargs):
        self.connections.pop(scope.cache_key, None)


class _FakeBackend:
    def __init__(self, output: str, *, state_present: bool = True, on_execute=None):
        self.output = output
        self.state_present = state_present
        self.on_execute = on_execute
        self.commands: list[str] = []

    def execute(self, command: str, timeout: int | None = None):
        self.commands.append(command)
        if command.startswith("test -d"):
            output = "__PRESENT__" if self.state_present else ""
            return SimpleNamespace(output=output, exit_code=0, truncated=False)
        if self.on_execute is not None:
            self.on_execute()
        return SimpleNamespace(output=self.output, exit_code=0, truncated=False)


class _FakeLeaseService:
    def __init__(self, *, active: bool = True):
        self.active = active
        self.acquired = False
        self.released = False

    async def acquire(self, **_kwargs):
        self.acquired = True
        return SimpleNamespace()

    async def heartbeat(self, **_kwargs):
        return self.active

    async def owns_active(self, **_kwargs):
        return self.active

    async def owns_active_prefix(self, **_kwargs):
        return self.active

    async def release(self, **_kwargs):
        self.released = True
        return True


@pytest_asyncio.fixture()
async def session(monkeypatch):
    monkeypatch.setenv("YUXI_CODING_CREDENTIAL_KEY", MASTER_KEY)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _factory_for(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def test_duplicate_job_attempts_use_distinct_fencing_owners():
    """重复投递必须使用不同 owner，后到任务不能重入或释放先到任务的租约。"""
    turn_id = "turn-1"
    first = _new_coding_turn_owner_id(turn_id)
    duplicate = _new_coding_turn_owner_id(turn_id)

    assert first != duplicate
    assert first.startswith(coding_turn_owner_prefix(turn_id))
    assert duplicate.startswith(coding_turn_owner_prefix(turn_id))
    assert len(first) <= 64


async def test_heartbeat_exception_marks_attempt_ownership_lost(monkeypatch):
    """心跳存储异常必须 fail-closed，不能让 worker 继续提交终态。"""

    class FailingLease:
        async def heartbeat(self, **_kwargs):
            raise RuntimeError("database unavailable")

    async def immediate_sleep(_seconds):
        return None

    monkeypatch.setattr(execution_module.asyncio, "sleep", immediate_sleep)
    lost = execution_module.asyncio.Event()
    scope = SimpleNamespace(uid="user-1", agent_slug="coder", project_id="project-1")

    await _heartbeat_coding_turn_lease(
        lease=FailingLease(),
        scope=scope,
        owner_id="coding-turn:abc:attempt",
        lost=lost,
    )

    assert lost.is_set()


async def _seed_pending_turn(session, *, plan_only=True):
    await CodingCredentialService(session).upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(executor="opencode", provider="sf", api_key="sk-job"),
        actor="user-1",
    )
    service = CodingSessionService(session)
    created = await service.create_session(
        uid="user-1",
        project_id="project-1",
        runtime_scope_id=SCOPE_KEY,
        executor="opencode",
        workdir_path=WORKDIR,
        parent_run_id="run-1",
        policy={"agent_config": {"sandbox": {"mode": "dedicated"}, "coding": {"executors": ["opencode"]}}},
    )
    turn = await service.queue_turn(
        created,
        request_text="后台执行",
        plan_only=plan_only,
    )
    await session.commit()
    return created, turn


async def test_job_executes_pending_turn(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)
    backend = _FakeBackend(OPENCODE_OUTPUT)

    result = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        plan_only=False,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=backend,
        lease_service=_FakeLeaseService(),
    )

    assert result["status"] == "idle"
    assert result["output_text"] == "PONG"
    detail = await CodingSessionService(session).session_detail(uid="user-1", session_id=created.id)
    assert detail["turns"][0]["status"] == "completed"
    assert "turn_queued" in [event["kind"] for event in detail["events"]]
    assert any("--agent plan" in command for command in backend.commands)
    assert "pending_turn" not in (created.policy_json or {})


async def test_job_commits_lifecycle_row_lock_before_cli_execution(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    def assert_transaction_released():
        assert not session.in_transaction(), "CLI 执行前仍持有准备事务"

    backend = _FakeBackend(OPENCODE_OUTPUT, on_execute=assert_transaction_released)

    result = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=backend,
        lease_service=_FakeLeaseService(),
    )

    assert result["status"] == "idle"


async def test_job_redacts_credential_before_persisting_events(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)
    output = "\n".join(
        [
            json.dumps({"type": "text", "part": {"text": "leak sk-job"}}),
            json.dumps({"type": "step_finish", "part": {}}),
        ]
    )

    await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(output),
        lease_service=_FakeLeaseService(),
    )

    detail = await CodingSessionService(session).session_detail(uid="user-1", session_id=created.id)
    serialized = json.dumps(detail, ensure_ascii=False)
    assert "sk-job" not in serialized
    assert "[redacted]" in serialized


async def test_event_redaction_recurses_into_nested_payloads():
    payload = {
        "outer": [
            {"message": "token sk-nested-secret"},
            {"details": ["safe", "sk-nested-secret"]},
        ]
    }

    redacted = execution_module._redact_event_payload(payload, ["sk-nested-secret"])

    assert json.dumps(redacted, ensure_ascii=False).count("[redacted]") == 2
    assert "sk-nested-secret" not in json.dumps(redacted, ensure_ascii=False)


async def test_job_skips_terminal_turn(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
        lease_service=_FakeLeaseService(),
    )
    replay = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
        lease_service=_FakeLeaseService(),
    )

    assert replay == {"status": "skipped", "reason": "completed"}


async def test_job_honors_cancel_signal(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_true)
    monkeypatch.setattr(execution_module, "clear_coding_cancel_signal", _async_noop)
    created, turn = await _seed_pending_turn(session)

    result = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
        lease_service=_FakeLeaseService(),
    )

    assert result["status"] == "cancelled"
    detail = await CodingSessionService(session).session_detail(uid="user-1", session_id=created.id)
    assert detail["status"] == "cancelled"
    assert detail["turns"][0]["status"] == "cancelled"


async def test_wait_for_latest_turn_reports_terminal_and_timeout(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    timed_out = await wait_for_latest_turn(
        uid="user-1",
        session_id=created.id,
        timeout_seconds=0,
        poll_seconds=0.05,
        session_factory=_factory_for(session),
    )
    assert timed_out["status"] == "wait_timed_out"

    await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
        lease_service=_FakeLeaseService(),
    )
    settled = await wait_for_latest_turn(
        uid="user-1",
        session_id=created.id,
        timeout_seconds=1,
        poll_seconds=0.05,
        session_factory=_factory_for(session),
    )
    assert settled["status"] == "idle"
    assert settled["turn"]["status"] == "completed"


async def test_reconcile_republishes_pending_and_fails_stale_running(session):
    created, pending = await _seed_pending_turn(session)
    stale_session = await CodingSessionService(session).create_session(
        uid="user-1",
        project_id="project-1",
        runtime_scope_id=SCOPE_KEY,
        executor="opencode",
        workdir_path=WORKDIR,
    )
    stale = await CodingSessionService(session).start_turn(stale_session, request_text="失联")
    stale.started_at = stale.started_at.replace(year=2000)
    await session.commit()
    published = []

    async def capture(**payload):
        published.append(payload)

    counts = await reconcile_coding_turns(
        stale_seconds=1,
        session_factory=_factory_for(session),
        enqueue=capture,
        lease_service=_FakeLeaseService(active=False),
    )

    assert counts == {"republished": 1, "failed": 1}
    assert published == [{"session_id": created.id, "turn_id": pending.id, "plan_only": True}]
    assert stale.status == "failed"
    assert stale.error_code == "coding_worker_lost"
    assert stale_session.status == "failed"


async def test_job_prepare_failure_marks_turn_failed_immediately(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    async def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("credential unavailable")

    monkeypatch.setattr(execution_module.CodingExecutionService, "prepare", fail_prepare)
    result = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        lease_service=_FakeLeaseService(),
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "coding_prepare_failed"
    detail = await CodingSessionService(session).session_detail(uid="user-1", session_id=created.id)
    assert detail["status"] == "failed"
    assert detail["turns"][0]["status"] == "failed"


async def test_job_lost_ownership_cannot_persist_late_result(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)
    session_id = created.id

    result = await run_coding_turn_job(
        session_id=session_id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
        lease_service=_FakeLeaseService(active=False),
    )

    assert result == {"status": "skipped", "reason": "ownership_lost"}
    detail = await CodingSessionService(session).session_detail(uid="user-1", session_id=session_id)
    assert detail["status"] == "running"
    assert detail["turns"][0]["status"] == "running"
    assert "PONG" not in json.dumps(detail, ensure_ascii=False)


async def test_reconcile_keeps_stale_running_turn_with_active_owner(session):
    stale_session = await CodingSessionService(session).create_session(
        uid="user-1",
        project_id="project-1",
        runtime_scope_id=SCOPE_KEY,
        executor="opencode",
        workdir_path=WORKDIR,
    )
    stale = await CodingSessionService(session).start_turn(stale_session, request_text="仍在执行")
    stale.started_at = stale.started_at.replace(year=2000)
    await session.commit()

    counts = await reconcile_coding_turns(
        stale_seconds=1,
        session_factory=_factory_for(session),
        enqueue=_async_noop,
        lease_service=_FakeLeaseService(active=True),
    )

    assert counts == {"republished": 0, "failed": 0}
    assert stale.status == "running"
    assert stale_session.status == "running"


async def _async_false(*_args, **_kwargs):
    return False


async def _async_true(*_args, **_kwargs):
    return True


async def _async_noop(*_args, **_kwargs):
    return None
