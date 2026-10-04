"""工作树人工操作不执行智能体可写配置，回读真实 Git 文件与引用。"""

import asyncio
import subprocess

import pytest

from yuxi.git.executor import GitExecutor, GitExecutionError
from yuxi.git.worktree_executor import GitWorktreeExecutor


def git(*args, cwd=None):
    """独立 Git 命令验证引用、索引与文件。"""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def task_workspace(tmp_path):
    """初始化真实隔离工作树与私有审查根。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-b", "main", cwd=origin)
    git("config", "user.name", "Test", cwd=origin)
    git("config", "user.email", "test@local.invalid", cwd=origin)
    (origin / "README.md").write_text("initial\n")
    (origin / ".gitignore").write_text("ignored/\n")
    git("add", ".", cwd=origin)
    git("commit", "-m", "initial", cwd=origin)
    bundle = tmp_path / "remote.bundle"
    git("bundle", "create", str(bundle), "--all", cwd=origin)
    bare, checkout = tmp_path / "repository.git", tmp_path / "task"
    executor = GitExecutor()
    asyncio.run(executor.import_bundle(bundle_path=bundle, bare_path=bare))
    asyncio.run(
        executor.ensure_worktree(
            bare_path=bare, worktree_path=checkout, branch="agent/task", base_branch="main", worktree_name="task"
        )
    )
    private_root = tmp_path / "trusted"
    params = dict(bare=bare, checkout=checkout, branch="agent/task", task_key="task", private_root=private_root)
    return GitWorktreeExecutor(), params


def test_human_commit_ignores_untrusted_filters_and_updates_actual_ref(task_workspace, tmp_path):
    executor, params = task_workspace
    checkout, bare = params["checkout"], params["bare"]
    marker = tmp_path / "must-not-run"
    git("config", "filter.hostile.clean", f"touch {marker}", cwd=checkout)
    (checkout / ".gitattributes").write_text("*.md filter=hostile\n")
    (checkout / "README.md").write_text("human result\n")
    state = asyncio.run(executor.operate(**params))
    result = asyncio.run(
        executor.operate(
            **params,
            action="commit",
            expected_head=state["head_sha"],
            expected_tree=state["tree_sha"],
            message="human approval",
            review_base=state["head_sha"],
        )
    )
    assert "human result" in result["committed_diff"]
    assert not marker.exists()
    assert git("--git-dir", str(bare), "rev-parse", "agent/task") == result["committed_sha"]
    assert git("--git-dir", str(bare), "show", "agent/task:README.md") == "human result"
    assert git("--git-dir", str(bare), "rev-parse", "refs/remotes/origin/main") == state["head_sha"]


def test_human_discard_preserves_pointer_and_unreviewed_ignored_files(task_workspace):
    executor, params = task_workspace
    checkout = params["checkout"]
    pointer = (checkout / ".git").read_text()
    (checkout / "README.md").write_text("discard\n")
    state = asyncio.run(executor.operate(**params))
    (checkout / "ignored").mkdir()
    (checkout / "ignored" / "cache").write_text("retain\n")
    result = asyncio.run(
        executor.operate(**params, action="discard", expected_head=state["head_sha"], expected_tree=state["tree_sha"])
    )
    assert result["dirty"] is False
    assert (checkout / ".git").read_text() == pointer
    assert (checkout / "README.md").read_text() == "initial\n"
    assert (checkout / "ignored" / "cache").read_text() == "retain\n"


def test_stale_approval_and_external_object_alias_are_rejected(task_workspace, tmp_path):
    executor, params = task_workspace
    (params["checkout"] / "README.md").write_text("review\n")
    state = asyncio.run(executor.operate(**params))
    (params["checkout"] / "README.md").write_text("later\n")
    with pytest.raises(GitExecutionError, match="已变化"):
        asyncio.run(
            executor.operate(
                **params,
                action="commit",
                expected_head=state["head_sha"],
                expected_tree=state["tree_sha"],
                message="reject",
            )
        )
    (params["bare"] / "objects" / "info" / "alternates").write_text(str(tmp_path / "external"))
    with pytest.raises(GitExecutionError, match="外部对象"):
        asyncio.run(executor.operate(**params))


def test_cleanup_ignores_hostile_config_and_retains_task_branch(task_workspace, tmp_path):
    executor, params = task_workspace
    checkout, bare = params["checkout"], params["bare"]
    marker = tmp_path / "must-not-run"
    git("config", "filter.hostile.clean", f"touch {marker}; cat", cwd=checkout)
    (checkout / ".gitattributes").write_text("*.md filter=hostile\n")
    state = asyncio.run(executor.operate(**params))
    result = asyncio.run(
        executor.operate(
            **params,
            action="commit",
            expected_head=state["head_sha"],
            expected_tree=state["tree_sha"],
            message="attributes",
        )
    )
    head = result["head_sha"]
    asyncio.run(executor.operate(**params, action="cleanup", expected_head=head))
    assert not marker.exists()
    assert not checkout.exists()
    assert not (bare / "worktrees" / params["task_key"]).exists()
    assert git("--git-dir", str(bare), "rev-parse", params["branch"]) == head


def test_cleanup_rejects_uncommitted_or_unpushed_progress(task_workspace):
    executor, params = task_workspace
    state = asyncio.run(executor.operate(**params))
    with pytest.raises(GitExecutionError, match="未提交或未推送"):
        asyncio.run(executor.operate(**params, action="cleanup", expected_head="a" * 40))
    (params["checkout"] / "README.md").write_text("retain\n")
    with pytest.raises(GitExecutionError, match="未提交或未推送"):
        asyncio.run(executor.operate(**params, action="cleanup", expected_head=state["head_sha"]))
    assert (params["checkout"] / "README.md").read_text() == "retain\n"
