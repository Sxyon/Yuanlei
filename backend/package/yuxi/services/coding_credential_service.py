"""编码执行器凭据的用例：加密存储、掩码自检、解析与指纹。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.coding.credentials import (
    VALID_EXECUTORS,
    CodingCredentialOwner,
    coding_executor_environment,
    credential_fingerprint,
    key_fingerprint,
    redact_credential_values,
)
from yuxi.models.providers.service import (
    check_credential_status,
    get_all_model_providers,
    get_model_provider_by_id,
    resolve_api_key,
)
from yuxi.repositories.coding_credential_repository import CodingCredentialRepository
from yuxi.repositories.project_agent_repository import ProjectAgentRepository
from yuxi.storage.postgres.models_business import CodingCredential

CREDENTIAL_SOURCES = {"manual", "model_provider"}
REFERENCE_KEY_MODES = {"inherit", "custom"}


class CodingCredentialMissingError(RuntimeError):
    """所需编码执行器凭据未配置。"""

    error_code = "credential_missing"

    def __init__(self, executor: str):
        super().__init__(f"coding_credential_missing: {executor}")
        self.executor = executor


class CodingCredentialUnavailableError(RuntimeError):
    """引用的模型供应商不可用；reason 为稳定分类，detail 供人读。"""

    error_code = "credential_unavailable"

    def __init__(self, executor: str, provider_id: str | None, reason: str, detail: str):
        super().__init__(f"coding_credential_unavailable: {executor} {reason}: {detail}")
        self.executor = executor
        self.provider_id = provider_id or ""
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CodingCredentialWrite:
    """PUT 请求的规范化写入载荷。"""

    executor: str
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    extra: dict | None = None
    source: str = "manual"
    model_provider_id: str | None = None
    key_mode: str | None = None


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
    mode: str = "manual"
    model_provider_id: str | None = None
    key_mode: str | None = None


@dataclass(frozen=True)
class CodingEnvironment:
    """一次沙盒准备所需的编码环境结果。"""

    env: dict[str, str]
    fingerprint: str | None
    unavailable: tuple[dict, ...]
    missing: tuple[str, ...]

    def require_executor(self, executor: str) -> None:
        """工具执行前校验选中执行器；缺失或引用不可用时显式失败。"""
        normalized = str(executor or "").strip().lower()
        for item in self.unavailable:
            if item["executor"] == normalized:
                raise CodingCredentialUnavailableError(
                    normalized,
                    item.get("provider_id"),
                    item["reason"],
                    item["detail"],
                )
        if normalized in self.missing:
            raise CodingCredentialMissingError(normalized)


def mask_credential(
    row: CodingCredential,
    *,
    availability: str = "active",
    unavailable_reason: str | None = None,
    unavailable_detail: str | None = None,
    provider_display_name: str | None = None,
) -> dict:
    """把凭据行投影为不含密钥的对外视图（含引用自检状态）。"""
    source = str(row.source or "manual")
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
        "source": source,
        "model_provider_id": row.model_provider_id,
        "key_mode": row.key_mode,
        "provider_display_name": provider_display_name,
        "availability": availability,
        "unavailable_reason": unavailable_reason,
        "unavailable_detail": unavailable_detail,
    }


def _chat_model_entries(provider) -> dict[str, dict]:
    """提取供应商已启用的 chat 模型，引用只允许从中选择。"""
    entries: dict[str, dict] = {}
    for model in getattr(provider, "enabled_models", None) or []:
        if not isinstance(model, dict) or str(model.get("type") or "chat") != "chat":
            continue
        model_id = str(model.get("id") or "").strip()
        if model_id:
            entries[model_id] = model
    return entries


def _provider_base_url(provider, model_entry: dict) -> str | None:
    """模型级 base_url 覆盖优先，其次供应商基础地址。"""
    return str(model_entry.get("base_url_override") or provider.base_url or "").strip() or None


@dataclass(frozen=True)
class CodingSettings:
    """Agent/项目生效的编码执行器设置。"""

    executors: tuple[str, ...]
    default_executor: str | None


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
        """写入或轮换凭据；同 scope 同执行器只保留最新一条。"""
        executor = str(payload.executor or "").strip().lower()
        if executor not in VALID_EXECUTORS:
            raise ValueError(f"unsupported coding executor: {payload.executor!r}")
        source = str(payload.source or "manual").strip().lower()
        if source not in CREDENTIAL_SOURCES:
            raise ValueError(f"unsupported coding credential source: {payload.source!r}")

        credential_id = str(uuid.uuid4())
        ciphertext = nonce = key_version = None
        if source == "manual":
            provider = str(payload.provider or "").strip()
            if not provider:
                raise ValueError("coding credential provider is required")
            if not payload.api_key:
                raise ValueError("coding credential api_key is required")
            existing = await self.repo.get(
                scope=scope, uid=uid, executor=executor, provider=provider
            )
            credential_id = existing.id if existing is not None else credential_id
            encrypted = self.owner.encrypt(
                scope=scope,
                uid=uid,
                executor=executor,
                provider=provider,
                plaintext=payload.api_key,
                credential_id=credential_id,
            )
            ciphertext, nonce, key_version = encrypted.ciphertext, encrypted.nonce, encrypted.key_version
            stored_base_url = (payload.base_url or "").strip() or None
            stored_model = (payload.model or "").strip() or None
            stored_key_mode = None
            stored_provider_id = None
        else:
            key_mode = str(payload.key_mode or "").strip().lower()
            if key_mode not in REFERENCE_KEY_MODES:
                raise ValueError("引用模型供应商时必须指定 key_mode（inherit/custom）")
            provider_id = str(payload.model_provider_id or "").strip()
            if not provider_id:
                raise ValueError("引用模型供应商时必须指定 model_provider_id")
            provider_row = await get_model_provider_by_id(self.db, provider_id)
            if provider_row is None:
                raise ValueError(f"模型供应商 {provider_id} 不存在")
            if not provider_row.is_enabled:
                raise ValueError(f"模型供应商 {provider_id} 已停用，不能保存引用")
            model_id = str(payload.model or "").strip()
            if model_id not in _chat_model_entries(provider_row):
                raise ValueError(f"模型 {model_id or '(未选择)'} 不在供应商已启用模型列表中")
            provider = provider_id
            stored_provider_id = provider_id
            stored_base_url = None
            stored_model = model_id
            stored_key_mode = key_mode
            if key_mode == "inherit":
                if payload.api_key:
                    raise ValueError("共用供应商密钥时不应携带 api_key")
            else:
                if not payload.api_key:
                    raise ValueError("单独密钥模式必须提供 api_key")
                existing = await self.repo.get(
                    scope=scope, uid=uid, executor=executor, provider=provider
                )
                credential_id = existing.id if existing is not None else credential_id
                encrypted = self.owner.encrypt(
                    scope=scope,
                    uid=uid,
                    executor=executor,
                    provider=provider,
                    plaintext=payload.api_key,
                    credential_id=credential_id,
                )
                ciphertext, nonce, key_version = (
                    encrypted.ciphertext,
                    encrypted.nonce,
                    encrypted.key_version,
                )

        row = await self.repo.upsert(
            credential_id=credential_id,
            scope=scope,
            uid=uid,
            executor=executor,
            provider=provider,
            source=source,
            model_provider_id=stored_provider_id,
            key_mode=stored_key_mode,
            base_url=stored_base_url,
            model=stored_model,
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=key_version,
            extra=payload.extra or {} if source == "manual" else {},
            actor=actor,
        )
        await self.repo.deactivate_other_executor_rows(
            scope=scope, uid=uid, executor=executor, keep_id=row.id, actor=actor
        )
        await self.db.commit()
        return row

    async def delete(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str | None = None,
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

    async def _reference_context(self, row: CodingCredential):
        """校验引用目标；返回 (provider, model_entry, model_id) 或结构化不可用。"""
        provider_id = str(row.model_provider_id or "").strip()
        provider = await get_model_provider_by_id(self.db, provider_id) if provider_id else None
        if provider is None:
            raise CodingCredentialUnavailableError(
                row.executor, provider_id, "provider_missing", "引用的模型供应商不存在"
            )
        if not provider.is_enabled:
            raise CodingCredentialUnavailableError(
                row.executor, provider_id, "provider_disabled", "引用的模型供应商已停用"
            )
        model_id = str(row.model or "").strip()
        entry = _chat_model_entries(provider).get(model_id)
        if entry is None:
            raise CodingCredentialUnavailableError(
                row.executor,
                provider_id,
                "model_not_enabled",
                f"模型 {model_id or '(未选择)'} 不在供应商已启用模型列表中",
            )
        if str(row.key_mode or "inherit") == "custom":
            if not row.api_key_cipher:
                raise CodingCredentialUnavailableError(
                    row.executor, provider_id, "credential_key_missing", "单独密钥缺失"
                )
        elif not resolve_api_key(provider):
            raise CodingCredentialUnavailableError(
                row.executor,
                provider_id,
                "provider_key_missing",
                "引用的模型供应商未配置 API Key",
            )
        return provider, entry, model_id

    async def _resolve_reference(self, row: CodingCredential, *, source: str) -> ResolvedCodingCredential:
        """解析引用凭据：密钥来自供应商或本行密文，渠道/模型来自供应商。"""
        provider, entry, model_id = await self._reference_context(row)
        key_mode = str(row.key_mode or "inherit")
        if key_mode == "custom":
            if not row.api_key_cipher:
                raise CodingCredentialUnavailableError(
                    row.executor, provider.provider_id, "credential_key_missing", "单独密钥缺失"
                )
            api_key = self.owner.decrypt(row)
        else:
            api_key = resolve_api_key(provider)
            if not api_key:
                raise CodingCredentialUnavailableError(
                    row.executor,
                    provider.provider_id,
                    "provider_key_missing",
                    "引用的模型供应商未配置 API Key",
                )
        base_url = _provider_base_url(provider, entry)
        return ResolvedCodingCredential(
            executor=row.executor,
            provider=provider.provider_id,
            base_url=base_url,
            model=model_id,
            api_key=api_key,
            extra={},
            fingerprint=credential_fingerprint(
                executor=row.executor,
                provider=provider.provider_id,
                base_url=base_url,
                model=model_id,
                secret_version=int(row.version or 0),
                extra={"source": "model_provider", "key_mode": key_mode},
                key_hash=key_fingerprint(api_key),
            ),
            source=source,
            mode="model_provider",
            model_provider_id=provider.provider_id,
            key_mode=key_mode,
        )

    async def list_masked(self, *, scope: str, uid: str | None = None) -> list[dict]:
        rows = await self.repo.list_active(scope=scope, uid=uid)
        views: list[dict] = []
        for row in rows:
            if str(row.source or "manual") != "model_provider":
                views.append(mask_credential(row))
                continue
            try:
                provider, entry, model_id = await self._reference_context(row)
            except CodingCredentialUnavailableError as exc:
                provider = await get_model_provider_by_id(
                    self.db, str(row.model_provider_id or "")
                )
                views.append(
                    mask_credential(
                        row,
                        availability="unavailable",
                        unavailable_reason=exc.reason,
                        unavailable_detail=exc.detail,
                        provider_display_name=(
                            provider.display_name if provider is not None else None
                        ),
                    )
                )
                continue
            view = mask_credential(row, provider_display_name=provider.display_name)
            view["base_url"] = _provider_base_url(provider, entry)
            view["model"] = model_id
            views.append(view)
        return views

    async def resolve(
        self,
        *,
        uid: str,
        executor: str,
        provider: str | None = None,
    ) -> ResolvedCodingCredential:
        """按「用户级 > 管理端全局」解析凭据；同层取最近更新的一条。"""
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
            row = max(
                candidates,
                key=lambda item: (
                    item.updated_at or datetime.min,
                    item.created_at or datetime.min,
                    item.id or "",
                ),
            )
            if str(row.source or "manual") == "model_provider":
                return await self._resolve_reference(row, source=source)
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
                mode="manual",
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

    async def list_model_provider_options(self) -> list[dict]:
        """用户可见的供应商选择器：只返回掩码信息与 chat 模型。"""
        providers = await get_all_model_providers(self.db)
        options: list[dict] = []
        for provider in providers:
            models = [
                {
                    "id": model_id,
                    "display_name": str(entry.get("display_name") or model_id),
                }
                for model_id, entry in _chat_model_entries(provider).items()
            ]
            options.append(
                {
                    "provider_id": provider.provider_id,
                    "display_name": provider.display_name,
                    "base_url": provider.base_url,
                    "is_enabled": bool(provider.is_enabled),
                    "credential_status": check_credential_status(provider),
                    "models": models,
                }
            )
        return options

    async def resolve_settings(
        self,
        *,
        agent_config: dict | None,
        agent_slug: str,
        project_id: str | None,
    ) -> CodingSettings:
        """合并 Agent 默认与项目覆盖，得到执行器白名单与默认执行器。"""
        merged: dict = {}
        agent_block = (agent_config or {}).get("coding")
        if isinstance(agent_block, dict):
            merged.update(agent_block)
        if project_id:
            binding = await ProjectAgentRepository(self.db).get(str(project_id), agent_slug)
            if binding is not None:
                override = (binding.config_overrides or {}).get("coding")
                if isinstance(override, dict):
                    merged.update(override)
        raw_executors = merged.get("executors")
        executors: list[str] = []
        if isinstance(raw_executors, list):
            for item in raw_executors:
                candidate = str(item).strip().lower()
                if candidate in VALID_EXECUTORS and candidate not in executors:
                    executors.append(candidate)
        default_executor = str(merged.get("default_executor") or "").strip().lower() or None
        if default_executor not in executors:
            default_executor = None
        return CodingSettings(executors=tuple(executors), default_executor=default_executor)

    async def build_coding_environment(
        self,
        *,
        uid: str,
        executors: list[str],
    ) -> CodingEnvironment:
        """解析执行器白名单，返回 env、聚合指纹与不可用/缺失分类。"""
        env: dict[str, str] = {}
        fingerprints: list[str] = []
        unavailable: list[dict] = []
        missing: list[str] = []
        for executor in executors:
            try:
                resolved = await self.resolve(uid=uid, executor=executor)
            except CodingCredentialMissingError:
                missing.append(executor)
                continue
            except CodingCredentialUnavailableError as exc:
                unavailable.append(
                    {
                        "executor": exc.executor,
                        "provider_id": exc.provider_id,
                        "reason": exc.reason,
                        "detail": exc.detail,
                    }
                )
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
        fingerprint = (
            hashlib.sha256("|".join(sorted(fingerprints)).encode("utf-8")).hexdigest()[:64]
            if fingerprints
            else None
        )
        return CodingEnvironment(
            env=env,
            fingerprint=fingerprint,
            unavailable=tuple(unavailable),
            missing=tuple(missing),
        )

    async def ensure_executor_available(self, *, uid: str, executor: str) -> None:
        """工具调用前的执行器可用性校验：缺失或引用不可用时显式失败。"""
        environment = await self.build_coding_environment(uid=uid, executors=[executor])
        environment.require_executor(executor)

    @staticmethod
    def redact(text: str, secrets: list[str]) -> str:
        """执行输出写库/发流前的值级脱敏入口。"""
        return redact_credential_values(text, secrets)
