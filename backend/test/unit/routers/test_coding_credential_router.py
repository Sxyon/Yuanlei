from __future__ import annotations

import base64

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.coding_credential_router import (
    delete_user_coding_credential,
    list_user_coding_credentials,
    upsert_user_coding_credential,
)
from yuxi.storage.postgres.models_business import Base, Department, User

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")


class _FakeRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


@pytest_asyncio.fixture()
async def session(monkeypatch):
    monkeypatch.setenv("YUXI_CODING_CREDENTIAL_KEY", MASTER_KEY)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        department = Department(name="Coding Credential Dept")
        user = User(
            username="Coder",
            uid="user_coder",
            password_hash="$argon2id$placeholder",
            role="user",
            department=department,
        )
        db.add_all([department, user])
        await db.commit()
        await db.refresh(user)
        yield db, user
    await engine.dispose()


async def test_user_coding_credential_routes_are_write_only_and_scoped(session):
    db, user = session
    payload = {
        "executor": "opencode",
        "provider": "sf",
        "api_key": "sk-route-secret",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V4-Flash",
    }

    created = await upsert_user_coding_credential(
        request=_FakeRequest(payload), current_user=user, db=db
    )
    listed = await list_user_coding_credentials(current_user=user, db=db)

    assert created["has_key"] is True
    assert "api_key" not in created
    assert "sk-route-secret" not in str(created)
    assert len(listed) == 1
    assert listed[0]["executor"] == "opencode"

    deleted = await delete_user_coding_credential(
        executor="opencode", provider="sf", current_user=user, db=db
    )
    assert deleted == {"success": True}
    assert await list_user_coding_credentials(current_user=user, db=db) == []

    with pytest.raises(HTTPException) as exc_info:
        await delete_user_coding_credential(
            executor="opencode", provider="sf", current_user=user, db=db
        )
    assert exc_info.value.status_code == 404


async def test_user_coding_credential_route_rejects_unknown_executor(session):
    db, user = session

    with pytest.raises(HTTPException) as exc_info:
        await upsert_user_coding_credential(
            request=_FakeRequest({"executor": "aider", "provider": "sf", "api_key": "sk-x"}),
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == 422
