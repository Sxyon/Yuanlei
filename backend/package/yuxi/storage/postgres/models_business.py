"""PostgreSQL 业务数据模型 - 用户、部门、对话等相关表"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from yuxi.storage.minio.client import normalize_public_minio_url
from yuxi.utils.datetime_utils import duration_ms, format_utc_datetime, utc_now_naive

Base = declarative_base()

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")

MAX_LOGIN_FAILED_ATTEMPTS = 5
LOGIN_LOCK_DURATION_SECONDS = 300
AGENT_RUN_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")
MODEL_AUDIT_MESSAGE_TYPE = "model_audit"
TOOL_AUDIT_MESSAGE_TYPE = "tool_audit"
AUDIT_MESSAGE_TYPES = (MODEL_AUDIT_MESSAGE_TYPE, TOOL_AUDIT_MESSAGE_TYPE)
AGENT_RUN_SHAPE_CONSTRAINT_NAME = "ck_agent_runs_nonterminal_shape"
AGENT_RUN_SHAPE_CONSTRAINT_SQL = """
status IN ('completed', 'failed', 'cancelled', 'interrupted')
OR (
    runtime_scope_id <> ''
 AND conversation_thread_id <> ''
 AND ((run_type = 'chat'
     AND runtime_scope_id = conversation_thread_id
     AND created_by_run_id IS NULL
     AND subagent_thread_relation_id IS NULL)
 OR (run_type = 'resume'
     AND runtime_scope_id = conversation_thread_id
     AND created_by_run_id IS NOT NULL
     AND subagent_thread_relation_id IS NULL)
 OR (run_type = 'subagent'
     AND created_by_run_id IS NOT NULL
     AND subagent_thread_relation_id IS NOT NULL))
)
"""
PROJECT_STATUS_CONSTRAINT_NAME = "ck_projects_status"
PROJECT_STATUS_CONSTRAINT_SQL = "status IN ('active', 'deleted')"


# 新建线程的初始已查看标记，用于区分"尚无任何 Run"与"上线前的历史会话"，
# 避免 startup 回填把后续新产生的未读状态误清为已读。不会与真实 Run id 冲突。
UNVIEWED_RUN_MARKER = "__unviewed__"


def build_agent_run_timing(
    *,
    created_at: datetime | None,
    started_at: datetime | None,
    prepared_at: datetime | None,
    first_output_at: datetime | None,
    finished_at: datetime | None,
    first_model_request_at: datetime | None = None,
) -> dict[str, Any]:
    """从 AgentRun 权威时间点生成统一的阶段时延投影。"""
    return {
        "created_at": format_utc_datetime(created_at),
        "started_at": format_utc_datetime(started_at),
        "prepared_at": format_utc_datetime(prepared_at),
        "first_model_request_at": format_utc_datetime(first_model_request_at),
        "first_output_at": format_utc_datetime(first_output_at),
        "finished_at": format_utc_datetime(finished_at),
        "dispatch_latency_ms": duration_ms(created_at, started_at),
        "preparation_latency_ms": duration_ms(started_at, prepared_at),
        "first_model_request_latency_ms": duration_ms(created_at, first_model_request_at),
        "model_first_output_latency_ms": duration_ms(prepared_at, first_output_at),
        "first_output_latency_ms": duration_ms(created_at, first_output_at),
        "total_latency_ms": duration_ms(created_at, finished_at),
    }


class Project(Base):
    """用户项目及其 Workdir 绑定。"""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("id", "uid", name="uq_projects_id_uid"),
        UniqueConstraint("uid", "idempotency_key", name="uq_projects_uid_idempotency_key"),
        CheckConstraint("selection_status IN ('implicit', 'selectable')", name="ck_projects_selection_status"),
        CheckConstraint("directory_mode IN ('managed', 'linked')", name="ck_projects_directory_mode"),
        CheckConstraint(PROJECT_STATUS_CONSTRAINT_SQL, name=PROJECT_STATUS_CONSTRAINT_NAME),
    )

    id = Column(String(64), primary_key=True, comment="Project UUID")
    uid = Column(
        String(64),
        ForeignKey("users.uid", ondelete="CASCADE", name="fk_projects_uid_users"),
        nullable=False,
        index=True,
        comment="UID",
    )
    name = Column(String(255), nullable=True, comment="项目名称；implicit Project 可为空")
    selection_status = Column(String(20), nullable=False, index=True, comment="implicit/selectable")
    workdir_path = Column(String(512), nullable=False, comment="UserWorkspace-relative Workdir path")
    directory_mode = Column(String(20), nullable=False, comment="managed/linked")
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")
    idempotency_key = Column(String(128), nullable=True, comment="幂等创建键")
    created_at = Column(DateTime, default=utc_now_naive, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, server_default=func.now(), nullable=False
    )

    conversations = relationship("Conversation", back_populates="project")

    def to_dict(self) -> dict[str, Any]:
        """序列化项目公开字段。"""
        return {
            "id": self.id,
            "uid": self.uid,
            "name": self.name,
            "selection_status": self.selection_status,
            "workdir_path": self.workdir_path,
            "directory_mode": self.directory_mode,
            "status": self.status,
            "deleted_at": format_utc_datetime(self.deleted_at),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ProjectSettings(Base):
    """元垒项目管理属性，不改变项目权限与软删除状态。"""

    __tablename__ = "project_settings"
    __table_args__ = (
        CheckConstraint(
            "work_status IN ('planned', 'in_progress', 'paused', 'completed', 'cancelled')",
            name="ck_project_settings_status",
        ),
        CheckConstraint("priority IN ('urgent', 'high', 'medium', 'low', 'none')", name="ck_project_settings_priority"),
        CheckConstraint("owner_type IN ('none', 'member', 'agent')", name="ck_project_settings_owner_type"),
        CheckConstraint(
            "(owner_type = 'none' AND owner_id IS NULL) OR (owner_type <> 'none' AND owner_id IS NOT NULL)",
            name="ck_project_settings_owner_identity",
        ),
        CheckConstraint(
            "start_date IS NULL OR due_date IS NULL OR start_date <= due_date", name="ck_project_settings_dates"
        ),
    )

    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    work_status = Column(String(20), nullable=False, default="planned", server_default="planned")
    priority = Column(String(16), nullable=False, default="none", server_default="none")
    owner_type = Column(String(16), nullable=False, default="member")
    owner_id = Column(String(80), nullable=True)
    description = Column(String(255), nullable=False, default="", server_default="")
    start_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)

    def to_dict(self) -> dict:
        """序列化管理属性，日期保持无时区日历语义。"""
        return {
            "work_status": self.work_status,
            "priority": self.priority,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
        }


class ProjectKnowledgeLink(Base):
    """项目指向知识库的弱关联，不授予读取权限。"""

    __tablename__ = "project_knowledge_links"
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    kb_id = Column(String(80), primary_key=True)


class GitCredential(Base):
    """保存由可信 Git 服务加密的凭据。"""

    __tablename__ = "git_credentials"
    __table_args__ = (
        UniqueConstraint("id", "uid", name="uq_git_credentials_id_uid"),
        CheckConstraint(
            "purpose IN ('gitea_api_token', 'deploy_private_key')",
            name="ck_git_credentials_purpose",
        ),
        CheckConstraint("status IN ('active', 'destroyed')", name="ck_git_credentials_status"),
    )

    id = Column(String(64), primary_key=True)
    uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(32), nullable=False)
    ciphertext = Column(LargeBinary, nullable=False)
    nonce = Column(LargeBinary, nullable=False)
    key_version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    created_at = Column(DateTime, default=utc_now_naive, server_default=func.now(), nullable=False)
    destroyed_at = Column(DateTime, nullable=True)


class GitConnection(Base):
    """用户级 Git 托管连接及其非敏感信任锚。"""

    __tablename__ = "git_connections"
    __table_args__ = (
        UniqueConstraint("id", "uid", name="uq_git_connections_id_uid"),
        UniqueConstraint("uid", "idempotency_key", name="uq_git_connections_uid_idempotency_key"),
        ForeignKeyConstraint(
            ["api_token_credential_id", "uid"],
            ["git_credentials.id", "git_credentials.uid"],
            name="fk_git_connections_credential_uid",
        ),
        CheckConstraint("provider IN ('gitea')", name="ck_git_connections_provider"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_git_connections_status"),
    )

    id = Column(String(64), primary_key=True)
    uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    provider = Column(String(20), nullable=False)
    api_origin = Column(String(512), nullable=False)
    ssh_host = Column(String(255), nullable=False)
    ssh_port = Column(Integer, nullable=False)
    ssh_known_host_key = Column(Text, nullable=False)
    api_token_credential_id = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active", index=True)
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        """序列化连接公开字段，不暴露凭据或完整 known-host 内容。"""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "api_origin": self.api_origin,
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "credential_status": "stored" if self.status == "active" else "destroyed",
            "status": self.status,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ProjectGitRepository(Base):
    """Project 绑定的远端 Git 仓库及持久化操作状态。"""

    __tablename__ = "project_git_repositories"
    __table_args__ = (
        UniqueConstraint("id", "uid", name="uq_project_git_repositories_id_uid"),
        UniqueConstraint("id", "project_id", "uid", name="uq_project_git_repositories_identity"),
        UniqueConstraint("uid", "idempotency_key", name="uq_project_git_repositories_uid_idempotency_key"),
        ForeignKeyConstraint(
            ["project_id", "uid"], ["projects.id", "projects.uid"], name="fk_project_git_repositories_project_uid"
        ),
        ForeignKeyConstraint(
            ["connection_id", "uid"],
            ["git_connections.id", "git_connections.uid"],
            name="fk_project_git_repositories_connection_uid",
        ),
        ForeignKeyConstraint(
            ["deploy_private_credential_id", "uid"],
            ["git_credentials.id", "git_credentials.uid"],
            name="fk_project_git_repositories_credential_uid",
        ),
        CheckConstraint("usage_mode IN ('in_place', 'worktree')", name="ck_project_git_repositories_usage_mode"),
        CheckConstraint(
            "approval_mode IN ('automatic', 'protected')", name="ck_project_git_repositories_approval_mode"
        ),
        CheckConstraint(
            "status IN ('provisioning', 'active', 'provision_failed', 'deleting', 'delete_failed', 'disabled')",
            name="ck_project_git_repositories_status",
        ),
    )

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=False, index=True)
    uid = Column(String(64), nullable=False, index=True)
    connection_id = Column(String(64), nullable=False, index=True)
    alias = Column(String(80), nullable=False)
    directory_name = Column(String(128), nullable=False)
    remote_repository_id = Column(String(128), nullable=True)
    repository_owner = Column(String(255), nullable=False)
    repository_name = Column(String(255), nullable=False)
    purpose = Column(Text, nullable=False, default="项目仓库", server_default="项目仓库")
    usage_mode = Column(String(16), nullable=False, default="worktree", server_default="worktree")
    approval_mode = Column(String(16), nullable=False, default="protected", server_default="protected")
    checkout_path = Column(String(512), nullable=True)
    checkout_head_sha = Column(String(64), nullable=True)
    canonical_ssh_url = Column(String(1024), nullable=True)
    default_branch = Column(String(255), nullable=True)
    configured_base_branch = Column(String(255), nullable=True)
    allowed_base_branches = Column(JSON_VALUE, nullable=False, default=list)
    deploy_public_key = Column(Text, nullable=False)
    deploy_public_key_fingerprint = Column(String(128), nullable=False)
    deploy_private_credential_id = Column(String(64), nullable=False)
    remote_deploy_key_id = Column(String(128), nullable=True)
    status = Column(String(24), nullable=False, default="provisioning", server_default="provisioning", index=True)
    last_error_code = Column(String(80), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    operation_generation = Column(Integer, nullable=False, default=1, server_default="1")
    idempotency_key = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        """序列化仓库绑定的非敏感业务状态。"""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "connection_id": self.connection_id,
            "alias": self.alias,
            "directory_name": self.directory_name,
            "usage_mode": self.usage_mode,
            "approval_mode": self.approval_mode,
            "checkout_path": self.checkout_path,
            "checkout_head_sha": self.checkout_head_sha,
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "purpose": self.purpose,
            "default_branch": self.default_branch,
            "configured_base_branch": self.configured_base_branch,
            "allowed_base_branches": self.allowed_base_branches or [],
            "status": self.status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ProjectGitAction(Base):
    """项目 Git 申请、批准依据和执行结果的不可变身份快照。"""

    __tablename__ = "project_git_actions"
    __table_args__ = (
        UniqueConstraint("uid", "request_id", name="uq_project_git_actions_request"),
        ForeignKeyConstraint(
            ["repository_id", "project_id", "uid"],
            ["project_git_repositories.id", "project_git_repositories.project_id", "project_git_repositories.uid"],
            name="fk_project_git_actions_resource",
        ),
        CheckConstraint("action IN ('commit', 'push', 'merge')", name="ck_project_git_actions_action"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'running', 'succeeded', 'failed', 'rejected')",
            name="ck_project_git_actions_status",
        ),
        CheckConstraint("approval_kind IN ('human', 'automatic', 'required')", name="ck_project_git_actions_approval"),
        Index("ix_project_git_actions_history", "project_id", "uid", "created_at", "id"),
    )
    id = Column(String(64), primary_key=True)
    uid = Column(String(64), nullable=False)
    project_id = Column(String(64), nullable=False)
    repository_id = Column(String(64), nullable=False)
    request_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    run_id = Column(String(64), nullable=True)
    agent_slug = Column(String(64), nullable=True)
    scope_key = Column(String(191), nullable=True)
    worktree_id = Column(String(64), nullable=True)
    action = Column(String(16), nullable=False)
    branch = Column(String(255), nullable=False)
    target_branch = Column(String(255), nullable=True)
    expected_head = Column(String(64), nullable=False)
    expected_tree = Column(String(64), nullable=True)
    expected_base = Column(String(64), nullable=True)
    pull_number = Column(Integer, nullable=True)
    message = Column(Text, nullable=False, default="")
    diff = Column(Text, nullable=False, default="")
    approval_kind = Column(String(16), nullable=False)
    approval_reason = Column(Text, nullable=False)
    approved_by = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False)
    task_id = Column(String(64), nullable=True)
    result = Column(JSON_VALUE, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    approved_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self):
        """输出批准与执行时间线，不输出内部幂等指纹。"""
        result = {
            column.name: getattr(self, column.name) for column in self.__table__.columns if column.name != "fingerprint"
        }
        for key in ("created_at", "approved_at", "started_at", "finished_at"):
            result[key] = format_utc_datetime(result[key]) if result[key] else None
        return result


class ProjectGitOccupancy(Base):
    """任务资源的持续占用、FIFO 顺序和当前根运行。"""

    __tablename__ = "project_git_occupancies"
    __table_args__ = (
        UniqueConstraint("repository_id", "scope_key", name="uq_project_git_occupancies_resource_scope"),
        ForeignKeyConstraint(
            ["repository_id", "project_id", "uid"],
            ["project_git_repositories.id", "project_git_repositories.project_id", "project_git_repositories.uid"],
            name="fk_project_git_occupancies_resource",
        ),
        CheckConstraint("status IN ('queued', 'owned', 'released')", name="ck_project_git_occupancies_status"),
        Index("ix_project_git_occupancies_fifo", "repository_id", "status", "requested_at", "id"),
    )

    id = Column(String(64), primary_key=True)
    repository_id = Column(String(64), nullable=False)
    project_id = Column(String(64), nullable=False)
    uid = Column(String(64), nullable=False)
    scope_key = Column(String(191), nullable=False)
    status = Column(String(16), nullable=False, default="queued", server_default="queued")
    active_run_id = Column(String(64), nullable=True)
    requested_at = Column(DateTime, nullable=False, default=utc_now_naive, server_default=func.now())
    released_at = Column(DateTime, nullable=True)


class ProjectGitWorktree(Base):
    """根任务在一个仓库中的分支和 worktree 状态。"""

    __tablename__ = "project_git_worktrees"
    __table_args__ = (
        UniqueConstraint("repository_id", "runtime_scope_id", name="uq_project_git_worktrees_repository_scope"),
        UniqueConstraint("uid", "selection_request_id", name="uq_project_git_worktrees_uid_selection_request"),
        ForeignKeyConstraint(
            ["repository_id", "project_id", "uid"],
            ["project_git_repositories.id", "project_git_repositories.project_id", "project_git_repositories.uid"],
            name="fk_project_git_worktrees_repository_identity",
        ),
        CheckConstraint("usage_mode IN ('in_place', 'worktree')", name="ck_project_git_worktrees_usage_mode"),
        CheckConstraint(
            "status IN ('requested', 'preparing', 'ready', 'prepare_failed', "
            "'cleanup_pending', 'cleanup_failed', 'removed')",
            name="ck_project_git_worktrees_status",
        ),
        CheckConstraint(
            "selection_source IN ('user', 'agent', 'legacy')",
            name="ck_project_git_worktrees_selection_source",
        ),
        CheckConstraint(
            "branch_kind IN ('feature', 'fix', 'docs', 'refactor', 'chore', 'test', 'legacy')",
            name="ck_project_git_worktrees_branch_kind",
        ),
        CheckConstraint(
            "(branch_kind = 'legacy' AND branch_slug IS NULL) OR (branch_kind <> 'legacy' AND branch_slug IS NOT NULL)",
            name="ck_project_git_worktrees_branch_slug",
        ),
    )

    id = Column(String(64), primary_key=True)
    repository_id = Column(String(64), nullable=False, index=True)
    project_id = Column(String(64), nullable=False, index=True)
    uid = Column(String(64), nullable=False, index=True)
    runtime_scope_id = Column(String(191), nullable=False, index=True)
    task_key = Column(String(64), nullable=False)
    selection_source = Column(String(16), nullable=False)
    task_purpose = Column(Text, nullable=False)
    branch_kind = Column(String(16), nullable=False)
    branch_slug = Column(String(48), nullable=True)
    requested_by_run_id = Column(String(64), nullable=True, index=True)
    allocation_generation = Column(Integer, nullable=False, default=1, server_default="1")
    selection_request_id = Column(String(128), nullable=True)
    branch_name = Column(String(255), nullable=False)
    base_branch = Column(String(255), nullable=False)
    base_sha = Column(String(64), nullable=True)
    usage_mode = Column(String(16), nullable=False, default="worktree", server_default="worktree")
    source_parent_worktree_id = Column(
        String(64), ForeignKey("project_git_worktrees.id", name="fk_project_git_worktrees_source_parent"), nullable=True
    )
    last_observed_head_sha = Column(String(64), nullable=True)
    last_pushed_sha = Column(String(64), nullable=True)
    relative_path = Column(String(512), nullable=False)
    status = Column(String(24), nullable=False, default="preparing", server_default="preparing", index=True)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    last_error_code = Column(String(80), nullable=True)
    last_error_message = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        """序列化 worktree 可观察状态。"""
        return {
            "id": self.id,
            "repository_id": self.repository_id,
            "project_id": self.project_id,
            "runtime_scope_id": self.runtime_scope_id,
            "task_key": self.task_key,
            "selection_source": self.selection_source,
            "task_purpose": self.task_purpose,
            "branch_kind": self.branch_kind,
            "branch_slug": self.branch_slug,
            "requested_by_run_id": self.requested_by_run_id,
            "allocation_generation": self.allocation_generation,
            "branch": self.branch_name,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "usage_mode": self.usage_mode,
            "source_parent_worktree_id": self.source_parent_worktree_id,
            "head_sha": self.last_observed_head_sha,
            "last_pushed_sha": self.last_pushed_sha,
            "relative_path": self.relative_path,
            "status": self.status,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


Index(
    "uq_git_connections_uid_lower_name",
    GitConnection.uid,
    func.lower(GitConnection.name),
    unique=True,
)
Index(
    "uq_project_git_repositories_project_lower_alias",
    ProjectGitRepository.project_id,
    func.lower(ProjectGitRepository.alias),
    unique=True,
)


class Department(Base):
    """部门模型"""

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)

    # 关联关系
    users = relationship("User", back_populates="department", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": format_utc_datetime(self.created_at),
        }


class User(Base):
    """用户模型"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True, index=True)  # 显示名称
    uid = Column(String, nullable=False, unique=True, index=True)  # 登录标识
    phone_number = Column(String, nullable=True, unique=True, index=True)  # 手机号
    avatar = Column(String, nullable=True)  # 头像URL
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # 角色: superadmin, admin, user
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)  # 部门ID
    created_at = Column(DateTime, default=utc_now_naive)
    last_login = Column(DateTime, nullable=True)

    # 登录失败限制相关字段
    login_failed_count = Column(Integer, nullable=False, default=0)  # 登录失败次数
    last_failed_login = Column(DateTime, nullable=True)  # 最后一次登录失败时间
    login_locked_until = Column(DateTime, nullable=True)  # 锁定到什么时候

    # 软删除相关字段
    is_deleted = Column(Integer, nullable=False, default=0, index=True)  # 是否已删除：0=否，1=是
    deleted_at = Column(DateTime, nullable=True)  # 删除时间

    # 关联操作日志
    operation_logs = relationship("OperationLog", back_populates="user", cascade="all, delete-orphan")

    # 关联部门
    department = relationship("Department", back_populates="users")

    # 关联 API Keys
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")

    agent_env = relationship("AgentEnv", back_populates="user", cascade="all, delete-orphan", uselist=False)
    user_config = relationship("UserConfig", back_populates="user", cascade="all, delete-orphan", uselist=False)

    def to_dict(self, include_password: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "username": self.username,
            "uid": self.uid,
            "phone_number": self.phone_number,
            "avatar": normalize_public_minio_url(self.avatar),
            "role": self.role,
            "department_id": self.department_id,
            "created_at": format_utc_datetime(self.created_at),
            "last_login": format_utc_datetime(self.last_login),
            "login_failed_count": self.login_failed_count,
            "last_failed_login": format_utc_datetime(self.last_failed_login),
            "login_locked_until": format_utc_datetime(self.login_locked_until),
            "is_deleted": self.is_deleted,
            "deleted_at": format_utc_datetime(self.deleted_at),
        }
        if include_password:
            result["password_hash"] = self.password_hash
        return result

    def is_login_locked(self) -> bool:
        """检查用户是否处于登录锁定状态"""
        if self.login_locked_until is None:
            return False
        return utc_now_naive() < self.login_locked_until

    def get_remaining_lock_time(self) -> int:
        """获取剩余锁定时间（秒）"""
        if self.login_locked_until is None:
            return 0
        remaining = int((self.login_locked_until - utc_now_naive()).total_seconds())
        return max(0, remaining)

    def increment_failed_login(self):
        """增加登录失败计数，并在达到阈值后锁定登录"""
        self.login_failed_count += 1
        self.last_failed_login = utc_now_naive()
        if self.login_failed_count >= MAX_LOGIN_FAILED_ATTEMPTS:
            self.login_locked_until = self.last_failed_login + timedelta(seconds=LOGIN_LOCK_DURATION_SECONDS)

    def reset_failed_login(self):
        """重置登录失败相关字段"""
        self.login_failed_count = 0
        self.last_failed_login = None
        self.login_locked_until = None


