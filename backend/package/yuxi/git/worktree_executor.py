"""隔离工作树的人工成果操作，不加载智能体可写的 Git 配置。"""

import asyncio
import os
import stat
import shutil
import tempfile
from pathlib import Path

from yuxi.git.executor import GitExecutionError
from yuxi.git.resource_executor import GitResourceExecutor
from yuxi.utils.paths import open_directory_fd
from yuxi.workspace.git_paths import require_commit_sha, normalize_base_branch


class GitWorktreeExecutor(GitResourceExecutor):
    """在私有镜像中审查与提交，通过引用锁回写任务分支。"""

    async def operate(
        self,
        *,
        bare: Path,
        checkout: Path,
        branch: str,
        task_key: str,
        private_root: Path,
        action: str = "review",
        expected_head: str | None = None,
        expected_tree: str | None = None,
        message: str | None = None,
        remote: dict | None = None,
        review_base: str | None = None,
    ) -> dict:
        """复制对象到可信临时目录，人工修改只接受固定内容快照。"""
        return await asyncio.to_thread(
            self._operate,
            bare,
            checkout,
            branch,
            task_key,
            private_root,
            action,
            expected_head,
            expected_tree,
            message,
            remote,
            review_base,
        )

    def _operate(
        self,
        bare,
        checkout,
        branch,
        task_key,
        private_root,
        action,
        expected_head,
        expected_tree,
        message,
        remote,
        review_base,
    ):
        normalize_base_branch(branch)
        if not task_key or "/" in task_key or task_key in {".", ".."}:
            raise GitExecutionError("工作树身份非法")
        bare_fd = open_directory_fd(bare, ())
        checkout_fd = None
        try:
            checkout_fd = open_directory_fd(checkout, ())
            expected_pointer = f"gitdir: {os.path.relpath(bare / 'worktrees' / task_key, checkout)}"
            if self._read_text(checkout_fd, (".git",)).strip() != expected_pointer:
                raise GitExecutionError("工作树 Git 指针已变化，请先恢复分配目录")
            head = self._allocated_head(bare_fd, branch, task_key)
            private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryDirectory(prefix="task-review-", dir=private_root) as raw:
                metadata = Path(raw) / "task.git"
                self._run(["git", "init", "--bare", str(metadata)])
                source = open_directory_fd(bare_fd, ("objects",))
                target = open_directory_fd(metadata, ("objects",))
                try:
                    self._copy_objects(source, target)
                finally:
                    os.close(source)
                    os.close(target)
                self._run(self._git_args(metadata, "update-ref", f"refs/heads/{branch}", head))
                executor = GitResourceExecutor(checkout_fd=checkout_fd)
                state = executor._review(metadata, checkout, branch)
                if review_base:
                    base = require_commit_sha(review_base)
                    state["committed_diff"] = self._run(
                        self._git_args(metadata, "diff", "--no-ext-diff", "--no-textconv", base, head)
                    ).stdout
                if action == "cleanup":
                    if state["dirty"] or head != expected_head:
                        raise GitExecutionError("工作树存在未提交或未推送进展")
                    if self._allocated_head(bare_fd, branch, task_key) != head:
                        raise GitExecutionError("任务分支在清理期间已变化")
                    shutil.rmtree(checkout)
                    worktrees_fd = open_directory_fd(bare_fd, ("worktrees",))
                    try:
                        shutil.rmtree(task_key, dir_fd=worktrees_fd)
                    finally:
                        os.close(worktrees_fd)
                    return state
                if action == "review":
                    if self._allocated_head(bare_fd, branch, task_key) != head:
                        raise GitExecutionError("任务分支在审查期间已变化，请刷新")
                    return state
                if head != expected_head or state["tree_sha"] != expected_tree:
                    raise GitExecutionError("工作树 HEAD 或内容已变化，请重新审查并确认")
                if action not in {"commit", "discard", "push"}:
                    raise GitExecutionError("不支持的工作树操作")
                parent = open_directory_fd(bare_fd, ("refs", "heads", *branch.split("/")[:-1]), create=True)
                name = branch.split("/")[-1]
                lock_name = name + ".lock"
                lock = None
                index_lock = None
                worktree_metadata = open_directory_fd(bare_fd, ("worktrees", task_key))
                try:
                    index_lock = os.open(
                        "index.lock",
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o644,
                        dir_fd=worktree_metadata,
                    )
                    lock = os.open(
                        lock_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644, dir_fd=parent
                    )
                    if self._allocated_head(bare_fd, branch, task_key) != head:
                        raise GitExecutionError("任务分支已变化，请重新审查并确认")
                    if action == "commit":
                        committed = executor._commit(metadata, checkout, branch, expected_head, expected_tree, message)
                    elif action == "push":
                        if state["dirty"]:
                            raise GitExecutionError("工作树存在未提交内容，请先提交")
                        pushed = self._push_commit(bare_path=metadata, expected_sha=head, branch=branch, **remote)
                        committed = {**state, "pushed_sha": pushed}
                    else:
                        committed = executor._discard(metadata, checkout, branch, expected_head, expected_tree)
                    with (metadata / "index").open("rb") as index, os.fdopen(os.dup(index_lock), "wb") as target:
                        shutil.copyfileobj(index, target)
                        target.flush()
                        os.fsync(target.fileno())
                    source = open_directory_fd(metadata, ("objects",))
                    target = open_directory_fd(bare_fd, ("objects",))
                    try:
                        self._copy_objects(source, target, skip_existing=True)
                    finally:
                        os.close(source)
                        os.close(target)
                    os.write(lock, (committed.get("committed_sha", head) + "\n").encode())
                    os.fsync(lock)
                    os.replace(lock_name, name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.replace("index.lock", "index", src_dir_fd=worktree_metadata, dst_dir_fd=worktree_metadata)
                finally:
                    if index_lock is not None:
                        os.close(index_lock)
                        try:
                            os.unlink("index.lock", dir_fd=worktree_metadata)
                        except FileNotFoundError:
                            pass
                    os.close(worktree_metadata)
                    if lock is not None:
                        os.close(lock)
                        try:
                            os.unlink(lock_name, dir_fd=parent)
                        except FileNotFoundError:
                            pass
                    os.close(parent)
                if review_base:
                    committed["committed_diff"] = self._run(
                        self._git_args(
                            metadata,
                            "diff",
                            "--no-ext-diff",
                            "--no-textconv",
                            require_commit_sha(review_base),
                            committed["head_sha"],
                        )
                    ).stdout
                return committed
        finally:
            if checkout_fd is not None:
                os.close(checkout_fd)
            os.close(bare_fd)

    @classmethod
    def _allocated_head(cls, bare_fd, branch, task_key):
        """只读取已知 HEAD/ref 文件，拒绝配置、指针与符号链接重定向。"""
        ref = f"refs/heads/{branch}"
        if cls._read_text(bare_fd, ("worktrees", task_key, "HEAD")).strip() != f"ref: {ref}":
            raise GitExecutionError("工作树分支与任务分配不一致")
        try:
            value = cls._read_text(bare_fd, tuple(ref.split("/"))).strip()
        except FileNotFoundError:
            value = None
            for line in cls._read_text(bare_fd, ("packed-refs",)).splitlines():
                if line and not line.startswith(("#", "^")):
                    sha, stored_ref = line.split(" ", 1)
                    if stored_ref == ref:
                        value = sha
                        break
        return require_commit_sha(value)

    @staticmethod
    def _read_text(root_fd, parts):
        """固定父目录后读取普通元数据文件，禁止跟随链接。"""
        parent = open_directory_fd(root_fd, parts[:-1])
        try:
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise GitExecutionError("Git 元数据不是普通文件")
                return source.read().decode()
        finally:
            os.close(parent)

    @classmethod
    def _copy_objects(cls, source, destination, *, skip_existing=False, parts=()):
        """复制普通 Git 对象文件，拒绝对象别名与外部存储路径。"""
        for name in os.listdir(source):
            path = (*parts, name)
            if path == ("info", "alternates"):
                raise GitExecutionError("工作树使用外部对象存储，不能安全执行人工操作")
            info = os.stat(name, dir_fd=source, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = open_directory_fd(source, (name,))
                target = open_directory_fd(destination, (name,), create=True)
                try:
                    cls._copy_objects(child, target, skip_existing=skip_existing, parts=path)
                finally:
                    os.close(child)
                    os.close(target)
            elif stat.S_ISREG(info.st_mode):
                try:
                    cls._copy_file(source, destination, (name,))
                except FileExistsError:
                    if not skip_existing:
                        raise
            else:
                raise GitExecutionError("Git 对象存储包含链接或特殊文件")
