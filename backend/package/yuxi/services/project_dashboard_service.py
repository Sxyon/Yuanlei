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
        return {"exists": False, "usable": False, "sha256": None, "size": None, "html": None}
    except (FileTransferLimitError, PermissionError, IsADirectoryError, NotADirectoryError):
        return {"exists": True, "usable": False, "sha256": None, "size": None, "html": None}
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"exists": True, "usable": False, "sha256": None, "size": None, "html": None}
    return {
        "exists": True,
        "usable": True,
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
