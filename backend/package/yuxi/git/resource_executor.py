"""项目分支资源的可信元数据与内容快照执行边界。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from yuxi.git.executor import GitExecutionError, GitExecutor
from yuxi.utils.paths import open_directory_fd


class GitResourceExecutor(GitExecutor):
    """用私有 Git 索引处理可写内容，审批固定 HEAD 与内容树。"""

    def __init__(self, *, checkout_fd: int | None = None):
        super().__init__()
        self.checkout_fd = checkout_fd

    def _run(self, argv, **kwargs):
        if self.checkout_fd is not None:
            kwargs["pass_fds"] = (*kwargs.get("pass_fds", ()), self.checkout_fd)
        return super()._run(argv, **kwargs)

    def _checkout_directory_fd(self, checkout):
        return os.dup(self.checkout_fd) if self.checkout_fd is not None else open_directory_fd(checkout, ())

    def prepared_branch(self, metadata: Path) -> str:
        """从可信检出意图回读失败初始化时仍可审查的分支。"""
        intent = metadata.parent / "checkout-intent.json"
        if not intent.exists():
            raise GitExecutionError("检出尚未开始，没有可恢复的资源内容")
        return json.loads(intent.read_text())["branch"]

    async def prepare(self, *, metadata: Path, checkout: Path, branch: str, bundle: Path) -> dict:
        """导入可信远端对象，在空目录中完整检出分支。"""
        return await asyncio.to_thread(self._prepare, metadata, checkout, branch, bundle)

    async def review(self, *, metadata: Path, checkout: Path, branch: str) -> dict:
        """回读 HEAD、内容树、待提交差异与变更摘要。"""
        return await asyncio.to_thread(self._review, metadata, checkout, branch)

    async def commit(
        self, *, metadata: Path, checkout: Path, branch: str, expected_head: str, expected_tree: str, message: str
    ) -> dict:
        """确认快照未变化后提交，使用 CAS 更新可信分支。"""
        return await asyncio.to_thread(self._commit, metadata, checkout, branch, expected_head, expected_tree, message)

    async def discard(self, *, metadata: Path, checkout: Path, branch: str, expected_head: str, expected_tree: str):
        """确认当前差异后丢弃未提交内容，不跟随 checkout 的符号链接。"""
        return await asyncio.to_thread(self._discard, metadata, checkout, branch, expected_head, expected_tree)

    def _head(self, metadata: Path, branch: str) -> str:
        return self._run(
            self._git_args(metadata, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        ).stdout.strip()

    def _prepare(self, metadata: Path, checkout: Path, branch: str, bundle: Path) -> dict:
        metadata.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._import_bundle(bundle_path=bundle, bare_path=metadata)
        ref = f"refs/heads/{branch}"
        existing = self._run(self._git_args(metadata, "show-ref", "--verify", "--quiet", ref), check=False)
        if existing.returncode != 0:
            sha = self._run(
                self._git_args(metadata, "rev-parse", f"refs/remotes/origin/{branch}^{{commit}}")
            ).stdout.strip()
            self._run(self._git_args(metadata, "update-ref", ref, sha, "0" * len(sha)))
        head = self._head(metadata, branch)
        intent = metadata.parent / "checkout-intent.json"
        expected = {"branch": branch, "head": head}
        if intent.exists():
            if json.loads(intent.read_text()) != expected:
                raise GitExecutionError("检出意图与当前分支不一致，不能覆盖目录")
            self._run(self._git_args(metadata, "read-tree", head))
            state = self._review(metadata, checkout, branch)
            changes = self._run(
                self._git_args(metadata, "diff", "--name-status", "--no-renames", head, state["tree_sha"], "--")
            ).stdout.splitlines()
            if any(not line.startswith("D\t") for line in changes):
                raise GitExecutionError("未完成检出期间资源内容已变化，保留内容并拒绝覆盖")
        else:
            if checkout.exists() and any(checkout.iterdir()):
                raise GitExecutionError("项目资源目录已有内容，不能覆盖；请先查看并处理")
            checkout.mkdir(parents=True, exist_ok=True)
            with intent.open("x") as target:
                json.dump(expected, target)
                target.flush()
                os.fsync(target.fileno())
        self._restore(metadata, checkout, head, clear=False, missing_only=True)
        return self._review(metadata, checkout, branch)

    def _snapshot(self, metadata: Path, checkout: Path, head: str) -> str:
        # 私有临时工作区及索引不在 Agent 挂载范围内；Git 只读取已 no-follow 复制的内容。
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=metadata.parent) as temp:
            snapshot = Path(temp) / "files"
            snapshot.mkdir()
            env = self._sanitized_env(metadata.parent)
            env["GIT_INDEX_FILE"] = str(Path(temp) / "index")
            self._run(self._git_args(metadata, "read-tree", head))
            prefix = [*self._git_args(metadata), "--work-tree", str(checkout)]
            paths = self._run([*prefix, "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).stdout
            source_fd = self._checkout_directory_fd(checkout)
            destination_fd = open_directory_fd(snapshot, ())
            try:
                for value in sorted(set(paths.split("\0")) - {""}):
                    parts = tuple(value.split("/"))
                    if any(part in {"", ".", "..", ".git"} for part in parts):
                        raise GitExecutionError("资源包含非法 Git 路径")
                    try:
                        self._copy_file(source_fd, destination_fd, parts)
                    except FileNotFoundError:
                        # tracked 文件删除是有效改动；后续审批比较最终 tree。
                        continue
            finally:
                os.close(source_fd)
                os.close(destination_fd)
            self._run(self._git_args(metadata, "read-tree", head), env=env)
            self._run([*self._git_args(metadata), "--work-tree", str(snapshot), "add", "-A", "--", "."], env=env)
            return self._run(self._git_args(metadata, "write-tree"), env=env).stdout.strip()

    def _review(self, metadata: Path, checkout: Path, branch: str) -> dict:
        head = self._head(metadata, branch)
        tree = self._snapshot(metadata, checkout, head)
        base_tree = self._run(self._git_args(metadata, "rev-parse", f"{head}^{{tree}}")).stdout.strip()
        remote = self._run(
            self._git_args(metadata, "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"), check=False
        )
        remote_sha = remote.stdout.strip() if remote.returncode == 0 else None
        return {
            "branch": branch,
            "head_sha": head,
            "tree_sha": tree,
            "dirty": tree != base_tree,
            "committed_diff": self._run(
                self._git_args(metadata, "diff", "--no-ext-diff", "--no-textconv", remote_sha, head)
            ).stdout
            if remote_sha
            else "",
            "remote_tracking_sha": remote_sha,
            "unpushed": head != remote_sha,
            "summary": self._run(self._git_args(metadata, "diff", "--stat", head, tree, "--")).stdout,
            "diff": self._run(
                self._git_args(metadata, "diff", "--no-ext-diff", "--no-textconv", head, tree, "--")
            ).stdout,
        }

    def _commit(self, metadata, checkout, branch, expected_head, expected_tree, message):
        head = self._head(metadata, branch)
        tree = self._snapshot(metadata, checkout, head)
        if head != expected_head or tree != expected_tree:
            raise GitExecutionError("资源内容或 HEAD 已变化，请重新查看并确认")
        base_tree = self._run(self._git_args(metadata, "rev-parse", f"{head}^{{tree}}")).stdout.strip()
        if tree == base_tree:
            raise GitExecutionError("没有需要提交的改动")
        env = self._sanitized_env(metadata.parent)
        env.update(
            {
                "GIT_AUTHOR_NAME": "Yuanlei",
                "GIT_AUTHOR_EMAIL": "yuanlei@local.invalid",
                "GIT_COMMITTER_NAME": "Yuanlei",
                "GIT_COMMITTER_EMAIL": "yuanlei@local.invalid",
            }
        )
        commit = self._run(
            self._git_args(metadata, "commit-tree", tree, "-p", head), env=env, input_text=message
        ).stdout.strip()
        self._run(self._git_args(metadata, "update-ref", f"refs/heads/{branch}", commit, head))
        self._run(self._git_args(metadata, "read-tree", commit))
        return {**self._review(metadata, checkout, branch), "committed_sha": commit}

    def _discard(self, metadata, checkout, branch, expected_head, expected_tree):
        state = self._review(metadata, checkout, branch)
        if state["head_sha"] != expected_head or state["tree_sha"] != expected_tree:
            raise GitExecutionError("资源内容或 HEAD 已变化，请重新查看并确认")
        self._restore(metadata, checkout, expected_head, clear=True)
        return self._review(metadata, checkout, branch)

    def _restore(self, metadata, checkout, head, *, clear, missing_only=False):
        with tempfile.TemporaryDirectory(prefix="restore-", dir=metadata.parent) as temp:
            files = Path(temp) / "files"
            files.mkdir()
            env = self._sanitized_env(metadata.parent)
            env["GIT_INDEX_FILE"] = str(Path(temp) / "index")
            self._run(self._git_args(metadata, "read-tree", head), env=env)
            self._run(
                [*self._git_args(metadata), "--work-tree", str(files), "checkout-index", "--all", f"--prefix={files}/"],
                env=env,
            )
            destination_fd = self._checkout_directory_fd(checkout)
            source_fd = open_directory_fd(files, ())
            try:
                if clear:
                    prefix = [*self._git_args(metadata), "--work-tree", str(checkout)]
                    removable = self._run(
                        [*prefix, "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
                    ).stdout
                    self._clear_reviewed_files(destination_fd, removable)
                paths = self._run(self._git_args(metadata, "ls-tree", "-r", "--name-only", "-z", head)).stdout
                for value in paths.split("\0"):
                    if value:
                        parts = tuple(value.split("/"))
                        if missing_only:
                            try:
                                parent_fd = open_directory_fd(destination_fd, parts[:-1])
                            except FileNotFoundError:
                                parent_fd = None
                            if parent_fd is not None:
                                try:
                                    os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                                except FileNotFoundError:
                                    pass
                                else:
                                    continue
                                finally:
                                    os.close(parent_fd)
                        self._copy_file(source_fd, destination_fd, parts)
            finally:
                os.close(source_fd)
                os.close(destination_fd)
            self._run(self._git_args(metadata, "read-tree", head))

    @staticmethod
    def _copy_file(source_fd: int, destination_fd: int, parts: tuple[str, ...]):
        """通过固定目录 fd 复制普通文件或链接文本，拒绝特殊文件。"""
        source_parent = open_directory_fd(source_fd, parts[:-1])
        destination_parent = None
        try:
            info = os.stat(parts[-1], dir_fd=source_parent, follow_symlinks=False)
            destination_parent = open_directory_fd(destination_fd, parts[:-1], create=True)
            if stat.S_ISLNK(info.st_mode):
                os.symlink(os.readlink(parts[-1], dir_fd=source_parent), parts[-1], dir_fd=destination_parent)
            elif stat.S_ISREG(info.st_mode):
                source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_parent)
                try:
                    if not stat.S_ISREG(os.fstat(source).st_mode):
                        raise GitExecutionError("资源文件类型已变化")
                    destination = os.open(
                        parts[-1],
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o755 if info.st_mode & 0o111 else 0o644,
                        dir_fd=destination_parent,
                    )
                    with os.fdopen(destination, "wb") as target, os.fdopen(os.dup(source), "rb") as origin:
                        shutil.copyfileobj(origin, target)
                finally:
                    os.close(source)
            else:
                raise GitExecutionError("资源包含无法提交的特殊文件")
        finally:
            os.close(source_parent)
            if destination_parent is not None:
                os.close(destination_parent)

    @staticmethod
    def _clear_reviewed_files(directory_fd: int, paths: str):
        """只移除 Git 审查范围内的文件，忽略文件与目录保持原样。"""
        for value in sorted(set(paths.split("\0")) - {""}):
            parts = tuple(value.split("/"))
            if any(part in {"", ".", "..", ".git"} for part in parts):
                raise GitExecutionError("资源包含非法 Git 路径")
            try:
                parent = open_directory_fd(directory_fd, parts[:-1])
            except FileNotFoundError:
                continue
            try:
                try:
                    os.unlink(parts[-1], dir_fd=parent)
                except FileNotFoundError:
                    pass
            finally:
                os.close(parent)
