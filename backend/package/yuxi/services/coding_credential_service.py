"""编码执行器凭据的用例：加密存储、掩码读取、解析与指纹。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.coding.credentials import (
    VALID_EXECUTORS,
    CodingCredentialOwner,
    coding_executor_environment,
    credential_fingerprint,
    redact_credential_values,
)
from yuxi.repositories.coding_credential_repository import CodingCredentialRepository
from yuxi.storage.postgres.models_business import CodingCredential
from yuxi.utils.datetime_utils import utc_now_naive


class CodingCredentialMissingError(RuntimeError):
    """所需编码执行器凭据未配置。"""

    error_code = "credential_missing"

    def __init__(self, executor: str):
        super().__init__(f"coding_credential_missing: {executor}")
        self.executor = executor


@dataclass(frozen=True)
class CodingCredentialWrite:
    """PUT 请求的规范化写入载荷。"""

    executor: str
    provider: str
    api_key: str
    base_url: str | None = None
    model: str | None = None
    extra: dict | None = None


@dataclass(frozen=True)
class ResolvedCodingCredential:
    """解析后的可用凭据（含明文密钥，只在执行边界内使用）。"""

    executor: str
    provider: str
    base_url: str | None
    model: str | None
    api_key: str
    extra: dict
    fingerprint: str
    source: str


def mask_credential(row: CodingCredential) -> dict:
    """把凭据行投影为不含密钥的对外视图。"""
    return {
        "id": row.id,
        "scope": row.scope,
        "executor": row.executor,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "extra": row.extra_json or {},
        "has_key": bool(row.api_key_cipher),
        "status": row.status,
        "version": int(row.version or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class CodingCredentialService:
    """编码执行器凭据的读写与解析；写操作用例由本服务提交事务。"""

    def __init__(self, db: AsyncSession, *, owner: CodingCredentialOwner | None = None):
        self.db = db
        self.repo = CodingCredentialRepository(db)
        self._owner = owner

    @property
    def owner(self) -> CodingCredentialOwner:
        if self._owner is None:
            self._owner = CodingCredentialOwner()
        return self._owner

    async def upsert(
        self,
        *,
        scope: str,
        uid: str | None,
        payload: CodingCredentialWrite,
        actor: str | None,
    ) -> CodingCredential:
        """加密并写入用户级或全局凭据；版本自增供指纹变化检测。"""
        executor = str(payload.executor or "").strip().lower()
        provider = str(payload.provider or "").strip()
        if executor not in VALID_EXECUTORS:
            raise ValueError(f"unsupported coding executor: {payload.executor!r}")
        if not provider:
            raise ValueError("coding credential provider is required")
        if not payload.api_key:
            raise ValueError("coding credential api_key is required")
        existing = await self.repo.get(
            scope=scope, uid=uid, executor=executor, provider=provider
        )
        credential_id = existing.id if existing is not None else str(uuid.uuid4())
        encrypted = self.owner.encrypt(
            scope=scope,
            uid=uid,
            executor=executor,
            provider=provider,
            plaintext=payload.api_key,
            credential_id=credential_id,
        )
        row = await self.repo.upsert(
            credential_id=credential_id,
            scope=scope,
            uid=uid,
            executor=executor,
            provider=provider,
            base_url=(payload.base_url or "").strip() or None,
            model=(payload.model or "").strip() or None,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
            extra=payload.extra or {},
            actor=actor,
        )
        await self.db.commit()
        return row

    async def delete(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
        actor: str | None,
    ) -> bool:
        deleted = await self.repo.delete(
            scope=scope,
            uid=uid,
            executor=executor,
            provider=provider,
            actor=actor,
        )
        if deleted:
            await self.db.commit()
        return deleted

    async def list_masked(self, *, scope: str, uid: str | None = None) -> list[dict]:
        rows = await self.repo.list_active(scope=scope, uid=uid)
        return [mask_credential(row) for row in rows]

    async def resolve(
        self,
        *,
        uid: str,
        executor: str,
        provider: str | None = None,
    ) -> ResolvedCodingCredential:
        """按「用户级 > 管理端全局」解析凭据；缺失时显式失败。"""
        normalized_executor = str(executor or "").strip().lower()
        if normalized_executor not in VALID_EXECUTORS:
            raise ValueError(f"unsupported coding executor: {executor!r}")
        for scope, scope_uid, source in (("user", uid, "user"), ("global", None, "global")):
            rows = await self.repo.list_active(scope=scope, uid=scope_uid)
            candidates = [row for row in rows if row.executor == normalized_executor]
            if provider:
                candidates = [row for row in candidates if row.provider == provider]
            if not candidates:
                continue
            row = candidates[0]
            return ResolvedCodingCredential(
                executor=row.executor,
                provider=row.provider,
                base_url=row.base_url,
                model=row.model,
                api_key=self.owner.decrypt(row),
                extra=dict(row.extra_json or {}),
                fingerprint=credential_fingerprint(
                    executor=row.executor,
                    provider=row.provider,
                    base_url=row.base_url,
                    model=row.model,
                    secret_version=int(row.version or 0),
                    extra=row.extra_json or {},
                ),
                source=source,
            )
        raise CodingCredentialMissingError(normalized_executor)

    @staticmethod
    def declared_executors(agent_config: dict | None) -> list[str]:
        """读取 Agent 配置声明的编码执行器白名单。"""
        coding = (agent_config or {}).get("coding")
        raw = coding.get("executors") if isinstance(coding, dict) else None
        if not isinstance(raw, list):
            return []
        return [
            str(item).strip().lower()
            for item in raw
            if str(item).strip().lower() in VALID_EXECUTORS
        ]

    async def build_coding_environment(
        self,
        *,
        uid: str,
        executors: list[str],
    ) -> tuple[dict[str, str], str | None]:
        """按执行器白名单解析凭据并生成沙盒 env 与聚合指纹；缺失的执行器跳过。"""
        env: dict[str, str] = {}
        fingerprints: list[str] = []
        for executor in executors:
            try:
                resolved = await self.resolve(uid=uid, executor=executor)
            except CodingCredentialMissingError:
                continue
            env.update(
                coding_executor_environment(
                    executor=resolved.executor,
                    provider=resolved.provider,
                    api_key=resolved.api_key,
                    base_url=resolved.base_url,
                    model=resolved.model,
                    extra=resolved.extra,
                )
            )
            fingerprints.append(resolved.fingerprint)
        if not env:
            return {}, None
        fingerprint = hashlib.sha256("|".join(sorted(fingerprints)).encode("utf-8")).hexdigest()[:64]
        return env, fingerprint

    @staticmethod
    def redact(text: str, secrets: list[str]) -> str:
        """执行输出写库/发流前的值级脱敏入口。"""
        return redact_credential_values(text, secrets)
