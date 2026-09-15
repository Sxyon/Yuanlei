from __future__ import annotations

from types import SimpleNamespace

import pytest
import yuxi.agents.backends.sandbox.provider as provider_module

from yuxi.agents.backends.sandbox.provider import sandbox_provisioner_token
from yuxi.agents.backends.sandbox.provisioner_client import ProvisionerClient


def test_provisioner_client_sends_bearer_token(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"sandboxes": [], "count": 0})

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.health()

    assert calls == [
        {
            "method": "GET",
            "url": "http://sandbox-provisioner:8002/health",
            "timeout": client._timeout,
            "headers": {"Authorization": "Bearer test-provisioner-token-that-is-long-enough"},
        }
    ]


def test_provisioner_client_can_disable_sandbox_environment(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"sandbox_id": "sandbox-1", "sandbox_url": "http://sandbox"},
        )

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.create("sandbox-1", "thread-1", "user-1", {"SECRET": "value"}, inherit_env=False)

    assert calls[0]["json"]["inherit_env"] is False
    create_timeout = calls[0]["timeout"]
    assert create_timeout is client._create_timeout
    assert create_timeout.connect == 20
    assert create_timeout.write == 20
    assert create_timeout.pool == 20
    assert create_timeout.read is None


def test_provisioner_client_sends_project_workdir_contract(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "sandbox_id": "sandbox-1",
                "sandbox_url": "http://sandbox",
                "generation": "generation-1",
                "workdir_path": "projects/11111111-1111-4111-8111-111111111111",
            },
        )

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    record = client.create(
        "sandbox-1", "root-thread", "user-1", workdir_path="projects/11111111-1111-4111-8111-111111111111"
    )

    assert calls[0]["json"]["workdir_path"] == "projects/11111111-1111-4111-8111-111111111111"
    assert record.generation == "generation-1"
    assert record.workdir_path == "projects/11111111-1111-4111-8111-111111111111"


def test_provisioner_client_delete_sends_expected_generation(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.delete("sandbox-1", expected_generation="generation-1")

    assert calls[0]["params"] == {"expected_generation": "generation-1"}
    assert calls[0]["timeout"] is client._delete_timeout
    assert client._delete_timeout.read == 120


def test_sandbox_provider_uses_configured_delete_timeout(monkeypatch):
    captured = {}

    def create_client(_url, *, token, delete_timeout_seconds):
        captured.update(
            token=token,
            delete_timeout_seconds=delete_timeout_seconds,
        )
        return SimpleNamespace()

    monkeypatch.setenv(
        "SANDBOX_PROVISIONER_TOKEN",
        "test-provisioner-token-that-is-long-enough",
    )
    monkeypatch.setenv("SANDBOX_PROVISIONER_DELETE_TIMEOUT_SECONDS", "90")
    monkeypatch.setattr(provider_module, "ProvisionerClient", create_client)

    provider_module.ProvisionerSandboxProvider()

    assert captured == {
        "token": "test-provisioner-token-that-is-long-enough",
        "delete_timeout_seconds": 90,
    }


def test_sandbox_provisioner_token_reads_environment(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVISIONER_TOKEN", "test-provisioner-token-that-is-long-enough")

    assert sandbox_provisioner_token() == "test-provisioner-token-that-is-long-enough"


def test_sandbox_provisioner_token_is_required(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROVISIONER_TOKEN", raising=False)

    with pytest.raises(ValueError, match="at least 32 characters"):
        sandbox_provisioner_token()