class AgentEnv(Base):
    """用户级 Agent 沙盒环境变量"""

    __tablename__ = "agent_envs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String, ForeignKey("users.uid"), nullable=False, unique=True, index=True)
    env = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    user = relationship("User", back_populates="agent_env")

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "env": self.env or {},
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class UserConfig(Base):
    """用户级配置"""

    __tablename__ = "user_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String, ForeignKey("users.uid"), nullable=False, unique=True, index=True)
    enable_memory = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    user = relationship("User", back_populates="user_config")

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "enable_memory": bool(self.enable_memory),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class Agent(Base):
    """用户可管理、可授权、可切换的智能体。"""

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(80), nullable=False, unique=True, index=True)
    backend_id = Column(String(64), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(255), nullable=True)

    pics = Column(JSON, nullable=False, default=list)
    config_json = Column(JSON, nullable=False, default=dict)
    share_config = Column(JSON_VALUE, nullable=False)

    is_default = Column(Boolean, nullable=False, default=False, index=True)
    is_subagent = Column(Boolean, nullable=False, default=False, index=True)

    created_by = Column(String(64), nullable=True, index=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    __table_args__ = (
        Index(
            "uq_agents_default",
            "is_default",
            unique=True,
            postgresql_where=is_default.is_(True),
            sqlite_where=is_default.is_(True),
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "agent_id": self.slug,
            "backend_id": self.backend_id,
            "name": self.name,
            "description": self.description,
            "icon": normalize_public_minio_url(self.icon),
            "pics": [normalize_public_minio_url(pic) for pic in (self.pics or [])],
            "config_json": self.config_json or {},
            "share_config": self.share_config or {},
            "is_default": bool(self.is_default),
            "is_subagent": bool(self.is_subagent),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ProjectAgent(Base):
    """项目数字员工：Agent 在某个 Project 内的归属与配置覆盖层（yuanlei 域）。"""

    __tablename__ = "project_agents"
    __table_args__ = (UniqueConstraint("project_id", "agent_slug", name="uq_project_agents_project_agent"),)

    id = Column(String(64), primary_key=True, comment="ProjectAgent UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_agents_project_id"),
        nullable=False,
        index=True,
        comment="所属 Project ID",
    )
    agent_slug = Column(
        String(80),
        ForeignKey("agents.slug", ondelete="CASCADE", name="fk_project_agents_agent_slug"),
        nullable=False,
        index=True,
        comment="Agent slug",
    )
    config_overrides = Column(JSON_VALUE, nullable=False, default=dict, comment="项目级配置覆盖层")
    auto_accept_work = Column(Boolean, nullable=False, default=False, server_default="false")
    work_default_model_spec = Column(String(512), nullable=True)
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    updated_by = Column(String(64), nullable=True, comment="最近更新者 uid")
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "agent_slug": self.agent_slug,
            "config_overrides": self.config_overrides or {},
            "auto_accept_work": self.auto_accept_work,
            "work_default_model_spec": self.work_default_model_spec,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class AgentSandbox(Base):
    """Agent 专属沙盒：绑定 (uid, agent, project) 的 runtime 所有权与生命周期（yuanlei 域）。"""

    __tablename__ = "agent_sandboxes"
    __table_args__ = (
        UniqueConstraint("uid", "agent_slug", "project_id", name="uq_agent_sandboxes_owner"),
        UniqueConstraint("scope_key", name="uq_agent_sandboxes_scope_key"),
        UniqueConstraint("sandbox_id", name="uq_agent_sandboxes_sandbox_id"),
        Index("ix_agent_sandboxes_status", "status"),
    )

    id = Column(String(64), primary_key=True, comment="记录 UUID")
    uid = Column(
        String(64),
        ForeignKey("users.uid", ondelete="CASCADE", name="fk_agent_sandboxes_uid_users"),
        nullable=False,
        comment="所有者 uid",
    )
    agent_slug = Column(
        String(80),
        ForeignKey("agents.slug", ondelete="CASCADE", name="fk_agent_sandboxes_agent_slug"),
        nullable=False,
        comment="专属 Agent slug",
    )
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_agent_sandboxes_project_id"),
        nullable=False,
        comment="绑定 Project ID",
    )
    scope_key = Column(String(191), nullable=False, comment="provider scope key")
    sandbox_id = Column(String(64), nullable=False, comment="确定性沙盒 id")
    generation = Column(String(128), nullable=True, comment="最近一次已知 runtime generation")
    lifecycle = Column(String(20), nullable=False, default="persistent", comment="ephemeral/persistent/resident")
    resume_policy = Column(String(20), nullable=False, default="auto", comment="auto/confirm")
    status = Column(String(20), nullable=False, default="active", comment="active/reaping/suspended/error")
    idle_timeout_seconds = Column(Integer, nullable=True, comment="按沙盒空闲阈值，0 表示不回收")
    credential_fingerprint = Column(String(128), nullable=True, comment="最近注入凭据/环境指纹")
    lease_owner_kind = Column(String(32), nullable=True, comment="run/coding_session/terminal")
    lease_owner_id = Column(String(64), nullable=True, comment="租约持有者标识")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约到期时间")
    lease_heartbeat_at = Column(DateTime, nullable=True, comment="租约最近心跳时间")
    last_activity_at = Column(DateTime, nullable=True, comment="最近活动时间")
    last_keepalive_at = Column(DateTime, nullable=True, comment="最近保活时间")
    suspended_at = Column(DateTime, nullable=True, comment="最近 suspend 时间")
    error_code = Column(String(64), nullable=True, comment="结构化错误码")
    error_message = Column(Text, nullable=True, comment="错误详情（脱敏后）")
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class AgentSandboxEvent(Base):
    """专属沙盒生命周期事件（yuanlei 域），供管理面板时间线与审计。"""

    __tablename__ = "agent_sandbox_events"
    __table_args__ = (Index("ix_agent_sandbox_events_sandbox_created", "sandbox_id", "created_at"),)

    id = Column(String(64), primary_key=True, comment="事件 UUID")
    sandbox_id = Column(String(64), nullable=False, comment="确定性沙盒 id")
    kind = Column(String(32), nullable=False, comment="created/keepalive/suspend/rebuilt/released/error 等")
    actor_kind = Column(String(32), nullable=True, comment="agent/user/supervisor")
    actor_id = Column(String(64), nullable=True, comment="触发者标识")
    payload_json = Column(JSON_VALUE, nullable=False, default=dict, comment="事件负载（脱敏）")
    created_at = Column(DateTime, default=utc_now_naive)


class AgentRunScope(Base):
    """Run 的执行 scope 映射（yuanlei 域）。

    上游 ck_agent_runs_nonterminal_shape 要求根 chat/resume run 的
    runtime_scope_id 等于会话线程 id；专属沙盒的 agent-project scope key
    存在本表，由 resolve_run_scope_key 统一解析。
    """

    __tablename__ = "agent_run_scopes"

    run_id = Column(
        String(64),
        ForeignKey("agent_runs.id", ondelete="CASCADE", name="fk_agent_run_scopes_run_id"),
        primary_key=True,
    )
    scope_key = Column(String(191), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)


class ProjectDocument(Base):
    """项目命名 JSON 文档：按 (project_id, key) 版本化持久化（yuanlei 域）。"""

    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_project_documents_project_key"),
        CheckConstraint("version > 0", name="ck_project_documents_version"),
    )

    id = Column(String(64), primary_key=True, comment="文档 UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_documents_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    key = Column(String(120), nullable=False, comment="规范化文档 key")
    content = Column(JSON_VALUE, nullable=False, comment="JSON 内容")
    version = Column(Integer, nullable=False, default=1, comment="单调递增版本，从 1 开始")
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    updated_by = Column(String(64), nullable=True, comment="最近更新者 uid")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class ProjectDashboard(Base):
    """项目 Dashboard 入口页面的 revision 元数据（yuanlei 域）。"""

    __tablename__ = "project_dashboards"
    __table_args__ = (CheckConstraint("revision > 0", name="ck_project_dashboards_revision"),)

    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_dashboards_project_id"),
        primary_key=True,
        comment="Project ID；每个项目至多一行",
    )
    revision = Column(BigInteger, nullable=False, default=1, comment="页面 revision，从 1 开始")
    content_sha256 = Column(String(64), nullable=False, comment="最近一次受控写入的页面内容 SHA-256")
    content_size = Column(Integer, nullable=False, comment="页面字节数")
    updated_by = Column(String(64), nullable=True, comment="最近提交者 uid")
    updated_at = Column(DateTime, default=utc_now_naive, nullable=False, comment="最近 revision 时间")


