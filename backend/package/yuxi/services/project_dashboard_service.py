"""项目 Dashboard 页面 revision 的读视图与 hash 对账（yuanlei 域）。"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.project_dashboard_repository import ProjectDashboardRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import ProjectDashboard, User
from yuxi.utils.datetime_utils import format_utc_datetime
from yuxi.workspace import Workdir
from yuxi.workspace.errors import FileTransferLimitError

PAGE_ENTRY_PATH = "/dashboard/index.html"
MAX_PAGE_BYTES = 1024 * 1024


def _read_page_snapshot(workdir: Workdir) -> dict[str, Any]:
    """读取入口页面字节并计算 hash；不可信路径或超限时返回不可用快照。"""
    try:
        raw = workdir.read_file(PAGE_ENTRY_PATH, MAX_PAGE_BYTES)
    except FileNotFoundError:
        return {
            "exists": False,
            "usable": False,
            "unusable_reason": None,
            "sha256": None,
            "size": None,
            "html": None,
        }
    except FileTransferLimitError:
        return {
            "exists": True,
            "usable": False,
            "unusable_reason": "content",
            "sha256": None,
            "size": None,
            "html": None,
        }
    except (PermissionError, IsADirectoryError, NotADirectoryError):
        return {
            "exists": True,
            "usable": False,
            "unusable_reason": "path",
            "sha256": None,
            "size": None,
            "html": None,
        }
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "exists": True,
            "usable": False,
            "unusable_reason": "content",
            "sha256": None,
            "size": None,
            "html": None,
        }
    return {
        "exists": True,
        "usable": True,
        "unusable_reason": None,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "html": html,
    }


def _repair_state(row: ProjectDashboard | None, *, observed_sha256: str | None, observed_size: int | None) -> dict:
    """构造待修复视图：不返回可与 revision 对应的页面内容。"""
    return {
        "state": "repair_required",
        "revision": int(row.revision) if row is not None else 0,
        "sha256": observed_sha256,
        "size": observed_size,
        "updated_at": format_utc_datetime(row.updated_at) if row is not None else None,
        "html": None,
    }


async def get_project_dashboard_view(*, project_id: str, db: AsyncSession, user: User) -> dict[str, Any]:
    """读取项目页面状态；元数据与磁盘哈希不一致时显式返回待修复。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    row = await ProjectDashboardRepository(db).get(project_id=project.id)
    try:
        workdir = Workdir.open_existing(str(user.uid), project.workdir_path)
    except (FileNotFoundError, ValueError, PermissionError):
        return _repair_state(row, observed_sha256=None, observed_size=None)

    snapshot = _read_page_snapshot(workdir)
    if row is None and not snapshot["exists"]:
        return {
            "state": "empty",
            "revision": 0,
            "sha256": None,
            "size": None,
            "updated_at": None,
            "html": None,
        }
    if (
        row is not None
        and snapshot["usable"]
        and snapshot["sha256"] == row.content_sha256
        and snapshot["size"] == int(row.content_size)
    ):
        return {
            "state": "ready",
            "revision": int(row.revision),
            "sha256": row.content_sha256,
            "size": int(row.content_size),
            "updated_at": format_utc_datetime(row.updated_at),
            "html": snapshot["html"],
        }
    return _repair_state(
        row,
        observed_sha256=snapshot["sha256"] if snapshot["usable"] else None,
        observed_size=snapshot["size"] if snapshot["usable"] else None,
    )


def _encode_page_html(html: str) -> bytes:
    """校验页面内容并返回 UTF-8 字节。"""
    if not isinstance(html, str) or not html.strip():
        raise ValueError("页面 HTML 不能为空")
    lowered = html.lower()
    if "<html" not in lowered and "<!doctype html" not in lowered:
        raise ValueError("页面必须包含 <html> 或 <!doctype html>")
    raw = html.encode("utf-8")
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError(f"页面 HTML 超过 {MAX_PAGE_BYTES} 字节上限")
    return raw


def _revision_conflict(current_revision: int) -> HTTPException:
    """构造携带当前 revision 的结构化 409。"""
    return HTTPException(
        status_code=409,
        detail={"code": "revision_conflict", "current_revision": current_revision},
    )


def _page_path_invalid(exc: Exception | None = None) -> HTTPException:
    """入口路径不可信时失败关闭。"""
    error = HTTPException(status_code=409, detail={"code": "invalid_page_path"})
    if exc is not None:
        error.__cause__ = exc
    return error


