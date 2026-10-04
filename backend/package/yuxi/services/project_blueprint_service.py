"""项目蓝图用例：以 Workdir 固定目录为事实源，读写可 diff 的方案文档。

蓝图文档的事实 Owner 是 Project Workdir 下的 `.yuanlei/blueprint/` 目录，
没有对应的数据库行；读取路径始终回读文件本身，因此绕过文件系统直接改数据库
不会改变蓝图内容。所有名称在进入文件系统前归一为单层 `.md` 文件名。
"""

from __future__ import annotations

import re
import uuid
import errno
from datetime import UTC, datetime
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
ARCHIVE_DIR_NAME = "archive"
ARCHIVE_DIRECTORY = f"{BLUEPRINT_DIRECTORY}/{ARCHIVE_DIR_NAME}"
MAX_BLUEPRINT_NAME_LENGTH = 120
MAX_BLUEPRINT_STEM_BYTES = 194
MAX_BLUEPRINT_BYTES = 256 * 1024
_BLUEPRINT_NAME_PATTERN = re.compile(r"^[^\W_][\w.，。！？、；：（）【】《》“”‘’！!#$%&'+,;=@^`~(){}\[\]+-]*\.md$")
_ARCHIVE_NAME_PATTERN = re.compile(r"^(?P<stem>.+)--(?P<archived_at>\d{8}T\d{12}Z)--[0-9a-f]{32}\.md$")


def validate_blueprint_name(name: str) -> str:
    """校验蓝图文档名是支持中文的单层 `.md` 文件名。"""
    normalized = str(name or "").strip()
    if (
        len(normalized) > MAX_BLUEPRINT_NAME_LENGTH
        or len(normalized[:-3].encode("utf-8")) > MAX_BLUEPRINT_STEM_BYTES
        or not _BLUEPRINT_NAME_PATTERN.fullmatch(normalized)
    ):
        raise ValueError("蓝图文档名须为不超过 120 字的中文、英文、数字或常用标点组成的 .md 文件名（无空格）")
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


def _ensure_archive_directory(workdir: Workdir) -> None:
    """在蓝图目录内建立归档目录，拒绝同名非目录。"""
    _ensure_blueprint_directory(workdir)
    path = f"/{ARCHIVE_DIRECTORY}"
    try:
        info = workdir.stat(path)
    except FileNotFoundError:
        info = None
    except PermissionError as exc:
        raise _blueprint_directory_conflict(path) from exc
    if info is not None:
        if not info["is_dir"]:
            raise _blueprint_directory_conflict(path)
        return
    try:
        workdir.create_directory(f"/{BLUEPRINT_DIRECTORY}", ARCHIVE_DIR_NAME)
    except FileExistsError:
        if not workdir.stat(path)["is_dir"]:
            raise _blueprint_directory_conflict(path)
    except PermissionError as exc:
        raise _blueprint_directory_conflict(path) from exc


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
    documents = []
    for entry in entries:
        if entry["is_dir"]:
            continue
        filename = str(entry["name"])
        try:
            name = validate_blueprint_name(filename)
        except ValueError:
            continue
        if name != filename:
            continue
        documents.append(
            {
                "name": name,
                "size": int(entry["size"]),
                "modified_at": float(entry["modified_at"]),
            }
        )
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
    return _read_blueprint_file(workdir, path, normalized_name)


def _read_blueprint_file(workdir: Workdir, path: str, name: str) -> dict[str, Any]:
    """从受限 Workdir 回读蓝图正文和文件元数据。"""
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
        "name": name,
        "content": content,
        "size": int(metadata["size"]),
        "modified_at": float(metadata["modified_at"]),
    }


async def create_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    content: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """独占创建蓝图；同名文件已存在时返回冲突且不覆盖内容。"""
    normalized_name = validate_blueprint_name(name)
    encoded = encode_blueprint_content(content)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    _ensure_blueprint_directory(workdir)
    path = f"/{BLUEPRINT_DIRECTORY}/{normalized_name}"
    try:
        metadata = workdir.create_file(path, encoded)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "blueprint_exists", "message": "同名蓝图已存在，请换一个名称"},
        ) from exc
    except PermissionError as exc:
        raise _blueprint_directory_conflict(path) from exc
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


