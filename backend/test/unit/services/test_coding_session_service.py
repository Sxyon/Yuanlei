from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.coding.adapters import NormalizedEvent
from yuxi.repositories.coding_session_repository import CodingSessionRepository
from yuxi.services.coding_session_service import (
    CodingSessionService,
    CodingSessionStateError,
)
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

SCOPE_KEY = "agent-project:user-1:coder:project-1"


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _create(session):
    service = CodingSessionService(session)
    created = await service.create_session(
        uid="user-1",
        project_id="project-1",
        runtime_scope_id=SCOPE_KEY,
        executor="opencode",
        workdir_path="projects/probe",
        conversation_id=7,
        parent_run_id="run-1",
    )
    return service, created


async def test_create_session_starts_pending_with_event(session):
    _, created = await _create(session)
    events = await CodingSessionRepository(session).list_events(session_id=created.id)

    assert created.status == "pending"
    assert created.policy_json == {}
    assert [event.kind for event in events] == ["session_status"]
    assert events[0].payload_json == {"status": "pending"}


async def test_turn_lifecycle_and_seq_allocation(session):
    service, created = await _create(session)

    first = await service.start_turn(created, request_text="第一轮")
    await service.record_events(
        created,
        turn_id=first.id,
        events=[
            NormalizedEvent("output_delta", {"text": "PONG"}),
            NormalizedEvent("usage", {"tokens": {"total": 3}}),
        ],
    )
    await service.finish_turn(
        created,
        first,
        status="completed",
        result_summary="PONG",
        usage={"tokens": {"total": 3}},
        cli_session_ref="ses_1",
    )

    assert created.status == "idle"
    assert created.cli_session_ref == "ses_1"
    assert first.seq == 1
    assert first.status == "completed"

    second = await service.start_turn(created, request_text="第二轮")
    assert second.seq == 2
    assert created.status == "running"

    events = await CodingSessionRepository(session).list_events(session_id=created.id)
    assert [event.seq for event in events] == list(range(1, 12))
    assert [event.kind for event in events] == [
        "session_status",
        "session_status",
        "session_status",
        "session_status",
        "turn_started",
        "output_delta",
        "usage",
        "turn_finished",
        "session_status",
        "session_status",
        "turn_started",
    ]


async def test_finish_turn_failure_marks_session_failed(session):
    service, created = await _create(session)
    turn = await service.start_turn(created, request_text="会失败的轮次")

    await service.finish_turn(
        created,
        turn,
        status="failed",
        error_code="executor_error",
        error_message="boom",
    )

    assert created.status == "failed"
    assert created.error_code == "executor_error"
    assert created.terminal_at is not None
    with pytest.raises(CodingSessionStateError, match="not ready for a new turn"):
        await service.start_turn(created, request_text="不允许的新轮次")


async def test_record_events_after_seq_replay(session):
    service, created = await _create(session)
    turn = await service.start_turn(created, request_text="一轮")
    await service.record_events(
        created,
        turn_id=turn.id,
        events=[NormalizedEvent("output_delta", {"text": "a"}), NormalizedEvent("warning", {"m": "x"})],
    )

    repo = CodingSessionRepository(session)
    replayed = await repo.list_events(session_id=created.id, after_seq=5)

    assert [event.kind for event in replayed] == ["output_delta", "warning"]
