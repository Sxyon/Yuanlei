"""项目蓝图用例：以 Workdir 固定目录为事实源，读写可 diff 的方案文档。

蓝图文档的事实 Owner 是 Project Workdir 下的 `.yuanlei/blueprint/` 目录，
没有对应的数据库行；读取路径始终回读文件本身，因此绕过文件系统直接改数据库
不会改变蓝图内容。所有名称在进入文件系统前归一为单层 `.md` 文件名。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import Project, User
from yuxi.workspace.errors import FileTransferLimitError
from yuxi.workspace.paths import ensure_bound_user_workdir
from yuxi.workspace.workdir import Workdir

YUANLEI_DIR_NAME = ".yuanlei"
BLUEPRINT_DIR_NAME = "blueprint"
BLUEPRINT_DIRECTORY = f"{YUANLEI_DIR_NAME}/{BLUEPRINT_DIR_NAME}"
MAX_BLUEPRINT_NAME_LENGTH = 120
MAX_BLUEPRINT_BYTES = 256 * 1024
_BLUEPRINT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")


def validate_blueprint_name(name: str) -> str:
    """校验蓝图文档名是单层小写 `.md` 文件名。"""
    normalized = str(name or "").strip()
    if len(normalized) > MAX_BLUEPRINT_NAME_LENGTH or not _BLUEPRINT_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("蓝图文档名必须是长度不超过 120 的小写 .md 文件名")
    return normalized


def encode_blueprint_content(content: str) -> bytes:
    """把蓝图正文编码为 UTF-8 并限制大小。"""
    if not isinstance(content, str):
        raise ValueError("蓝图正文必须是字符串")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_BLUEPRINT_BYTES:
        raise ValueError(f"蓝图正文超过 {MAX_BLUEPRINT_BYTES} 字节上限")
    return encoded


def _blueprint_directory_conflict(scope: str) -> HTTPException:
    """构造蓝图目录被非目录占用的结构化冲突。"""
    return HTTPException(
        status_code=409,
        detail={"code": "blueprint_directory_conflict", "path": scope},
    )


async def _require_project(*, project_id: str, db: AsyncSession, user: User) -> Project:
    """只在当前用户可管理的 active selectable Project 上操作，否则 404。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return project


def _open_project_workdir(*, uid: str, project: Project) -> Workdir:
    """打开已提交绑定的 Project Workdir；不可用时显式失败。"""
    try:
        if project.directory_mode == "managed":
            ensure_bound_user_workdir(uid, project.workdir_path)
        return Workdir.open_existing(uid, project.workdir_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "workdir_unavailable", "message": "Project Workdir 不可用"},
        ) from exc


def _ensure_blueprint_directory(workdir: Workdir) -> None:
    """幂等创建 `.yuanlei/blueprint`；任一层被非目录占用时 fail-closed。"""
    steps = (
        ("/", YUANLEI_DIR_NAME, f"/{YUANLEI_DIR_NAME}"),
        (f"/{YUANLEI_DIR_NAME}", BLUEPRINT_DIR_NAME, f"/{BLUEPRINT_DIRECTORY}"),
    )
    for parent, name, scope in steps:
        try:
            info = workdir.stat(scope)
        except FileNotFoundError:
            info = None
        except PermissionError as exc:
            raise _blueprint_directory_conflict(scope) from exc
        if info is not None:
            if not info["is_dir"]:
                raise _blueprint_directory_conflict(scope)
            continue
        try:
            workdir.create_directory(parent, name)
        except FileExistsError:
            if not workdir.stat(scope)["is_dir"]:
                raise _blueprint_directory_conflict(scope)
        except PermissionError as exc:
            raise _blueprint_directory_conflict(scope) from exc


async def list_project_blueprint_view(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """列出当前用户项目 Workdir 内的蓝图文档；目录尚未建立时返回空列表。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    try:
        entries = workdir.list_directory(f"/{BLUEPRINT_DIRECTORY}")
    except FileNotFoundError:
        entries = []
    except (NotADirectoryError, PermissionError) as exc:
        raise _blueprint_directory_conflict(f"/{BLUEPRINT_DIRECTORY}") from exc
    documents = [
        {
            "name": entry["name"],
            "size": int(entry["size"]),
            "modified_at": float(entry["modified_at"]),
        }
        for entry in entries
        if not entry["is_dir"] and _BLUEPRINT_NAME_PATTERN.fullmatch(str(entry["name"]))
    ]
    documents.sort(key=lambda document: document["name"])
    return {
        "project_id": project.id,
        "directory": BLUEPRINT_DIRECTORY,
        "documents": documents,
    }


async def get_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """读取单个蓝图文档；缺失与超限分别返回结构化错误。"""
    normalized_name = validate_blueprint_name(name)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    path = f"/{BLUEPRINT_DIRECTORY}/{normalized_name}"
    try:
        payload = workdir.read_file(path, MAX_BLUEPRINT_BYTES)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail="蓝图文档不存在") from exc
    except FileTransferLimitError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "blueprint_too_large", "max_bytes": MAX_BLUEPRINT_BYTES},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="蓝图文档不存在") from exc
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "blueprint_not_utf8", "message": "蓝图文档必须是 UTF-8 文本"},
        ) from exc
    metadata = workdir.stat(path)
    return {
        "name": normalized_name,
        "content": content,
        "size": int(metadata["size"]),
        "modified_at": float(metadata["modified_at"]),
    }


async def put_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    content: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """创建或整体替换蓝图文档；目录按需建立，文件以原子替换写入。"""
    normalized_name = validate_blueprint_name(name)
    encoded = encode_blueprint_content(content)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    _ensure_blueprint_directory(workdir)
    path = f"/{BLUEPRINT_DIRECTORY}/{normalized_name}"
    try:
        metadata = workdir.replace_file(path, encoded)
    except PermissionError as exc:
        raise _blueprint_directory_conflict(path) from exc
    return {
        "name": normalized_name,
        "content": content,
        "size": int(metadata["size"]),
        "modified_at": float(metadata["modified_at"]),
    }
