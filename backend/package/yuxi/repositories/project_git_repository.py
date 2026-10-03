"""Project Git 连接、仓库绑定和 worktree 的持久化 Owner。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    AgentRun,
    AgentRunRequest,
    Conversation,
    GitConnection,
    GitCredential,
    ProjectGitRepository,
    ProjectGitWorktree,
    ProjectGitOccupancy,
    ProjectWorkExecution,
    ProjectWorkTask,
)


class ProjectGitRepositoryStore:
    """在当前事务中读写 Project Git 业务事实。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def task_tree_has_git_history(self, *, task_id: str, project_id: str, uid: str) -> bool:
        """共享子任务已有执行或分支时，禁止改变整条历史 Git 作用域。"""
        tasks = (
            select(ProjectWorkTask.id)
            .where(ProjectWorkTask.id == task_id, ProjectWorkTask.project_id == project_id)
            .cte("git_scope_tasks", recursive=True)
        )
        tasks = tasks.union_all(
            select(ProjectWorkTask.id)
            .join(tasks, ProjectWorkTask.parent_id == tasks.c.id)
            .where(ProjectWorkTask.project_id == project_id, ProjectWorkTask.git_workspace_mode == "inherit")
        )
        executions = (
            select(ProjectWorkExecution.id)
            .where(
                ProjectWorkExecution.task_id.in_(select(tasks.c.id)),
                ProjectWorkExecution.project_id == project_id,
                ProjectWorkExecution.uid == uid,
            )
            .exists()
        )
        allocations = (
            select(ProjectGitWorktree.id)
            .where(
                ProjectGitWorktree.runtime_scope_id.in_(select("task:" + tasks.c.id)),
                ProjectGitWorktree.project_id == project_id,
                ProjectGitWorktree.uid == uid,
            )
            .exists()
        )
        return bool(await self.db.scalar(select(executions | allocations)))

    async def add_credential(self, credential: GitCredential) -> GitCredential:
        """新增加密凭据并 flush。"""
        self.db.add(credential)
        await self.db.flush()
        return credential

    async def get_credential(self, credential_id: str, uid: str) -> GitCredential | None:
        """按用户读取 active 凭据。"""
        return await self.db.scalar(
            select(GitCredential).where(
                GitCredential.id == credential_id,
                GitCredential.uid == str(uid),
                GitCredential.status == "active",
            )
        )

    async def add_connection(self, connection: GitConnection) -> GitConnection:
        """新增 Git connection 并 flush。"""
        self.db.add(connection)
        await self.db.flush()
        return connection

    async def get_connection(
        self, connection_id: str, uid: str, *, active_only: bool = False, lock: bool = False
    ) -> GitConnection | None:
        """按用户读取 connection。"""
        query = select(GitConnection).where(GitConnection.id == connection_id, GitConnection.uid == str(uid))
        if active_only:
            query = query.where(GitConnection.status == "active")
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def get_connection_by_idempotency_key(self, request_id: str, uid: str) -> GitConnection | None:
        """读取幂等创建的 connection。"""
        return await self.db.scalar(
            select(GitConnection).where(GitConnection.uid == str(uid), GitConnection.idempotency_key == request_id)
        )

    async def list_connections(self, uid: str) -> list[GitConnection]:
        """列出用户 connections。"""
        result = await self.db.execute(
            select(GitConnection).where(GitConnection.uid == str(uid)).order_by(GitConnection.created_at.desc())
        )
        return list(result.scalars())

    async def connection_has_live_bindings(self, connection_id: str, uid: str) -> bool:
        """判断 connection 是否仍被未停用仓库引用。"""
        count = await self.db.scalar(
            select(func.count())
            .select_from(ProjectGitRepository)
            .where(
                ProjectGitRepository.connection_id == connection_id,
                ProjectGitRepository.uid == str(uid),
                ProjectGitRepository.status != "disabled",
            )
        )
        return bool(count)

    async def add_binding(self, binding: ProjectGitRepository) -> ProjectGitRepository:
        """新增仓库绑定并 flush。"""
        self.db.add(binding)
        await self.db.flush()
        return binding

    async def get_binding(self, repository_id: str, uid: str, *, lock: bool = False) -> ProjectGitRepository | None:
        """按用户读取仓库绑定。"""
        query = select(ProjectGitRepository).where(
            ProjectGitRepository.id == repository_id, ProjectGitRepository.uid == str(uid)
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def get_binding_by_idempotency_key(self, request_id: str, uid: str) -> ProjectGitRepository | None:
        """读取幂等创建的仓库绑定。"""
        return await self.db.scalar(
            select(ProjectGitRepository).where(
                ProjectGitRepository.uid == str(uid), ProjectGitRepository.idempotency_key == request_id
            )
        )

    async def get_active_binding_by_alias(
        self, *, project_id: str, uid: str, alias: str, lock: bool = False
    ) -> ProjectGitRepository | None:
        """大小写不敏感读取当前 Project 的 active 仓库。"""
        query = select(ProjectGitRepository).where(
            ProjectGitRepository.project_id == project_id,
            ProjectGitRepository.uid == str(uid),
            func.lower(ProjectGitRepository.alias) == alias.lower(),
            ProjectGitRepository.status == "active",
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_project_bindings(self, project_id: str, uid: str) -> list[ProjectGitRepository]:
        """列出 Project 的全部仓库绑定。"""
        result = await self.db.execute(
            select(ProjectGitRepository)
            .where(ProjectGitRepository.project_id == project_id, ProjectGitRepository.uid == str(uid))
            .order_by(ProjectGitRepository.id)
        )
        return list(result.scalars())

    async def project_has_non_disabled_binding(self, project_id: str, uid: str) -> bool:
        """判断 Project 是否配置了仍可发现的 Git binding。"""
        count = await self.db.scalar(
            select(func.count())
            .select_from(ProjectGitRepository)
            .where(
                ProjectGitRepository.project_id == project_id,
                ProjectGitRepository.uid == str(uid),
                ProjectGitRepository.status != "disabled",
            )
        )
        return bool(count)

    async def list_pending_bindings(self) -> list[ProjectGitRepository]:
        """列出需要 reconciler 重投的仓库操作。"""
        result = await self.db.execute(
            select(ProjectGitRepository).where(
                ProjectGitRepository.status.in_(("provisioning", "provision_failed", "deleting", "delete_failed"))
            )
        )
        return list(result.scalars())

    async def get_worktree(
        self, repository_id: str, runtime_scope_id: str, uid: str, *, lock: bool = False
    ) -> ProjectGitWorktree | None:
        """读取一个 repository + root scope worktree。"""
        query = select(ProjectGitWorktree).where(
            ProjectGitWorktree.repository_id == repository_id,
            ProjectGitWorktree.runtime_scope_id == runtime_scope_id,
            ProjectGitWorktree.uid == str(uid),
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def add_worktree(self, worktree: ProjectGitWorktree) -> ProjectGitWorktree:
        """新增 worktree 并 flush。"""
        self.db.add(worktree)
        await self.db.flush()
        return worktree

    async def get_worktree_by_selection_request(
        self, request_id: str, uid: str, *, lock: bool = False
    ) -> ProjectGitWorktree | None:
        """读取当前 allocation generation 的用户幂等请求。"""
        query = select(ProjectGitWorktree).where(
            ProjectGitWorktree.uid == str(uid),
            ProjectGitWorktree.selection_request_id == request_id,
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_scope_worktrees(self, runtime_scope_id: str, uid: str) -> list[ProjectGitWorktree]:
        """列出根任务显式持久化的全部仓库 allocation。"""
        result = await self.db.execute(
            select(ProjectGitWorktree)
            .where(
                ProjectGitWorktree.runtime_scope_id == runtime_scope_id,
                ProjectGitWorktree.uid == str(uid),
                ProjectGitWorktree.status != "removed",
            )
            .order_by(ProjectGitWorktree.created_at)
        )
        return list(result.scalars())

    async def get_project_worktree(self, worktree_id: str, project_id: str, uid: str, *, lock: bool = False):
        """按 Project 和用户读取 worktree。"""
        query = select(ProjectGitWorktree).where(
            ProjectGitWorktree.id == worktree_id,
            ProjectGitWorktree.project_id == project_id,
            ProjectGitWorktree.uid == str(uid),
        )
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list_project_worktrees(self, project_id: str, uid: str) -> list[ProjectGitWorktree]:
        """列出 Project 的全部任务 worktree。"""
        result = await self.db.execute(
            select(ProjectGitWorktree)
            .where(ProjectGitWorktree.project_id == project_id, ProjectGitWorktree.uid == str(uid))
            .order_by(ProjectGitWorktree.created_at.desc())
        )
        return list(result.scalars())

    async def list_pending_worktrees(self) -> list[ProjectGitWorktree]:
        """列出需要 reconciler 重投的 worktree 清理意图。"""
        result = await self.db.execute(
            select(ProjectGitWorktree).where(ProjectGitWorktree.status.in_(("cleanup_pending", "cleanup_failed")))
        )
        return list(result.scalars())

    async def has_nonterminal_run(self, project_id: str, runtime_scope_id: str, uid: str) -> bool:
        """判断 scope 是否仍有未终态 Run。"""
        slots = await self.project_occupancies(project_id, uid)
        for slot in slots:
            if slot.scope_key == runtime_scope_id and await self.active_root_run(slot.active_run_id, uid):
                return True
        count = await self.db.scalar(
            select(func.count())
            .select_from(AgentRun)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(
                Conversation.project_id == project_id,
                AgentRun.runtime_scope_id == runtime_scope_id,
                AgentRun.uid == str(uid),
                AgentRun.status.notin_(("completed", "failed", "cancelled", "interrupted")),
            )
        )
        return bool(count)

    async def acquire_user_runtime_lock(self, uid: str) -> None:
        """串行化目录保护清单初始化与真实 PostgreSQL Run 派发。"""
        if self.db.get_bind().dialect.name == "sqlite":
            return
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"project-git-user:{uid}"},
        )

    async def user_has_nonterminal_runs(self, uid: str) -> bool:
        """资源目录初始化不能使正在执行的旧挂载绕过保护。"""
        return bool(
            await self.db.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.uid == uid, AgentRun.status.not_in(["completed", "failed", "cancelled"]))
            )
        )

    async def acquire_maintenance_lock(self, repository_id: str) -> None:
        """在当前事务中串行化共享 bare repo 的短修改。"""
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"project-git-repository:{repository_id}"},
        )

    async def acquire_worktree_lease(
        self, worktree: ProjectGitWorktree, *, owner: str, expires_at: datetime, now: datetime
    ) -> bool:
        """在锁行后取得可过期 worktree lease。"""
        if (
            worktree.lease_owner
            and worktree.lease_owner != owner
            and worktree.lease_expires_at
            and worktree.lease_expires_at > now
        ):
            return False
        worktree.lease_owner = owner
        worktree.lease_expires_at = expires_at
        worktree.status = "preparing"
        await self.db.flush()
        return True

    async def task_for_thread(self, thread_id: str, project_id: str, uid: str):
        """从真实执行关系读取会话所属项目任务。"""
        return await self.db.scalar(
            select(ProjectWorkTask)
            .join(ProjectWorkExecution, ProjectWorkExecution.task_id == ProjectWorkTask.id)
            .where(
                ProjectWorkExecution.thread_id == thread_id,
                ProjectWorkExecution.uid == uid,
                ProjectWorkTask.project_id == project_id,
            )
        )

    async def task_for_project(self, task_id: str, project_id: str):
        """按同一项目读取父任务，拒绝跨项目继承。"""
        return await self.db.scalar(
            select(ProjectWorkTask).where(ProjectWorkTask.id == task_id, ProjectWorkTask.project_id == project_id)
        )

    async def queued_project_threads(self, project_id: str, uid: str) -> list[str]:
        """读取项目尚未派发请求的线程，用于判断共享任务等待者。"""
        values = await self.db.scalars(
            select(AgentRunRequest.conversation_thread_id)
            .join(Conversation, Conversation.thread_id == AgentRunRequest.conversation_thread_id)
            .where(
                AgentRunRequest.uid == uid,
                AgentRunRequest.status == "queued",
                Conversation.uid == uid,
                Conversation.project_id == project_id,
            )
            .distinct()
        )
        return list(values)

    async def occupancy(self, repository_id: str, scope_key: str, uid: str):
        """在资源锁下读取任务的持久占用。"""
        return await self.db.scalar(
            select(ProjectGitOccupancy)
            .where(
                ProjectGitOccupancy.repository_id == repository_id,
                ProjectGitOccupancy.scope_key == scope_key,
                ProjectGitOccupancy.uid == uid,
            )
            .with_for_update()
        )

    async def checkout_occupancies(self, repository_id: str, uid: str):
        """只对共享 checkout 的等待者执行 FIFO，隔离工作区不占用该目录。"""
        values = await self.db.scalars(
            select(ProjectGitOccupancy)
            .join(
                ProjectGitWorktree,
                (ProjectGitWorktree.repository_id == ProjectGitOccupancy.repository_id)
                & (ProjectGitWorktree.runtime_scope_id == ProjectGitOccupancy.scope_key)
                & (ProjectGitWorktree.uid == ProjectGitOccupancy.uid),
            )
            .where(
                ProjectGitOccupancy.repository_id == repository_id,
                ProjectGitOccupancy.uid == uid,
                ProjectGitOccupancy.status != "released",
                ProjectGitWorktree.usage_mode == "in_place",
            )
            .order_by(ProjectGitOccupancy.requested_at, ProjectGitOccupancy.id)
        )
        return list(values)

    async def occupancies(self, repository_id: str, uid: str):
        """按 FIFO 顺序列出尚未释放的任务占用。"""
        result = await self.db.scalars(
            select(ProjectGitOccupancy)
            .where(
                ProjectGitOccupancy.repository_id == repository_id,
                ProjectGitOccupancy.uid == uid,
                ProjectGitOccupancy.status != "released",
            )
            .order_by(ProjectGitOccupancy.requested_at, ProjectGitOccupancy.id)
        )
        return list(result)

    async def active_root_run(self, run_id: str | None, uid: str):
        """检查根运行及其执行树，崩溃后仍活跃的子智能体继续阻止写入。"""
        if not run_id:
            return None
        tree = select(AgentRun.id).where(AgentRun.id == run_id, AgentRun.uid == uid).cte("git_run_tree", recursive=True)
        tree = tree.union_all(
            select(AgentRun.id).join(tree, AgentRun.created_by_run_id == tree.c.id).where(AgentRun.uid == uid)
        )
        return await self.db.scalar(
            select(AgentRun)
            .where(
                AgentRun.id.in_(select(tree.c.id)),
                AgentRun.uid == uid,
                AgentRun.status.notin_(("completed", "failed", "cancelled", "interrupted")),
            )
            .limit(1)
        )

    async def run_for_user(self, run_id: str, uid: str):
        """按用户读取父运行，供 Git scope 独立于沙盒 scope 解析。"""
        return await self.db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.uid == uid))

    async def project_occupancies(self, project_id: str, uid: str):
        """回读项目内占用与等待队列。"""
        result = await self.db.scalars(
            select(ProjectGitOccupancy)
            .where(
                ProjectGitOccupancy.project_id == project_id,
                ProjectGitOccupancy.uid == uid,
                ProjectGitOccupancy.status != "released",
            )
            .order_by(ProjectGitOccupancy.requested_at, ProjectGitOccupancy.id)
        )
        return list(result)
