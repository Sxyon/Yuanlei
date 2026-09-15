"""Project Git 用例的事务边界与安全清理测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import yuxi.services.project_git_service as service
from yuxi.git.executor import WorktreeState
from yuxi.git.hosting import DeployKey, HostedRepository


class _Db:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _patch_cleanup_dependencies(monkeypatch, tmp_path, *, clean: bool, pushed: bool = True):
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    head = "a" * 40
    worktree = SimpleNamespace(
        id="worktree-1",
        repository_id="repository-1",
        project_id="project-1",
        uid="user-1",
        runtime_scope_id="scope-1",
        task_key="task-1",
        status="ready",
        last_pushed_sha=head if pushed else None,
        last_error_code=None,
        last_error_message=None,
        to_dict=lambda: {"id": "worktree-1", "status": worktree.status},
    )
    binding = SimpleNamespace(id="repository-1", directory_name="api-safe")
    project = SimpleNamespace(id="project-1", workdir_path="projects/project-1")

    class Store:
        def __init__(self, _db):
            pass

        async def get_project_worktree(self, *args, **kwargs):
            return worktree

        async def has_nonterminal_run(self, *args, **kwargs):
            return False

        async def get_binding(self, *args, **kwargs):
            return binding

    class Projects:
        def __init__(self, _db):
            pass

        async def get_for_user(self, *args, **kwargs):
            return project

    class Executor:
        async def inspect_worktree(self, path):
            assert path == worktree_path
            return WorktreeState("codex/task-1", head, clean)

        async def remove_worktree(self, **kwargs):
            raise AssertionError("HTTP 用例不得在提交意图前删除 worktree")

    monkeypatch.setattr(service, "ProjectGitRepositoryStore", Store)
    monkeypatch.setattr(service, "ProjectRepository", Projects)
    monkeypatch.setattr(service, "GitExecutor", Executor)
    monkeypatch.setattr(
        service,
        "resolve_project_git_host_paths",
        lambda *args, **kwargs: (tmp_path / "repository.git", worktree_path),
    )
    return worktree


@pytest.mark.asyncio
async def test_cleanup_persists_intent_before_returning_worker_job(monkeypatch, tmp_path):
    worktree = _patch_cleanup_dependencies(monkeypatch, tmp_path, clean=True)
    db = _Db()

    result, job = await service.cleanup_project_worktree_view(
        uid="user-1", project_id="project-1", worktree_id="worktree-1", db=db
    )

    assert result == {"id": "worktree-1", "status": "cleanup_pending"}
    assert job == "worktree-1"
    assert worktree.status == "cleanup_pending"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_cleanup_rejects_dirty_worktree_without_persisting_intent(monkeypatch, tmp_path):
    worktree = _patch_cleanup_dependencies(monkeypatch, tmp_path, clean=False)
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        await service.cleanup_project_worktree_view(
            uid="user-1", project_id="project-1", worktree_id="worktree-1", db=db
        )

    assert exc.value.status_code == 409
    assert worktree.status == "ready"
    assert db.commits == 0


@pytest.mark.asyncio
async def test_ready_worktree_is_reused_without_lease_or_fetch(monkeypatch, tmp_path):
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    binding = SimpleNamespace(
        id="repository-1",
        project_id="project-1",
        uid="user-1",
        connection_id="connection-1",
        alias="api",
        directory_name="api-safe",
        default_branch="main",
        status="active",
    )
    task_key = service.derive_task_key("user-1", "scope-1")
    branch = service.derive_task_branch("user-1", "scope-1")
    worktree = SimpleNamespace(
        repository_id=binding.id,
        runtime_scope_id="scope-1",
        task_key=task_key,
        branch_name=branch,
        base_branch="main",
        base_sha="a" * 40,
        relative_path=f"repos/api-safe/worktrees/{task_key}",
        status="ready",
    )

    class Db:
        async def scalar(self, _query):
            return binding

    class Context:
        async def __aenter__(self):
            return Db()

        async def __aexit__(self, *_args):
            return False

    class Store:
        def __init__(self, _db):
            pass

        async def get_worktree(self, *args, **kwargs):
            return worktree

        async def acquire_worktree_lease(self, *args, **kwargs):
            raise AssertionError("ready worktree 不应重新获取 lease")

    class Executor:
        async def inspect_worktree(self, path):
            assert path == worktree_path
            return WorktreeState(branch, "b" * 40, False)

        async def fetch_remote_bundle(self, **kwargs):
            raise AssertionError("ready worktree 不应重新 fetch")

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", lambda: Context())
    monkeypatch.setattr(service, "ProjectGitRepositoryStore", Store)
    monkeypatch.setattr(service, "GitExecutor", Executor)
    monkeypatch.setattr(
        service,
        "resolve_project_git_host_paths",
        lambda *args, **kwargs: (tmp_path / "repository.git", worktree_path),
    )

    snapshot = await service._prepare_repository_worktree(
        uid="user-1",
        binding_id=binding.id,
        workdir_path="projects/project-1",
        runtime_scope_id="scope-1",
        worker_id="worker-2",
    )

    assert snapshot["path"].endswith(f"repos/api-safe/worktrees/{task_key}")
    assert snapshot["branch"] == branch


@pytest.mark.asyncio
async def test_superseded_provision_revokes_remote_key(monkeypatch, tmp_path):
    initial = SimpleNamespace(
        id="repository-1",
        operation_generation=1,
        status="provisioning",
        connection_id="connection-1",
        uid="user-1",
        project_id="project-1",
        repository_owner="owner",
        repository_name="repo",
        deploy_private_credential_id="private-1",
        deploy_public_key="ssh-ed25519 AAAA test",
        deploy_public_key_fingerprint="SHA256:fingerprint",
        directory_name="api-safe",
    )
    superseded = SimpleNamespace(operation_generation=2, status="deleting")
    connection = SimpleNamespace(
        api_token_credential_id="token-1",
        provider="gitea",
        api_origin="https://gitea.example.invalid",
        ssh_host="gitea.example.invalid",
        ssh_port=22,
        ssh_known_host_key="known-host",
    )
    project = SimpleNamespace(status="active", workdir_path="projects/project-1")
    contexts = iter([initial, superseded])

    class Db:
        def __init__(self, value):
            self.value = value

        async def scalar(self, _query):
            return self.value

    class Context:
        def __init__(self, value):
            self.db = Db(value)

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *_args):
            return False

    class Store:
        def __init__(self, _db):
            pass

        async def get_connection(self, *args, **kwargs):
            return connection

        async def get_credential(self, credential_id, _uid):
            return SimpleNamespace(id=credential_id)

    class Projects:
        def __init__(self, _db):
            pass

        async def get_for_user(self, *args, **kwargs):
            return project

    class CredentialOwner:
        def decrypt(self, credential):
            return f"plaintext-{credential.id}"

    class Provider:
        def __init__(self):
            self.deleted = []

        async def get_repository(self, owner, name):
            return HostedRepository("remote-1", owner, name, "ssh://git@gitea/repo.git", "main")

        async def list_deploy_keys(self, owner, name):
            return []

        async def create_deploy_key(self, owner, name, **kwargs):
            return DeployKey("key-1", kwargs["title"], kwargs["public_key"], False)

        async def delete_deploy_key(self, owner, name, key_id):
            self.deleted.append((owner, name, key_id))

    bundle = tmp_path / "remote.bundle"
    bundle.write_bytes(b"bundle")

    class Executor:
        async def fetch_remote_bundle(self, **kwargs):
            return bundle

    provider = Provider()
    monkeypatch.setattr(
        service.pg_manager,
        "get_async_session_context",
        lambda: Context(next(contexts)),
    )
    monkeypatch.setattr(service, "ProjectGitRepositoryStore", Store)
    monkeypatch.setattr(service, "ProjectRepository", Projects)
    monkeypatch.setattr(service, "GitCredentialOwner", CredentialOwner)
    monkeypatch.setattr(service, "create_git_hosting_provider", lambda **kwargs: provider)
    monkeypatch.setattr(service, "GitExecutor", Executor)
    monkeypatch.setattr(
        service,
        "resolve_project_git_host_paths",
        lambda *args, **kwargs: (tmp_path / "repository.git", tmp_path / "worktree"),
    )

    await service._provision_repository(initial.id, 1)

    assert provider.deleted == [("owner", "repo", "key-1")]
    assert not bundle.exists()
