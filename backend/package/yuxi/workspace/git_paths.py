"""Project Git 目录和分支的安全派生。"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath

from yuxi.agents.backends.paths import runtime_workdir_path
from yuxi.utils.paths import open_directory_fd
from yuxi.workspace.paths import user_workdir_host_dir

_UNSAFE_SLUG = re.compile(r"[^a-z0-9]+")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")


def derive_repository_directory(alias: str, repository_id: str) -> str:
    """由显示 alias 和绑定 ID 派生不可碰撞的目录名。"""
    normalized = unicodedata.normalize("NFKD", str(alias or "")).encode("ascii", "ignore").decode().lower()
    slug = _UNSAFE_SLUG.sub("-", normalized).strip("-")[:48] or "repo"
    digest = hashlib.sha256(str(repository_id).encode()).hexdigest()[:12]
    return f"{slug}-{digest}"


def derive_task_key(uid: str, runtime_scope_id: str) -> str:
    """由用户和根任务作用域派生稳定且不泄露身份的任务键。"""
    if not str(uid).strip() or not str(runtime_scope_id).strip():
        raise ValueError("uid and runtime_scope_id are required")
    return hashlib.sha256(f"{uid}\0{runtime_scope_id}".encode()).hexdigest()[:24]


def configured_branch_prefix() -> str:
    """读取并校验全局任务分支前缀。"""
    prefix = os.getenv("YUXI_GIT_BRANCH_PREFIX", "codex/").strip()
    parts = prefix[:-1].split("/") if prefix.endswith("/") else []
    if not parts or any(not _SAFE_REF_PART.fullmatch(part) for part in parts):
        raise ValueError("YUXI_GIT_BRANCH_PREFIX must be a safe prefix ending with '/'")
    if any(part.endswith((".", ".lock")) for part in parts) or "@{" in prefix:
        raise ValueError("YUXI_GIT_BRANCH_PREFIX contains invalid ref characters")
    return prefix


def derive_task_branch(uid: str, runtime_scope_id: str) -> str:
    """派生根任务分支。"""
    return f"{configured_branch_prefix()}task-{derive_task_key(uid, runtime_scope_id)}"


def normalize_branch_slug(value: str) -> str:
    """校验模型或用户提供的分支描述，支持用 ``/`` 表达分支层级分组。

    每个 ``/`` 分隔的段须为 ASCII kebab-case（小写字母、数字、连字符），
    总长不超过 48 字符。
    """
    slug = str(value or "").strip()
    if len(slug) > 48 or not _BRANCH_SLUG.fullmatch(slug):
        raise ValueError("branch_slug must be ASCII kebab-case with at most 48 characters")
    return slug


def normalize_base_branch(value: str) -> str:
    """校验用户可选择的精确 branch name，拒绝完整 ref 与 revision 表达式。"""
    branch = str(value or "").strip()
    if not branch or len(branch) > 255 or branch.startswith("refs/"):
        raise ValueError("invalid base branch")
    completed = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("invalid base branch")
    return branch


def derive_allocation_branch(kind: str, slug: str, uid: str, runtime_scope_id: str) -> str:
    """由受限业务意图生成任务分支，并交给 Git 校验最终 ref。"""
    normalized_kind = str(kind or "").strip()
    if normalized_kind not in {"feature", "fix", "docs", "refactor", "chore", "test"}:
        raise ValueError("unsupported branch_kind")
    branch = (
        f"{configured_branch_prefix()}{normalized_kind}/"
        f"{normalize_branch_slug(slug)}-{derive_task_key(uid, runtime_scope_id)[:8]}"
    )
    completed = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("generated task branch is not a valid Git branch")
    return branch


def repository_relative_paths(directory_name: str, task_key: str | None = None) -> tuple[str, str | None]:
    """构造 Project Workdir 内的 bare repo 与可选 worktree 相对路径。"""
    for value in (directory_name, task_key):
        if value is not None and (not value or "/" in value or "\\" in value or value in {".", ".."}):
            raise ValueError("invalid Git path component")
    base = PurePosixPath("repos", directory_name)
    bare = (base / "repository.git").as_posix()
    worktree = (base / "worktrees" / task_key).as_posix() if task_key else None
    return bare, worktree


def resolve_project_git_host_paths(
    uid: str,
    workdir_path: str,
    directory_name: str,
    task_key: str | None = None,
    *,
    create_parents: bool = False,
) -> tuple[Path, Path | None]:
    """在已校验 Project Workdir 下解析 Git 宿主机路径。"""
    project_root = user_workdir_host_dir(uid, workdir_path)
    bare_relative, worktree_relative = repository_relative_paths(directory_name, task_key)
    bare = project_root.joinpath(*PurePosixPath(bare_relative).parts)
    worktree = project_root.joinpath(*PurePosixPath(worktree_relative).parts) if worktree_relative else None
    parent_parts = ("repos", directory_name)
    descriptor = open_directory_fd(project_root, parent_parts, create=create_parents)
    os.close(descriptor)
    if bare.is_symlink() or (bare.exists() and not bare.is_dir()):
        raise ValueError("bare repository path is not a regular directory")
    if worktree is not None:
        descriptor = open_directory_fd(project_root, (*parent_parts, "worktrees"), create=create_parents)
        os.close(descriptor)
        if worktree.is_symlink() or (worktree.exists() and not worktree.is_dir()):
            raise ValueError("worktree path is not a regular directory")
    return bare, worktree


def runtime_git_worktree_path(workdir_path: str, relative_path: str) -> str:
    """将 Project 内的 worktree 相对路径映射到 Sandbox runtime。"""
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("invalid worktree relative path")
    return f"{runtime_workdir_path(workdir_path).rstrip('/')}/{relative.as_posix()}"


def require_commit_sha(value: str) -> str:
    """校验 Git commit SHA-256/当前 SHA-1 的十六进制形态。"""
    normalized = str(value or "").strip().lower()
    if not (re.fullmatch(r"[0-9a-f]{40}", normalized) or _SHA256_HEX.fullmatch(normalized)):
        raise ValueError("expected_head_sha must be a full commit SHA")
    return normalized
