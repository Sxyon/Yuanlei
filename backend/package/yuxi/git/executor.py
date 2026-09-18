"""不依赖托管商的可信 Git 命令执行器。"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class GitExecutionError(RuntimeError):
    """Git 命令或状态验证失败。"""


@dataclass(frozen=True)
class WorktreeState:
    """从本地 Git 回读的 worktree 状态。"""

    branch: str
    head_sha: str
    clean: bool


class GitExecutor:
    """通过私有 staging 隔离远端凭据与 Agent 可写目录。"""

    def __init__(self, *, timeout_seconds: int = 120, max_output_bytes: int = 131_072):
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    async def fetch_into_bare(
        self,
        *,
        remote_url: str,
        private_key: str,
        known_hosts: str,
        bare_path: Path,
    ) -> None:
        """在私有 staging 拉取，再以无凭据 bundle 导入共享 bare repo。"""
        await asyncio.to_thread(
            self._fetch_into_bare,
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
            bare_path=bare_path,
        )

    async def fetch_remote_bundle(self, *, remote_url: str, private_key: str, known_hosts: str) -> Path:
        """在私有 staging 拉取远端并返回不含凭据的临时 bundle。"""
        return await asyncio.to_thread(
            self._fetch_remote_bundle,
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
        )

    async def import_bundle(self, *, bundle_path: Path, bare_path: Path, pass_fds: tuple[int, ...] = ()) -> None:
        """将已拉取对象无凭据导入共享 bare repo。"""
        await asyncio.to_thread(
            self._import_bundle,
            bundle_path=bundle_path,
            bare_path=bare_path,
            pass_fds=pass_fds,
        )

    async def ensure_worktree(
        self,
        *,
        bare_path: Path,
        worktree_path: Path,
        branch: str,
        base_branch: str,
        base_sha: str | None = None,
        worktree_add_path: Path | None = None,
        worktree_name: str | None = None,
        worktree_registered: bool | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> WorktreeState:
        """创建或验证任务 worktree，并配置默认 commit identity。"""
        return await asyncio.to_thread(
            self._ensure_worktree,
            bare_path=bare_path,
            worktree_path=worktree_path,
            branch=branch,
            base_branch=base_branch,
            base_sha=base_sha,
            worktree_add_path=worktree_add_path,
            worktree_name=worktree_name,
            worktree_registered=worktree_registered,
            pass_fds=pass_fds,
        )

    async def inspect_worktree(
        self,
        worktree_path: Path,
        *,
        bare_path: Path | None = None,
        worktree_name: str | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> WorktreeState:
        """读取当前分支、HEAD 和 dirty 状态。"""
        return await asyncio.to_thread(
            self._inspect_worktree,
            worktree_path,
            bare_path=bare_path,
            worktree_name=worktree_name,
            pass_fds=pass_fds,
        )

    async def remove_worktree(self, *, bare_path: Path, worktree_path: Path, pass_fds: tuple[int, ...] = ()) -> None:
        """移除已经由服务层确认安全的 worktree。"""
        await asyncio.to_thread(
            self._remove_worktree,
            bare_path=bare_path,
            worktree_path=worktree_path,
            pass_fds=pass_fds,
        )

    async def push_commit(
        self,
        *,
        bare_path: Path,
        expected_sha: str,
        branch: str,
        remote_url: str,
        private_key: str,
        known_hosts: str,
        pass_fds: tuple[int, ...] = (),
    ) -> str:
        """从共享 bare 导入精确 commit，并在私有 staging fast-forward push。"""
        return await asyncio.to_thread(
            self._push_commit,
            bare_path=bare_path,
            expected_sha=expected_sha,
            branch=branch,
            remote_url=remote_url,
            private_key=private_key,
            known_hosts=known_hosts,
            pass_fds=pass_fds,
        )

    def _fetch_into_bare(self, *, remote_url: str, private_key: str, known_hosts: str, bare_path: Path) -> None:
        bundle = self._fetch_remote_bundle(remote_url=remote_url, private_key=private_key, known_hosts=known_hosts)
        try:
            self._import_bundle(bundle_path=bundle, bare_path=bare_path)
        finally:
            bundle.unlink(missing_ok=True)

    def _fetch_remote_bundle(self, *, remote_url: str, private_key: str, known_hosts: str) -> Path:
        with tempfile.TemporaryDirectory(prefix="yuxi-git-fetch-") as raw_temp:
            temp = Path(raw_temp)
            staging = temp / "staging.git"
            staged_bundle = temp / "objects.bundle"
            self._run(["git", "init", "--bare", str(staging)], cwd=temp)
            with self._ssh_environment(temp, private_key, known_hosts) as remote_env:
                self._run(
                    self._git_args(staging, "fetch", "--prune", remote_url, "+refs/heads/*:refs/heads/*"),
                    env=remote_env,
                )
            self._run(self._git_args(staging, "bundle", "create", str(staged_bundle), "--all"))
            descriptor, raw_bundle = tempfile.mkstemp(prefix="yuxi-git-objects-", suffix=".bundle")
            os.close(descriptor)
            bundle = Path(raw_bundle)
            shutil.copyfile(staged_bundle, bundle)
            bundle.chmod(0o600)
            return bundle

    def _import_bundle(self, *, bundle_path: Path, bare_path: Path, pass_fds: tuple[int, ...] = ()) -> None:
        bare_path.parent.mkdir(parents=True, exist_ok=True)
        if not bare_path.exists():
            self._run(["git", "init", "--bare", str(bare_path)], pass_fds=pass_fds)
        self._run(
            self._git_args(
                bare_path,
                "fetch",
                "--prune",
                str(bundle_path),
                "+refs/heads/*:refs/remotes/origin/*",
            ),
            pass_fds=pass_fds,
        )

    def _ensure_worktree(
        self,
        *,
        bare_path: Path,
        worktree_path: Path,
        branch: str,
        base_branch: str,
        base_sha: str | None = None,
        worktree_add_path: Path | None = None,
        worktree_name: str | None = None,
        worktree_registered: bool | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> WorktreeState:
        registered = worktree_path.exists() if worktree_registered is None else worktree_registered
        metadata_name = worktree_name or worktree_path.name
        if registered:
            state = self._inspect_worktree(
                worktree_path,
                bare_path=bare_path,
                worktree_name=metadata_name,
                pass_fds=pass_fds,
            )
            if state.branch != branch:
                raise GitExecutionError("existing worktree is bound to another branch")
            return state
        base_ref = f"refs/remotes/origin/{base_branch}"
        resolved_base_sha = base_sha
        if resolved_base_sha is None:
            resolved_base_sha = self._run(
                self._git_args(bare_path, "rev-parse", "--verify", f"{base_ref}^{{commit}}"),
                pass_fds=pass_fds,
            ).stdout.strip()
        else:
            verified = self._run(
                self._git_args(bare_path, "rev-parse", "--verify", f"{resolved_base_sha}^{{commit}}"),
                pass_fds=pass_fds,
            ).stdout.strip()
            if verified != resolved_base_sha:
                raise GitExecutionError("frozen base SHA is not an exact commit")
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = (
            self._run(
                self._git_args(bare_path, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
                check=False,
                pass_fds=pass_fds,
            ).returncode
            == 0
        )
        add_path = worktree_add_path or worktree_path
        if branch_exists:
            args = self._git_args(bare_path, "worktree", "add", str(add_path), branch)
        else:
            args = self._git_args(bare_path, "worktree", "add", "-b", branch, str(add_path), resolved_base_sha)
        self._run(args, pass_fds=pass_fds)
        self._run(
            self._git_args(bare_path, "config", "user.name", "Yuxi Agent"),
            pass_fds=pass_fds,
        )
        self._run(
            self._git_args(bare_path, "config", "user.email", "yuxi-agent@local.invalid"),
            pass_fds=pass_fds,
        )
        return self._inspect_worktree(
            worktree_path,
            bare_path=bare_path,
            worktree_name=metadata_name,
            pass_fds=pass_fds,
        )

    def _inspect_worktree(
        self,
        worktree_path: Path,
        *,
        bare_path: Path | None = None,
        worktree_name: str | None = None,
        pass_fds: tuple[int, ...] = (),
    ) -> WorktreeState:
        if bare_path is not None and worktree_name is not None:
            prefix = [
                "git",
                *self._safe_git_options(),
                "--git-dir",
                str(bare_path / "worktrees" / worktree_name),
                "--work-tree",
                str(worktree_path),
            ]
        else:
            prefix = ["git", *self._safe_git_options(), "-C", str(worktree_path)]
        branch = self._run([*prefix, "branch", "--show-current"], pass_fds=pass_fds).stdout.strip()
        head = self._run([*prefix, "rev-parse", "HEAD^{commit}"], pass_fds=pass_fds).stdout.strip()
        status = self._run([*prefix, "status", "--porcelain=v1"], pass_fds=pass_fds).stdout
        return WorktreeState(branch=branch, head_sha=head, clean=not status.strip())

    def _remove_worktree(self, *, bare_path: Path, worktree_path: Path, pass_fds: tuple[int, ...] = ()) -> None:
        if worktree_path.exists():
            self._run(
                self._git_args(bare_path, "worktree", "remove", str(worktree_path)),
                pass_fds=pass_fds,
            )
        self._run(self._git_args(bare_path, "worktree", "prune"), pass_fds=pass_fds)

    def _push_commit(
        self,
        *,
        bare_path: Path,
        expected_sha: str,
        branch: str,
        remote_url: str,
        private_key: str,
        known_hosts: str,
        pass_fds: tuple[int, ...] = (),
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="yuxi-git-push-") as raw_temp:
            temp = Path(raw_temp)
            staging = temp / "staging.git"
            self._run(["git", "init", "--bare", str(staging)], cwd=temp)
            self._run(
                self._git_args(staging, "fetch", str(bare_path), expected_sha),
                pass_fds=pass_fds,
            )
            imported = self._run(self._git_args(staging, "rev-parse", "FETCH_HEAD^{commit}")).stdout.strip()
            if imported != expected_sha:
                raise GitExecutionError("expected commit was not imported")

            ref = f"refs/heads/{branch}"
            with self._ssh_environment(temp, private_key, known_hosts) as remote_env:
                remote_sha = self._ls_remote(remote_url, ref, remote_env)
                if remote_sha == expected_sha:
                    return expected_sha
                if remote_sha:
                    self._run(self._git_args(staging, "fetch", remote_url, ref), env=remote_env)
                    ancestor = self._run(
                        self._git_args(staging, "merge-base", "--is-ancestor", remote_sha, expected_sha),
                        env=remote_env,
                        check=False,
                    )
                    if ancestor.returncode != 0:
                        raise GitExecutionError("remote branch is not an ancestor of expected HEAD")
                self._run(self._git_args(staging, "push", remote_url, f"{expected_sha}:{ref}"), env=remote_env)
                verified = self._ls_remote(remote_url, ref, remote_env)
            if verified != expected_sha:
                raise GitExecutionError("remote branch verification failed")
            return verified

    def _ls_remote(self, remote_url: str, ref: str, env: dict[str, str]) -> str | None:
        result = self._run(["git", *self._safe_git_options(), "ls-remote", "--heads", remote_url, ref], env=env)
        line = result.stdout.strip()
        return line.split(maxsplit=1)[0] if line else None

    def _git_args(self, git_dir: Path, *args: str) -> list[str]:
        return ["git", *self._safe_git_options(), "--git-dir", str(git_dir), *args]

    @staticmethod
    def _safe_git_options() -> list[str]:
        """返回所有可信 Git 命令共享的安全配置。"""
        return ["-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", "-c", "core.fsmonitor=false"]

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        """以 argv、超时和输出上限运行 Git，不记录命令参数。"""
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env or self._sanitized_env(cwd or Path(tempfile.gettempdir())),
            check=False,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            pass_fds=pass_fds,
        )
        if len(result.stdout.encode()) + len(result.stderr.encode()) > self.max_output_bytes:
            raise GitExecutionError("Git output exceeded the configured limit")
        if check and result.returncode != 0:
            raise GitExecutionError(f"Git operation failed with exit code {result.returncode}")
        return result

    def _sanitized_env(self, home: Path) -> dict[str, str]:
        """创建不继承凭据、代理和用户 Git 配置的最小环境。"""
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }

    def _ssh_environment(self, temp: Path, private_key: str, known_hosts: str):
        return _SshEnvironment(self, temp, private_key, known_hosts)


class _SshEnvironment:
    """限制私钥生命周期并生成固定 SSH 配置。"""

    def __init__(self, executor: GitExecutor, temp: Path, private_key: str, known_hosts: str):
        self.executor = executor
        self.temp = temp
        self.private_key = private_key
        self.known_hosts = known_hosts
        self.key_path = temp / "deploy-key"
        self.hosts_path = temp / "known-hosts"

    def __enter__(self) -> dict[str, str]:
        self.key_path.write_text(self.private_key)
        self.hosts_path.write_text(self.known_hosts.rstrip() + "\n")
        self.key_path.chmod(0o600)
        self.hosts_path.chmod(0o600)
        env = self.executor._sanitized_env(self.temp)
        env["GIT_SSH_VARIANT"] = "ssh"
        env["GIT_SSH_COMMAND"] = " ".join(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={shlex.quote(str(self.hosts_path))}",
                "-i",
                shlex.quote(str(self.key_path)),
            ]
        )
        return env

    def __exit__(self, exc_type, exc, traceback) -> None:
        for path in (self.key_path, self.hosts_path):
            if path.exists():
                try:
                    path.write_bytes(b"\0" * path.stat().st_size)
                finally:
                    path.unlink(missing_ok=True)
        shutil.rmtree(self.temp / ".ssh", ignore_errors=True)
