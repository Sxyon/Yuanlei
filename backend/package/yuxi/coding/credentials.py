"""编码执行器凭据的加密与指纹 Owner。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_VERSION = 1
VALID_EXECUTORS = {"opencode", "codex"}


class CodingNotConfiguredError(RuntimeError):
    """编码凭据 master key 缺失或无效。"""


@dataclass(frozen=True)
class EncryptedCodingCredential:
    """可持久化的编码凭据密文载荷。"""

    id: str
    scope: str
    uid: str
    executor: str
    provider: str
    ciphertext: bytes
    nonce: bytes
    key_version: int = KEY_VERSION


class CodingCredentialOwner:
    """使用配置 master key 加解密编码执行器凭据。"""

    def __init__(self, key: bytes | None = None):
        self._key = key if key is not None else _configured_key()
        if len(self._key) != 32:
            raise CodingNotConfiguredError("YUXI_CODING_CREDENTIAL_KEY must decode to 32 bytes")

    def encrypt(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
        plaintext: str,
        credential_id: str | None = None,
    ) -> EncryptedCodingCredential:
        """加密一项编码凭据并绑定身份、作用域与用途。"""
        if executor not in VALID_EXECUTORS or not plaintext:
            raise ValueError("invalid coding credential")
        identifier = credential_id or str(uuid.uuid4())
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext.encode(),
            _aad(identifier, scope, uid or "", executor, provider, KEY_VERSION),
        )
        return EncryptedCodingCredential(
            id=identifier,
            scope=str(scope),
            uid=str(uid or ""),
            executor=str(executor),
            provider=str(provider),
            ciphertext=ciphertext,
            nonce=nonce,
        )

    def decrypt(self, credential) -> str:
        """解密 active 凭据并验证 AAD。"""
        if credential.status != "active" or credential.key_version != KEY_VERSION:
            raise CodingNotConfiguredError("coding credential is unavailable")
        value = AESGCM(self._key).decrypt(
            bytes(credential.nonce),
            bytes(credential.api_key_cipher),
            _aad(
                credential.id,
                credential.scope,
                credential.uid or "",
                credential.executor,
                credential.provider,
                credential.key_version,
            ),
        )
        return value.decode()


def key_fingerprint(api_key: str) -> str:
    """密钥短哈希：只参与指纹计算，不可逆且不落库。"""
    return hashlib.sha256(str(api_key).encode("utf-8")).hexdigest()[:16]


def credential_fingerprint(
    *,
    executor: str,
    provider: str,
    base_url: str | None,
    model: str | None,
    secret_version: int,
    extra: dict | None = None,
    key_hash: str | None = None,
) -> str:
    """按冻结契约计算指纹：非密配置 + 密文版本 + 扩展 env 贡献。

    `key_hash` 只在引用模型供应商时提供，用于感知供应商密钥轮换；
    manual 模式不传以保持既有指纹不变（升级不触发存量沙盒重建）。
    """
    payload = {
        "executor": str(executor),
        "provider": str(provider),
        "base_url": base_url or "",
        "model": model or "",
        "secret_version": int(secret_version),
        "extra": extra or {},
    }
    if key_hash:
        payload["key_hash"] = str(key_hash)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:64]


def redact_credential_values(text: str, secrets: Iterable[str]) -> str:
    """按已知明文做值级脱敏；过短的串会被忽略以避免误伤普通文本。"""
    redacted = text or ""
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def coding_executor_environment(
    *,
    executor: str,
    provider: str,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    extra: dict | None = None,
) -> dict[str, str]:
    """把解析后的凭据映射为镜像原生 CLI 环境变量（M0 契约）。"""
    normalized = str(executor or "").strip().lower()
    extra = extra or {}
    if normalized == "opencode":
        env = {
            "OPENCODE_PROVIDER": str(provider),
            "OPENCODE_API_KEY": str(api_key),
            "OPENCODE_PROVIDER_NPM": str(
                extra.get("provider_npm") or "@ai-sdk/openai-compatible"
            ),
        }
        if base_url:
            env["OPENCODE_BASE_URL"] = str(base_url)
        if model:
            env["OPENCODE_MODEL"] = str(model)
        return env
    if normalized == "codex":
        env = {"CODEX_API_KEY": str(api_key)}
        if base_url:
            env["CODEX_BASE_URL"] = str(base_url)
        if model:
            env["CODEX_MODEL"] = str(model)
        if extra.get("config_toml"):
            env["CODEX_CONFIG_TOML"] = str(extra["config_toml"])
        return env
    raise ValueError(f"unsupported coding executor: {executor!r}")


def _configured_key() -> bytes:
    """解析 base64url master key，缺失时 fail-closed。"""
    raw = os.getenv("YUXI_CODING_CREDENTIAL_KEY", "").strip()
    if not raw:
        raise CodingNotConfiguredError("coding credential encryption is not configured")
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise CodingNotConfiguredError("YUXI_CODING_CREDENTIAL_KEY is invalid") from exc


def _aad(
    credential_id: str,
    scope: str,
    uid: str,
    executor: str,
    provider: str,
    key_version: int,
) -> bytes:
    """构造稳定且无歧义的 AES-GCM AAD。"""
    return (
        f"yuxi-coding\0{credential_id}\0{scope}\0{uid}\0{executor}\0{provider}\0{key_version}"
    ).encode()
