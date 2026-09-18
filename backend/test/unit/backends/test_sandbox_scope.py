from __future__ import annotations

import threading

import pytest

from yuxi.agents.backends.sandbox import (
    ProvisionerSandboxProvider,
    SandboxScope,
    sandbox_id_for_thread,
)


def _make_provider(client) -> ProvisionerSandboxProvider:
    provider = ProvisionerSandboxProvider.__new__(ProvisionerSandboxProvider)
    provider._client = client
    provider._lock = threading.Lock()
    provider._thread_locks = {}
    provider._connections = {}
    provider._last_touch_at = {}
    provider._touch_interval_seconds = 30
    provider._release_lock_timeout_seconds = 0.05
    return provider


class _RecordingClient:
    def __init__(self):
        self.created: list[dict] = []
        self.deleted: list[tuple[str, str | None]] = []
        self.records: dict[str, object] = {}

    def create(self, sandbox_id, identity, _uid, _env, *, workdir_path, inherit_env, lifecycle=None, idle_timeout_seconds=None):
        self.created.append(
            {
                "sandbox_id": sandbox_id,
                "identity": identity,
                "workdir_path": workdir_path,
                "inherit_env": inherit_env,
                "lifecycle": lifecycle,
                "idle_timeout_seconds": idle_timeout_seconds,
            }
        )
        record = type(
            "_Record",
            (),
            {
                "sandbox_id": sandbox_id,
                "sandbox_url": f"http://sandbox/{sandbox_id}",
                "generation": f"gen-{sandbox_id}",
                "workdir_path": workdir_path,
            },
        )()
        self.records[sandbox_id] = record
        return record

    def discover(self, sandbox_id):
        return self.records.get(sandbox_id)

    def touch(self, _sandbox_id):
        return True

    def delete(self, sandbox_id, *, expected_generation=None):
        self.deleted.append((sandbox_id, expected_generation))
        self.records.pop(sandbox_id, None)


WORKDIR = "projects/11111111-1111-4111-8111-111111111111"


def test_scope_validates_required_identity_fields():
    assert SandboxScope.thread(uid="user-1", thread_id="thread-1").kind == "thread"
    with pytest.raises(ValueError):
        SandboxScope.thread(uid="user-1", thread_id="")
    with pytest.raises(ValueError):
        SandboxScope.agent_project(uid="user-1", agent_slug="", project_id="p-1")
    with pytest.raises(ValueError):
        SandboxScope.agent_project(uid="user-1", agent_slug="a-1", project_id="")


def test_thread_scope_keeps_legacy_cache_key_and_sandbox_id():
    scope = SandboxScope.thread(uid="user-1", thread_id="thread-1")

    assert scope.cache_key == "user-1::thread-1"
    assert scope.sandbox_id == sandbox_id_for_thread("thread-1", uid="user-1")
    assert scope.provisioner_identity == "thread-1"


def test_agent_project_scope_is_deterministic_and_isolated():
    scope = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")
    same = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")
    other_project = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-2")
    other_agent = SandboxScope.agent_project(uid="user-1", agent_slug="reviewer", project_id="project-1")

    assert scope.cache_key == "agent-project:user-1:coder:project-1"
    assert scope.sandbox_id == same.sandbox_id
    assert len({scope.sandbox_id, other_project.sandbox_id, other_agent.sandbox_id}) == 3
    assert scope.sandbox_id != SandboxScope.thread(uid="user-1", thread_id="project-1").sandbox_id


def test_agent_project_scope_sanitizes_provisioner_identity():
    scope = SandboxScope.agent_project(uid="user:1", agent_slug="co der", project_id="p/1")

    assert scope.provisioner_identity == "agent-project-user-1-co-der-p-1"


def test_provider_creates_agent_project_sandbox_with_scope_identity(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})
    scope = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")

    connection = provider.get_scope(scope, create_if_missing=True, workdir_path=WORKDIR)

    assert connection is not None
    assert connection.scope_kind == "agent_project"
    assert connection.agent_slug == "coder"
    assert connection.project_id == "project-1"
    assert connection.thread_id is None
    assert client.created[0]["sandbox_id"] == scope.sandbox_id
    assert client.created[0]["identity"] == scope.provisioner_identity
    assert client.created[0]["workdir_path"] == WORKDIR


