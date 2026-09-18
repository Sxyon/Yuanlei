"""运行清单构建、脱敏与指纹规范化的单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yuxi.services import agent_run_manifest_service as manifest_service
from yuxi.services.agent_run_manifest_service import (
    _manifest_skill_scope,
    build_manifest_payload,
    canonical_json,
    compute_config_digest,
    compute_manifest_fingerprint,
    resolve_skill_entries,
)


class _FakeContext:
    """build_run_manifest_result 只要求可实例化、可更新字段。"""

    def update_from_dict(self, data: dict):
        for key, value in data.items():
            setattr(self, key, value)


@pytest.mark.asyncio
async def test_build_run_manifest_result_uses_project_scope_and_effective_context(monkeypatch):
    """执行边界必须带上项目范围校验，并使用项目覆盖后的有效配置。"""
    agent = SimpleNamespace(
        slug="employee",
        backend_id="ChatbotAgent",
        config_json={"context": {"model": "base-model"}},
    )
    run = SimpleNamespace(
        run_type="chat",
        agent_slug="employee",
        conversation_thread_id="thread-1",
        input_payload={},
    )

    class _AgentRepository:
        def __init__(self, _db):
            pass

        async def get_visible_by_slug(self, **_kwargs):
            return agent

    class _ConversationRepository:
        def __init__(self, _db):
            pass

        async def get_conversation_by_thread_id(self, _thread_id):
            return SimpleNamespace(project_id="project-1")

    class _Backend:
        context_schema = _FakeContext

    scope_calls: list[dict] = []

    async def _record_scope(**kwargs):
        scope_calls.append(kwargs)

    async def _effective_context(**_kwargs):
        return {"model": "project-model"}

    async def _runtime_skills(_context, *, db, user):
        return {}

    async def _skill_entries(*_args, **_kwargs):
        return []

    monkeypatch.setattr(manifest_service, "AgentRepository", _AgentRepository)
    monkeypatch.setattr(manifest_service, "ConversationRepository", _ConversationRepository)
    monkeypatch.setattr(manifest_service, "ensure_agent_project_scope", _record_scope)
    monkeypatch.setattr(manifest_service, "resolve_effective_agent_context", _effective_context)
    monkeypatch.setattr(manifest_service.agent_manager, "get_agent", lambda _backend_id: _Backend())
    monkeypatch.setattr(manifest_service, "resolve_runtime_skills_for_context", _runtime_skills)
    monkeypatch.setattr(manifest_service, "resolve_skill_entries", _skill_entries)

    result = await manifest_service.build_run_manifest_result(
        run=run,
        user=SimpleNamespace(uid="user-1"),
        db=object(),
    )

    assert scope_calls[0]["agent_slug"] == "employee"
    assert scope_calls[0]["project_id"] == "project-1"
    assert result.normalized_context == {"model": "project-model"}


def _manifest(**overrides):
    payload = {
        "run_type": "chat",
        "agent_slug": "main",
        "backend_id": "chatbot",
        "model_spec": "siliconflow-cn:Pro/MiniMaxAI/MiniMax-M2.5",
        "tool_approval_mode": "default",
        "normalized_context": {
            "model": "siliconflow-cn:Pro/MiniMaxAI/MiniMax-M2.5",
            "tools": ["fs", "web"],
            "mcps": [],
            "skills": ["code-review"],
            "max_execution_steps": 150,
            "model_retry_times": 2,
            "system_prompt": "You are a reviewer.",
            "summary_prompt": "Summarize: {messages}",
        },
        "limits": {"max_execution_steps": 150, "model_retry_times": 2},
        "skill_entries": [{"slug": "code-review", "version": "1.2.0", "content_hash": "abc123"}],
        "code_revision": None,
    }
    payload.update(overrides)
    return build_manifest_payload(
        run_type=payload["run_type"],
        agent_slug=payload["agent_slug"],
        backend_id=payload["backend_id"],
        model_spec=payload["model_spec"],
        tool_approval_mode=payload["tool_approval_mode"],
        normalized_context=payload["normalized_context"],
        skill_entries=payload["skill_entries"],
        code_revision=payload["code_revision"],
        limits=payload["limits"],
    )


def test_same_assets_produce_same_fingerprint_regardless_of_field_order():
    first = _manifest()
    second = _manifest(
        normalized_context={
            "skills": ["code-review"],
            "mcps": [],
            "tools": ["fs", "web"],
            "summary_prompt": "Summarize: {messages}",
            "system_prompt": "You are a reviewer.",
            "model_retry_times": 2,
            "max_execution_steps": 150,
            "model": "siliconflow-cn:Pro/MiniMaxAI/MiniMax-M2.5",
        }
    )

    assert compute_manifest_fingerprint(first) == compute_manifest_fingerprint(second)
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_different_assets_produce_different_fingerprint():
    changed = _manifest(skill_entries=[{"slug": "code-review", "version": "1.3.0", "content_hash": "abc123"}])

    assert compute_manifest_fingerprint(_manifest()) != compute_manifest_fingerprint(changed)


def test_preload_skill_config_changes_config_digest():
    base_context = _manifest()["config_digest"]
    changed_context = {
        **{
            "model": "siliconflow-cn:Pro/MiniMaxAI/MiniMax-M2.5",
            "tools": ["fs", "web"],
            "mcps": [],
            "skills": ["code-review"],
            "max_execution_steps": 150,
            "model_retry_times": 2,
            "system_prompt": "You are a reviewer.",
            "summary_prompt": "Summarize: {messages}",
        },
        "preload_skills": ["code-review"],
    }

    assert base_context != compute_config_digest(changed_context)


def test_preloaded_dependency_content_changes_manifest_fingerprint():
    normalized_context = {"skills": ["parent"], "preload_skills": ["parent"]}
    first_slugs, first_hashes, _ = _manifest_skill_scope(
        normalized_context,
        {
            "preloaded_skills": ["parent", "dependency"],
            "preloaded_skill_contents": {"parent": "first", "dependency": "dependency"},
        },
    )
    second_slugs, second_hashes, _ = _manifest_skill_scope(
        normalized_context,
        {
            "preloaded_skills": ["parent", "dependency"],
            "preloaded_skill_contents": {"parent": "changed", "dependency": "dependency"},
        },
    )

    assert first_slugs == second_slugs == ["parent", "dependency"]
    first = _manifest(
        skill_entries=[
            {"slug": slug, "version": None, "content_hash": None, "preload_content_hash": first_hashes[slug]}
            for slug in first_slugs
        ]
    )
    second = _manifest(
        skill_entries=[
            {"slug": slug, "version": None, "content_hash": None, "preload_content_hash": second_hashes[slug]}
            for slug in second_slugs
        ]
    )
    assert compute_manifest_fingerprint(first) != compute_manifest_fingerprint(second)


@pytest.mark.asyncio
async def test_personal_preloaded_skill_does_not_borrow_shadowed_database_identity():
    class FakeResult:
        def first(self):
            return type("Row", (), {"version": "shared-v1", "content_hash": "shared-hash"})()

    class FakeDB:
        async def execute(self, statement):
            del statement
            return FakeResult()

    entries = await resolve_skill_entries(
        FakeDB(),
        ["shadowed"],
        preload_content_hashes={"shadowed": "personal-root-hash"},
        personal_skill_slugs={"shadowed"},
    )

    assert entries == [
        {
            "slug": "shadowed",
            "version": None,
            "content_hash": None,
            "preload_content_hash": "personal-root-hash",
        }
    ]


def test_manifest_excludes_prompts_and_secret_shaped_values():
    context = {
        "system_prompt": "SECRET-PROMPT-BODY",
        "summary_prompt": "SECRET-SUMMARY-BODY",
        "api_key": "sk-live-abcdef",
        "token": "tok-live-abcdef",
        "tools": ["fs"],
        "mcps": [],
        "skills": [],
    }
    manifest = build_manifest_payload(
        run_type="chat",
        agent_slug="main",
        backend_id="chatbot",
        model_spec=None,
        tool_approval_mode=None,
        normalized_context=context,
        skill_entries=[],
        code_revision=None,
        limits={},
    )
    serialized = canonical_json(manifest)

    assert "SECRET-PROMPT-BODY" not in serialized
    assert "SECRET-SUMMARY-BODY" not in serialized
    assert "sk-live-abcdef" not in serialized
    assert "tok-live-abcdef" not in serialized
    # 未列入直接字段的 context 值只能以 config_digest 摘要存在。
    assert manifest["config_digest"] == compute_config_digest(context)
    assert manifest["resources"] == {
        "tools": ["fs"],
        "mcps": [],
        "skills": [],
        "git_repositories": [],
    }


def test_missing_code_revision_is_explicitly_unresolved():
    manifest = _manifest()

    assert manifest["code_revision"] == "unresolved"
    assert manifest["manifest_version"] == 3


def test_git_snapshot_is_explicit_and_excludes_remote_credentials():
    manifest = build_manifest_payload(
        run_type="chat",
        agent_slug="main",
        backend_id="chatbot",
        model_spec=None,
        tool_approval_mode="default",
        normalized_context={},
        skill_entries=[],
        code_revision="revision",
        limits={},
        git_repositories=[
            {
                "alias": "api",
                "repository_id": "repository-id",
                "purpose": "后端 API",
                "task_purpose": "实现退款",
                "path": "/home/gem/user-data/projects/p/repos/api/worktrees/task",
                "branch": "codex/task-abc",
                "base_branch": "main",
                "base_sha": "a" * 40,
                "selection_source": "user",
                "remote_url": "ssh://secret@example.invalid/repo.git",
                "private_key": "SECRET",
            }
        ],
    )

    serialized = canonical_json(manifest)
    assert "remote_url" not in serialized
    assert "private_key" not in serialized
    assert "SECRET" not in serialized
    # 运行时派生字段（path/branch/base_sha）不进入 manifest，避免 worktree
    # 准备进度导致 write-once 指纹漂移。
    assert "worktrees/task" not in serialized
    assert "codex/task-abc" not in serialized
    assert "a" * 40 not in serialized


def test_git_runtime_derived_fields_do_not_shift_manifest_fingerprint():
    """worktree 准备过程中 path/branch/base_sha 变化不应改变 manifest 指纹。"""
    base = {
        "alias": "api",
        "repository_id": "repository-id",
        "purpose": "后端 API",
        "task_purpose": "实现退款",
        "base_branch": "main",
        "selection_source": "user",
    }

    def _manifest_with_git(**git_overrides):
        git = dict(base)
        git.update(git_overrides)
        return build_manifest_payload(
            run_type="chat",
            agent_slug="main",
            backend_id="chatbot",
            model_spec=None,
            tool_approval_mode="default",
            normalized_context={},
            skill_entries=[],
            code_revision="revision",
            limits={},
            git_repositories=[git],
        )

    # base_sha 从 None 落到真实 SHA、path/branch 随分配进度变化，指纹必须保持一致。
    preparing = _manifest_with_git(path="/tmp/unprepared", branch="codex/task-abc", base_sha=None)
    ready = _manifest_with_git(
        path="/home/gem/user-data/projects/p/repos/api/worktrees/task",
        branch="codex/task-abc",
        base_sha="a" * 40,
    )

    assert compute_manifest_fingerprint(preparing) == compute_manifest_fingerprint(ready)


def test_git_identity_field_change_does_shift_manifest_fingerprint():
    """仓库身份字段（alias/repository_id/base_branch）变化必须改变 manifest 指纹。"""

    def _manifest_with_git(**overrides):
        base = {
            "alias": "api",
            "repository_id": "repository-id",
            "purpose": "后端 API",
            "task_purpose": "实现退款",
            "base_branch": "main",
            "selection_source": "user",
        }
        base.update(overrides)
        return build_manifest_payload(
            run_type="chat",
            agent_slug="main",
            backend_id="chatbot",
            model_spec=None,
            tool_approval_mode="default",
            normalized_context={},
            skill_entries=[],
            code_revision="revision",
            limits={},
            git_repositories=[base],
        )

    baseline = _manifest_with_git()
    assert compute_manifest_fingerprint(baseline) != compute_manifest_fingerprint(
        _manifest_with_git(repository_id="other-repository-id")
    )
    assert compute_manifest_fingerprint(baseline) != compute_manifest_fingerprint(
        _manifest_with_git(base_branch="develop")
    )


def test_non_string_model_spec_normalizes_to_none():
    manifest = _manifest(model_spec="")

    assert manifest["model"] == {"spec": None}


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("max_execution_steps", 150),
        ("model_retry_times", 2),
    ],
)
def test_limits_captured_from_context(field, expected):
    assert _manifest()["limits"][field] == expected


def test_effective_limits_fill_schema_defaults_for_unset_fields():
    from yuxi.agents.context import BaseContext
    from yuxi.services.agent_run_manifest_service import _effective_limits

    class FakeBackend:
        context_schema = BaseContext

    effective = _effective_limits(FakeBackend(), {"max_execution_steps": 200})

    assert effective["max_execution_steps"] == 200
    assert effective["model_retry_times"] == 2
    assert _effective_limits(None, {"max_execution_steps": 200})["model_retry_times"] is None
