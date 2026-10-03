"""真实 Git 验证资源隔离与审批快照。"""

import asyncio
import os
import subprocess

import pytest

from yuxi.git.executor import GitExecutionError, GitExecutor
from yuxi.git.resource_executor import GitResourceExecutor


def git(*args, cwd=None):
    """使用独立测试仓库回读 Git 事实。"""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def resource(tmp_path):
    """创建带默认分支及 develop 分支的真实 bundle。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-b", "main", cwd=origin)
    git("config", "user.name", "Test", cwd=origin)
    git("config", "user.email", "test@local.invalid", cwd=origin)
    (origin / "README.md").write_text("main\n")
    (origin / ".gitignore").write_text("ignored/\n")
    git("add", ".", cwd=origin)
    git("commit", "-m", "initial", cwd=origin)
    git("switch", "-c", "develop", cwd=origin)
    (origin / "README.md").write_text("develop\n")
    git("commit", "-am", "develop", cwd=origin)
    bundle = tmp_path / "remote.bundle"
    git("bundle", "create", str(bundle), "--all", cwd=origin)
    metadata = tmp_path / "trusted" / "resource.git"
    checkout = tmp_path / "project" / "repository"
    executor = GitResourceExecutor()
    state = asyncio.run(executor.prepare(metadata=metadata, checkout=checkout, branch="develop", bundle=bundle))
    return executor, metadata, checkout, state


def test_full_selected_branch_without_visible_git_and_shell_cannot_commit(resource):
    _, metadata, checkout, state = resource
    assert (checkout / "README.md").read_text() == "develop\n"
    assert not (checkout / ".git").exists()
    command = subprocess.run(["git", "-C", str(checkout), "commit", "-am", "bypass"], capture_output=True)
    assert command.returncode != 0
    assert git("--git-dir", str(metadata), "rev-parse", "refs/heads/develop") == state["head_sha"]
    assert state["dirty"] is False


def test_task_worktree_git_commands_survive_runtime_root_relocation(resource, tmp_path):
    """API 与沙盒使用不同根路径，智能体仍能提交专属任务分支。"""
    project = tmp_path / "api-root" / "project"
    bare = project / "repos" / "repository.git"
    worktree = project / "repos" / "tasks" / "verify"
    executor = GitExecutor()
    asyncio.run(executor.import_bundle(bundle_path=tmp_path / "remote.bundle", bare_path=bare))
    asyncio.run(
        executor.ensure_worktree(bare_path=bare, worktree_path=worktree, branch="agent/verify", base_branch="develop")
    )
    runtime_project = tmp_path / "sandbox-root" / "project"
    runtime_project.parent.mkdir()
    project.rename(runtime_project)
    relocated = runtime_project / "repos" / "tasks" / "verify"
    (relocated / "README.md").write_text("agent result\n")
    git("commit", "-am", "agent changes", cwd=relocated)
    assert git("branch", "--show-current", cwd=relocated) == "agent/verify"
    assert git("show", "HEAD:README.md", cwd=relocated) == "agent result"
    assert git("status", "--porcelain", cwd=relocated) == ""


def test_commit_changes_exact_snapshot_and_rejects_stale_approval(resource):
    executor, metadata, checkout, initial = resource
    (checkout / "README.md").write_text("reviewed\n")
    review = asyncio.run(executor.review(metadata=metadata, checkout=checkout, branch="develop"))
    assert review["dirty"] and "reviewed" in review["diff"]
    (checkout / "README.md").write_text("changed after approval\n")
    with pytest.raises(GitExecutionError, match="已变化"):
        asyncio.run(
            executor.commit(
                metadata=metadata,
                checkout=checkout,
                branch="develop",
                expected_head=review["head_sha"],
                expected_tree=review["tree_sha"],
                message="approved",
            )
        )
    assert git("--git-dir", str(metadata), "rev-parse", "refs/heads/develop") == initial["head_sha"]
    (checkout / "README.md").write_text("reviewed\n")
    commit = asyncio.run(
        executor.commit(
            metadata=metadata,
            checkout=checkout,
            branch="develop",
            expected_head=review["head_sha"],
            expected_tree=review["tree_sha"],
            message="approved",
        )
    )
    assert git("--git-dir", str(metadata), "show", f"{commit['head_sha']}:README.md") == "reviewed"
    assert asyncio.run(executor.review(metadata=metadata, checkout=checkout, branch="develop"))["dirty"] is False


def test_snapshot_does_not_follow_external_symlink_and_discard_does_not_delete_target(resource, tmp_path):
    executor, metadata, checkout, _ = resource
    external = tmp_path / "outside"
    external.mkdir()
    secret = external / "secret.txt"
    secret.write_text("outside must remain\n")
    (checkout / "link").symlink_to(external, target_is_directory=True)
    (checkout / "README.md").unlink()
    review = asyncio.run(executor.review(metadata=metadata, checkout=checkout, branch="develop"))
    assert "outside must remain" not in review["diff"]
    asyncio.run(
        executor.discard(
            metadata=metadata,
            checkout=checkout,
            branch="develop",
            expected_head=review["head_sha"],
            expected_tree=review["tree_sha"],
        )
    )
    assert secret.read_text() == "outside must remain\n"
    assert not (checkout / "link").exists()
    assert (checkout / "README.md").read_text() == "develop\n"


def test_ignored_files_do_not_change_approval_tree(resource):
    executor, metadata, checkout, state = resource
    (checkout / "ignored").mkdir()
    (checkout / "ignored" / "cache").write_text("cache\n")
    review = asyncio.run(executor.review(metadata=metadata, checkout=checkout, branch="develop"))
    assert review["tree_sha"] == state["tree_sha"] and review["dirty"] is False


def test_pinned_directory_handle_survives_parent_path_replacement(resource, tmp_path):
    executor, metadata, checkout, _ = resource
    fd = os.open(checkout, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        relocated = checkout.with_name("retained")
        checkout.rename(relocated)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret").write_text("private\n")
        checkout.symlink_to(outside, target_is_directory=True)
        (relocated / "README.md").write_text("pinned\n")
        state = asyncio.run(
            GitResourceExecutor(checkout_fd=fd).review(
                metadata=metadata, checkout=__import__("pathlib").Path(f"/proc/self/fd/{fd}"), branch="develop"
            )
        )
        assert "pinned" in state["diff"] and "private" not in state["diff"]
    finally:
        os.close(fd)


def test_retry_after_checkout_before_database_commit_reuses_content(resource, tmp_path):
    executor, metadata, checkout, initial = resource
    bundle = tmp_path / "remote.bundle"
    repeated = asyncio.run(executor.prepare(metadata=metadata, checkout=checkout, branch="develop", bundle=bundle))
    assert repeated["head_sha"] == initial["head_sha"]
    assert (checkout / "README.md").read_text() == "develop\n"
    (checkout / "README.md").unlink()
    resumed = asyncio.run(executor.prepare(metadata=metadata, checkout=checkout, branch="develop", bundle=bundle))
    assert resumed["dirty"] is False
    assert (checkout / "README.md").read_text() == "develop\n"
    (checkout / "README.md").write_text("user changes\n")
    with pytest.raises(GitExecutionError, match="内容已变化"):
        asyncio.run(executor.prepare(metadata=metadata, checkout=checkout, branch="develop", bundle=bundle))
    assert (checkout / "README.md").read_text() == "user changes\n"


def test_discard_preserves_ignored_files_added_after_review(resource):
    """不属于审查内容树的忽略文件，清理时始终保留。"""
    executor, metadata, checkout, _ = resource
    (checkout / "README.md").write_text("discard this\n")
    (checkout / "untracked.txt").write_text("reviewed untracked\n")
    review = asyncio.run(executor.review(metadata=metadata, checkout=checkout, branch="develop"))
    (checkout / "ignored").mkdir()
    (checkout / "ignored" / "cache").write_text("not reviewed, retain\n")
    result = asyncio.run(
        executor.discard(
            metadata=metadata,
            checkout=checkout,
            branch="develop",
            expected_head=review["head_sha"],
            expected_tree=review["tree_sha"],
        )
    )
    assert result["dirty"] is False
    assert (checkout / "README.md").read_text() == "develop\n"
    assert not (checkout / "untracked.txt").exists()
    assert (checkout / "ignored" / "cache").read_text() == "not reviewed, retain\n"