GOVERNANCE_SOURCE_CHANNELS = ("project", "multica", "github", "gitea")
GOVERNANCE_LIFECYCLE_STATUSES = ("proposed", "canonical", "rejected")

_GOVERNANCE_STATUS_SQL = "status IN ('proposed', 'canonical', 'rejected')"
_GOVERNANCE_SOURCE_CHANNEL_SQL = "source_channel IN ('project', 'multica', 'github', 'gitea')"
# 项目内来源不携带外部标识与链接；外部渠道必须带外部标识，外部镜像无法直接写入 canonical。
_GOVERNANCE_SOURCE_SHAPE_SQL = (
    "(source_channel = 'project' AND source_external_id IS NULL AND source_url IS NULL)"
    " OR (source_channel <> 'project' AND source_external_id IS NOT NULL)"
)
# 未经审核的 proposed 不得落入 canonical/rejected；审核必须留下责任人与时间。
_GOVERNANCE_REVIEW_SHAPE_SQL = (
    "(status = 'proposed' AND review_owner_uid IS NULL AND reviewed_at IS NULL)"
    " OR (status IN ('canonical', 'rejected') AND review_owner_uid IS NOT NULL AND reviewed_at IS NOT NULL)"
)


class GovernanceTopic(Base):
    """项目治理议题：来源归一化后的 proposed → 审核 → canonical 事实（yuanlei 域）。"""

    __tablename__ = "governance_topics"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_governance_topics_id_project"),
        CheckConstraint(_GOVERNANCE_STATUS_SQL, name="ck_governance_topics_status"),
        CheckConstraint(_GOVERNANCE_SOURCE_CHANNEL_SQL, name="ck_governance_topics_source_channel"),
        CheckConstraint(_GOVERNANCE_SOURCE_SHAPE_SQL, name="ck_governance_topics_source_shape"),
        CheckConstraint(_GOVERNANCE_REVIEW_SHAPE_SQL, name="ck_governance_topics_review_shape"),
        Index("ix_governance_topics_project_id", "project_id"),
        Index("ix_governance_topics_status", "status"),
        Index(
            "uq_governance_topics_source_external",
            "project_id",
            "source_channel",
            "source_external_id",
            unique=True,
            postgresql_where=text("source_external_id IS NOT NULL"),
        ),
    )

    id = Column(String(64), primary_key=True, comment="议题 UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_governance_topics_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    title = Column(String(512), nullable=False, comment="规范化标题")
    summary = Column(Text, nullable=True, comment="背景与候选方案摘要")
    status = Column(String(16), nullable=False, default="proposed", comment="proposed/canonical/rejected")
    source_channel = Column(String(32), nullable=False, comment="project/multica/github/gitea")
    source_external_id = Column(String(191), nullable=True, comment="外部渠道标识，项目内来源为空")
    source_url = Column(String(1024), nullable=True, comment="原文链接")
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    review_owner_uid = Column(String(64), nullable=True, comment="审核责任人 uid")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    review_note = Column(Text, nullable=True, comment="审核说明")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class GovernanceTopicComment(Base):
    """项目议题讨论回复；按议题追加保存作者、正文与时间。"""

    __tablename__ = "governance_topic_comments"
    __table_args__ = (Index("ix_governance_topic_comments_topic_created", "topic_id", "created_at", "id"),)

    id = Column(String(64), primary_key=True, comment="议题回复 UUID")
    topic_id = Column(
        String(64),
        ForeignKey("governance_topics.id", ondelete="CASCADE", name="fk_governance_topic_comments_topic_id"),
        nullable=False,
        comment="所属议题",
    )
    content = Column(Text, nullable=False, comment="Markdown 回复正文")
    author_name = Column(Text, nullable=False, comment="发帖时作者显示名快照")
    created_by = Column(String(64), nullable=True, comment="作者 uid，不建立用户外键以保留历史回复")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)


