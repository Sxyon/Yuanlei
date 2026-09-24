"""编码凭据引用模型供应商的单元测试：解析、自检、去重与指纹。"""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.coding.credentials import CodingCredentialOwner
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialUnavailableError,
    CodingCredentialWrite,
)
from yuxi.storage.postgres.models_business import Base, CodingCredential, ModelProvider
from yuxi.utils.datetime_utils import utc_now_naive

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")
PROVIDER_ID = "siliconflow-cn"


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


async def _seed_provider(
    session,
    *,
    provider_id: str = PROVIDER_ID,
    api_key: str | None = "sk-provider",
    is_enabled: bool = True,
    models: list[dict] | None = None,
    base_url: str = "https://api.siliconflow.cn/v1",
    display_name: str = "SiliconFlow",
) -> ModelProvider:
    provider = ModelProvider(
        provider_id=provider_id,
        display_name=display_name,
        provider_type="openai",
        base_url=base_url,
        api_key=api_key,
        capabilities=["chat"],
        enabled_models=models
        if models is not None
        else [{"id": "m1", "type": "chat", "display_name": "M1"}],
        is_enabled=is_enabled,
        is_builtin=False,
    )
    session.add(provider)
    await session.flush()
    return provider


def _reference_write(**overrides) -> CodingCredentialWrite:
    payload = {
        "executor": "opencode",
        "source": "model_provider",
        "model_provider_id": PROVIDER_ID,
        "key_mode": "inherit",
        "model": "m1",
    }
    payload.update(overrides)
    return CodingCredentialWrite(**payload)


async def test_reference_inherit_resolves_provider_key_and_channel(session):
    """共用密钥：渠道/模型/密钥都来自供应商，行内不存密文。"""
    await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))

    row = await service.upsert(
        scope="user", uid="user-1", payload=_reference_write(), actor="user-1"
    )
    assert row.source == "model_provider"
    assert row.key_mode == "inherit"
    assert row.model_provider_id == PROVIDER_ID
    assert row.provider == PROVIDER_ID
    assert row.api_key_cipher is None

    resolved = await service.resolve(uid="user-1", executor="opencode")
    assert resolved.mode == "model_provider"
    assert resolved.provider == PROVIDER_ID
    assert resolved.api_key == "sk-provider"
    assert resolved.base_url == "https://api.siliconflow.cn/v1"
    assert resolved.model == "m1"
    assert resolved.extra == {}

    masked = await service.list_masked(scope="user", uid="user-1")
    assert masked[0]["availability"] == "active"
    assert masked[0]["provider_display_name"] == "SiliconFlow"
    assert masked[0]["model"] == "m1"
    assert masked[0]["has_key"] is False
    assert "sk-provider" not in str(masked)


async def test_reference_custom_key_keeps_provider_channel(session):
    """单独密钥：渠道/模型跟随供应商，密钥只加密存在本表。"""
    await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))
    await service.upsert(
        scope="user",
        uid="user-1",
        payload=_reference_write(key_mode="custom", api_key="sk-custom"),
        actor="user-1",
    )

    resolved = await service.resolve(uid="user-1", executor="opencode")
    assert resolved.key_mode == "custom"
    assert resolved.api_key == "sk-custom"
    assert resolved.base_url == "https://api.siliconflow.cn/v1"

    row = (await session.execute(select(CodingCredential))).scalars().one()
    assert row.api_key_cipher is not None


async def test_reference_write_rejects_invalid_combinations(session):
    """写入边界拒绝：inherit 带 key、custom 缺 key、未知模型、停用供应商。"""
    await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))

    with pytest.raises(ValueError, match="api_key"):
        await service.upsert(
            scope="user",
            uid="user-1",
            payload=_reference_write(api_key="sk-should-not-be-here"),
            actor="user-1",
        )
    with pytest.raises(ValueError, match="api_key"):
        await service.upsert(
            scope="user", uid="user-1", payload=_reference_write(key_mode="custom"), actor="user-1"
        )
    with pytest.raises(ValueError, match="不在供应商已启用模型"):
        await service.upsert(
            scope="user", uid="user-1", payload=_reference_write(model="unknown"), actor="user-1"
        )

    disabled = await _seed_provider(
        session, provider_id="disabled-provider", is_enabled=False, api_key="sk-x"
    )
    with pytest.raises(ValueError, match="已停用"):
        await service.upsert(
            scope="user",
            uid="user-1",
            payload=_reference_write(model_provider_id=disabled.provider_id),
            actor="user-1",
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        ("provider_disabled", "provider_disabled"),
        ("provider_key_missing", "provider_key_missing"),
        ("model_removed", "model_not_enabled"),
    ],
)
async def test_reference_unavailable_reasons(session, mutate, reason):
    """供应商停用/缺 key/模型移除都在解析与自检中给出结构化原因。"""
    provider = await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))
    await service.upsert(
        scope="user", uid="user-1", payload=_reference_write(), actor="user-1"
    )

    if mutate == "provider_disabled":
        provider.is_enabled = False
    elif mutate == "provider_key_missing":
        provider.api_key = None
    else:
        provider.enabled_models = [{"id": "other", "type": "chat"}]
    await session.flush()

    with pytest.raises(CodingCredentialUnavailableError) as excinfo:
        await service.resolve(uid="user-1", executor="opencode")
    assert excinfo.value.reason == reason

    masked = await service.list_masked(scope="user", uid="user-1")
    assert masked[0]["availability"] == "unavailable"
    assert masked[0]["unavailable_reason"] == reason

    environment = await service.build_coding_environment(uid="user-1", executors=["opencode"])
    assert environment.env == {}
    assert environment.unavailable[0]["reason"] == reason
    with pytest.raises(CodingCredentialUnavailableError):
        environment.require_executor("opencode")


