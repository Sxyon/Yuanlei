"""项目资源真实 HTTP、PostgreSQL 与文件提交的联合证据。"""

import subprocess
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