def test_provider_isolates_thread_and_agent_project_caches(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})

    thread_connection = provider.get_scope(
        SandboxScope.thread(uid="user-1", thread_id="thread-1"),
        create_if_missing=True,
        workdir_path=WORKDIR,
    )
    project_connection = provider.get_scope(
        SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1"),
        create_if_missing=True,
        workdir_path=WORKDIR,
    )

    assert thread_connection is not None and project_connection is not None
    assert thread_connection.cache_key != project_connection.cache_key
    assert thread_connection.sandbox_id != project_connection.sandbox_id
    assert len(client.created) == 2


def test_provider_rejects_agent_project_identity_mismatch_on_cached_connection(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})
    provider.get_scope(
        SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1"),
        create_if_missing=True,
        workdir_path=WORKDIR,
    )

    # 同一缓存键只可能来自同一 scope；构造人为错配验证防御性校验。
    connection = next(iter(provider._connections.values()))
    connection.agent_slug = "reviewer"

    with pytest.raises(Exception, match="Agent/Project"):
        provider.get_scope(
            SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1"),
            workdir_path=WORKDIR,
        )


def test_scope_from_runtime_scope_parses_dedicated_and_legacy():
    dedicated = SandboxScope.from_runtime_scope(
        uid="user-1", runtime_scope_id="agent-project:user-1:coder:project-1"
    )
    assert dedicated.kind == "agent_project"
    assert dedicated.agent_slug == "coder"
    assert dedicated.project_id == "project-1"

    legacy = SandboxScope.from_runtime_scope(uid="user-1", runtime_scope_id="thread-1")
    assert legacy.kind == "thread"
    assert legacy.cache_key == "user-1::thread-1"


def test_scope_from_cache_key_round_trips_both_formats():
    assert SandboxScope.from_cache_key("agent-project:user-1:coder:project-1") == SandboxScope.agent_project(
        uid="user-1", agent_slug="coder", project_id="project-1"
    )
    assert SandboxScope.from_cache_key("user-1::thread-1") == SandboxScope.thread(
        uid="user-1", thread_id="thread-1"
    )
    with pytest.raises(ValueError):
        SandboxScope.from_cache_key("thread-1")


def test_provider_forwards_lifecycle_policy_to_provisioner(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})
    scope = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")

    connection = provider.get_scope(
        scope,
        create_if_missing=True,
        workdir_path=WORKDIR,
        lifecycle="persistent",
        idle_timeout_seconds=1800,
    )

    assert connection is not None
    assert client.created[0]["lifecycle"] == "persistent"
    assert client.created[0]["idle_timeout_seconds"] == 1800


def test_thread_scope_keepalive_omits_policy_fields(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})

    provider.get("thread-1", uid="user-1", create_if_missing=True, workdir_path=WORKDIR)

    assert client.created[0]["lifecycle"] is None
    assert client.created[0]["idle_timeout_seconds"] is None


def test_provider_release_scope_deletes_by_scope_sandbox_id(monkeypatch):
    client = _RecordingClient()
    provider = _make_provider(client)
    monkeypatch.setattr("yuxi.agents.backends.sandbox.provider.load_user_agent_env", lambda _uid: {})
    scope = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")
    provider.get_scope(scope, create_if_missing=True, workdir_path=WORKDIR)

    provider.release_scope(scope, workdir_path=WORKDIR)

    assert client.deleted[0][0] == scope.sandbox_id
    assert provider._connections == {}


def test_provider_release_scope_discovers_when_cache_is_empty():
    client = _RecordingClient()
    provider = _make_provider(client)
    scope = SandboxScope.agent_project(uid="user-1", agent_slug="coder", project_id="project-1")
    client.records[scope.sandbox_id] = type(
        "_Record",
        (),
        {
            "sandbox_id": scope.sandbox_id,
            "sandbox_url": "http://sandbox/x",
            "generation": "gen-x",
            "workdir_path": WORKDIR,
        },
    )()

    provider.release_scope(scope, workdir_path=WORKDIR)

    assert client.deleted == [(scope.sandbox_id, "gen-x")]