class ProjectWorkCode(Base):
    """项目工作任务编号配置与项目内序号。"""

    __tablename__ = "project_work_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_project_work_codes_code"),)

    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    code = Column(String(12), nullable=False)
    next_number = Column(Integer, nullable=False, default=1)


class ProjectTopicCode(Base):
    """议题编号缩写，固化后不随标题变化。"""

    __tablename__ = "project_topic_codes"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_project_topic_codes_project_code"),
        ForeignKeyConstraint(
            ["topic_id", "project_id"],
            ["governance_topics.id", "governance_topics.project_id"],
            name="fk_project_topic_codes_topic_project",
            ondelete="CASCADE",
        ),
    )

    topic_id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(12), nullable=False)


class ProjectWorkTask(Base):
    """独立项目工作任务，状态不复用治理任务或 AgentRun。"""

    __tablename__ = "project_work_tasks"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_project_work_tasks_id_project"),
        UniqueConstraint("project_id", "number", name="uq_project_work_tasks_project_number"),
        ForeignKeyConstraint(
            ["topic_id", "project_id"],
            ["governance_topics.id", "governance_topics.project_id"],
            name="fk_project_work_tasks_topic_project",
        ),
        ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["project_work_tasks.id", "project_work_tasks.project_id"],
            name="fk_project_work_tasks_parent_project",
        ),
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'blocked', 'done', 'cancelled')",
            name="ck_project_work_tasks_status",
        ),
        CheckConstraint(
            "git_workspace_mode IN ('inherit', 'isolated')", name="ck_project_work_tasks_git_workspace_mode"
        ),
        Index("ix_project_work_tasks_project_created", "project_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(String(64), ForeignKey("governance_topics.id", ondelete="SET NULL"), nullable=True)
    parent_id = Column(String(64), ForeignKey("project_work_tasks.id", ondelete="SET NULL"), nullable=True)
    number = Column(String(48), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="todo")
    start_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    primary_owner_agent_slug = Column(String(80), ForeignKey("agents.slug", ondelete="SET NULL"), nullable=True)
    knowledge_ids = Column(JSON_VALUE, nullable=False, default=list, server_default=text("'[]'"))
    git_workspace_mode = Column(String(16), nullable=False, default="inherit", server_default="inherit")
    inspection_enabled = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    inspection_interval_minutes = Column(Integer, nullable=True)
    inspection_next_run_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


PROJECT_WORK_ACTIVE_STATUSES = ("pending_acceptance", "queued", "dispatching", "submitted", "interrupted")
PROJECT_WORK_EXECUTING_STATUSES = ("dispatching", "submitted", "interrupted")


class ProjectWorkExecution(Base):
    """任务分配与一次 Agent 执行尝试的持久队列事实。"""

    __tablename__ = "project_work_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["project_work_tasks.id", "project_work_tasks.project_id"],
            name="fk_project_work_executions_task_project",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending_acceptance', 'queued', 'dispatching', 'submitted', "
            "'interrupted', 'completed', 'failed', 'cancelled')",
            name="ck_project_work_executions_status",
        ),
        Index(
            "uq_project_work_executions_active_task",
            "task_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_acceptance', 'queued', 'dispatching', 'submitted', 'interrupted')"
            ),
        ),
        Index(
            "uq_project_work_executions_active_agent",
            "agent_slug",
            unique=True,
            postgresql_where=text("status IN ('dispatching', 'submitted', 'interrupted')"),
        ),
        Index("ix_project_work_executions_agent_queue", "agent_slug", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), nullable=False)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    uid = Column(String(64), nullable=False)
    agent_slug = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="pending_acceptance")
    prompt = Column(Text, nullable=False)
    model_spec = Column(String(512), nullable=True)
    request_id = Column(String(64), nullable=False, unique=True)
    thread_id = Column(String(64), nullable=False, unique=True)
    current_run_id = Column(String(64), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    error_message = Column(Text, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class ProjectWorkIssue(Base):
    """任务下独立问题单。"""

    __tablename__ = "project_work_issues"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_project_work_issues_task_sequence"),
        CheckConstraint("status IN ('open', 'resolved', 'closed')", name="ck_project_work_issues_status"),
    )

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("project_work_tasks.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="open")
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class ProjectWorkReference(Base):
    """项目任务中追加的网页引用。"""

    __tablename__ = "project_work_references"
    __table_args__ = (Index("ix_project_work_references_task_created", "task_id", "created_at"),)

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("project_work_tasks.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False)
    url = Column(String(2048), nullable=False)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)


class ProjectWorkAttachment(Base):
    """项目任务的文件附件元数据；内容保存在对象存储。"""

    __tablename__ = "project_work_attachments"
    __table_args__ = (
        UniqueConstraint("object_name", name="uq_project_work_attachments_object"),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["project_work_tasks.id", "project_work_tasks.project_id"],
            name="fk_project_work_attachments_task_project",
            ondelete="CASCADE",
        ),
        Index("ix_project_work_attachments_task_created", "task_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), nullable=False)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(512), nullable=False)
    content_type = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=False)
    object_name = Column(String(1024), nullable=False)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)


class ProjectWorkInspectionRun(Base):
    """第一负责人周期巡检的一次运行事实。"""

    __tablename__ = "project_work_inspection_runs"
    __table_args__ = (
        UniqueConstraint("task_id", "occurrence_key", name="uq_project_work_inspection_runs_occurrence"),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            ["project_work_tasks.id", "project_work_tasks.project_id"],
            name="fk_project_work_inspection_runs_task_project",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('claimed', 'completed', 'failed')",
            name="ck_project_work_inspection_runs_status",
        ),
        Index("ix_project_work_inspection_runs_task_created", "task_id", "created_at"),
        Index("ix_project_work_inspection_runs_status_created", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), nullable=False)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    occurrence_key = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="claimed")
    finding = Column(String(64), nullable=True)
    summary = Column(Text, nullable=True)
    inspected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class ProjectWorkComment(Base):
    """任务或问题单的追加式讨论记录。"""

    __tablename__ = "project_work_comments"
    __table_args__ = (
        CheckConstraint("(task_id IS NOT NULL) <> (issue_id IS NOT NULL)", name="ck_project_work_comments_one_parent"),
        Index("ix_project_work_comments_task_created", "task_id", "created_at"),
        Index("ix_project_work_comments_issue_created", "issue_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("project_work_tasks.id", ondelete="CASCADE"), nullable=True)
    issue_id = Column(String(64), ForeignKey("project_work_issues.id", ondelete="CASCADE"), nullable=True)
    source_run_id = Column(String(64), nullable=True, unique=True)
    content = Column(Text, nullable=False)
    author_uid = Column(String(64), nullable=False)
    author_name = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)


class UserInboxItem(Base):
    """用户收件箱中的持久通知。"""

    __tablename__ = "user_inbox_items"
    __table_args__ = (
        UniqueConstraint("uid", "kind", "source_id", name="uq_user_inbox_items_source"),
        CheckConstraint(
            "kind IN ('task_completed', 'run_question', 'task_failed', 'task_interrupted', 'task_inspection')",
            name="ck_user_inbox_items_kind",
        ),
        Index("ix_user_inbox_items_uid_created", "uid", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    uid = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=False)
    project_id = Column(String(64), nullable=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=True)
    occurrences = Column(
        JSON_VALUE,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
        comment="同一来源的通知发生过程快照，按发生时间排列",
    )
    read_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive, server_default=func.now())


class GovernanceDecision(Base):
    """项目治理决策：人拍板的结论、理由与被否替代（yuanlei 域）。"""

    __tablename__ = "governance_decisions"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'implemented')", name="ck_governance_decisions_status"),
        CheckConstraint(
            "(status = 'proposed' AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status = 'implemented' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_governance_decisions_decision_shape",
        ),
        Index("ix_governance_decisions_project_id", "project_id"),
        Index("ix_governance_decisions_topic_id", "topic_id"),
    )

    id = Column(String(64), primary_key=True, comment="决策 UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_governance_decisions_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    topic_id = Column(
        String(64),
        ForeignKey("governance_topics.id", ondelete="SET NULL", name="fk_governance_decisions_topic_id"),
        nullable=True,
        comment="来源议题",
    )
    title = Column(String(512), nullable=False, comment="决策标题")
    conclusion = Column(Text, nullable=False, comment="结论")
    rationale = Column(Text, nullable=True, comment="理由与被否替代")
    status = Column(String(16), nullable=False, default="proposed", comment="proposed/implemented")
    decided_by = Column(String(64), nullable=True, comment="拍板人 uid")
    decided_at = Column(DateTime, nullable=True, comment="拍板时间")
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class GovernanceTask(Base):
    """项目治理任务：由决策拆出并指派项目数字员工，来源归一化同议题（yuanlei 域）。"""

    __tablename__ = "governance_tasks"
    __table_args__ = (
        CheckConstraint(_GOVERNANCE_STATUS_SQL, name="ck_governance_tasks_status"),
        CheckConstraint(_GOVERNANCE_SOURCE_CHANNEL_SQL, name="ck_governance_tasks_source_channel"),
        CheckConstraint(_GOVERNANCE_SOURCE_SHAPE_SQL, name="ck_governance_tasks_source_shape"),
        CheckConstraint(_GOVERNANCE_REVIEW_SHAPE_SQL, name="ck_governance_tasks_review_shape"),
        Index("ix_governance_tasks_project_id", "project_id"),
        Index("ix_governance_tasks_topic_id", "topic_id"),
        Index("ix_governance_tasks_decision_id", "decision_id"),
        Index("ix_governance_tasks_status", "status"),
        Index(
            "uq_governance_tasks_source_external",
            "project_id",
            "source_channel",
            "source_external_id",
            unique=True,
            postgresql_where=text("source_external_id IS NOT NULL"),
        ),
    )

    id = Column(String(64), primary_key=True, comment="任务 UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_governance_tasks_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    topic_id = Column(
        String(64),
        ForeignKey("governance_topics.id", ondelete="SET NULL", name="fk_governance_tasks_topic_id"),
        nullable=True,
        comment="来源议题",
    )
    decision_id = Column(
        String(64),
        ForeignKey("governance_decisions.id", ondelete="SET NULL", name="fk_governance_tasks_decision_id"),
        nullable=True,
        comment="来源决策",
    )
    assignee_agent_slug = Column(
        String(80),
        ForeignKey("agents.slug", ondelete="SET NULL", name="fk_governance_tasks_assignee_agent_slug"),
        nullable=True,
        comment="指派项目数字员工 slug",
    )
    title = Column(String(512), nullable=False, comment="规范化标题")
    description = Column(Text, nullable=True, comment="任务说明")
    status = Column(String(16), nullable=False, default="proposed", comment="proposed/canonical/rejected")
    source_channel = Column(String(32), nullable=False, comment="project/multica/github/gitea")
    source_external_id = Column(String(191), nullable=True, comment="外部渠道标识，项目内来源为空")
    source_url = Column(String(1024), nullable=True, comment="原文链接")
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    review_owner_uid = Column(String(64), nullable=True, comment="审核责任人 uid")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    review_note = Column(Text, nullable=True, comment="审核说明")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class GovernanceReport(Base):
    """项目治理汇报：定时任务产出的 artifact 引用与聚合摘要（yuanlei 域）。

    只引用产生 Run 与 artifact 路径，不复制 Run 终态，避免形成第二状态源。
    """

    __tablename__ = "governance_reports"
    __table_args__ = (Index("ix_governance_reports_project_id", "project_id"),)

    id = Column(String(64), primary_key=True, comment="汇报 UUID")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_governance_reports_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    title = Column(String(512), nullable=False, comment="汇报标题")
    summary = Column(Text, nullable=True, comment="人可读摘要")
    content = Column(JSON_VALUE, nullable=False, default=dict, comment="结构化汇报载荷")
    source_run_id = Column(
        String(64),
        ForeignKey("agent_runs.id", ondelete="SET NULL", name="fk_governance_reports_source_run_id"),
        nullable=True,
        comment="产出汇报的 Run 引用，不承载其状态",
    )
    artifact_path = Column(String(512), nullable=True, comment="Workdir 相对 artifact 路径")
    created_by = Column(String(64), nullable=True, comment="创建者 uid")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


