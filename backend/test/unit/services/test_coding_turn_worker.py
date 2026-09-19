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
    def __init__(self, output: str, *, state_present: bool = True):
        self.output = output
        self.state_present = state_present

    def execute(self, command: str, timeout: int | None = None):
        if command.startswith("test -d"):
            output = "__PRESENT__" if self.state_present else ""
            return SimpleNamespace(output=output, exit_code=0, truncated=False)
        return SimpleNamespace(output=self.output, exit_code=0, truncated=False)


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
    )
    turn = await service.queue_turn(created, request_text="后台执行")
    await session.commit()
    return created, turn


async def test_job_executes_pending_turn(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    result = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        plan_only=True,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
    )

    assert result["status"] == "idle"
    assert result["output_text"] == "PONG"
    detail = await CodingSessionService(session).session_detail(
        uid="user-1", session_id=created.id
    )
    assert detail["turns"][0]["status"] == "completed"
    assert "turn_queued" in [event["kind"] for event in detail["events"]]


async def test_job_skips_terminal_turn(session, monkeypatch):
    monkeypatch.setattr(execution_module, "coding_cancel_requested", _async_false)
    created, turn = await _seed_pending_turn(session)

    await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
    )
    replay = await run_coding_turn_job(
        session_id=created.id,
        turn_id=turn.id,
        session_factory=_factory_for(session),
        provider=_FakeProvider(),
        backend=_FakeBackend(OPENCODE_OUTPUT),
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
    )

    assert result["status"] == "cancelled"
    detail = await CodingSessionService(session).session_detail(
        uid="user-1", session_id=created.id
    )
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


async def _async_false(*_args, **_kwargs):
    return False


async def _async_true(*_args, **_kwargs):
    return True


async def _async_noop(*_args, **_kwargs):
    return None
