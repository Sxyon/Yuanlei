"""授权 Conversation 对持久化 Project Workdir 的访问。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from yuxi.repositories.conversation_repository import ConversationRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import Conversation, Project
from yuxi.workspace.paths import ensure_bound_user_workdir
from yuxi.workspace.workdir import Workdir


@dataclass(frozen=True, slots=True)
class WorkdirBinding:
    """Conversation 当前 Project 所拥有的已授权 Workdir 快照。"""

    conversation_id: int
    thread_id: str
    uid: str
    project_id: str
    workdir_path: str
    directory_mode: str

    @property
    def materialize_managed(self) -> bool:
        """判断该绑定是否需要在事务提交后物化目录。"""
        return self.directory_mode == "managed"


@dataclass(frozen=True, slots=True)
class AuthorizedWorkdir:
    """Service 授权上下文与持久化 Workdir。"""

    conversation_id: int
    thread_id: str
    uid: str
    workdir: Workdir
    project_id: str
    directory_mode: str

    @property
    def workdir_path(self) -> str:
        return self.workdir.relative_path


def workdir_binding_from_project(*, conversation: Conversation, uid: str, project: Project | None) -> WorkdirBinding:
    """从已加载的 Project 构造线程 Workdir 快照，避免再次查询 Project。"""
    if project is None:
        raise RuntimeError("Conversation 绑定的 Project 不存在")
    conversation_project_id = str(conversation.project_id or "")
    project_id = str(project.id or "")
    if not conversation_project_id or not project_id or project_id != conversation_project_id:
        raise RuntimeError("Conversation 与 Project 绑定不一致")
    if str(project.uid or "") != str(uid):
        raise RuntimeError("Project 不属于当前用户")
    thread_id = str(conversation.thread_id or "")
    if not thread_id:
        raise RuntimeError("Conversation 缺少 thread_id")
    workdir_path = str(project.workdir_path or "")
    directory_mode = str(project.directory_mode or "")
    if not workdir_path or directory_mode not in {"managed", "linked"}:
        raise RuntimeError("Project Workdir 绑定无效")
    return WorkdirBinding(
        conversation_id=int(conversation.id),
        thread_id=thread_id,
        uid=str(uid),
        project_id=project_id,
        workdir_path=workdir_path,
        directory_mode=directory_mode,
    )


def _validate_workdir_binding(binding: WorkdirBinding, *, conversation: Conversation, uid: str) -> None:
    """校验传入快照仍属于当前用户和 Conversation。"""
    if (
        binding.uid != str(uid)
        or binding.conversation_id != int(conversation.id)
        or binding.thread_id != str(conversation.thread_id)
        or binding.project_id != str(conversation.project_id)
    ):
        raise RuntimeError("传入的 Workdir 绑定与 Conversation 不一致")


async def resolve_authorized_workdir(*, thread_id: str, uid: str, db) -> AuthorizedWorkdir:
    """按公共 Thread ID 授权并打开持久化 Workdir。"""
    conversation = await ConversationRepository(db).get_conversation_by_thread_id(thread_id)
    return await resolve_authorized_conversation_workdir(
        conversation=conversation,
        uid=uid,
        db=db,
    )


async def resolve_authorized_conversation_workdir(
    *, conversation: Conversation | None, uid: str, db
) -> AuthorizedWorkdir:
    """复用已查询的 Conversation，重新校验归属后打开 Workdir。"""
    if conversation is None or conversation.uid != str(uid) or conversation.status == "deleted":
        raise HTTPException(status_code=404, detail="对话线程不存在")
    binding = await resolve_conversation_workdir_binding(
        conversation=conversation,
        uid=str(uid),
        db=db,
    )
    return AuthorizedWorkdir(
        conversation_id=conversation.id,
        thread_id=conversation.thread_id,
        uid=str(uid),
        workdir=Workdir.open_existing(str(uid), binding.workdir_path),
        project_id=binding.project_id,
        directory_mode=binding.directory_mode,
    )


async def resolve_conversation_workdir_path(*, conversation: Conversation, uid: str, db) -> str:
    """解析 Conversation 的持久 Workdir 路径。"""
    binding = await resolve_conversation_workdir_binding(
        conversation=conversation,
        uid=uid,
        db=db,
    )
    return binding.workdir_path


async def ensure_conversation_workdir_available(
    *,
    conversation,
    uid: str,
    db,
    workdir_binding: WorkdirBinding | None = None,
) -> str:
    """确保 Conversation 的持久 Workdir 可用，并返回其相对路径。"""
    binding = workdir_binding
    if binding is None:
        binding = await resolve_conversation_workdir_binding(
            conversation=conversation,
            uid=uid,
            db=db,
        )
    else:
        _validate_workdir_binding(binding, conversation=conversation, uid=uid)
    if binding.materialize_managed:
        ensure_bound_user_workdir(binding.uid, binding.workdir_path)
    else:
        Workdir.open_existing(binding.uid, binding.workdir_path)
    return binding.workdir_path


async def resolve_conversation_workdir_binding(
    *, conversation: Conversation, uid: str, db, project: Project | None = None
) -> WorkdirBinding:
    """解析 Conversation 唯一 Project 所拥有的持久 Workdir。"""
    resolved_project = project
    if resolved_project is None:
        resolved_project = await ProjectRepository(db).get_for_user(conversation.project_id, str(uid))
    return workdir_binding_from_project(conversation=conversation, uid=uid, project=resolved_project)
