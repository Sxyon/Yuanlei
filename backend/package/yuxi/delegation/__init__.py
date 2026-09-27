"""外部执行器委派抽象：统一接口、沙盒与 Multica 适配器（yuanlei 域）。"""

from yuxi.delegation.contracts import (
    DISPATCH_STATES,
    TERMINAL_DISPATCH_STATES,
    ChannelUnavailableError,
    DelegatedExecutor,
    DelegationError,
    DelegationHandle,
    DelegationLeaseLostError,
    DelegationNotFoundError,
    DelegationRequest,
    DelegationResult,
    ExecutorUnavailableError,
)
from yuxi.delegation.multica import (
    MULTICA_EXECUTOR_KEY,
    MulticaClient,
    MulticaExecutor,
    MulticaIssue,
    build_multica_client_from_env,
    operation_marker,
)
from yuxi.delegation.sandbox import SandboxCodingExecutor

__all__ = [
    "DISPATCH_STATES",
    "TERMINAL_DISPATCH_STATES",
    "MULTICA_EXECUTOR_KEY",
    "ChannelUnavailableError",
    "DelegatedExecutor",
    "DelegationError",
    "DelegationHandle",
    "DelegationLeaseLostError",
    "DelegationNotFoundError",
    "DelegationRequest",
    "DelegationResult",
    "ExecutorUnavailableError",
    "MulticaClient",
    "MulticaExecutor",
    "MulticaIssue",
    "SandboxCodingExecutor",
    "build_multica_client_from_env",
    "operation_marker",
]
