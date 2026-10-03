"""项目 Git 资源的可信元数据路径与 no-follow 目录边界。"""

import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from yuxi.config import get_user_data_dir
from yuxi.git.executor import GitExecutionError
from yuxi.git.resource_executor import GitResourceExecutor
from yuxi.utils.paths import open_directory_fd
from yuxi.workspace.paths import normalize_workdir_path, user_workdir_host_dir


def normalize_resource_path(value: str) -> str:
    """资源目录相对于项目空间，禁止与 Git 内部目录混用。"""
    path = normalize_workdir_path(value)
    if len(path) > 512 or any(part == ".git" for part in PurePosixPath(path).parts):
        raise ValueError("资源目录非法")
    if PurePosixPath(path).parts[0] == "repos":
        raise ValueError("repos 是现有任务工作树目录，请选择其他目录")
    return path


def resource_metadata_path(repository_id: str) -> Path:
    """解析不挂载到智能体的共享持久 Git 存储。"""
    raw = os.getenv("YUXI_GIT_STATE_DIR", "").strip()
    if not raw:
        raise GitExecutionError("可信 Git 存储未配置")
    root = Path(raw).resolve(strict=True)
    if root.is_relative_to(get_user_data_dir().resolve()):
        raise GitExecutionError("可信 Git 存储不能位于智能体可写目录")
    if not repository_id or any(char not in "0123456789abcdef-" for char in repository_id):
        raise GitExecutionError("资源身份非法")
    return root / repository_id / "resource.git"


@contextmanager
def open_resource_checkout(uid: str, workdir_path: str, relative_path: str, *, create: bool = False):
    """固定 no-follow 目录句柄，将同一目录传给文件与 Git 子进程。"""
    root = user_workdir_host_dir(uid, workdir_path)
    descriptor = open_directory_fd(root, PurePosixPath(normalize_resource_path(relative_path)).parts, create=create)
    try:
        yield Path(f"/proc/self/fd/{descriptor}"), GitResourceExecutor(checkout_fd=descriptor)
    finally:
        os.close(descriptor)
