"""统一可委派执行者接口与委派值对象（yuanlei 域）。

MVP 只覆盖委派、查询、回收三件事：句柄绑定具体委派操作 `operation_id` 与
`session_id` / `turn_id`，不承诺 `cancel` / `resume` / `streaming`。能力差异由
`capabilities()` 显式声明，缺失时结构化失败，不静默降级。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DISPATCH_STATES = ("pending", "dispatched", "collecting", "reclaimed", "failed")
TERMINAL_DISPATCH_STATES = ("reclaimed", "failed")


class DelegationError(RuntimeError):
    """委派编排的结构化失败基类。"""

    error_code = "delegation_error"

    def __init__(self, message: str, *, error_code: str | None = None):
        super().__init__(message)
        if error_code:
            self.error_code = error_code


class ExecutorUnavailableError(DelegationError):
    """执行器未注册或未配置，禁止静默换基底。"""

    error_code = "executor_unavailable"


class ChannelUnavailableError(DelegationError):
    """渠道凭据缺失或不可用。"""

    error_code = "channel_unavailable"


class DelegationNotFoundError(DelegationError):
    """委派操作不存在或不属于当前 Project。"""

    error_code = "delegation_not_found"


class DelegationLeaseLostError(DelegationError):
    """投递/回收租约已被其他 owner 持有或过期，当前写者不得推进。"""

    error_code = "delegation_lease_lost"


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """一次委派的输入；metadata 承载执行器专属引导数据，不外泄给远端。"""

    operation_id: str
    project_id: str
    task: str
    initiator_run_id: str | None = None
    context_refs: tuple[dict[str, Any], ...] = ()
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DelegationHandle:
    """委派句柄：绑定具体委派操作与（沙盒场景的）session/turn。"""

    operation_id: str
    executor_key: str
    session_id: str | None = None
    turn_id: str | None = None
    external_ref: str | None = None
    external_url: str | None = None
    remote_status: str | None = None


@dataclass(frozen=True, slots=True)
class DelegationResult:
    """回收结果：归一化摘要、产物引用、用量与错误码。"""

    summary: str | None = None
    text: str | None = None
    artifacts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    remote_status: str | None = None
    error_code: str | None = None


@runtime_checkable
class DelegatedExecutor(Protocol):
    """可委派执行者的窄接口；实现不得声明没有消费者的能力。"""

    key: str

    def capabilities(self) -> dict[str, bool]:
        """声明能力：multi_turn（稳定多轮续接入口）、remote_artifacts（产物仅远端 URL）。"""
        ...

    async def dispatch(self, request: DelegationRequest) -> DelegationHandle:
        """投递意图已在元垒侧持久化后调用；返回绑定本操作的句柄。"""
        ...

    async def status(self, handle: DelegationHandle) -> str | None:
        """返回远端执行状态的只读投影；不拥有远端终态。"""
        ...

    async def collect(self, handle: DelegationHandle) -> DelegationResult:
        """回收被委派操作的归一化结果。"""
        ...
