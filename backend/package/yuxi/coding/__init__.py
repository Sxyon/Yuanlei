"""编码执行器（opencode/codex）域：凭据加密、指纹与脱敏原语。"""

from .credentials import (
    KEY_VERSION,
    VALID_EXECUTORS,
    CodingCredentialOwner,
    CodingNotConfiguredError,
    EncryptedCodingCredential,
    coding_executor_environment,
    credential_fingerprint,
    redact_credential_values,
)

__all__ = [
    "KEY_VERSION",
    "VALID_EXECUTORS",
    "CodingCredentialOwner",
    "CodingNotConfiguredError",
    "EncryptedCodingCredential",
    "coding_executor_environment",
    "credential_fingerprint",
    "redact_credential_values",
]
