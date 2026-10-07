"""项目资源真实 HTTP、PostgreSQL 与文件提交的联合证据。"""

import subprocess
from contextlib import asynccontextmanager
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from test.integration.api import test_project_settings_api as settings_fixtures
from server.utils.auth_middleware import get_required_user
from yuxi.git.resource_executor import GitResourceExecutor
from yuxi.storage.postgres.models_business import GitCredential, GitConnection, ProjectGitRepository, User
from yuxi.workspace.git_resource_paths import resource_metadata_path
from yuxi.workspace.paths import user_workspace_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
settings_api = settings_fixtures.settings_api
ensure_live_api_schema = settings_fixtures.ensure_live_api_schema
cleanup_test_knowledge_resources = settings_fixtures.cleanup_test_knowledge_resources
cleanup_test_sandboxes = settings_fixtures.cleanup_test_sandboxes


def git(*args, cwd=None):
    """独立读取测试仓库文件与提交事实。"""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest_asyncio.fixture
async def resource_api(settings_api, tmp_path, monkeypatch):
    """以真实选定分支初始化资源，仅远端连接身份使用不可解密占位。"""
    client, sessions, _, app, user, project_id = settings_api

    @asynccontextmanager
    async def committed_sessions():
        """与生产 Task repository 相同的提交事务边界。"""
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    monkeypatch.setattr("yuxi.storage.postgres.manager.pg_manager.get_async_session_context", committed_sessions)
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path / "data"))
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    monkeypatch.setenv("YUXI_GIT_STATE_DIR", str(trusted))
    checkout = user_workspace_dir(user.uid) / "projects" / project_id / "repository"
    checkout.mkdir(parents=True)
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-b", "develop", cwd=origin)
    git("config", "user.name", "Test", cwd=origin)
    git("config", "user.email", "test@local.invalid", cwd=origin)
    (origin / "README.md").write_text("initial\n")
    git("add", ".", cwd=origin)
    git("commit", "-m", "initial", cwd=origin)
    bundle = tmp_path / "remote.bundle"
    git("bundle", "create", str(bundle), "--all", cwd=origin)
    repository_id = str(uuid.uuid4())
    metadata = resource_metadata_path(repository_id)
    executor = GitResourceExecutor()
    prepared = await executor.prepare(metadata=metadata, checkout=checkout, branch="develop", bundle=bundle)
    async with sessions() as db:
        db.add(
            GitCredential(
                id="credential",
                uid=user.uid,
                purpose="gitea_api_token",
                ciphertext=b"test-only",
                nonce=b"test-only",
                key_version=1,
            )
        )
        await db.flush()
        db.add(
            GitConnection(
                id="connection",
                uid=user.uid,
                name="Test",
                provider="gitea",
                api_origin="http://test.invalid",
                ssh_host="test.invalid",
                ssh_port=22,
                ssh_known_host_key="test-only",
                api_token_credential_id="credential",
                idempotency_key="connection",
            )
        )
        await db.flush()
        db.add(
            ProjectGitRepository(
                id=repository_id,
                project_id=project_id,
                uid=user.uid,
                connection_id="connection",
                alias="repo",
                directory_name="repo",
                repository_owner="owner",
                repository_name="repository",
                status="active",
                deploy_public_key="test-only",
                deploy_public_key_fingerprint="test-only",
                deploy_private_credential_id="credential",
                idempotency_key="repository",
                usage_mode="in_place",
                approval_mode="protected",
                configured_base_branch="develop",
                allowed_base_branches=["develop"],
                checkout_path="repository",
                checkout_head_sha=prepared["head_sha"],
            )
        )
        await db.commit()
    yield (
        client,
        sessions,
        app,
        user,
        repository_id,
        checkout,
        metadata,
        f"/api/projects/{project_id}/repositories/{repository_id}",
    )


async def test_human_commit_uses_exact_review_and_persists_actual_head(resource_api):
    client, sessions, _, _, repository_id, checkout, metadata, path = resource_api
    (checkout / "README.md").write_text("reviewed\n")
    response = await client.get(path + "/review")
    assert response.status_code == 200, response.text
    review = response.json()
    payload = {"expected_head": review["head_sha"], "expected_tree": review["tree_sha"], "message": "人工确认"}
    (checkout / "README.md").write_text("changed after approval\n")
    rejected = await client.post(path + "/commit", json=payload)
    assert rejected.status_code == 409
    assert git("--git-dir", str(metadata), "rev-parse", "develop") == review["head_sha"]
    (checkout / "README.md").write_text("reviewed\n")
    committed = await client.post(path + "/commit", json=payload)
    assert committed.status_code == 200, committed.text
    actual = git("--git-dir", str(metadata), "rev-parse", "develop")
    assert actual == committed.json()["committed_sha"]
    assert git("--git-dir", str(metadata), "show", f"{actual}:README.md") == "reviewed"
    async with sessions() as db:
        assert (await db.get(ProjectGitRepository, repository_id)).checkout_head_sha == actual
    assert (await client.get(path + "/review")).json()["dirty"] is False


async def test_other_user_cannot_review_or_commit_protected_resource(resource_api):
    client, _, app, _, _, checkout, metadata, path = resource_api
    before = git("--git-dir", str(metadata), "rev-parse", "develop")
    app.dependency_overrides[get_required_user] = lambda: User(uid="outsider", username="outsider", role="user")
    assert (await client.get(path + "/review")).status_code == 404
    response = await client.post(
        path + "/commit",
        json={
            "expected_head": before,
            "expected_tree": "a" * 40,
            "message": "不能提交",
        },
    )
    assert response.status_code == 404
    assert git("--git-dir", str(metadata), "rev-parse", "develop") == before
    assert (checkout / "README.md").read_text() == "initial\n"