async def list_project_blueprint_archives_view(
    *,
    project_id: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """列出项目 Workdir 的整份蓝图归档。"""
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    try:
        entries = workdir.list_directory(f"/{ARCHIVE_DIRECTORY}")
    except FileNotFoundError:
        entries = []
    except (NotADirectoryError, PermissionError) as exc:
        raise _blueprint_directory_conflict(f"/{ARCHIVE_DIRECTORY}") from exc
    documents = []
    for entry in entries:
        match = _ARCHIVE_NAME_PATTERN.fullmatch(str(entry["name"]))
        if (
            entry["is_dir"]
            or match is None
            or len(match.group("stem")) + 3 > MAX_BLUEPRINT_NAME_LENGTH
            or len(match.group("stem").encode("utf-8")) > MAX_BLUEPRINT_STEM_BYTES
        ):
            continue
        try:
            validate_blueprint_name(f"{match.group('stem')}.md")
        except ValueError:
            continue
        documents.append(
            {
                "archive_name": entry["name"],
                "name": f"{match.group('stem')}.md",
                "archived_at": match.group("archived_at"),
                "size": int(entry["size"]),
            }
        )
    documents.sort(key=lambda document: (document["archived_at"], document["archive_name"]), reverse=True)
    return {"project_id": project.id, "documents": documents}


async def get_project_blueprint_archive_view(
    *,
    project_id: str,
    archive_name: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """只读回顾一份归档蓝图。"""
    match = _ARCHIVE_NAME_PATTERN.fullmatch(str(archive_name or ""))
    if (
        match is None
        or len(match.group("stem")) + 3 > MAX_BLUEPRINT_NAME_LENGTH
        or len(match.group("stem").encode("utf-8")) > MAX_BLUEPRINT_STEM_BYTES
    ):
        raise ValueError("无效的蓝图归档名称")
    validate_blueprint_name(f"{match.group('stem')}.md")
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    document = _read_blueprint_file(
        workdir,
        f"/{ARCHIVE_DIRECTORY}/{archive_name}",
        f"{match.group('stem')}.md",
    )
    return {**document, "archive_name": archive_name, "archived_at": match.group("archived_at")}


async def archive_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """把当前蓝图原子移入归档目录，拒绝覆盖已有历史文件。"""
    normalized_name = validate_blueprint_name(name)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    _ensure_archive_directory(workdir)
    archived_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive_name = f"{normalized_name[:-3]}--{archived_at}--{uuid.uuid4().hex}.md"
    try:
        metadata = workdir.move_file(
            f"/{BLUEPRINT_DIRECTORY}/{normalized_name}",
            f"/{ARCHIVE_DIRECTORY}/{archive_name}",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="蓝图文档不存在") from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "blueprint_archive_conflict", "message": "归档目标已存在，请重试"},
        ) from exc
    except PermissionError as exc:
        raise _blueprint_directory_conflict(f"/{BLUEPRINT_DIRECTORY}/{normalized_name}") from exc
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}:
            raise
        raise HTTPException(
            status_code=409,
            detail={"code": "blueprint_archive_unavailable", "message": "当前文件系统不支持安全归档"},
        ) from exc
    return {
        "archive_name": archive_name,
        "name": normalized_name,
        "archived_at": archived_at,
        "size": int(metadata["size"]),
    }


async def rename_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    new_name: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """修改当前蓝图文件名，保留正文并拒绝覆盖同名文件。"""
    name = validate_blueprint_name(name)
    new_name = validate_blueprint_name(new_name)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    source = f"/{BLUEPRINT_DIRECTORY}/{name}"
    target = f"/{BLUEPRINT_DIRECTORY}/{new_name}"
    try:
        if name == new_name:
            metadata = workdir.stat(source)
            if metadata["is_dir"]:
                raise PermissionError("only regular files can be renamed")
        else:
            metadata = workdir.move_file(source, target)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail="蓝图文档不存在") from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "blueprint_exists", "message": "同名蓝图已存在，请换一个名称"}
        ) from exc
    except PermissionError as exc:
        raise _blueprint_directory_conflict(source) from exc
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}:
            raise
        raise HTTPException(
            status_code=409, detail={"code": "blueprint_rename_unavailable", "message": "当前文件系统不支持安全重命名"}
        ) from exc
    return {"name": new_name, "size": int(metadata["size"]), "modified_at": float(metadata["modified_at"])}


async def delete_project_blueprint_view(
    *,
    project_id: str,
    name: str,
    archived: bool = False,
    db: AsyncSession,
    user: User,
) -> None:
    """永久删除当前或归档蓝图，仅允许删除受控名称的普通文件。"""
    if archived:
        match = _ARCHIVE_NAME_PATTERN.fullmatch(name)
        if match is None:
            raise ValueError("无效的蓝图归档名称")
        validate_blueprint_name(f"{match.group('stem')}.md")
    else:
        name = validate_blueprint_name(name)
    project = await _require_project(project_id=project_id, db=db, user=user)
    workdir = _open_project_workdir(uid=str(user.uid), project=project)
    directory = ARCHIVE_DIRECTORY if archived else BLUEPRINT_DIRECTORY
    try:
        workdir.delete_file(f"/{directory}/{name}")
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail="蓝图文档不存在") from exc
    except PermissionError as exc:
        raise _blueprint_directory_conflict(f"/{directory}/{name}") from exc
