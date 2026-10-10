"""个人连接管理与固定目标核验，不修改远端长期配置。"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from yuxi.delegation.contracts import DelegationError
from yuxi.delegation.openclaw import OpenClawGateway
from yuxi.repositories.collaborator_repository import CollaboratorRepository
from yuxi.repositories.project_repository import ProjectRepository
from yuxi.storage.postgres.models_business import (
    CollaboratorConnection,
    CollaboratorConnectionProject,
    CollaboratorTarget,
)
from yuxi.utils.datetime_utils import utc_now_naive


def validate_endpoint(endpoint: str) -> None:
    """连接地址仅限部署者明确列举，避免个人输入触达任意内网。"""
    allowed = os.getenv("YUANLEI_OPENCLAW_ALLOWED_ENDPOINTS", "").split(",")
    if endpoint not in {x.strip() for x in allowed if x.strip()} or not endpoint.startswith(("ws://", "wss://")):
        raise HTTPException(422, detail={"code": "endpoint_not_allowed", "message": "Gateway地址未纳入部署允许范围"})


def tools_are_denied(effective: dict, agent_id: str) -> bool:
    """按安装版公开库存核对目标及所有工具排除，不接受自造tools字段。"""
    access = effective.get("toolAccess") or {}
    tools = access.get("tools")
    return (
        effective.get("agentId") == agent_id
        and effective.get("groups") == []
        and access.get("checked") in {"local-config", "live-session"}
        and isinstance(tools, list)
        and bool(tools)
        and all(item.get("status") == "excluded" for item in tools)
    )


def credential_cipher():
    """用途专属密钥缺失时拒绝保存及执行。"""
    try:
        raw = os.getenv("YUANLEI_COLLABORATION_KEY", "")
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(key) != 32:
            raise ValueError
        return AESGCM(key)
    except (ValueError, TypeError) as exc:
        raise DelegationError("协作者凭据加密未配置", error_code="credential_store_unavailable") from exc


class CollaboratorService:
    """管理本人连接，项目许可由当前数据库归属最终校验。"""

    def __init__(self, db, gateway_factory=OpenClawGateway):
        self.db = db
        self.repo = CollaboratorRepository(db)
        self.gateway_factory = gateway_factory

    async def save_connection(
        self, *, uid, label, endpoint, project_ids, token=None, identifier=None, expected_revision=None, enabled=True
    ):
        """保存或CAS修改连接，保留撤销许可及旧尝试。"""
        validate_endpoint(endpoint)
        for project_id in project_ids:
            if await ProjectRepository(self.db).get_active_selectable_for_user(project_id, uid) is None:
                raise HTTPException(404, detail="项目不存在")
        row = await self.repo.connection(identifier, uid, lock=True) if identifier else None
        if identifier and row is None:
            raise HTTPException(404, detail="连接不存在")
        if row is not None and row.revision != expected_revision:
            raise HTTPException(409, detail={"code": "connection_revision_conflict"})
        if row is None:
            if not token:
                raise HTTPException(422, detail="新连接需要本人Gateway凭据")
            row = CollaboratorConnection(id=uuid.uuid4().hex, uid=uid, provider_key="openclaw", revision=1)
            self.db.add(row)
        else:
            row.revision += 1
        row.label, row.enabled, row.config_json = (
            label,
            enabled,
            {"endpoint": endpoint, "protocol": 4, "server_version": "2026.9.8"},
        )
        if token:
            nonce = os.urandom(12)
            row.nonce = nonce
            row.ciphertext = credential_cipher().encrypt(
                nonce, token.encode(), f"yuanlei-collaboration:{row.id}:{uid}".encode()
            )
        await self.db.flush()
        permissions = {x.project_id: x for x in await self.repo.permissions(row.id)}
        for project_id, permission in permissions.items():
            permission.enabled = project_id in project_ids
        for project_id in set(project_ids) - permissions.keys():
            self.db.add(
                CollaboratorConnectionProject(connection_id=row.id, project_id=project_id, uid=uid, enabled=True)
            )
        await self.db.commit()
        return await self.connection_view(row)

    async def connection_view(self, row):
        """仅返回配置引用与本人范围，永不返回密文或秘密。"""
        return {
            "id": row.id,
            "provider_key": row.provider_key,
            "revision": row.revision,
            "label": row.label,
            "enabled": row.enabled,
            "config": row.config_json,
            "credential_ref": row.id,
            "project_ids": [x.project_id for x in await self.repo.permissions(row.id) if x.enabled],
        }

    async def save_target(
        self, *, uid, connection_id, remote_identity, label, identifier=None, expected_revision=None, enabled=True
    ):
        """固定目标身份；任何修改使旧核验失效。"""
        if await self.repo.connection(connection_id, uid) is None:
            raise HTTPException(404, detail="连接不存在")
        row = await self.repo.target(identifier, uid, lock=True) if identifier else None
        if identifier and (row is None or row.connection_id != connection_id):
            raise HTTPException(404, detail="目标不存在")
        if row and row.revision != expected_revision:
            raise HTTPException(409, detail={"code": "target_revision_conflict"})
        if row is None:
            row = CollaboratorTarget(id=uuid.uuid4().hex, connection_id=connection_id, uid=uid, revision=1)
            self.db.add(row)
        else:
            row.revision += 1
        row.remote_identity, row.label, row.enabled, row.check_json = remote_identity, label, enabled, None
        await self.db.commit()
        return self.target_view(row)

    @staticmethod
    def target_view(row):
        """呈现目标专属核验和限制。"""
        return {
            "id": row.id,
            "connection_id": row.connection_id,
            "remote_identity": row.remote_identity,
            "label": row.label,
            "revision": row.revision,
            "enabled": row.enabled,
            "capability_check": row.check_json,
        }

    def gateway(self, connection):
        """按允许地址与AAD解密当前用途凭据。"""
        endpoint = connection.config_json["endpoint"]
        validate_endpoint(endpoint)
        token = (
            credential_cipher()
            .decrypt(
                bytes(connection.nonce),
                bytes(connection.ciphertext),
                f"yuanlei-collaboration:{connection.id}:{connection.uid}".encode(),
            )
            .decode()
        )
        return self.gateway_factory(endpoint, token)

    async def check_target(self, identifier, uid):
        """只读核对安装版目标与deny-all策略，核验不能由请求自报。"""
        target = await self.repo.target(identifier, uid, lock=True)
        if target is None:
            raise HTTPException(404, detail="目标不存在")
        connection = await self.repo.connection(target.connection_id, uid, lock=True)
        if not target.enabled or not connection.enabled:
            raise HTTPException(409, detail="连接或目标已禁用")
        gateway = self.gateway(connection)
        entry = await self.read_target_policy(gateway, target.remote_identity)
        target.check_json = {
            "checked_at": utc_now_naive().isoformat(),
            "target_revision": target.revision,
            "connection_revision": connection.revision,
            "mode": "structured-text",
            "tools": "deny-all",
            "model": entry["model"],
            "memory_search": False,
            "version": "2026.9.8",
            "evidence_level": "read-only-policy",
        }
        await self.db.commit()
        return self.target_view(target)

    @staticmethod
    async def read_target_policy(gateway, remote_identity, expected_model=None):
        """真实派发前重读目标策略，拒绝核验后远端配置漂移。"""
        agents = await gateway.call("agents.list", {})
        config = await gateway.call("config.get", {})
        effective = await gateway.call("tools.effective", {"agentId": remote_identity})
        entries = (config.get("runtimeConfig") or config.get("config") or {}).get("agents", {}).get("entries", {})
        entry = entries.get(remote_identity) or {}
        known = any(x.get("id") == remote_identity for x in agents.get("agents", []))
        deny = (entry.get("tools") or {}).get("deny") == ["*"]
        fallback = (entry.get("model") or {}).get("fallbacks") == [] if isinstance(entry.get("model"), dict) else False
        memory_off = (entry.get("memory") or {}).get("search", {}).get("enabled") is False
        primary = (entry.get("model") or {}).get("primary") if isinstance(entry.get("model"), dict) else None
        if (
            not isinstance(primary, str)
            or "/" not in primary
            or any(not part.strip() for part in primary.split("/", 1))
            or not known
            or not deny
            or not fallback
            or entry.get("skills") != []
            or not memory_off
            or not tools_are_denied(effective, remote_identity)
        ):
            raise DelegationError(
                "首包目标须核实无工具/无fallback/无skills/关闭检索", error_code="target_policy_unverified"
            )
        if expected_model is not None and entry["model"] != expected_model:
            raise DelegationError("远端模型配置已变更", error_code="target_policy_unverified")
        return entry

    async def dispatch_target(self, target_id, project_id, uid, expected_revision, *, require_fresh=True, lock=True):
        """派发前校验本人、项目许可、目标版本和核验时效。"""
        target = await self.repo.target(target_id, uid, lock=lock)
        if target is None:
            raise HTTPException(404, detail="目标不存在")
        connection = await self.repo.connection(target.connection_id, uid, lock=lock)
        allowed = any(x.project_id == project_id and x.enabled for x in await self.repo.permissions(connection.id))
        check = target.check_json or {}
        from datetime import datetime

        checked_at = datetime.fromisoformat(check["checked_at"]) if check.get("checked_at") else None
        if (
            not allowed
            or not connection.enabled
            or not target.enabled
            or target.revision != expected_revision
            or check.get("target_revision") != target.revision
            or check.get("connection_revision") != connection.revision
            or checked_at is None
            or (require_fresh and checked_at + timedelta(minutes=30) < utc_now_naive())
        ):
            raise DelegationError("目标许可、版本或核验已失效", error_code="target_unavailable")
        return target, connection

    async def resolve_attempt(self, identifier, *, require_current, expected_owner=None, lock_policy=False):
        """恢复准确尝试映射，配置变更时保留历史但停止远端动作。"""
        attempt = await self.repo.attempt(identifier=identifier)
        if attempt is None:
            raise DelegationError("准确尝试不存在", error_code="binding_unknown")
        if require_current:
            project = await ProjectRepository(self.db).lock_active_selectable_for_user(attempt.project_id, attempt.uid)
            row = await self.repo.delegation_owner(attempt.delegation_id)
            if (
                project is None
                or row is None
                or row.dispatch_state != "pending"
                or not expected_owner
                or row.owner_token != expected_owner
                or row.lease_expires_at is None
                or row.lease_expires_at <= utc_now_naive()
            ):
                raise DelegationError("派发租约失效", error_code="delegation_lease_lost")
        attempt = await self.repo.attempt(identifier=identifier, lock=require_current)
        target, connection = await self.dispatch_target(
            attempt.target_id,
            attempt.project_id,
            attempt.uid,
            attempt.snapshot_json["target_revision"],
            require_fresh=require_current,
            lock=require_current or lock_policy,
        )
        if connection.revision != attempt.snapshot_json["connection_revision"]:
            raise DelegationError("连接已变更，需准确核对旧运行", error_code="connection_changed")
        return attempt, target, self.gateway(connection)