CHANNEL_DELEGATION_DISPATCH_STATES = ("pending", "dispatched", "collecting", "reclaimed", "failed")
CHANNEL_DELEGATION_EXECUTORS = ("opencode", "codex", "multica")
CHANNEL_SYNC_CHANNELS = ("multica",)


class ChannelDelegation(Base):
    """外部执行器委派事实：本地投递/回收状态与远端只读投影分离（yuanlei 域）。

    `dispatch_state` 只由 `DelegationService` 写；`remote_status` 是远端执行的只读
    投影，远端状态变化不改写本地状态，也不复制为 canonical。结果只引用发起 Run。
    """

    __tablename__ = "channel_delegations"
    __table_args__ = (
        CheckConstraint(
            "dispatch_state IN ('pending', 'dispatched', 'collecting', 'reclaimed', 'failed')",
            name="ck_channel_delegations_dispatch_state",
        ),
        CheckConstraint(
            "executor_key IN ('opencode', 'codex', 'multica')",
            name="ck_channel_delegations_executor_key",
        ),
        Index("ix_channel_delegations_project_id", "project_id"),
        Index("ix_channel_delegations_state_lease", "dispatch_state", "lease_expires_at"),
        Index("uq_channel_delegations_operation_id", "operation_id", unique=True),
    )

    id = Column(String(64), primary_key=True, comment="委派行 UUID")
    operation_id = Column(String(128), nullable=False, comment="元垒侧稳定委派操作标识")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_channel_delegations_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    initiator_run_id = Column(
        String(64),
        ForeignKey("agent_runs.id", ondelete="SET NULL", name="fk_channel_delegations_initiator_run_id"),
        nullable=True,
        comment="发起委派的 Run，只引用不承载其状态",
    )
    executor_key = Column(String(32), nullable=False, comment="opencode/codex/multica")
    task = Column(Text, nullable=False, comment="委派任务描述（投递意图）")
    request_json = Column(JSON_VALUE, nullable=False, default=dict, comment="委派意图快照，供崩溃后重投")
    session_id = Column(String(64), nullable=True, comment="沙盒委派的 coding session id")
    turn_id = Column(String(64), nullable=True, comment="沙盒委派那一轮的 coding turn id")
    external_ref = Column(String(191), nullable=True, comment="远端渠道工作项标识")
    external_url = Column(String(1024), nullable=True, comment="远端渠道工作项链接")
    dispatch_state = Column(
        String(16), nullable=False, default="pending", comment="pending/dispatched/collecting/reclaimed/failed"
    )
    attempts = Column(Integer, nullable=False, default=0, comment="投递/回收尝试次数")
    remote_status = Column(String(32), nullable=True, comment="远端执行状态只读投影")
    remote_status_synced_at = Column(DateTime, nullable=True, comment="远端投影同步时间")
    result_summary = Column(Text, nullable=True, comment="回收归一化摘要")
    result_json = Column(JSON_VALUE, nullable=False, default=dict, comment="回收结构化结果")
    artifact_path = Column(String(512), nullable=True, comment="Workdir 相对产物路径")
    owner_token = Column(String(128), nullable=True, comment="当前投递/回收租约 owner")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约到期时间")
    error_code = Column(String(64), nullable=True, comment="最近结构化错误码")
    last_error_at = Column(DateTime, nullable=True, comment="最近错误时间")
    created_by = Column(String(64), nullable=True, comment="发起者 uid")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class ChannelSyncCursor(Base):
    """入向渠道同步游标：确定性同步服务持有，不依赖 Agent 决定同步（yuanlei 域）。"""

    __tablename__ = "channel_sync_cursors"
    __table_args__ = (
        CheckConstraint("channel IN ('multica')", name="ck_channel_sync_cursors_channel"),
        Index("uq_channel_sync_cursors_scope", "channel", "project_id", unique=True),
    )

    id = Column(String(64), primary_key=True, comment="游标行 UUID")
    channel = Column(String(32), nullable=False, comment="multica")
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_channel_sync_cursors_project_id"),
        nullable=False,
        comment="所属 Project ID",
    )
    cursor_value = Column(String(512), nullable=True, comment="上次成功同步位置")
    last_synced_at = Column(DateTime, nullable=True, comment="上次成功同步时间")
    owner_token = Column(String(128), nullable=True, comment="当前同步租约 owner")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约到期时间")
    last_error = Column(Text, nullable=True, comment="最近同步失败原因")
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class CodingCredential(Base):
    """编码执行器（opencode/codex）的用户级或全局凭据（yuanlei 域）。"""

    __tablename__ = "coding_credentials"
    __table_args__ = (
        Index(
            "uq_coding_credentials_user",
            "uid",
            "executor",
            "provider",
            unique=True,
            postgresql_where=text("scope = 'user'"),
            sqlite_where=text("scope = 'user'"),
        ),
        Index(
            "uq_coding_credentials_global",
            "executor",
            "provider",
            unique=True,
            postgresql_where=text("scope = 'global'"),
            sqlite_where=text("scope = 'global'"),
        ),
    )

    id = Column(String(64), primary_key=True, comment="凭据 UUID")
    scope = Column(String(16), nullable=False, default="user", comment="user/global")
    uid = Column(
        String(64),
        ForeignKey("users.uid", ondelete="CASCADE", name="fk_coding_credentials_uid_users"),
        nullable=True,
        comment="所有者 uid；global 行为空",
    )
    executor = Column(String(16), nullable=False, comment="opencode/codex")
    provider = Column(String(64), nullable=False, comment="供应商标识")
    source = Column(
        String(16),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="manual/model_provider",
    )
    model_provider_id = Column(String(100), nullable=True, comment="引用的模型供应商 provider_id")
    key_mode = Column(String(16), nullable=True, comment="引用模式密钥来源：inherit/custom")
    base_url = Column(String(512), nullable=True, comment="OpenAI 兼容/Responses 端点")
    model = Column(String(255), nullable=True, comment="默认模型")
    api_key_cipher = Column(LargeBinary, nullable=True, comment="AES-GCM 密文")
    nonce = Column(LargeBinary, nullable=True, comment="AES-GCM nonce")
    key_version = Column(Integer, nullable=True, comment="加密密钥版本")
    extra_json = Column(JSON_VALUE, nullable=False, default=dict, comment="非密扩展配置")
    status = Column(String(16), nullable=False, default="active", comment="active/deleted")
    version = Column(Integer, nullable=False, default=1, comment="凭据版本，用于指纹")
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class CodingSession(Base):
    """编码执行器会话：跨 Run 的多轮协作与产物所有权（yuanlei 域）。"""

    __tablename__ = "coding_sessions"
    __table_args__ = (
        Index("ix_coding_sessions_uid_status", "uid", "status"),
        Index("ix_coding_sessions_conversation", "conversation_id"),
    )

    id = Column(String(64), primary_key=True, comment="会话 UUID")
    uid = Column(
        String(64),
        ForeignKey("users.uid", ondelete="CASCADE", name="fk_coding_sessions_uid_users"),
        nullable=False,
        comment="所有者 uid",
    )
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_coding_sessions_project_id"),
        nullable=False,
        comment="绑定 Project ID",
    )
    conversation_id = Column(Integer, nullable=True, comment="创建会话的 Conversation（可空）")
    parent_run_id = Column(String(64), nullable=True, comment="创建会话的根 Run id")
    runtime_scope_id = Column(String(191), nullable=False, comment="沙盒 runtime scope key")
    executor = Column(String(16), nullable=False, comment="opencode/codex")
    mode = Column(String(16), nullable=False, default="headless", comment="headless/session/terminal")
    status = Column(String(32), nullable=False, default="pending", comment="会话状态机")
    title = Column(String(255), nullable=True)
    workdir_path = Column(String(512), nullable=False, comment="UserWorkspace 相对 Workdir")
    worktree_ref = Column(String(255), nullable=True, comment="可选 Git worktree 引用")
    sandbox_id = Column(String(64), nullable=True)
    sandbox_generation = Column(String(128), nullable=True)
    credential_fingerprint = Column(String(128), nullable=True)
    cli_session_ref = Column(String(191), nullable=True, comment="CLI 原生会话引用")
    policy_json = Column(JSON_VALUE, nullable=False, default=dict)
    budget_json = Column(JSON_VALUE, nullable=False, default=dict)
    usage_json = Column(JSON_VALUE, nullable=False, default=dict)
    last_activity_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    terminal_at = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class CodingSessionTurn(Base):
    """编码会话内的一次「发消息 → CLI 执行到停止」（yuanlei 域）。"""

    __tablename__ = "coding_session_turns"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_coding_session_turns_seq"),)

    id = Column(String(64), primary_key=True, comment="turn UUID")
    session_id = Column(
        String(64),
        ForeignKey("coding_sessions.id", ondelete="CASCADE", name="fk_coding_session_turns_session_id"),
        nullable=False,
        comment="所属会话",
    )
    seq = Column(Integer, nullable=False, comment="会话内递增序号")
    request_text = Column(Text, nullable=False, comment="本轮输入")
    status = Column(String(16), nullable=False, default="pending", comment="pending/running/completed/failed/cancelled")
    result_summary = Column(Text, nullable=True)
    usage_json = Column(JSON_VALUE, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)