async def test_failed_checkout_can_be_reviewed_and_restored_before_explicit_retry(resource_api, monkeypatch):
    client, sessions, _, _, repository_id, checkout, _, path = resource_api
    async with sessions() as db:
        resource = await db.get(ProjectGitRepository, repository_id)
        resource.status = "provision_failed"
        resource.checkout_head_sha = None
        resource.configured_base_branch = None
        await db.commit()
    (checkout / "README.md").write_text("partial copy\n")
    review_response = await client.get(path + "/review")
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    assert review["incomplete_checkout"] and review["dirty"]
    assert (
        await client.post(
            path + "/commit",
            json={
                "expected_head": review["head_sha"],
                "expected_tree": review["tree_sha"],
                "message": "尚不能提交",
            },
        )
    ).status_code == 404
    monkeypatch.setattr(
        "yuxi.agents.backends.sandbox.get_sandbox_provider",
        lambda: SimpleNamespace(revoke_user_git_runtimes=lambda _uid: None),
    )
    restored = await client.post(
        path + "/discard",
        json={
            "expected_head": review["head_sha"],
            "expected_tree": review["tree_sha"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert (checkout / "README.md").read_text() == "initial\n"
    async with sessions() as db:
        resource = await db.get(ProjectGitRepository, repository_id)
        assert resource.status == "provision_failed" and resource.checkout_head_sha is None


async def _seed_incomplete_checkout_with_run(sessions, repository_id, uid, status):
    """把资源置为未检出，并在同一用户下写入一个指定状态的 Run。"""
    from yuxi.storage.postgres.models_business import AgentRun

    async with sessions() as db:
        resource = await db.get(ProjectGitRepository, repository_id)
        resource.status = "provision_failed"
        resource.checkout_head_sha = None
        resource.configured_base_branch = None
        db.add(
            AgentRun(
                id=f"guard-{status}",
                uid=uid,
                conversation_thread_id=f"guard-{status}",
                runtime_scope_id=f"guard-{status}",
                agent_slug="test",
                status=status,
                request_id=f"guard-request-{status}",
            )
        )
        await db.commit()


async def test_interrupted_terminal_run_does_not_block_directory_guard(resource_api, monkeypatch):
    client, sessions, _, user, repository_id, _, _, path = resource_api
    await _seed_incomplete_checkout_with_run(sessions, repository_id, user.uid, "interrupted")
    monkeypatch.setattr(
        "yuxi.agents.backends.sandbox.get_sandbox_provider",
        lambda: SimpleNamespace(revoke_user_git_runtimes=lambda _uid: None),
    )
    review = (await client.get(path + "/review")).json()
    response = await client.post(
        path + "/discard",
        json={"expected_head": review["head_sha"], "expected_tree": review["tree_sha"]},
    )
    assert response.status_code == 200, response.text


async def test_running_run_still_blocks_directory_guard(resource_api, monkeypatch):
    client, sessions, _, user, repository_id, _, _, path = resource_api
    await _seed_incomplete_checkout_with_run(sessions, repository_id, user.uid, "running")
    monkeypatch.setattr(
        "yuxi.agents.backends.sandbox.get_sandbox_provider",
        lambda: SimpleNamespace(revoke_user_git_runtimes=lambda _uid: None),
    )
    review = (await client.get(path + "/review")).json()
    response = await client.post(
        path + "/discard",
        json={"expected_head": review["head_sha"], "expected_tree": review["tree_sha"]},
    )
    assert response.status_code == 409
    assert "运行" in response.json()["detail"]


async def test_human_push_verifies_remote_head_without_force(resource_api, monkeypatch):
    client, sessions, _, _, repository_id, checkout, metadata, path = resource_api
    remote = metadata.parents[2] / "remote.git"
    git("init", "--bare", str(remote))
    git("--git-dir", str(metadata), "push", str(remote), "develop")
    async with sessions() as db:
        (await db.get(ProjectGitRepository, repository_id)).canonical_ssh_url = str(remote)
        await db.commit()
    monkeypatch.setattr(
        "yuxi.services.project_git_resource_service.GitCredentialOwner",
        lambda: SimpleNamespace(decrypt=lambda _credential: "test-only"),
    )
    (checkout / "README.md").write_text("approved result\n")
    review = (await client.get(path + "/review")).json()
    committed = await client.post(
        path + "/commit",
        json={
            "expected_head": review["head_sha"],
            "expected_tree": review["tree_sha"],
            "message": "人工提交",
        },
    )
    assert committed.status_code == 200, committed.text
    committed_review = committed.json()
    assert committed_review["unpushed"]
    payload = {"expected_head": committed_review["head_sha"], "expected_tree": committed_review["tree_sha"]}
    pushed = await client.post(path + "/push", json=payload)
    assert pushed.status_code == 200, pushed.text
    actual = git("--git-dir", str(remote), "rev-parse", "develop")
    assert actual == committed_review["committed_sha"] == pushed.json()["pushed_sha"]
    assert pushed.json()["unpushed"] is False
    assert git("--git-dir", str(remote), "show", f"{actual}:README.md") == "approved result"
    (checkout / "README.md").write_text("new uncommitted change\n")
    assert (await client.post(path + "/push", json=payload)).status_code == 409
    assert git("--git-dir", str(remote), "rev-parse", "develop") == actual


async def test_human_push_preserves_divergent_remote_progress(resource_api, monkeypatch):
    client, sessions, _, _, repository_id, checkout, metadata, path = resource_api
    remote = metadata.parents[2] / "remote.git"
    origin = metadata.parents[2] / "origin"
    git("init", "--bare", str(remote))
    git("--git-dir", str(metadata), "push", str(remote), "develop")
    (origin / "README.md").write_text("other remote author\n")
    git("commit", "-am", "remote progress", cwd=origin)
    git("push", str(remote), "develop", cwd=origin)
    before = git("--git-dir", str(remote), "rev-parse", "develop")
    async with sessions() as db:
        (await db.get(ProjectGitRepository, repository_id)).canonical_ssh_url = str(remote)
        await db.commit()
    monkeypatch.setattr(
        "yuxi.services.project_git_resource_service.GitCredentialOwner",
        lambda: SimpleNamespace(decrypt=lambda _credential: "test-only"),
    )
    (checkout / "README.md").write_text("local author\n")
    review = (await client.get(path + "/review")).json()
    committed = await client.post(
        path + "/commit",
        json={
            "expected_head": review["head_sha"],
            "expected_tree": review["tree_sha"],
            "message": "本地提交",
        },
    )
    assert committed.status_code == 200, committed.text
    value = committed.json()
    rejected = await client.post(
        path + "/push",
        json={
            "expected_head": value["head_sha"],
            "expected_tree": value["tree_sha"],
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert git("--git-dir", str(remote), "rev-parse", "develop") == before
    assert git("--git-dir", str(remote), "show", "develop:README.md") == "other remote author"
    assert (await client.get(path + "/review")).json()["unpushed"] is True


async def test_prepare_obeys_user_lock_before_workspace_row(resource_api, monkeypatch):
    """释放侧持有用户及占用锁时，准备侧不能先占用 worktree 行。"""
    import asyncio
    from contextlib import asynccontextmanager
    from sqlalchemy import text
    from yuxi.repositories.project_git_repository import ProjectGitRepositoryStore
    from yuxi.services import project_git_service as service
    from yuxi.storage.postgres.models_business import ProjectGitOccupancy, ProjectGitWorktree

    _, sessions, _, user, repository_id, _, _, _ = resource_api
    async with sessions() as db:
        binding = await db.get(ProjectGitRepository, repository_id)
        project_id = binding.project_id
        db.add(
            ProjectGitWorktree(
                id="workspace",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                runtime_scope_id="scope",
                task_key="scope",
                selection_source="user",
                task_purpose="test",
                branch_kind="test",
                branch_slug="test",
                branch_name="develop",
                base_branch="develop",
                relative_path="repository",
                usage_mode="in_place",
                status="requested",
            )
        )
        db.add(
            ProjectGitOccupancy(
                id="slot",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                scope_key="scope",
                status="owned",
            )
        )
        await db.commit()
    prepared_pid = asyncio.Future()

    @asynccontextmanager
    async def preparation_session():
        """让准备侧使用同一隔离 Schema，并暴露数据库会话身份给锁 oracle。"""
        async with sessions() as db:
            prepared_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            yield db

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", preparation_session)
    async with sessions() as blocker:
        store = ProjectGitRepositoryStore(blocker)
        await store.acquire_user_runtime_lock(user.uid)
        await store.get_binding(repository_id, user.uid, lock=True)
        await store.occupancy(repository_id, "scope", user.uid)
        pending = asyncio.create_task(
            service._prepare_repository_worktree(
                uid=user.uid,
                binding_id=repository_id,
                workdir_path=f"projects/{project_id}",
                runtime_scope_id="scope",
                worker_id="test",
            )
        )
        try:
            pid = await asyncio.wait_for(prepared_pid, 3)
            async with sessions() as observer:
                async with asyncio.timeout(5):
                    while not await observer.scalar(
                        text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"), {"pid": pid}
                    ):
                        await asyncio.sleep(0.01)
            row = await asyncio.wait_for(store.get_worktree(repository_id, "scope", user.uid, lock=True), 2)
            assert row.status == "requested"
            await blocker.commit()
            result = await asyncio.wait_for(pending, 5)
            assert result["status"] == "ready"
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as db:
        assert (await db.get(ProjectGitWorktree, "workspace")).status == "ready"


async def test_task_outcomes_reads_actual_files_without_completing_or_committing(resource_api, monkeypatch):
    """完成提示来自真实工作区与远端回读，不改变任务、分支或占用。"""
    from unittest.mock import AsyncMock
    from server.routers.project_work_router import project_work
    from yuxi.services import project_task_git_outcome_service as service
    from yuxi.storage.postgres.models_business import ProjectWorkTask, ProjectGitWorktree, ProjectGitOccupancy

    client, sessions, app, user, repository_id, checkout, metadata, _ = resource_api
    app.include_router(project_work, prefix="/api")
    head = git("--git-dir", str(metadata), "rev-parse", "develop")
    async with sessions() as db:
        binding = await db.get(ProjectGitRepository, repository_id)
        project_id = binding.project_id
        db.add(ProjectWorkTask(id="task", project_id=project_id, number="TS-1", title="Check", created_by=user.uid))
        db.add(
            ProjectGitWorktree(
                id="workspace",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                runtime_scope_id="task:task",
                task_key="task",
                selection_source="user",
                task_purpose="test",
                branch_kind="test",
                branch_slug="test",
                branch_name="develop",
                base_branch="develop",
                relative_path="repository",
                usage_mode="in_place",
                status="ready",
            )
        )
        db.add(
            ProjectGitOccupancy(
                id="slot",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                scope_key="task:task",
                status="owned",
            )
        )
        await db.commit()
    provider = AsyncMock()
    provider.get_branch.return_value = SimpleNamespace(commit_sha=head)
    monkeypatch.setattr(service, "get_resource_provider", AsyncMock(return_value=(provider, None)))
    (checkout / "README.md").write_text("task result, uncommitted\n")
    response = await client.get(f"/api/projects/{project_id}/work/tasks/task/git-outcomes")
    assert response.status_code == 200, response.text
    row = response.json()["resources"][0]
    assert row["dirty"] is True and row["unpushed"] is False
    assert set(row["issues"]) == {"uncommitted", "unreleased"}
    assert response.json()["requires_attention"] is True
    assert git("--git-dir", str(metadata), "rev-parse", "develop") == head
    assert (checkout / "README.md").read_text() == "task result, uncommitted\n"
    async with sessions() as db:
        assert (await db.get(ProjectWorkTask, "task")).status == "todo"
        assert (await db.get(ProjectGitOccupancy, "slot")).status == "owned"
    app.dependency_overrides[get_required_user] = lambda: User(
        uid="outsider", username="outsider", password_hash="test"
    )
    rejected = await client.get(f"/api/projects/{project_id}/work/tasks/task/git-outcomes")
    assert rejected.status_code == 404
    assert provider.get_branch.await_count == 1


async def test_task_outcomes_does_not_count_merge_to_unmanaged_branch(resource_api, monkeypatch):
    """真实工作树成果合并到无关目标分支，仍应提示未确认合并。"""
    from unittest.mock import AsyncMock
    from server.routers.project_work_router import project_work
    from yuxi.git.executor import GitExecutor
    from yuxi.services import project_task_git_outcome_service as service
    from yuxi.storage.postgres.models_business import ProjectWorkTask, ProjectGitWorktree
    from yuxi.workspace.git_paths import resolve_project_git_host_paths

    client, sessions, app, user, repository_id, _, metadata, _ = resource_api
    app.include_router(project_work, prefix="/api")
    async with sessions() as db:
        binding = await db.get(ProjectGitRepository, repository_id)
        binding.remote_repository_id = "7"
        project_id = binding.project_id
        db.add(ProjectWorkTask(id="task", project_id=project_id, number="TS-1", title="Check", created_by=user.uid))
        db.add(
            ProjectGitWorktree(
                id="workspace",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                runtime_scope_id="task:task",
                task_key="task",
                selection_source="user",
                task_purpose="test",
                branch_kind="test",
                branch_slug="test",
                branch_name="agent/test",
                base_branch="develop",
                relative_path="repos/repo/worktrees/task",
                usage_mode="worktree",
                status="ready",
            )
        )
        await db.commit()
    bare, path = resolve_project_git_host_paths(user.uid, f"projects/{project_id}", "repo", "task", create_parents=True)
    executor = GitExecutor()
    await executor.import_bundle(bundle_path=metadata.parent.parent.parent / "remote.bundle", bare_path=bare)
    await executor.ensure_worktree(bare_path=bare, worktree_path=path, branch="agent/test", base_branch="develop")
    head = git("rev-parse", "HEAD", cwd=path)
    provider = AsyncMock()
    provider.get_branch.return_value = SimpleNamespace(commit_sha=head)
    pull = {
        "merged": True,
        "head_sha": head,
        "head_branch": "agent/test",
        "base_branch": "unrelated",
        "head_repository_id": "7",
        "base_repository_id": "7",
    }
    provider.list_pull_requests.return_value = [pull]
    monkeypatch.setattr(service, "get_resource_provider", AsyncMock(return_value=(provider, None)))
    endpoint = f"/api/projects/{project_id}/work/tasks/task/git-outcomes"
    response = await client.get(endpoint)
    assert response.status_code == 200, response.text
    result = response.json()["resources"][0]
    assert result["merged"] is False
    assert "unmerged" in result["issues"]
    provider.list_pull_requests.return_value = [{**pull, "base_branch": "develop"}]
    result = (await client.get(endpoint)).json()["resources"][0]
    assert result["merged"] is True
    assert "unmerged" not in result["issues"]
    assert git("rev-parse", "HEAD", cwd=path) == head


async def test_task_worktree_human_artifacts_use_real_refs_and_reject_stale_or_foreign_user(resource_api, monkeypatch):
    """真实 HTTP 和 PostgreSQL 操作任务分支，提交推送回读对象与远端引用。"""
    from yuxi.git.executor import GitExecutor
    from yuxi.storage.postgres.models_business import ProjectGitWorktree
    from yuxi.workspace.git_paths import resolve_project_git_host_paths, derive_allocation_branch

    client, sessions, app, user, repository_id, _, metadata, _ = resource_api
    branch = derive_allocation_branch("test", "artifacts", user.uid, "task:artifacts")
    async with sessions() as db:
        binding = await db.get(ProjectGitRepository, repository_id)
        project_id = binding.project_id
        remote = metadata.parents[2] / "task-remote.git"
        git("init", "--bare", str(remote))
        binding.canonical_ssh_url = str(remote)
        db.add(
            ProjectGitWorktree(
                id="artifacts",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                runtime_scope_id="task:artifacts",
                task_key="artifacts",
                selection_source="user",
                task_purpose="test",
                branch_kind="test",
                branch_slug="artifacts",
                branch_name=branch,
                base_branch="develop",
                relative_path="repos/repo/worktrees/artifacts",
                usage_mode="worktree",
                status="ready",
            )
        )
        await db.commit()
    bare, checkout = resolve_project_git_host_paths(
        user.uid, f"projects/{project_id}", "repo", "artifacts", create_parents=True
    )
    executor = GitExecutor()
    await executor.import_bundle(bundle_path=metadata.parents[2] / "remote.bundle", bare_path=bare)
    await executor.ensure_worktree(
        bare_path=bare, worktree_path=checkout, branch=branch, base_branch="develop", worktree_name="artifacts"
    )
    monkeypatch.setattr(
        "yuxi.services.project_git_worktree_artifact_service.GitCredentialOwner",
        lambda: SimpleNamespace(decrypt=lambda _: "test-only"),
    )
    endpoint = f"/api/projects/{project_id}/git-worktrees/artifacts"
    (checkout / "README.md").write_text("approved task\n")
    response = await client.get(endpoint + "/review")
    assert response.status_code == 200, response.text
    state = response.json()
    payload = {"expected_head": state["head_sha"], "expected_tree": state["tree_sha"]}
    (checkout / "README.md").write_text("later change\n")
    assert (await client.post(endpoint + "/commit", json={**payload, "message": "reject stale"})).status_code == 409
    (checkout / "README.md").write_text("approved task\n")
    committed = await client.post(endpoint + "/commit", json={**payload, "message": "human approval"})
    assert committed.status_code == 200, committed.text
    state = committed.json()
    assert git("--git-dir", str(bare), "show", f"{branch}:README.md") == "approved task"
    payload = {"expected_head": state["head_sha"], "expected_tree": state["tree_sha"]}
    pushed = await client.post(endpoint + "/push", json=payload)
    assert pushed.status_code == 200, pushed.text
    assert git("--git-dir", str(remote), "rev-parse", branch) == state["head_sha"]
    async with sessions() as db:
        row = await db.get(ProjectGitWorktree, "artifacts")
        assert row.last_pushed_sha == state["head_sha"]
    (checkout / "README.md").write_text("discard me\n")
    state = (await client.get(endpoint + "/review")).json()
    response = await client.post(
        endpoint + "/discard", json={"expected_head": state["head_sha"], "expected_tree": state["tree_sha"]}
    )
    assert response.status_code == 200, response.text
    assert (checkout / "README.md").read_text() == "approved task\n"
    payload = {"expected_head": state["head_sha"], "expected_tree": state["tree_sha"]}
    app.dependency_overrides[get_required_user] = lambda: User(uid="outsider", username="outsider", role="user")
    assert (await client.get(endpoint + "/review")).status_code == 404
    for action in ("commit", "push", "discard"):
        body = {**payload, **({"message": "deny"} if action == "commit" else {})}
        assert (await client.post(endpoint + "/" + action, json=body)).status_code == 404
    assert git("--git-dir", str(bare), "rev-parse", branch) == state["head_sha"]
    app.dependency_overrides[get_required_user] = lambda: user
    from yuxi.storage.postgres.models_business import AgentRun, ProjectGitOccupancy

    async with sessions() as db:
        db.add_all(
            [
                AgentRun(
                    id="artifact-root",
                    uid=user.uid,
                    conversation_thread_id="root",
                    runtime_scope_id="task:artifacts",
                    agent_slug="test",
                    status="completed",
                    request_id="artifact-root",
                ),
                AgentRun(
                    id="artifact-child",
                    uid=user.uid,
                    conversation_thread_id="child-scope",
                    runtime_scope_id="child-scope",
                    run_type="resume",
                    agent_slug="test",
                    status="running",
                    request_id="artifact-child",
                    created_by_run_id="artifact-root",
                ),
                ProjectGitOccupancy(
                    id="artifact-slot",
                    uid=user.uid,
                    project_id=project_id,
                    repository_id=repository_id,
                    scope_key="task:artifacts",
                    status="owned",
                    active_run_id="artifact-root",
                ),
            ]
        )
        await db.commit()
    state = (await client.get(endpoint + "/review")).json()
    payload = {"expected_head": state["head_sha"], "expected_tree": state["tree_sha"]}
    for action in ("commit", "push", "discard"):
        response = await client.post(
            endpoint + "/" + action, json={**payload, **({"message": "deny"} if action == "commit" else {})}
        )
        assert response.status_code == 409
        assert "运行" in response.json()["detail"]
    assert (await client.delete(endpoint)).status_code == 409
    from unittest.mock import AsyncMock
    from server.routers import project_router
    from yuxi.services import project_git_service

    async with sessions() as db:
        (await db.get(AgentRun, "artifact-child")).status = "completed"
        (await db.get(ProjectGitRepository, repository_id)).status = "disabled"
        await db.commit()
    monkeypatch.setattr("yuxi.services.project_git_execution_service.revoke_git_owner_runtime", AsyncMock())
    enqueue = AsyncMock()
    monkeypatch.setattr(project_router, "enqueue_project_git_worktree_cleanup", enqueue)
    response = await client.delete(endpoint)
    assert response.status_code == 202, response.text
    async with sessions() as db:
        row = await db.get(ProjectGitWorktree, "artifacts")
        assert row.status == "cleanup_pending"
    enqueue.assert_awaited_once_with("artifacts")
    monkeypatch.setattr(project_git_service.pg_manager, "get_async_session_context", sessions)
    await project_git_service._cleanup_project_worktree("artifacts")
    assert not checkout.exists()
    assert not (bare / "worktrees" / "artifacts").exists()
    assert git("--git-dir", str(bare), "rev-parse", branch) == state["head_sha"]
    async with sessions() as db:
        assert (await db.get(ProjectGitWorktree, "artifacts")).status == "removed"


@pytest.mark.parametrize("protected", [True, False])
@pytest.mark.parametrize("usage_mode", ["in_place", "worktree"])
async def test_git_approval_records_and_executes_exact_snapshot(resource_api, monkeypatch, protected, usage_mode):
    """真实 PG、HTTP、Task attempt 与 Git 引用证明人工保护和自动批准都可追溯。"""
    from datetime import timedelta
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from yuxi.services import project_git_action_service as service
    from yuxi.services import project_git_action_task_service as execution
    from yuxi.services.task_service import process_task
    from yuxi.storage.postgres.models_business import (
        AgentRun,
        Conversation,
        ProjectGitAction,
        ProjectGitOccupancy,
        ProjectGitWorktree,
        TaskRecord,
    )
    from yuxi.utils.datetime_utils import utc_now_naive

    client, sessions, app, user, repository_id, checkout, metadata, path = resource_api
    branch = "develop"
    if usage_mode == "worktree":
        from yuxi.git.executor import GitExecutor
        from yuxi.workspace.git_paths import resolve_project_git_host_paths, derive_allocation_branch

        async with sessions() as db:
            project_id = (await db.get(ProjectGitRepository, repository_id)).project_id
        branch = derive_allocation_branch("test", "approval", user.uid, "approval-thread")
        bare, checkout = resolve_project_git_host_paths(
            user.uid, f"projects/{project_id}", "repo", "approval", create_parents=True
        )
        executor = GitExecutor()
        await executor.import_bundle(bundle_path=metadata.parents[2] / "remote.bundle", bare_path=bare)
        await executor.ensure_worktree(
            bare_path=bare, worktree_path=checkout, branch=branch, base_branch="develop", worktree_name="approval"
        )
        metadata = bare
        path = f"/api/projects/{project_id}/git-worktrees/approval-workspace"
    provider = AsyncMock()
    provider.is_branch_protected.return_value = protected
    monkeypatch.setattr(service, "get_resource_provider", AsyncMock(return_value=(provider, None)))
    monkeypatch.setattr(execution, "get_resource_provider", AsyncMock(return_value=(provider, None)))
    # 只隔离 ARQ 投递；下面实际取得 Durable Task lease 并执行注册 Handler。
    monkeypatch.setattr(service.tasker, "publish", AsyncMock())
    async with sessions() as db:
        binding = await db.get(ProjectGitRepository, repository_id)
        binding.approval_mode = "automatic"
        project_id = binding.project_id
        conversation = Conversation(thread_id="approval-thread", uid=user.uid, agent_id="test", project_id=project_id)
        db.add(conversation)
        await db.flush()
        db.add(
            AgentRun(
                id="approval-run",
                uid=user.uid,
                conversation_id=conversation.id,
                conversation_thread_id="approval-thread",
                runtime_scope_id="approval-thread",
                agent_slug="test",
                status="running",
                request_id="approval-request",
                worker_id="test-owner",
                lease_expires_at=utc_now_naive() + timedelta(minutes=20),
            )
        )
        db.add(
            ProjectGitWorktree(
                id="approval-workspace",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                runtime_scope_id="approval-thread",
                task_key="approval",
                selection_source="user",
                task_purpose="test",
                branch_kind="test",
                branch_slug="approval",
                branch_name=branch,
                base_branch="develop",
                base_sha=git("--git-dir", str(metadata), "rev-parse", branch),
                relative_path="repository" if usage_mode == "in_place" else "repos/repo/worktrees/approval",
                usage_mode=usage_mode,
                status="ready",
            )
        )
        db.add(
            ProjectGitOccupancy(
                id="approval-slot",
                repository_id=repository_id,
                project_id=project_id,
                uid=user.uid,
                scope_key="approval-thread",
                status="owned",
                active_run_id="approval-run",
            )
        )
        await db.commit()
    (checkout / "README.md").write_text("approved content\n")
    snapshot = (await client.get(path + "/review")).json()
    async with sessions() as db:
        row = await service.request_git_action_for_run(
            db=db,
            uid=user.uid,
            run_id="approval-run",
            repository_alias="repo",
            request_id="action-request",
            action="commit",
            expected_head=snapshot["head_sha"],
            expected_tree=snapshot["tree_sha"],
            message="审查提交",
        )
    assert row["status"] == ("pending" if protected else "approved")
    assert row["approval_kind"] == ("required" if protected else "automatic")
    assert git("--git-dir", str(metadata), "rev-parse", branch) == snapshot["head_sha"]
    history_url = f"/api/projects/{project_id}/git-actions"
    assert (await client.get(history_url)).json()[0]["diff"].find("approved content") >= 0
    if protected:
        async with sessions() as db:
            assert await db.scalar(select(TaskRecord).where(TaskRecord.type == "project_git_action")) is None
        response = await client.post(history_url + f"/{row['id']}/decision", json={"approve": True})
        assert response.status_code == 200, response.text
        row = response.json()
        assert "Gitea" in row["approval_reason"] and row["approved_by"] == user.uid
        assert (await client.post(history_url + f"/{row['id']}/decision", json={"approve": True})).status_code == 409
    await process_task({"worker_id": "approval-test"}, row["task_id"])
    async with sessions() as db:
        record = await db.get(ProjectGitAction, row["id"])
        task = await db.get(TaskRecord, row["task_id"])
        assert record.status == "succeeded", record.error
        assert task.status == "success"
        assert record.started_at and record.finished_at
        assert record.result["committed_sha"] == git("--git-dir", str(metadata), "rev-parse", branch)
        assert record.expected_head == snapshot["head_sha"]
        assert record.diff.find("approved content") >= 0
    async with sessions() as db:
        replay = await service.request_git_action_for_run(
            db=db,
            uid=user.uid,
            run_id="approval-run",
            repository_alias="repo",
            request_id="action-request",
            action="commit",
            expected_head=snapshot["head_sha"],
            expected_tree=snapshot["tree_sha"],
            message="审查提交",
        )
        assert replay["id"] == row["id"] and replay["status"] == "succeeded"
    remote = metadata.parent / "approval-remote.git"
    git("init", "--bare", str(remote))
    async with sessions() as db:
        (await db.get(ProjectGitRepository, repository_id)).canonical_ssh_url = str(remote)
        await db.commit()
    for module in (
        execution,
        __import__("yuxi.services.project_git_resource_service", fromlist=["GitCredentialOwner"]),
    ):
        monkeypatch.setattr(module, "GitCredentialOwner", lambda: SimpleNamespace(decrypt=lambda _: "test-only"))
    clean = (await client.get(path + "/review")).json()
    async with sessions() as db:
        push = await service.request_git_action_for_run(
            db=db,
            uid=user.uid,
            run_id="approval-run",
            repository_alias="repo",
            request_id="push-action",
            action="push",
            expected_head=clean["head_sha"],
            expected_tree=clean["tree_sha"],
        )
    assert "approved content" in push["diff"]
    if protected:
        push = (await client.post(history_url + f"/{push['id']}/decision", json={"approve": True})).json()
    await process_task({"worker_id": "approval-test"}, push["task_id"])
    async with sessions() as db:
        pushed = await db.get(ProjectGitAction, push["id"])
        assert pushed.status == "succeeded", pushed.error
        assert pushed.result["pushed_sha"] == git("--git-dir", str(remote), "rev-parse", branch)
    # 批准后内容改变不能被旧批准提交，失败也必须保留原快照与终态。
    committed_head = git("--git-dir", str(metadata), "rev-parse", branch)
    (checkout / "README.md").write_text("frozen second version\n")
    state = (await client.get(path + "/review")).json()
    assert state["committed_diff"] == ""
    async with sessions() as db:
        second = await service.request_git_action_for_run(
            db=db,
            uid=user.uid,
            run_id="approval-run",
            repository_alias="repo",
            request_id="second-action",
            action="commit",
            expected_head=state["head_sha"],
            expected_tree=state["tree_sha"],
            message="冻结第二次",
        )
    if protected:
        second = (await client.post(history_url + f"/{second['id']}/decision", json={"approve": True})).json()
    (checkout / "README.md").write_text("changed after approval\n")
    await process_task({"worker_id": "approval-test"}, second["task_id"])
    async with sessions() as db:
        failed = await db.get(ProjectGitAction, second["id"])
        assert failed.status == "failed" and failed.finished_at and failed.error
        assert "frozen second version" in failed.diff
        assert (await db.get(TaskRecord, second["task_id"])).status == "failed"
        # 持久 FIFO 次序由请求时间和 id 决定，显示顺序不能只按 UI 插入顺序。
        now = utc_now_naive()
        for index in (2, 1):
            db.add(
                ProjectGitWorktree(
                    id=f"queue-workspace-{index}",
                    repository_id=repository_id,
                    project_id=project_id,
                    uid=user.uid,
                    runtime_scope_id=f"queued-thread-{index}",
                    task_key=f"queued-{index}",
                    selection_source="user",
                    task_purpose="test",
                    branch_kind="test",
                    branch_slug=f"queued-{index}",
                    branch_name="develop",
                    base_branch="develop",
                    relative_path="repository",
                    usage_mode="in_place",
                    status="ready",
                )
            )
            db.add(
                ProjectGitOccupancy(
                    id=f"queued-{index}",
                    repository_id=repository_id,
                    project_id=project_id,
                    uid=user.uid,
                    scope_key=f"queued-thread-{index}",
                    status="queued",
                    requested_at=now + timedelta(seconds=index),
                )
            )
        await db.commit()
    assert git("--git-dir", str(metadata), "rev-parse", branch) == committed_head
    occupancy_response = await client.get(f"/api/projects/{project_id}/git-occupancies")
    assert occupancy_response.status_code == 200, occupancy_response.text
    slots = {value["id"]: value for value in occupancy_response.json()}
    assert slots["approval-slot"]["active_execution"] is True
    assert slots["approval-slot"]["branch"] == branch
    assert slots["queued-1"]["queue_position"] == 1 and slots["queued-2"]["queue_position"] == 2
    if usage_mode == "worktree":
        from yuxi.services import project_git_pull_request_service as pulls

        monkeypatch.setattr(pulls, "get_resource_provider", AsyncMock(return_value=(provider, None)))
        provider.get_branch.return_value = SimpleNamespace(commit_sha="a" * 40)
        provider.get_pull_request.return_value = {
            "number": 7,
            "head_branch": branch,
            "base_branch": "develop",
            "head_sha": committed_head,
            "head_repository_id": "7",
            "base_repository_id": "7",
            "merged": False,
            "state": "open",
            "mergeable": True,
        }
        provider.get_pull_request_diff.return_value = "frozen merge content"
        async with sessions() as db:
            (await db.get(ProjectGitRepository, repository_id)).remote_repository_id = "7"
            await db.commit()
            merge = await service.request_git_action_for_run(
                db=db,
                uid=user.uid,
                run_id="approval-run",
                repository_alias="repo",
                request_id="merge-action",
                action="merge",
                expected_head=committed_head,
                expected_base="a" * 40,
                pull_number=7,
            )
        if protected:
            merge = (await client.post(history_url + f"/{merge['id']}/decision", json={"approve": True})).json()
        provider.get_pull_request.return_value = {
            **provider.get_pull_request.return_value,
            "head_sha": "b" * 40,
            "merged": True,
            "state": "closed",
        }
        await process_task({"worker_id": "approval-test"}, merge["task_id"])
        async with sessions() as db:
            rejected_merge = await db.get(ProjectGitAction, merge["id"])
            assert rejected_merge.status == "failed" and rejected_merge.expected_head == committed_head
        provider.merge_pull_request.assert_not_awaited()
    # 无当前执行身份的根运行和子智能体不得产生批准意图。
    for field, invalid, restored in (
        ("worker_id", None, "test-owner"),
        ("lease_expires_at", utc_now_naive() - timedelta(seconds=1), utc_now_naive() + timedelta(minutes=20)),
    ):
        async with sessions() as db:
            run = await db.get(AgentRun, "approval-run")
            setattr(run, field, invalid)
            await db.commit()
            with pytest.raises(PermissionError, match="根运行"):
                await service.request_git_action_for_run(
                    db=db,
                    uid=user.uid,
                    run_id="approval-run",
                    repository_alias="repo",
                    request_id=f"denied-{field}",
                    action="commit",
                    expected_head=state["head_sha"],
                    expected_tree=state["tree_sha"],
                    message="不得产生申请",
                )
            await db.rollback()
            assert (
                await db.scalar(select(ProjectGitAction).where(ProjectGitAction.request_id == f"denied-{field}"))
                is None
            )
            run = await db.get(AgentRun, "approval-run")
            setattr(run, field, restored)
            await db.commit()
    if not protected:
        current = (await client.get(path + "/review")).json()
        async with sessions() as db:
            expired_action = await service.request_git_action_for_run(
                db=db,
                uid=user.uid,
                run_id="approval-run",
                repository_alias="repo",
                request_id="expired-during-policy",
                action="commit",
                expected_head=current["head_sha"],
                expected_tree=current["tree_sha"],
                message="执行前失去 lease",
            )

        async def expire_during_policy(*args):
            """远端策略读取期间失去 Root lease，Git 副作用前必须重新回读。"""
            async with sessions() as db:
                (await db.get(AgentRun, "approval-run")).lease_expires_at = utc_now_naive() - timedelta(seconds=1)
                await db.commit()
            return False

        provider.is_branch_protected.side_effect = expire_during_policy
        await process_task({"worker_id": "approval-test"}, expired_action["task_id"])
        async with sessions() as db:
            assert (await db.get(ProjectGitAction, expired_action["id"])).status == "failed"
            (await db.get(AgentRun, "approval-run")).lease_expires_at = utc_now_naive() + timedelta(minutes=20)
            await db.commit()
        assert git("--git-dir", str(metadata), "rev-parse", branch) == committed_head
        provider.is_branch_protected.side_effect = None
    from yuxi.storage.postgres.models_business import SubagentThread

    async with sessions() as db:
        parent = await db.get(AgentRun, "approval-run")
        child_conversation = Conversation(
            thread_id="approval-child-thread", uid=user.uid, agent_id="test", project_id=project_id
        )
        db.add(child_conversation)
        await db.flush()
        relation = SubagentThread(
            uid=user.uid,
            parent_conversation_id=parent.conversation_id,
            child_conversation_id=child_conversation.id,
            child_thread_id="approval-child-thread",
            subagent_slug="test",
            created_by_run_id=parent.id,
        )
        db.add(relation)
        await db.flush()
        db.add(
            AgentRun(
                id="approval-child",
                uid=user.uid,
                conversation_id=child_conversation.id,
                conversation_thread_id="approval-child-thread",
                runtime_scope_id="approval-child-thread",
                agent_slug="test",
                status="running",
                request_id="approval-child-request",
                worker_id="child-owner",
                run_type="subagent",
                created_by_run_id=parent.id,
                subagent_thread_relation_id=relation.id,
                lease_expires_at=utc_now_naive() + timedelta(minutes=20),
            )
        )
        await db.commit()
        with pytest.raises(PermissionError, match="根运行"):
            await service.request_git_action_for_run(
                db=db,
                uid=user.uid,
                run_id="approval-child",
                repository_alias="repo",
                request_id="denied-child",
                action="commit",
                expected_head=state["head_sha"],
                expected_tree=state["tree_sha"],
                message="不得产生申请",
            )
        await db.rollback()
        assert await db.scalar(select(ProjectGitAction).where(ProjectGitAction.request_id == "denied-child")) is None
    app.dependency_overrides[get_required_user] = lambda: User(uid="outsider", username="outsider")
    assert (await client.get(history_url)).status_code == 404
    assert (await client.post(history_url + f"/{row['id']}/decision", json={"approve": True})).status_code == 404
