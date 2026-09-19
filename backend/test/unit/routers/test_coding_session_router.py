from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.coding_session_router import (
    get_coding_session,
    iter_coding_session_events,
    list_coding_sessions,
)
from yuxi.coding.adapters import NormalizedEvent
from yuxi.services.coding_session_service import CodingSessionService
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed(session):
    service = CodingSessionService(session)
    created = await service.create_session(
        uid="user_a",
        project_id="project-1",
        runtime_scope_id="agent-project:user_a:coder:project-1",
        executor="opencode",
        workdir_path="projects/project-1",
        conversation_id=7,
    )
    turn = await service.start_turn(created, request_text="实现登录")
    await service.record_events(
        created,
        turn_id=turn.id,
        events=[NormalizedEvent("output_delta", {"text": "done"})],
    )
    await service.finish_turn(created, turn, status="completed", result_summary="done")
    return created


async def test_coding_session_routes_scope_to_current_user(session):
    created = await _seed(session)
    user_a = SimpleNamespace(uid="user_a")

    listed = await list_coding_sessions(conversation_id=7, current_user=user_a, db=session)
    detail = await get_coding_session(
        created.id, after_seq=0, event_limit=100, current_user=user_a, db=session
    )

    assert [item["id"] for item in listed] == [created.id]
    assert listed[0]["status"] == "idle"
    assert detail["turns"][0]["seq"] == 1
    assert detail["turns"][0]["status"] == "completed"
    assert any(event["kind"] == "output_delta" for event in detail["events"])


async def test_event_stream_replays_events_and_ends_on_terminal(session):
    created = await _seed(session)
    service = CodingSessionService(session)
    await service.transition(created, status="cancelled")

    @asynccontextmanager
    async def factory():
        yield session

    frames = [
        frame
        async for frame in iter_coding_session_events(
            uid="user_a",
            session_id=created.id,
            after_seq=0,
            session_factory=factory,
            poll_seconds=0,
        )
    ]

    assert any(frame.startswith("event: coding_event") for frame in frames)
    assert frames[-1].startswith("event: coding_end")
    assert '"cancelled"' in frames[-1]


async def test_coding_session_detail_hides_other_users_sessions(session):
    created = await _seed(session)

    with pytest.raises(HTTPException) as exc_info:
        await get_coding_session(
            created.id,
            after_seq=0,
            event_limit=100,
            current_user=SimpleNamespace(uid="user_b"),
            db=session,
        )

    assert exc_info.value.status_code == 404
