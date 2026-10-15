"""项目资料的薄HTTP适配。"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services import workspace_service
from yuxi.services.project_files_service import list_project_files, project_workspace_path

project_files = APIRouter(prefix="/projects/{project_id}/files", tags=["project-files"])


class FileContent(BaseModel):
    """文本正文。"""

    path: str
    content: str


class Directory(BaseModel):
    """项目内目录。"""

    parent_path: str
    name: str


@project_files.get("")
async def tree(project_id: str, path: str = "/", search: str = "", db=Depends(get_db), user=Depends(get_required_user)):
    """读取当前项目资料目录。"""
    return await list_project_files(project_id=project_id, path=path, search=search, db=db, user=user)


@project_files.get("/content")
async def content(project_id: str, path: str = Query(...), db=Depends(get_db), user=Depends(get_required_user)):
    """预览项目内文件。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=path, db=db, user=user)
    return await workspace_service.read_workspace_file_content(path=resolved, current_user=user)


@project_files.put("/content")
async def save(project_id: str, body: FileContent, db=Depends(get_db), user=Depends(get_required_user)):
    """保存项目内文本。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=body.path, db=db, user=user)
    return await workspace_service.write_workspace_file_content(path=resolved, content=body.content, current_user=user)


@project_files.post("/directory")
async def directory(project_id: str, body: Directory, db=Depends(get_db), user=Depends(get_required_user)):
    """新建项目内目录。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=body.parent_path, db=db, user=user)
    return await workspace_service.create_workspace_directory(parent_path=resolved, name=body.name, current_user=user)


@project_files.post("/upload")
async def upload(project_id: str, parent_path: str = Form("/"), files: list[UploadFile] = File(...), db=Depends(get_db), user=Depends(get_required_user)):
    """上传到当前项目目录。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=parent_path, db=db, user=user)
    return await workspace_service.upload_workspace_files(parent_path=resolved, files=files, current_user=user)


@project_files.get("/download")
async def download(project_id: str, path: str = Query(...), db=Depends(get_db), user=Depends(get_required_user)):
    """下载项目内文件。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=path, db=db, user=user)
    return await workspace_service.download_workspace_file(path=resolved, current_user=user)


@project_files.delete("")
async def delete(project_id: str, path: str = Query(..., min_length=2), db=Depends(get_db), user=Depends(get_required_user)):
    """删除明确选择的项目内资料，保留项目根。"""
    _, resolved = await project_workspace_path(project_id=project_id, path=path, db=db, user=user, allow_root=False)
    return await workspace_service.delete_workspace_path(path=resolved, current_user=user)
