"""编码凭据引用模型供应商的真实 API 集成测试（PostgreSQL）。"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_provider(test_client, headers, *, label: str) -> str:
    provider_id = f"pytest-coding-ref-{label}-{uuid.uuid4().hex[:8]}"
    response = await test_client.post(
        "/api/system/model-providers",
        headers=headers,
        json={
            "provider_id": provider_id,
            "display_name": f"Pytest 引用供应商 {label}",
            "provider_type": "openai",
            "default_protocol": "openai_compatible",
            "base_url": "https://api.pytest.example.com/v1",
            "api_key": "sk-pytest-provider-secret",
            "capabilities": ["chat"],
            "enabled_models": [{"id": "pytest-chat-model", "type": "chat"}],
            "is_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    return provider_id


async def test_manual_coding_credential_save_requires_live_master_key(test_client, admin_headers):
    """手动模式会真实加密：验证 api 容器已注入 YUXI_CODING_CREDENTIAL_KEY。"""
    await test_client.delete(
        "/api/user/coding-credentials",
        headers=admin_headers,
        params={"executor": "opencode", "provider": "pytest-manual"},
    )
    try:
        saved = await test_client.put(
            "/api/user/coding-credentials",
            headers=admin_headers,
            json={
                "executor": "opencode",
                "source": "manual",
                "provider": "pytest-manual",
                "api_key": "sk-pytest-manual-secret",
                "base_url": "https://api.pytest.example.com/v1",
                "model": "pytest-model",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["has_key"] is True
        assert "sk-pytest-manual-secret" not in saved.text

        listed = await test_client.get("/api/user/coding-credentials", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        item = next(
            entry
            for entry in listed.json()
            if entry["executor"] == "opencode" and entry["provider"] == "pytest-manual"
        )
        assert item["availability"] == "active"
        assert item["source"] == "manual"
    finally:
        await test_client.delete(
            "/api/user/coding-credentials",
            headers=admin_headers,
            params={"executor": "opencode", "provider": "pytest-manual"},
        )


async def test_coding_credential_provider_reference_lifecycle(test_client, admin_headers):
    """引用凭据可保存、自检；供应商停用后标记不可用且选择器不泄漏密钥。"""
    provider_id = await _create_provider(test_client, admin_headers, label="lifecycle")
    try:
        saved = await test_client.put(
            "/api/user/coding-credentials",
            headers=admin_headers,
            json={
                "executor": "opencode",
                "source": "model_provider",
                "model_provider_id": provider_id,
                "key_mode": "inherit",
                "model": "pytest-chat-model",
            },
        )
        assert saved.status_code == 200, saved.text
        created = saved.json()
        assert created["source"] == "model_provider"
        assert created["key_mode"] == "inherit"
        assert created["has_key"] is False
        assert "sk-pytest-provider-secret" not in saved.text

        listed = await test_client.get("/api/user/coding-credentials", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        item = next(entry for entry in listed.json() if entry["executor"] == "opencode")
        assert item["availability"] == "active"
        assert item["provider_display_name"].startswith("Pytest 引用供应商")
        assert item["base_url"] == "https://api.pytest.example.com/v1"
        assert item["model"] == "pytest-chat-model"

        options = await test_client.get(
            "/api/user/coding-credentials/model-providers", headers=admin_headers
        )
        assert options.status_code == 200, options.text
        option = next(
            entry for entry in options.json() if entry["provider_id"] == provider_id
        )
        assert option["models"] == [{"id": "pytest-chat-model", "display_name": "pytest-chat-model"}]
        assert "sk-pytest-provider-secret" not in options.text

        disabled = await test_client.put(
            f"/api/system/model-providers/{provider_id}",
            headers=admin_headers,
            json={"is_enabled": False},
        )
        assert disabled.status_code == 200, disabled.text

        unavailable = await test_client.get("/api/user/coding-credentials", headers=admin_headers)
        item = next(
            entry for entry in unavailable.json() if entry["executor"] == "opencode"
        )
        assert item["availability"] == "unavailable"
        assert item["unavailable_reason"] == "provider_disabled"

        options = await test_client.get(
            "/api/user/coding-credentials/model-providers", headers=admin_headers
        )
        option = next(
            entry for entry in options.json() if entry["provider_id"] == provider_id
        )
        assert option["is_enabled"] is False

        invalid = await test_client.put(
            "/api/user/coding-credentials",
            headers=admin_headers,
            json={
                "executor": "opencode",
                "source": "model_provider",
                "model_provider_id": provider_id,
                "key_mode": "inherit",
                "model": "unknown-model",
            },
        )
        assert invalid.status_code == 422, invalid.text
    finally:
        await test_client.delete(
            "/api/user/coding-credentials",
            headers=admin_headers,
            params={"executor": "opencode", "provider": provider_id},
        )
        await test_client.delete(
            f"/api/system/model-providers/{provider_id}", headers=admin_headers
        )
