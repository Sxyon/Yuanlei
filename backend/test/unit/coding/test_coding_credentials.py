from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.exceptions import InvalidTag
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.coding.credentials import (
    CodingCredentialOwner,
    CodingNotConfiguredError,
    credential_fingerprint,
    redact_credential_values,
)
from yuxi.services.coding_credential_service import (
    CodingCredentialMissingError,
    CodingCredentialService,
    CodingCredentialWrite,
    mask_credential,
)
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

KEY = b"0" * 32


def _owner() -> CodingCredentialOwner:
    return CodingCredentialOwner(key=KEY)


async def test_cipher_roundtrip_binds_scope_and_identity():
    owner = _owner()
    encrypted = owner.encrypt(
        scope="user",
        uid="user-1",
        executor="opencode",
        provider="sf",
        plaintext="sk-secret-value",
    )
    credential = type(
        "_Row",
        (),
        {
            "id": encrypted.id,
            "scope": "user",
            "uid": "user-1",
            "executor": "opencode",
            "provider": "sf",
            "api_key_cipher": encrypted.ciphertext,
            "nonce": encrypted.nonce,
            "key_version": encrypted.key_version,
            "status": "active",
        },
    )()

    assert owner.decrypt(credential) == "sk-secret-value"

    credential.scope = "global"
    with pytest.raises(InvalidTag):
        owner.decrypt(credential)


async def test_cipher_fails_closed_without_master_key(monkeypatch):
    monkeypatch.delenv("YUXI_CODING_CREDENTIAL_KEY", raising=False)

    with pytest.raises(CodingNotConfiguredError, match="not configured"):
        CodingCredentialOwner()


async def test_cipher_rejects_wrong_key_length():
    with pytest.raises(CodingNotConfiguredError, match="32 bytes"):
        CodingCredentialOwner(key=b"short")


async def test_fingerprint_changes_with_secret_version_and_config():
    base = credential_fingerprint(
        executor="codex",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
        secret_version=1,
    )
    rotated = credential_fingerprint(
        executor="codex",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
        secret_version=2,
    )
    changed_model = credential_fingerprint(
        executor="codex",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        secret_version=1,
    )

    assert base == credential_fingerprint(
        executor="codex",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-flash",
        secret_version=1,
    )
    assert base != rotated
    assert base != changed_model


async def test_redaction_replaces_known_secret_values_only():
    text = "using key sk-abcdefgh and short ab"

    assert redact_credential_values(text, ["sk-abcdefgh", "ab"]) == "using key [redacted] and short ab"
    assert redact_credential_values(text, []) == text


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _upsert_user(session, *, provider="sf", api_key="sk-user-secret", model="m-1"):
    service = CodingCredentialService(session, owner=_owner())
    return await service.upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(
            executor="opencode",
            provider=provider,
            api_key=api_key,
            base_url="https://api.siliconflow.cn/v1",
            model=model,
        ),
        actor="user-1",
    )


async def test_upsert_masks_reads_and_resolves(session):
    row = await _upsert_user(session)
    service = CodingCredentialService(session, owner=_owner())

    masked = mask_credential(row)
    assert masked["has_key"] is True
    assert "api_key" not in masked
    assert "sk-user-secret" not in str(masked)

    resolved = await service.resolve(uid="user-1", executor="opencode")
    assert resolved.api_key == "sk-user-secret"
    assert resolved.source == "user"
    assert resolved.model == "m-1"
    assert len(resolved.fingerprint) == 64


async def test_resolution_prefers_user_then_global(session):
    service = CodingCredentialService(session, owner=_owner())
    await service.upsert(
        scope="global",
        uid=None,
        payload=CodingCredentialWrite(executor="codex", provider="deepseek", api_key="sk-global"),
        actor="admin",
    )

    from_global = await service.resolve(uid="user-1", executor="codex")
    assert from_global.api_key == "sk-global"
    assert from_global.source == "global"

    await service.upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(executor="codex", provider="deepseek", api_key="sk-user"),
        actor="user-1",
    )
    from_user = await service.resolve(uid="user-1", executor="codex")
    assert from_user.api_key == "sk-user"
    assert from_user.source == "user"

    other_user = await service.resolve(uid="user-2", executor="codex")
    assert other_user.api_key == "sk-global"


async def test_resolution_fails_explicitly_when_missing(session):
    service = CodingCredentialService(session, owner=_owner())

    with pytest.raises(CodingCredentialMissingError, match="credential_missing"):
        await service.resolve(uid="user-1", executor="opencode")


async def test_rotation_changes_fingerprint_and_delete_destroys(session):
    service = CodingCredentialService(session, owner=_owner())
    first = await _upsert_user(session, api_key="sk-1")
    first_version = int(first.version)
    fingerprint_before = (
        await service.resolve(uid="user-1", executor="opencode")
    ).fingerprint

    rotated = await service.upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(executor="opencode", provider="sf", api_key="sk-2"),
        actor="user-1",
    )
    fingerprint_after = (
        await service.resolve(uid="user-1", executor="opencode")
    ).fingerprint

    assert rotated.version == first_version + 1
    assert fingerprint_after != fingerprint_before

    assert await service.delete(scope="user", uid="user-1", executor="opencode", provider="sf", actor="user-1")
    with pytest.raises(CodingCredentialMissingError):
        await service.resolve(uid="user-1", executor="opencode")
    assert await service.delete(scope="user", uid="user-1", executor="opencode", provider="sf", actor="user-1") is False


async def test_upsert_rejects_unknown_executor(session):
    service = CodingCredentialService(session, owner=_owner())

    with pytest.raises(ValueError, match="executor"):
        await service.upsert(
            scope="user",
            uid="user-1",
            payload=CodingCredentialWrite(executor="aider", provider="sf", api_key="sk-x"),
            actor="user-1",
        )
