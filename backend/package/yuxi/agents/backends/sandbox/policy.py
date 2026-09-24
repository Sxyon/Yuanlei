"""Agent 专属沙盒生命周期策略的解析与项目覆盖合并。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SandboxMode = Literal["shared", "dedicated"]
SandboxLifecycle = Literal["ephemeral", "persistent", "resident"]
SandboxResumePolicy = Literal["auto", "confirm"]

_SANDBOX_MODES = frozenset({"shared", "dedicated"})
_SANDBOX_LIFECYCLES = frozenset({"ephemeral", "persistent", "resident"})
_SANDBOX_RESUME_POLICIES = frozenset({"auto", "confirm"})


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """一次运行生效的沙盒策略；默认与现状一致（线程级 ephemeral）。"""

    mode: SandboxMode = "shared"
    lifecycle: SandboxLifecycle = "ephemeral"
    resume_policy: SandboxResumePolicy = "auto"
    idle_suspend_seconds: int | None = None

    @property
    def is_dedicated(self) -> bool:
        return self.mode == "dedicated"

    @property
    def provisioner_idle_timeout(self) -> int | None:
        """传给 provisioner 的空闲阈值：resident 永不回收，其余按配置。"""
        if self.lifecycle == "resident":
            return 0
        return self.idle_suspend_seconds


def merge_sandbox_config(agent_block: Any, project_block: Any) -> dict:
    """浅合并 sandbox 配置块：项目覆盖层按 key 覆盖 agent 默认。"""
    merged = dict(agent_block) if isinstance(agent_block, dict) else {}
    if isinstance(project_block, dict):
        merged.update(project_block)
    return merged


def parse_sandbox_policy(raw: dict | None) -> SandboxPolicy:
    """把配置块规范化为 SandboxPolicy；非法值在边界显式失败。"""
    block = raw or {}
    mode = _normalize_choice(block.get("mode"), _SANDBOX_MODES, "sandbox.mode", "shared")
    lifecycle = _normalize_choice(
        block.get("lifecycle"), _SANDBOX_LIFECYCLES, "sandbox.lifecycle", "ephemeral"
    )
    if mode == "shared":
        lifecycle = "ephemeral"
    resume_policy = _normalize_choice(
        block.get("resume_policy"), _SANDBOX_RESUME_POLICIES, "sandbox.resume_policy", "auto"
    )
    idle_suspend_seconds = block.get("idle_suspend_seconds")
    if idle_suspend_seconds is not None:
        if isinstance(idle_suspend_seconds, bool) or not isinstance(idle_suspend_seconds, int):
            raise ValueError("sandbox.idle_suspend_seconds must be a non-negative integer")
        if idle_suspend_seconds < 0:
            raise ValueError("sandbox.idle_suspend_seconds must be a non-negative integer")
    return SandboxPolicy(
        mode=mode,
        lifecycle=lifecycle,
        resume_policy=resume_policy,
        idle_suspend_seconds=idle_suspend_seconds,
    )


def resolve_sandbox_policy(*, agent_block: Any, project_block: Any = None) -> SandboxPolicy:
    """合并 agent 默认与项目覆盖后解析策略。"""
    return parse_sandbox_policy(merge_sandbox_config(agent_block, project_block))


def _normalize_choice(value: Any, allowed: frozenset[str], label: str, default: str) -> Any:
    if value is None:
        return default
    candidate = value.strip().lower() if isinstance(value, str) else value
    if candidate not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}, got {value!r}")
    return candidate