async def test_reference_missing_provider_is_unavailable(session):
    """供应商被删除后，引用自检与解析都给出 provider_missing。"""
    provider = await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))
    await service.upsert(
        scope="user", uid="user-1", payload=_reference_write(), actor="user-1"
    )
    await session.delete(provider)
    await session.flush()

    with pytest.raises(CodingCredentialUnavailableError) as excinfo:
        await service.resolve(uid="user-1", executor="opencode")
    assert excinfo.value.reason == "provider_missing"


async def test_reference_fingerprint_tracks_provider_changes(session):
    """指纹跟随供应商密钥/端点/模型，不跟随展示名。"""
    provider = await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))
    await service.upsert(
        scope="user", uid="user-1", payload=_reference_write(), actor="user-1"
    )

    first = await service.resolve(uid="user-1", executor="opencode")

    provider.display_name = "Renamed"
    await session.flush()
    assert (await service.resolve(uid="user-1", executor="opencode")).fingerprint == first.fingerprint

    provider.api_key = "sk-rotated"
    await session.flush()
    rotated = await service.resolve(uid="user-1", executor="opencode")
    assert rotated.fingerprint != first.fingerprint
    assert rotated.api_key == "sk-rotated"

    provider.base_url = "https://new.example.com/v1"
    await session.flush()
    assert (await service.resolve(uid="user-1", executor="opencode")).fingerprint != rotated.fingerprint


async def test_upsert_keeps_single_active_row_per_executor(session):
    """切换模式或供应商后，同执行器旧行被停用并清理密文。"""
    await _seed_provider(session)
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))
    await service.upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(executor="opencode", provider="sf", api_key="sk-manual"),
        actor="user-1",
    )
    await service.upsert(
        scope="user", uid="user-1", payload=_reference_write(), actor="user-1"
    )

    rows = (
        await session.execute(
            select(CodingCredential).order_by(CodingCredential.created_at, CodingCredential.id)
        )
    ).scalars().all()
    active = [row for row in rows if row.status == "active"]
    assert len(rows) == 2
    assert len(active) == 1
    assert active[0].source == "model_provider"
    assert all(row.api_key_cipher is None for row in rows if row.status == "deleted")


async def test_resolve_prefers_latest_within_scope(session):
    """同层多条 active 时按最近更新解析，而非字典序。"""
    await _seed_provider(session)
    owner = CodingCredentialOwner(key=b"0" * 32)
    service = CodingCredentialService(session, owner=owner)
    repo = service.repo

    async def seed_row(credential_id: str, provider: str, key: str, updated_at):
        encrypted = owner.encrypt(
            scope="user",
            uid="user-1",
            executor="opencode",
            provider=provider,
            plaintext=key,
            credential_id=credential_id,
        )
        return await repo.upsert(
            credential_id=credential_id,
            scope="user",
            uid="user-1",
            executor="opencode",
            provider=provider,
            source="manual",
            base_url=None,
            model=None,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
            extra={},
            actor="user-1",
            now=updated_at,
        )

    older = await seed_row("older", "aaa-first", "sk-old", utc_now_naive() - timedelta(hours=2))
    await seed_row("newer", "zzz-latest", "sk-new", utc_now_naive())
    assert older.provider < "zzz-latest"

    resolved = await service.resolve(uid="user-1", executor="opencode")

    assert resolved.provider == "zzz-latest"
    assert resolved.api_key == "sk-new"


async def test_list_model_provider_options_masks_keys(session):
    """选择器返回掩码选项与 chat 模型，不泄漏密钥。"""
    await _seed_provider(session)
    await _seed_provider(
        session,
        provider_id="disabled-provider",
        is_enabled=False,
        api_key="sk-hidden",
        models=[{"id": "m2", "type": "chat"}],
    )
    service = CodingCredentialService(session, owner=CodingCredentialOwner(key=b"0" * 32))

    options = await service.list_model_provider_options()

    assert {option["provider_id"] for option in options} == {PROVIDER_ID, "disabled-provider"}
    assert "sk-provider" not in str(options)
    assert "sk-hidden" not in str(options)
    disabled = next(item for item in options if item["provider_id"] == "disabled-provider")
    assert disabled["is_enabled"] is False
    assert disabled["models"] == [{"id": "m2", "display_name": "m2"}]