class CodingSessionEvent(Base):
    """编码会话归一化事件（yuanlei 域）；seq 在会话内递增，供 SSE 回放。"""

    __tablename__ = "coding_session_events"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_coding_session_events_seq"),)

    id = Column(String(64), primary_key=True, comment="事件 UUID")
    session_id = Column(
        String(64),
        ForeignKey("coding_sessions.id", ondelete="CASCADE", name="fk_coding_session_events_session_id"),
        nullable=False,
        comment="所属会话",
    )
    turn_id = Column(String(64), nullable=True, comment="所属 turn（可空）")
    seq = Column(Integer, nullable=False, comment="会话内递增序号")
    kind = Column(String(32), nullable=False, comment="session_status/output_delta/tool_call/usage/error 等")
    payload_json = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now_naive)


class Skill(Base):
    """Skill 元数据模型（内容存文件系统，索引存数据库）"""

    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), nullable=False, unique=True, index=True, comment="技能唯一标识（目录名）")
    name = Column(String(128), nullable=False, comment="技能名称（来自 SKILL.md frontmatter.name）")
    description = Column(Text, nullable=False, comment="技能描述（来自 SKILL.md frontmatter.description）")
    source_type = Column(
        String(32), nullable=False, default="upload", index=True, comment="来源: builtin/upload/remote"
    )
    tool_dependencies = Column(JSON, nullable=False, default=list, comment="依赖的内置工具名列表")
    mcp_dependencies = Column(JSON, nullable=False, default=list, comment="依赖的 MCP 服务名列表")
    skill_dependencies = Column(JSON, nullable=False, default=list, comment="依赖的其他 skill slug 列表")
    dir_path = Column(String(512), nullable=False, comment="共享技能目录路径（相对 Skill 数据根目录）")
    version = Column(String(64), nullable=True, comment="技能版本（内置 skill 使用语义化版本）")
    content_hash = Column(String(128), nullable=True, comment="技能目录内容哈希（内置 skill 安装时计算）")
    share_config = Column(JSON_VALUE, nullable=False, comment="共享权限配置")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "source_type": self.source_type,
            "tool_dependencies": self.tool_dependencies or [],
            "mcp_dependencies": self.mcp_dependencies or [],
            "skill_dependencies": self.skill_dependencies or [],
            "dir_path": self.dir_path,
            "version": self.version,
            "content_hash": self.content_hash,
            "share_config": self.share_config or {},
            "enabled": bool(self.enabled),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class Conversation(Base):
    """Conversation table - 对话表"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    thread_id = Column(String(64), unique=True, index=True, nullable=False, comment="Thread ID (UUID)")
    creation_request_id = Column(String(64), nullable=True, comment="新建 Conversation 幂等请求 ID")
    uid = Column(String(64), index=True, nullable=False, comment="UID")
    # 历史字段名，实际保存的是 Agent.slug。
    agent_id = Column(String(64), index=True, nullable=False, comment="Agent slug (legacy column name: agent_id)")
    title = Column(String(255), nullable=True, comment="Conversation title")
    status = Column(String(20), default="active", comment="Status: active/archived/deleted")
    is_pinned = Column(Boolean, default=False, nullable=False, index=True, comment="Is pinned to top")
    last_viewed_run_id = Column(String(64), nullable=True, comment="Latest top-level run id viewed by user")
    project_id = Column(String(64), nullable=False, index=True, comment="Conversation 绑定的 Project ID")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="Update time")
    extra_metadata = Column(JSON, nullable=True, comment="Additional metadata")

    # Relationships
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    stats = relationship(
        "ConversationStats", back_populates="conversation", uselist=False, cascade="all, delete-orphan"
    )
    project = relationship("Project", back_populates="conversations")

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "uid"],
            ["projects.id", "projects.uid"],
            name="fk_conversations_project_uid",
        ),
        UniqueConstraint("uid", "creation_request_id", name="uq_conversations_uid_creation_request_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        metadata = self.extra_metadata or {}
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "creation_request_id": self.creation_request_id,
            "uid": self.uid,
            "agent_id": self.agent_id,
            "title": self.title,
            "status": self.status,
            "is_pinned": bool(self.is_pinned),
            "project_id": self.project_id,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
            "metadata": metadata,
        }


class SubagentThread(Base):
    """SubagentThread table - 子智能体长期线程归属关系表"""

    __tablename__ = "subagent_threads"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    uid = Column(String(64), index=True, nullable=False, comment="UID")
    parent_conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True, comment="Parent conversation ID"
    )
    child_conversation_id = Column(
        Integer,
        ForeignKey("conversations.id"),
        nullable=False,
        unique=True,
        index=True,
        comment="Child conversation ID",
    )
    child_thread_id = Column(String(64), nullable=False, unique=True, index=True, comment="Child thread ID")
    subagent_slug = Column(String(64), nullable=False, index=True, comment="Subagent slug")
    created_by_run_id = Column(String(64), nullable=False, index=True, comment="Run that created this subagent thread")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="Update time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid": self.uid,
            "parent_conversation_id": self.parent_conversation_id,
            "child_conversation_id": self.child_conversation_id,
            "child_thread_id": self.child_thread_id,
            "subagent_slug": self.subagent_slug,
            "created_by_run_id": self.created_by_run_id,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class Message(Base):
    """Message table - 消息表"""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "execution_status IS NULL OR execution_status IN "
            "('running', 'completed', 'failed', 'interrupted', 'abandoned')",
            name="ck_messages_execution_status",
        ),
        Index(
            "uq_messages_run_role_operation_id",
            "run_id",
            "role",
            "operation_id",
            unique=True,
            postgresql_where=text("operation_id IS NOT NULL"),
            sqlite_where=text("operation_id IS NOT NULL"),
        ),
        Index(
            "ix_messages_run_sequence",
            "run_id",
            "sequence",
            postgresql_where=text("sequence IS NOT NULL"),
            sqlite_where=text("sequence IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True, comment="Conversation ID"
    )
    role = Column(String(20), nullable=False, comment="Message role: user/assistant/system/tool")
    content = Column(Text, nullable=False, comment="Message content")
    message_type = Column(String(30), default="text", comment="Message type: text/tool_call/tool_result")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    token_count = Column(Integer, nullable=True, comment="Token count (optional)")
    extra_metadata = Column(JSON, nullable=True, comment="Additional metadata (complete message dump)")
    image_content = Column(Text, nullable=True, comment="Base64 encoded image content for multimodal messages")
    run_id = Column(String(64), ForeignKey("agent_runs.id"), nullable=True, index=True, comment="Agent run ID")
    request_id = Column(String(64), nullable=True, index=True, comment="Request ID for idempotency")
    delivery_status = Column(String(32), nullable=False, default="complete", comment="Message status")
    operation_id = Column(String(128), nullable=True, comment="同一 Run 内的 Model/Tool 稳定来源键")
    started_at = Column(DateTime, nullable=True, comment="Yuxi 观察到操作开始的 wall-clock 时间")
    finished_at = Column(DateTime, nullable=True, comment="Yuxi 观察到操作结束的 wall-clock 时间")
    duration_ms = Column(BigInteger, nullable=True, comment="本进程 monotonic clock 计算的操作耗时")
    sequence = Column(BigInteger, nullable=True, comment="LangGraph 根 StreamMux 事件顺序")
    execution_status = Column(String(32), nullable=True, comment="Model/Tool 执行状态")
    usage = Column(JSON_VALUE, nullable=True, comment="Provider 返回的单次可靠 usage")

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    tool_calls = relationship("ToolCall", back_populates="message", cascade="all, delete-orphan")
    feedbacks = relationship("MessageFeedback", back_populates="message", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "message_type": self.message_type,
            "created_at": format_utc_datetime(self.created_at),
            "token_count": self.token_count,
            "metadata": self.extra_metadata or {},
            "image_content": self.image_content,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "status": self.delivery_status,
            "operation_id": self.operation_id,
            "started_at": format_utc_datetime(self.started_at),
            "finished_at": format_utc_datetime(self.finished_at),
            "duration_ms": self.duration_ms,
            "sequence": self.sequence,
            "execution_status": self.execution_status,
            "usage": self.usage,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls] if self.tool_calls else [],
        }

    def to_simple_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
        }


class ToolCall(Base):
    """ToolCall table - 工具调用表"""

    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True, comment="Message ID")
    langgraph_tool_call_id = Column(String(100), nullable=True, index=True, comment="LangGraph tool_call_id")
    tool_name = Column(String(100), nullable=False, comment="Tool name")
    tool_input = Column(JSON, nullable=True, comment="Tool input parameters")
    tool_output = Column(Text, nullable=True, comment="Tool execution result")
    status = Column(String(20), default="pending", comment="Status: pending/success/error")
    error_message = Column(Text, nullable=True, comment="Error message if failed")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")

    # Relationships
    message = relationship("Message", back_populates="tool_calls")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "langgraph_tool_call_id": self.langgraph_tool_call_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input or {},
            "tool_output": self.tool_output,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": format_utc_datetime(self.created_at),
        }


class ConversationStats(Base):
    """ConversationStats table - 对话统计表"""

    __tablename__ = "conversation_stats"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), unique=True, nullable=False, comment="Conversation ID"
    )
    message_count = Column(Integer, default=0, comment="Total message count")
    total_tokens = Column(Integer, default=0, comment="Total tokens used")
    model_used = Column(String(100), nullable=True, comment="Model used")
    user_feedback = Column(JSON, nullable=True, comment="User feedback")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="Update time")

    # Relationships
    conversation = relationship("Conversation", back_populates="stats")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "model_used": self.model_used,
            "user_feedback": self.user_feedback or {},
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class OperationLog(Base):
    """操作日志模型"""

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operation = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime, default=utc_now_naive)

    # 关联用户
    user = relationship("User", back_populates="operation_logs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "operation": self.operation,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": format_utc_datetime(self.timestamp),
        }


class MessageFeedback(Base):
    """Message feedback table - 消息反馈表"""

    __tablename__ = "message_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    message_id = Column(
        Integer, ForeignKey("messages.id"), nullable=False, index=True, comment="Message ID being rated"
    )
    uid = Column(String(64), nullable=False, index=True, comment="UID who provided feedback")
    rating = Column(String(10), nullable=False, comment="Feedback rating: like or dislike")
    reason = Column(Text, nullable=True, comment="Optional reason for dislike feedback")
    created_at = Column(DateTime, default=utc_now_naive, comment="Feedback creation time")

    # Relationships
    message = relationship("Message", back_populates="feedbacks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "uid": self.uid,
            "rating": self.rating,
            "reason": self.reason,
            "created_at": format_utc_datetime(self.created_at),
        }


class MCPServer(Base):
    """MCP 服务器配置模型"""

    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), nullable=False, unique=True, index=True, comment="稳定标识")
    name = Column(String(100), nullable=False, comment="展示名称")
    description = Column(String(500), nullable=True, comment="描述")

    # 连接配置
    transport = Column(String(20), nullable=False, comment="传输类型：sse/streamable_http")
    url = Column(String(500), nullable=True, comment="服务器 URL（sse/streamable_http）")
    # 历史 stdio 字段仅供管理员迁移旧配置，不参与运行时连接。
    command = Column(String(500), nullable=True, comment="历史 stdio 命令")
    args = Column(JSON, nullable=True, comment="命令参数数组（stdio）")
    env = Column(JSON, nullable=True, comment="环境变量（stdio）")
    headers = Column(JSON, nullable=True, comment="HTTP 请求头")
    timeout = Column(Integer, nullable=True, comment="HTTP 超时时间（秒）")
    sse_read_timeout = Column(Integer, nullable=True, comment="SSE 读取超时（秒）")

    # UI 增强字段
    tags = Column(JSON, nullable=True, comment="标签数组")
    icon = Column(String(50), nullable=True, comment="图标（emoji）")

    # 状态字段
    enabled = Column(Integer, nullable=False, default=1, comment="是否启用：1=是，0=否")
    disabled_tools = Column(JSON, nullable=True, comment="禁用的工具名称列表")

    # 用户追踪
    created_by = Column(String(100), nullable=False, comment="创建人用户名")
    updated_by = Column(String(100), nullable=False, comment="修改人用户名")

    # 时间戳
    created_at = Column(DateTime, default=utc_now_naive, comment="创建时间")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="更新时间")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "url": self.url,
            "command": self.command,
            "args": self.args or [],
            "env": self.env or {},
            "headers": self.headers or {},
            "timeout": self.timeout,
            "sse_read_timeout": self.sse_read_timeout,
            "tags": self.tags or [],
            "icon": self.icon,
            "enabled": bool(self.enabled),
            "disabled_tools": self.disabled_tools or [],
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }

    def to_mcp_config(self) -> dict[str, Any]:
        """生成远程 MCP 连接配置。"""
        import json

        if self.transport not in ("sse", "streamable_http"):
            raise ValueError("MCP 仅支持 sse 或 streamable_http，不支持 stdio 等其他 transport")
        config = {"transport": self.transport}
        if self.transport in ("sse", "streamable_http") and self.url:
            config["url"] = self.url
        # headers 只用于 sse/streamable_http 传输类型
        if self.transport in ("sse", "streamable_http") and self.headers:
            if isinstance(self.headers, dict):
                config["headers"] = self.headers
            elif isinstance(self.headers, str):
                try:
                    config["headers"] = json.loads(self.headers)
                except json.JSONDecodeError:
                    pass
        if self.timeout is not None:
            config["timeout"] = self.timeout
        if self.sse_read_timeout is not None:
            config["sse_read_timeout"] = self.sse_read_timeout
        if self.disabled_tools:
            config["disabled_tools"] = self.disabled_tools
        return config


class ModelProvider(Base):
    """模型供应商配置，存储 provider 基础信息、模型端点和可用模型。"""

    __tablename__ = "model_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(100), nullable=False, unique=True, index=True, comment="供应商稳定标识")
    display_name = Column(String(100), nullable=False, comment="展示名称")
    provider_type = Column(String(32), nullable=False, default="openai", comment="供应商适配类型，默认 openai")

    default_protocol = Column(String(64), nullable=True, comment="默认协议，如 openai_compatible")
    base_url = Column(String(500), nullable=False, comment="API 基础 URL")
    embedding_base_url = Column(String(500), nullable=True, comment="Embedding 模型请求基础 URL")
    rerank_base_url = Column(String(500), nullable=True, comment="Rerank 模型请求基础 URL")
    models_endpoint = Column(String(200), nullable=True, comment="聊天/通用模型列表端点")
    embedding_models_endpoint = Column(String(200), nullable=True, comment="Embedding 模型列表端点")
    rerank_models_endpoint = Column(String(200), nullable=True, comment="Rerank 模型列表端点")
    api_key_env = Column(String(128), nullable=True, comment="API Key 环境变量名")
    api_key = Column(String(500), nullable=True, comment="直接配置的 API Key")

    capabilities = Column(JSON, nullable=False, default=list, comment="支持能力：chat/embedding/rerank")
    enabled_models = Column(JSON, nullable=False, default=list, comment="已启用模型配置对象")
    headers_json = Column(JSON, nullable=True, comment="额外请求头")
    extra_json = Column(JSON, nullable=True, comment="扩展配置")

    is_enabled = Column(Boolean, nullable=False, default=True, index=True, comment="供应商是否启用")
    is_builtin = Column(Boolean, nullable=False, default=False, comment="是否内置")

    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, comment="创建时间")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="更新时间")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "default_protocol": self.default_protocol,
            "base_url": self.base_url,
            "embedding_base_url": self.embedding_base_url,
            "rerank_base_url": self.rerank_base_url,
            "models_endpoint": self.models_endpoint,
            "embedding_models_endpoint": self.embedding_models_endpoint,
            "rerank_models_endpoint": self.rerank_models_endpoint,
            "api_key_env": self.api_key_env,
            "api_key": self.api_key,
            "capabilities": self.capabilities or [],
            "enabled_models": self.enabled_models or [],
            "headers_json": self.headers_json or {},
            "extra_json": self.extra_json or {},
            "is_enabled": bool(self.is_enabled),
            "is_builtin": bool(self.is_builtin),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ConfigOption(Base):
    """系统定义、管理员维护值的通用配置项。"""

    __tablename__ = "config_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default="")
    params = Column(JSON, nullable=False, default=dict)
    value = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("type", "dedupe_key", name="uq_tasks_active_dedupe"),
        Index("ix_tasks_status_lease_expires", "status", "lease_expires_at"),
    )

    id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress = Column(Float, nullable=False, default=0.0)
    message = Column(Text, nullable=False, default="")
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    cancel_requested = Column(Integer, nullable=False, default=0)
    handler_version = Column(Integer, nullable=False, default=1)
    dedupe_key = Column(String(64), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    worker_id = Column(String(128), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    timeout_seconds = Column(Float, nullable=False, default=21600.0)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
            "started_at": format_utc_datetime(self.started_at),
            "completed_at": format_utc_datetime(self.completed_at),
            "payload": self.payload or {},
            "result": self.result,
            "error": self.error,
            "cancel_requested": bool(self.cancel_requested),
            "handler_version": int(self.handler_version if self.handler_version is not None else 1),
            "dedupe_key": self.dedupe_key,
            "attempt_count": int(self.attempt_count or 0),
            "worker_id": self.worker_id,
            "heartbeat_at": format_utc_datetime(self.heartbeat_at),
            "lease_expires_at": format_utc_datetime(self.lease_expires_at),
            "timeout_seconds": float(self.timeout_seconds or 0),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("payload", None)
        data.pop("result", None)
        return data


class ScheduledAgentJob(Base):
    """用户自建 Agent 定时任务。"""

    __tablename__ = "scheduled_agent_jobs"
    __table_args__ = (
        UniqueConstraint(
            "uid",
            "creation_request_id",
            name="uq_scheduled_agent_jobs_uid_creation_request",
        ),
        ForeignKeyConstraint(
            ["project_id", "uid"],
            ["projects.id", "projects.uid"],
            name="fk_scheduled_agent_jobs_project_uid",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "tool_approval_mode IN ('default', 'always_trust')",
            name="ck_scheduled_agent_jobs_tool_approval_mode",
        ),
    )

    id = Column(String(64), primary_key=True)
    uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    creation_request_id = Column(String(64), nullable=False)
    creation_intent_hash = Column(String(64), nullable=False)
    project_id = Column(String(64), nullable=False, index=True)
    agent_slug = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    tool_approval_mode = Column(String(32), nullable=False, default="default")
    model_spec = Column(String(512), nullable=True)
    cron_expression = Column(String(100), nullable=False)
    timezone = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    next_run_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid": self.uid,
            "project_id": self.project_id,
            "agent_slug": self.agent_slug,
            "name": self.name,
            "prompt": self.prompt,
            "tool_approval_mode": self.tool_approval_mode,
            "model_spec": self.model_spec,
            "cron_expression": self.cron_expression,
            "timezone": self.timezone,
            "enabled": bool(self.enabled),
            "deleted_at": format_utc_datetime(self.deleted_at),
            "next_run_at": format_utc_datetime(self.next_run_at),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class ScheduledAgentRun(Base):
    """一次定时或手动触发意图，保存配置快照并关联统一 Request。"""

    __tablename__ = "scheduled_agent_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "occurrence_key", name="uq_scheduled_agent_runs_job_occurrence"),
        UniqueConstraint("request_id", name="uq_scheduled_agent_runs_request"),
        UniqueConstraint("thread_id", name="uq_scheduled_agent_runs_thread"),
        Index("ix_scheduled_agent_runs_job_created", "job_id", "created_at"),
        Index("ix_scheduled_agent_runs_dispatching", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    job_id = Column(
        String(64),
        ForeignKey("scheduled_agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id = Column(String(64), nullable=False)
    thread_id = Column(String(64), nullable=False)
    trigger = Column(String(16), nullable=False, default="scheduled")
    occurrence_key = Column(String(128), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    project_id = Column(String(64), nullable=False)
    agent_slug = Column(String(64), nullable=False)
    conversation_title = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    tool_approval_mode = Column(String(32), nullable=False)
    model_spec = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="dispatching")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "trigger": self.trigger,
            "scheduled_for": format_utc_datetime(self.scheduled_for),
            "status": self.status,
            "run_id": None,
            "error_message": self.error_message,
            "created_at": format_utc_datetime(self.created_at),
            "completed_at": None,
        }


class APIKey(Base):
    """API Key 模型"""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)
    request_id = Column(String(64), nullable=True, unique=True, index=True)
    intent_hash = Column(String(64), nullable=True)
    name = Column(String(100), nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)

    expires_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    last_used_at = Column(DateTime, nullable=True)

    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive)

    # 关联
    user = relationship("User", back_populates="api_keys")
    department = relationship("Department")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key_prefix": self.key_prefix,
            "name": self.name,
            "user_id": self.user_id,
            "department_id": self.department_id,
            "expires_at": format_utc_datetime(self.expires_at),
            "is_enabled": bool(self.is_enabled),
            "last_used_at": format_utc_datetime(self.last_used_at),
            "created_by": self.created_by,
            "created_at": format_utc_datetime(self.created_at),
        }

    def is_valid(self) -> bool:
        """检查 Key 是否有效"""
        if not self.is_enabled:
            return False
        if self.revoked_at is not None:
            return False
        if self.expires_at and utc_now_naive() > self.expires_at:
            return False
        return True


class CLIAuthSession(Base):
    """CLI 浏览器授权会话。"""

    __tablename__ = "cli_auth_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_code_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_code = Column(String(16), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    key_name = Column(String(100), nullable=False)

    approved_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)

    approved_user = relationship("User")
    api_key = relationship("APIKey")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_code": self.user_code,
            "status": self.status,
            "key_name": self.key_name,
            "approved_user_id": self.approved_user_id,
            "api_key_id": self.api_key_id,
            "created_at": format_utc_datetime(self.created_at),
            "expires_at": format_utc_datetime(self.expires_at),
            "approved_at": format_utc_datetime(self.approved_at),
            "consumed_at": format_utc_datetime(self.consumed_at),
        }


class AgentRun(Base):
    """AgentRun table - 运行任务表"""

    __tablename__ = "agent_runs"

    id = Column(String(64), primary_key=True, comment="Run ID (UUID)")
    conversation_thread_id = Column(String(64), index=True, nullable=False, comment="Conversation thread ID snapshot")
    runtime_scope_id = Column(
        String(191),
        index=True,
        nullable=False,
        comment="Root conversation runtime scope；专属沙盒为 agent-project scope key",
    )
    runtime_cleanup_pending = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
        comment="Root terminal Run still owns execution runtime cleanup",
    )
    agent_slug = Column(String(64), index=True, nullable=False, comment="Agent slug")
    uid = Column(String(64), index=True, nullable=False, comment="UID")
    status = Column(
        String(32),
        index=True,
        nullable=False,
        default="pending",
        comment="Run status: pending/running/completed/failed/cancel_requested/cancelled/interrupted",
    )
    request_id = Column(String(64), unique=True, index=True, nullable=False, comment="Idempotency request ID")
    source = Column(String(32), nullable=False, default="chat", comment="Run source snapshot")
    channel = Column(String(32), nullable=False, default="web", comment="Run channel snapshot")
    external_id = Column(String(128), nullable=True, index=True, comment="Source-specific external ID snapshot")
    origin_metadata = Column(JSON, nullable=False, default=dict, comment="Immutable origin metadata snapshot")
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=True, index=True, comment="Conversation ID"
    )
    created_by_run_id = Column(String(64), nullable=True, index=True, comment="Run that created this run")
    subagent_thread_relation_id = Column(
        Integer,
        ForeignKey("subagent_threads.id"),
        nullable=True,
        index=True,
        comment="Subagent thread relation record ID",
    )
    run_type = Column(
        String(32),
        nullable=False,
        default="chat",
        comment="Run type: chat/resume/subagent",
    )
    input_message_id = Column(Integer, nullable=True, comment="Input message ID")
    output_message_id = Column(Integer, nullable=True, comment="Output message ID")
    input_payload = Column(JSON, nullable=False, default=dict, comment="Original input payload")
    token_usage = Column(JSON_VALUE, nullable=False, default=dict, comment="Run token usage grouped by model")
    langfuse_trace_id = Column(String(64), nullable=True, comment="Langfuse trace ID")
    error_type = Column(String(64), nullable=True, comment="Error type")
    error_message = Column(Text, nullable=True, comment="Error message")
    worker_id = Column(String(128), nullable=True, comment="稳定 worker identity 与 attempt UUID 组成的 owner token")
    heartbeat_at = Column(DateTime, nullable=True, comment="当前 owner 最近一次成功续租时间")
    lease_expires_at = Column(DateTime, nullable=True, comment="当前执行 ownership 的到期时间")
    manifest = Column(
        JSON_VALUE,
        nullable=True,
        comment="首次执行前固化的运行清单（脱敏）；NULL 表示历史 Run 未知，不从当前配置反推",
    )
    manifest_fingerprint = Column(String(64), nullable=True, comment="运行清单规范化 JSON 的 SHA-256 指纹")
    manifest_recorded_at = Column(DateTime, nullable=True, comment="运行清单固化时间")
    started_at = Column(DateTime, nullable=True, comment="Start time")
    prepared_at = Column(DateTime, nullable=True, comment="当前 Run 首次完成模型调用前准备的时间")
    first_model_request_at = Column(DateTime, nullable=True, comment="当前 Run 首次进入模型供应商请求前的时间")
    first_output_at = Column(DateTime, nullable=True, comment="当前 Run 首次产生非空模型语义输出的时间")
    finished_at = Column(DateTime, nullable=True, comment="Finish time")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="Update time")

    __table_args__ = (
        CheckConstraint(
            AGENT_RUN_SHAPE_CONSTRAINT_SQL,
            name=AGENT_RUN_SHAPE_CONSTRAINT_NAME,
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_thread_id": self.conversation_thread_id,
            "runtime_scope_id": self.runtime_scope_id,
            "runtime_cleanup_pending": bool(self.runtime_cleanup_pending),
            "agent_slug": self.agent_slug,
            "uid": self.uid,
            "status": self.status,
            "request_id": self.request_id,
            "source": self.source,
            "channel": self.channel,
            "external_id": self.external_id,
            "origin_metadata": self.origin_metadata or {},
            "conversation_id": self.conversation_id,
            "created_by_run_id": self.created_by_run_id,
            "subagent_thread_relation_id": self.subagent_thread_relation_id,
            "run_type": self.run_type,
            "input_message_id": self.input_message_id,
            "output_message_id": self.output_message_id,
            "input_payload": self.input_payload or {},
            "token_usage": self.token_usage or {},
            "langfuse_trace_id": self.langfuse_trace_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "manifest": self.manifest,
            "manifest_fingerprint": self.manifest_fingerprint,
            "started_at": format_utc_datetime(self.started_at),
            "prepared_at": format_utc_datetime(self.prepared_at),
            "first_model_request_at": format_utc_datetime(self.first_model_request_at),
            "first_output_at": format_utc_datetime(self.first_output_at),
            "finished_at": format_utc_datetime(self.finished_at),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
            "timing": build_agent_run_timing(
                created_at=self.created_at,
                started_at=self.started_at,
                prepared_at=self.prepared_at,
                first_output_at=self.first_output_at,
                finished_at=self.finished_at,
                first_model_request_at=self.first_model_request_at,
            ),
        }


Index(
    "uq_agent_runs_one_active_per_thread",
    AgentRun.uid,
    AgentRun.agent_slug,
    AgentRun.conversation_thread_id,
    unique=True,
    postgresql_where=AgentRun.status.notin_(AGENT_RUN_TERMINAL_STATUSES),
    sqlite_where=AgentRun.status.notin_(AGENT_RUN_TERMINAL_STATUSES),
)
Index("ix_agent_runs_status_lease_expires", AgentRun.status, AgentRun.lease_expires_at)


class AgentRunAttempt(Base):
    """AgentRunAttempt table - 单次执行占有的不可变事实记录。

    每当 worker 取得 Run 执行所有权时创建一条记录，(run_id, attempt_no) 唯一约束
    保证同一 Run 内序号唯一。终止事实（outcome/error/finished_at）写入后不得改写；
    AgentRun 保存面向业务查询的聚合状态，本表是执行历史与失败事实的 Owner。
    """

    __tablename__ = "agent_run_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    run_id = Column(
        String(64),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="Owning run ID（组合索引以 run_id 开头，无需独立索引）",
    )
    attempt_no = Column(Integer, nullable=False, comment="Run 内递增的执行序号")
    worker_id = Column(String(128), nullable=False, comment="取得执行所有权的 owner token")
    started_at = Column(DateTime, nullable=False, comment="取得执行所有权时间")
    heartbeat_at = Column(DateTime, nullable=True, comment="本 attempt 最近一次续租时间")
    lease_expires_at = Column(DateTime, nullable=True, comment="本 attempt 最近一次租约到期时间")
    finished_at = Column(DateTime, nullable=True, comment="执行占有结束时间；NULL 表示仍开放")
    outcome = Column(
        String(32),
        nullable=True,
        comment="终止事实: completed/failed/cancelled/interrupted/retry_released/lease_expired",
    )
    error_type = Column(String(64), nullable=True, comment="失败时的结构化错误分类")
    error_message = Column(Text, nullable=True, comment="失败时的错误摘要")
    created_at = Column(DateTime, default=utc_now_naive, comment="Creation time")
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, comment="Update time")

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_no", name="uq_agent_run_attempts_run_attempt_no"),
        Index("ix_agent_run_attempts_open", "run_id", "finished_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "attempt_no": self.attempt_no,
            "worker_id": self.worker_id,
            "started_at": format_utc_datetime(self.started_at),
            "heartbeat_at": format_utc_datetime(self.heartbeat_at),
            "lease_expires_at": format_utc_datetime(self.lease_expires_at),
            "finished_at": format_utc_datetime(self.finished_at),
            "outcome": self.outcome,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class AgentRunRequest(Base):
    """AgentRunRequest table - 智能体线程请求队列表。

    表示一次用户/外部请求；派发后由对应 AgentRun 表达执行状态。
    外部统一以 request_id 作为幂等键引用；id 为自增主键，仅用于 FIFO 排序。
    """

    __tablename__ = "agent_run_requests"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="Primary key")
    request_id = Column(String(64), unique=True, index=True, nullable=False, comment="幂等请求 ID")
    uid = Column(String(64), nullable=False, comment="UID")
    agent_slug = Column(String(64), nullable=False, comment="Agent slug")
    conversation_thread_id = Column(String(64), nullable=False, comment="Conversation thread ID")
    source = Column(String(32), nullable=False, default="chat", comment="请求来源: chat/agent_call/eval")
    channel = Column(String(32), nullable=False, default="web", comment="请求通道: web/api/im/internal")
    external_id = Column(String(128), nullable=True, index=True, comment="来源侧消息或调用 ID")
    origin_metadata = Column(JSON, nullable=False, default=dict, comment="来源 metadata 快照")
    queue_policy = Column(
        String(16),
        nullable=False,
        default="enqueue",
        comment="排队策略: enqueue/reject/steer",
    )
    status = Column(
        String(32),
        nullable=False,
        default="queued",
        comment="请求状态: queued/dispatched/cancelled/rejected/failed",
    )
    input_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, comment="关联输入消息 ID")
    dispatched_run_id = Column(String(64), ForeignKey("agent_runs.id"), nullable=True, comment="已派发的 AgentRun ID")
    input_payload = Column(
        JSON, nullable=False, default=dict, comment="接入时解析的模型与审批配置；消息由 input_message_id 关联"
    )
    error_message = Column(Text, nullable=True, comment="rejected/failed 时的错误信息")
    created_at = Column(DateTime, nullable=False, default=utc_now_naive, comment="创建时间")
    dispatched_at = Column(DateTime, nullable=True, comment="派发时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        comment="更新时间",
    )

    # Relationships
    input_message = relationship("Message", foreign_keys=[input_message_id])
    dispatched_run = relationship("AgentRun", foreign_keys=[dispatched_run_id])

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "uid": self.uid,
            "agent_slug": self.agent_slug,
            "thread_id": self.conversation_thread_id,
            "source": self.source,
            "channel": self.channel,
            "external_id": self.external_id,
            "origin_metadata": self.origin_metadata or {},
            "queue_policy": self.queue_policy,
            "status": self.status,
            "input_message_id": self.input_message_id,
            "dispatched_run_id": self.dispatched_run_id,
            "error_message": self.error_message,
            "created_at": format_utc_datetime(self.created_at),
            "dispatched_at": format_utc_datetime(self.dispatched_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


Index(
    "ix_agent_run_requests_queue",
    AgentRunRequest.uid,
    AgentRunRequest.agent_slug,
    AgentRunRequest.conversation_thread_id,
    AgentRunRequest.status,
    AgentRunRequest.created_at,
    AgentRunRequest.id,
)
