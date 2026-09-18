"""GitExecutor 在 Agent 可写配置存在时仍使用可信 staging。"""

from __future__ import annotations

import asyncio
import subprocess

from yuxi.git.executor import GitExecutor


def _git(*args, cwd=None) -> str:
    """运行测试仓库命令并返回 stdout。"""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()


def test_push_ignores_shared_repository_hooks_and_remote_rewrite(tmp_path):
    source = tmp_path / "source"
    shared = tmp_path / "repository.git"
    remote = tmp_path / "remote.git"
    marker = tmp_path / "hook-ran"
    source.mkdir()
    _git("init", "-b", "main", cwd=source)
    _git("config", "user.name", "Test", cwd=source)
    _git("config", "user.email", "test@example.invalid", cwd=source)
    (source / "README.md").write_text("safe\n")
    _git("add", "README.md", cwd=source)
    _git("commit", "-m", "initial", cwd=source)
    head = _git("rev-parse", "HEAD", cwd=source)
    _git("clone", "--bare", str(source), str(shared))
    _git("init", "--bare", str(remote))

    hooks = shared / "hooks"
    hook = hooks / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    hook.chmod(0o755)
    _git("--git-dir", str(shared), "config", "core.sshCommand", "false")
    _git("--git-dir", str(shared), "config", "url.invalid.insteadOf", str(remote))

    pushed = asyncio.run(
        GitExecutor().push_commit(
            bare_path=shared,
            expected_sha=head,
            branch="codex/task-test",
            remote_url=str(remote),
            private_key="test-only-unused-for-local-transport",
            known_hosts="test-only-unused-for-local-transport",
        )
    )

    assert pushed == head
    assert _git("--git-dir", str(remote), "rev-parse", "refs/heads/codex/task-test") == head
    assert marker.exists() is False


def test_sanitized_environment_drops_credentials_and_proxies(monkeypatch, tmp_path):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("GIT_ASKPASS", "steal")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")

    environment = GitExecutor()._sanitized_env(tmp_path)

    assert "SSH_AUTH_SOCK" not in environment
    assert "GIT_ASKPASS" not in environment
    assert "HTTPS_PROXY" not in environment
    assert environment["GIT_TERMINAL_PROMPT"] == "0"


def test_inspect_ignores_agent_controlled_fsmonitor_hook(tmp_path):
    repository = tmp_path / "worktree"
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "fsmonitor"
    repository.mkdir()
    _git("init", "-b", "codex/task-test", cwd=repository)
    _git("config", "user.name", "Test", cwd=repository)
    _git("config", "user.email", "test@example.invalid", cwd=repository)
    (repository / "README.md").write_text("safe\n")
    _git("add", "README.md", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nprintf '0\\n'\n")
    hook.chmod(0o755)
    _git("config", "core.fsmonitor", str(hook), cwd=repository)

    state = asyncio.run(GitExecutor().inspect_worktree(repository))

    assert state.clean is True
    assert marker.exists() is False
