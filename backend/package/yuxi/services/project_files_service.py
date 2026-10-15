"""项目资料的授权及虚拟路径边界，文件操作沿用Workspace。"""

from pathlib import PurePosixPath

from fastapi import HTTPException
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.services import workspace_service


async def project_workspace_path(*, project_id, path, db, user, allow_root=True):
    """在真实文件动作前确认Project可见性及相对路径。"""
    project = await ProjectRepository(db).get_active_selectable_for_user(project_id, str(user.uid))
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    if "\\" in path or "\x00" in path or any(part in (".", "..") for part in path.split("/")):
        raise HTTPException(status_code=400, detail="资料路径必须位于当前项目内")
    relative = path.lstrip("/")
    if not allow_root and not relative:
        raise HTTPException(status_code=400, detail="不能删除项目根目录")
    root = "/" + str(project.workdir_path).strip("/")
    return root, str(PurePosixPath(root) / relative)


async def list_project_files(*, project_id, path, search, db, user):
    """仅扫描当前项目目录，返回项目内虚拟路径。"""
    root, resolved = await project_workspace_path(project_id=project_id, path=path, db=db, user=user)
    result = await workspace_service.list_workspace_tree(
        path=resolved, recursive=bool(search), files_only=bool(search), current_user=user, db=db
    )
    entries = []
    for entry in result["entries"]:
        relative = "/" + str(PurePosixPath(entry["path"]).relative_to(root))
        if not search or search.casefold() in entry["name"].casefold():
            entries.append({**entry, "path": relative})
    return {"entries": entries}
