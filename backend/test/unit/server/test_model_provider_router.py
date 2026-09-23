from types import SimpleNamespace

import pytest

from server.routers import model_provider_router
from server.routers.model_provider_router import ModelProviderPayload


def test_model_provider_payload_accepts_embedding_and_rerank_urls():
    payload = ModelProviderPayload(
        provider_id="mixed-provider",
        display_name="Mixed Provider",
        base_url="https://api.example.com/v1",
        embedding_base_url="https://api.example.com/v1/embeddings",
        rerank_base_url="https://api.example.com/v1/rerank",
        capabilities=["chat", "embedding", "rerank"],
    )

    data = payload.model_dump(exclude_none=True)

    assert data["embedding_base_url"] == "https://api.example.com/v1/embeddings"
    assert data["rerank_base_url"] == "https://api.example.com/v1/rerank"


@pytest.mark.asyncio
async def test_update_provider_commits_before_refreshing_cache(monkeypatch):
    calls = []

    class Db:
        async def commit(self):
            calls.append("commit")

    class User:
        username = "admin"

    class Provider:
        def to_dict(self):
            return {"provider_id": "alibaba"}

    async def fake_update_provider_config(db, provider_id, data, username):
        calls.append("update")
        return Provider()

    async def fake_refresh_model_cache():
        calls.append("refresh")

    monkeypatch.setattr(model_provider_router, "update_provider_config", fake_update_provider_config)
    monkeypatch.setattr(model_provider_router, "_refresh_model_cache", fake_refresh_model_cache)

    result = await model_provider_router.update_provider(
        "alibaba",
        ModelProviderPayload(enabled_models=[]),
        current_user=User(),
        db=Db(),
    )

    assert result == {"success": True, "data": {"provider_id": "alibaba"}}
    assert calls == ["update", "commit", "refresh"]


@pytest.mark.asyncio
async def test_v2_model_list_exposes_the_resolved_capability_profile(monkeypatch):
    """模型列表 API 把缓存中的能力档案直接交给选择器。"""
    from yuxi.models.providers.cache import model_cache

    profile = {
        "protocol": "openai_chat_completions",
        "input": {"image": "supported"},
        "image": {"tool_result": "lift_to_user"},
        "tool_calling": {"chat_completions": "unknown"},
        "provenance": {"source": "test", "matched_key": "openai:openai_chat_completions:gpt-6-sol"},
    }
    model = SimpleNamespace(
        spec="openai:gpt-6-sol",
        model_id="gpt-6-sol",
        display_name="GPT-6 Sol",
        dimension=None,
        batch_size=40,
        capabilities=profile,
    )
    monkeypatch.setattr(model_cache, "get_specs_grouped_by_provider", lambda _model_type: {"openai": [model]})

    async def fake_get_all_model_providers(_db):
        """提供模型选择器所需的供应商展示名。"""
        return [SimpleNamespace(provider_id="openai", display_name="OpenAI")]

    monkeypatch.setattr(model_provider_router, "get_all_model_providers", fake_get_all_model_providers)

    result = await model_provider_router.get_v2_models(model_type="chat", _current_user=object(), db=object())

    assert result["data"]["openai"]["models"][0]["capabilities"] == profile
