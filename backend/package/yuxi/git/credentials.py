"""Git 凭据的加密 Owner。"""

from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_VERSION = 1
VALID_PURPOSES = {"gitea_api_token", "deploy_private_key"}


class GitNotConfiguredError(RuntimeError):
    """Git master key 缺失或无效。"""


@dataclass(frozen=True)
class EncryptedGitCredential:
    """可持久化的密文载荷。"""

    id: str
    uid: str
    purpose: str
    ciphertext: bytes
    nonce: bytes
    key_version: int = KEY_VERSION


class GitCredentialOwner:
    """使用配置 master key 加解密 Git 凭据。"""

    def __init__(self, key: bytes | None = None):
        self._key = key if key is not None else _configured_key()
        if len(self._key) != 32:
            raise GitNotConfiguredError("YUXI_GIT_CREDENTIAL_KEY must decode to 32 bytes")

    def encrypt(
        self, *, uid: str, purpose: str, plaintext: str, credential_id: str | None = None
    ) -> EncryptedGitCredential:
        """加密一项凭据并绑定身份与用途。"""
        if purpose not in VALID_PURPOSES or not plaintext:
            raise ValueError("invalid Git credential")
        identifier = credential_id or str(uuid.uuid4())
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            plaintext.encode(),
            _aad(identifier, uid, purpose, KEY_VERSION),
        )
        return EncryptedGitCredential(identifier, str(uid), purpose, ciphertext, nonce)

    def decrypt(self, credential) -> str:
        """解密 active 凭据并验证 AAD。"""
        if credential.status != "active" or credential.key_version != KEY_VERSION:
            raise GitNotConfiguredError("Git credential is unavailable")
        value = AESGCM(self._key).decrypt(
            bytes(credential.nonce),
            bytes(credential.ciphertext),
            _aad(credential.id, credential.uid, credential.purpose, credential.key_version),
        )
        return value.decode()


def _configured_key() -> bytes:
    """解析 base64url master key，缺失时 fail-closed。"""
    raw = os.getenv("YUXI_GIT_CREDENTIAL_KEY", "").strip()
    if not raw:
        raise GitNotConfiguredError("Git credential encryption is not configured")
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise GitNotConfiguredError("YUXI_GIT_CREDENTIAL_KEY is invalid") from exc


def _aad(credential_id: str, uid: str, purpose: str, key_version: int) -> bytes:
    """构造稳定且无歧义的 AES-GCM AAD。"""
    return f"yuxi-git\0{credential_id}\0{uid}\0{purpose}\0{key_version}".encode()
