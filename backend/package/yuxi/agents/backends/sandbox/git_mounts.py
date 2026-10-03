"""从持久占用事实派生沙盒 Git 目录的实际写权限。"""

import hashlib
import json
import os
import stat
from contextlib import contextmanager

from yuxi.workspace.paths import normalize_workdir_path, user_workspace_dir
from yuxi.utils.paths import open_directory_fd


def git_mount_fingerprint(mounts: list[dict]) -> str | None:
    """空清单沿用普通沙盒，非空清单固定完整目录及权限。"""
    if not mounts:
        return None
    return hashlib.sha256(json.dumps(mounts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@contextmanager
def git_mount_boundary(*, conninfo: str, uid: str):
    """在创建或发现沙盒期间，与资源目录初始化共享用户事务锁。"""
    if not conninfo:
        yield None
        return
    import psycopg

    with psycopg.connect(conninfo, connect_timeout=3) as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"project-git-user:{uid}",),
        )
        yield connection


def load_git_mounts(*, connection, uid: str, runtime_scope: str) -> list[dict]:
    """默认只读全部用户资源，仅当前根运行已持有的实际目录可写。"""
    if connection is None:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.workdir_path, r.checkout_path,
                   EXISTS (
                     SELECT 1 FROM project_git_occupancies o
                     JOIN agent_runs a ON a.id = o.active_run_id AND a.uid = o.uid
                     LEFT JOIN agent_run_scopes s ON s.run_id = a.id
                     WHERE o.repository_id = r.id AND o.uid = r.uid AND o.status = 'owned'
                       AND EXISTS (SELECT 1 FROM project_git_worktrees w WHERE w.repository_id = o.repository_id
                         AND w.runtime_scope_id = o.scope_key AND w.uid = o.uid AND w.usage_mode = 'in_place')
                       AND a.status IN ('pending', 'running', 'interrupted')
                       AND COALESCE(s.scope_key, a.runtime_scope_id) = %s
                   )
              FROM project_git_repositories r JOIN projects p ON p.id = r.project_id AND p.uid = r.uid
             WHERE r.uid = %s AND r.checkout_path IS NOT NULL AND r.checkout_head_sha IS NOT NULL
            UNION ALL
            SELECT DISTINCT p.workdir_path, 'repos', FALSE
              FROM project_git_repositories r JOIN projects p ON p.id = r.project_id AND p.uid = r.uid
             WHERE r.uid = %s AND r.status = 'active'
            UNION ALL
            SELECT DISTINCT p.workdir_path, 'repos/' || r.directory_name || '/repository.git', TRUE
              FROM project_git_repositories r JOIN projects p ON p.id = r.project_id AND p.uid = r.uid
             WHERE r.uid = %s
               AND EXISTS (
                 SELECT 1 FROM project_git_occupancies o
                 JOIN agent_runs a ON a.id = o.active_run_id AND a.uid = o.uid
                 LEFT JOIN agent_run_scopes s ON s.run_id = a.id
                 WHERE o.repository_id = r.id AND o.uid = r.uid AND o.status = 'owned'
                   AND EXISTS (SELECT 1 FROM project_git_worktrees w WHERE w.repository_id = o.repository_id
                       AND w.runtime_scope_id = o.scope_key AND w.uid = o.uid AND w.usage_mode = 'worktree')
                   AND a.status IN ('pending', 'running', 'interrupted')
                   AND COALESCE(s.scope_key, a.runtime_scope_id) = %s
               )
            UNION ALL
            SELECT p.workdir_path, w.relative_path,
                   EXISTS (
                     SELECT 1 FROM project_git_occupancies o
                     JOIN agent_runs a ON a.id = o.active_run_id AND a.uid = o.uid
                     LEFT JOIN agent_run_scopes s ON s.run_id = a.id
                     WHERE o.repository_id = w.repository_id AND o.scope_key = w.runtime_scope_id
                       AND o.uid = w.uid AND o.status = 'owned'
                       AND a.status IN ('pending', 'running', 'interrupted')
                       AND COALESCE(s.scope_key, a.runtime_scope_id) = %s
                   )
              FROM project_git_worktrees w JOIN projects p ON p.id = w.project_id AND p.uid = w.uid
              JOIN project_git_repositories r ON r.id = w.repository_id
             WHERE w.uid = %s AND w.status = 'ready' AND w.usage_mode = 'worktree'
               AND EXISTS (
                 SELECT 1 FROM project_git_occupancies o
                 JOIN agent_runs a ON a.id = o.active_run_id AND a.uid = o.uid
                 LEFT JOIN agent_run_scopes s ON s.run_id = a.id
                 WHERE o.repository_id = w.repository_id AND o.scope_key = w.runtime_scope_id
                   AND o.uid = w.uid AND o.status = 'owned'
                   AND a.status IN ('pending', 'running', 'interrupted')
                   AND COALESCE(s.scope_key, a.runtime_scope_id) = %s
               )
            """,
            (runtime_scope, uid, uid, uid, runtime_scope, runtime_scope, uid, runtime_scope),
        )
        values = cursor.fetchall()
    mounts = {}
    for project_path, relative_path, writable in values:
        path = normalize_workdir_path(f"{project_path}/{relative_path}")
        if path in mounts and mounts[path] != (not writable):
            raise RuntimeError("Git 目录存在冲突的持久占用")
        mounts[path] = not writable
    return [{"path": path, "read_only": read_only} for path, read_only in sorted(mounts.items())]


def verify_git_mount_aliases(*, uid: str, mounts: list[dict]):
    """启用挂载前拒绝历史硬链接，保留文件并要求显式复制修复。"""
    if not mounts:
        return
    root = open_directory_fd(user_workspace_dir(uid), ())
    checked = []
    try:
        for mount in mounts:
            path = mount["path"]
            if any(path.startswith(parent + "/") for parent in checked):
                continue
            descriptor = open_directory_fd(root, tuple(path.split("/")))
            try:
                _verify_directory_links(descriptor)
            finally:
                os.close(descriptor)
            checked.append(path)
    finally:
        os.close(root)


def _verify_directory_links(directory_fd: int):
    """固定目录 fd 递归扫描，符号链接只看链接本身。"""
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise RuntimeError("Git 目录存在历史硬链接，请将关联文件复制为独立文件后重试；系统没有删除任何内容")
        if stat.S_ISDIR(info.st_mode):
            child = open_directory_fd(directory_fd, (name,))
            try:
                _verify_directory_links(child)
            finally:
                os.close(child)