def _page_content_unusable() -> HTTPException:
    """入口已有不可安全读取的内容时拒绝覆盖。"""
    return HTTPException(status_code=409, detail={"code": "invalid_page_content"})


def _ensure_dashboard_directory(workdir: Workdir) -> None:
    """在 Workdir 内准备 dashboard/ 目录；已存在的对象必须是真实目录。"""
    try:
        meta = workdir.stat("/dashboard")
    except FileNotFoundError:
        try:
            workdir.create_directory("/", "dashboard")
        except FileExistsError:
            pass
        except (PermissionError, ValueError) as exc:
            raise _page_path_invalid(exc) from exc
        try:
            meta = workdir.stat("/dashboard")
        except (PermissionError, FileNotFoundError, ValueError) as exc:
            raise _page_path_invalid(exc) from exc
    except (PermissionError, ValueError) as exc:
        raise _page_path_invalid(exc) from exc
    if not meta.get("is_dir"):
        raise _page_path_invalid()


async def write_project_dashboard_view(
    *,
    project_id: str,
    expected_revision: int,
    html: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    """提交页面：锁项目、收敛外部改写、比较 revision、原子替换并回读。"""
    raw = _encode_page_html(html)
    digest = hashlib.sha256(raw).hexdigest()
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    repo = ProjectDashboardRepository(db)
    await repo.lock_project(project.id)
    row = await repo.get_for_update(project_id=project.id)
    try:
        workdir = Workdir.open_existing(str(user.uid), project.workdir_path)
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail={"code": "workdir_unavailable"}) from exc

    current_revision = int(row.revision) if row is not None else 0
    snapshot = _read_page_snapshot(workdir)
    # 非 UTF-8、超限、符号链接等既有入口不是可安全覆盖的页面；保留其字节，
    # 让读取端暴露 repair_required，避免 writer 把异常状态静默伪装成正常版本。
    if snapshot["exists"] and not snapshot["usable"]:
        if snapshot["unusable_reason"] == "path":
            raise _page_path_invalid()
        raise _page_content_unusable()
    disk_changed = snapshot["usable"] and (
        row is None or snapshot["sha256"] != row.content_sha256 or snapshot["size"] != int(row.content_size)
    )
    if disk_changed:
        # 外部改写或缺失元数据：先把磁盘内容采纳为普通 revision，再要求提交者基于该版本合并。
        current_revision += 1
        if row is None:
            row = await repo.add(
                project_id=project.id,
                revision=current_revision,
                content_sha256=snapshot["sha256"],
                content_size=snapshot["size"],
                operator=str(user.uid),
            )
        else:
            repo.apply_revision(
                row=row,
                revision=current_revision,
                content_sha256=snapshot["sha256"],
                content_size=snapshot["size"],
                operator=str(user.uid),
            )

    if int(expected_revision) != current_revision:
        if disk_changed:
            # 让收敛结果对后续读取可见；本次提交不写页面文件。
            await db.commit()
        raise _revision_conflict(current_revision)

    _ensure_dashboard_directory(workdir)
    try:
        workdir.replace_file(PAGE_ENTRY_PATH, raw)
    except (PermissionError, IsADirectoryError, ValueError) as exc:
        raise _page_path_invalid(exc) from exc

    try:
        read_back = workdir.read_file(PAGE_ENTRY_PATH, MAX_PAGE_BYTES)
    except (FileNotFoundError, PermissionError, IsADirectoryError, FileTransferLimitError, ValueError) as exc:
        raise HTTPException(status_code=500, detail={"code": "page_read_back_failed"}) from exc
    read_back_digest = hashlib.sha256(read_back).hexdigest()
    if read_back_digest != digest:
        raise HTTPException(status_code=500, detail={"code": "page_read_back_failed"})

    new_revision = current_revision + 1
    if row is None:
        row = await repo.add(
            project_id=project.id,
            revision=new_revision,
            content_sha256=read_back_digest,
            content_size=len(read_back),
            operator=str(user.uid),
        )
    else:
        repo.apply_revision(
            row=row,
            revision=new_revision,
            content_sha256=read_back_digest,
            content_size=len(read_back),
            operator=str(user.uid),
        )
    await db.commit()
    await db.refresh(row)
    return {
        "state": "ready",
        "revision": int(row.revision),
        "sha256": row.content_sha256,
        "size": int(row.content_size),
        "updated_at": format_utc_datetime(row.updated_at),
    }
