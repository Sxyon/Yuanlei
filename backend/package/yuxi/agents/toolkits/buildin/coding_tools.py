"""编码执行器工具：在专属沙盒内驱动 opencode/codex 的 headless 会话。"""

from __future__ import annotations

import json

from langchain.tools import ToolRuntime
from pydantic import BaseModel, Field

from yuxi.agents.toolkits.registry import tool
from yuxi.coding.credentials import VALID_EXECUTORS
from yuxi.services.coding_credential_service import CodingCredentialService
from yuxi.services.coding_execution_service import (
    CodingExecutionService,
    CodingScopeUnsupportedError,
)
from yuxi.services.coding_session_service import CodingSessionStateError
from yuxi.services.run_queue_service import publish_coding_cancel_signal
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import AgentRun

CODING_EXECUTOR_DESCRIPTION = "编码执行器：opencode 或 codex"


class CodingStartInput(BaseModel):
    """启动编码会话的输入。"""

    executor: str | None = Field(
        default=None, description=f"{CODING_EXECUTOR_DESCRIPTION}；省略时使用项目默认执行器"
    )
    task: str = Field(min_length=1, description="交给编码执行器的任务描述")
    plan_first: bool = Field(default=True, description="是否先执行只读计划轮，再由后续消息推进实现")
    max_turns: int | None = Field(default=None, ge=1, le=50, description="可选：本会话最大轮数预算")
    wait: bool = Field(
        default=True,
        description="是否等待本轮完成；false 时后台执行（需要 persistent/resident 专属沙盒），用 coding_session_await 收割",
    )


class CodingSendInput(BaseModel):
    """会话内追加一轮输入。"""

    session_id: str = Field(description="编码会话 id")
    message: str = Field(min_length=1, description="追加给编码执行器的消息")
    wait: bool = Field(default=True, description="是否等待本轮完成；false 时后台执行")


class CodingStatusInput(BaseModel):
    """查询会话状态。"""

    session_id: str = Field(description="编码会话 id")


class CodingAwaitInput(BaseModel):
    """等待会话 turn 结束。"""

    session_id: str = Field(description="编码会话 id")
    timeout_seconds: int = Field(default=300, ge=1, le=3600, description="最长等待秒数")


class CodingControlInput(BaseModel):
    """控制会话。"""

    session_id: str = Field(description="编码会话 id")
    action: str = Field(description="支持的动作：cancel")


class CodingListInput(BaseModel):
    """列出当前用户的编码会话。"""

    conversation_id: int | None = Field(default=None, description="可选：限定 Conversation")


def _scope_inputs(runtime: ToolRuntime):
    context = runtime.context
    return {
        "uid": str(context.uid),
        "thread_id": str(context.thread_id),
        "runtime_scope_id": str(getattr(context, "runtime_scope_id", "") or context.thread_id),
        "workdir_relative_path": str(getattr(context, "workdir_relative_path", "") or ""),
    }


async def _load_coding_context(db, runtime: ToolRuntime):
    """加载本次运行的 Agent 配置与编码执行器设置（含项目覆盖）。"""
    run = await db.get(AgentRun, str(runtime.context.run_id))
    if run is None:
        raise ValueError("agent run not found for coding tool")
    from yuxi.repositories.agent_repository import AgentRepository
    from yuxi.storage.postgres.models_business import Conversation

    agent = await AgentRepository(db).get_by_slug(run.agent_slug)
    agent_config = agent.config_json if agent is not None else None
    conversation = (
        await db.get(Conversation, run.conversation_id) if run.conversation_id is not None else None
    )
    settings = await CodingCredentialService(db).resolve_settings(
        agent_config=agent_config,
        agent_slug=run.agent_slug,
        project_id=conversation.project_id if conversation is not None else None,
    )
    return agent_config, settings


def _select_executor(settings, executor: str | None) -> str:
    """按显式参数或项目默认选择执行器，未启用时显式失败。"""
    normalized = str(executor or "").strip().lower() or settings.default_executor
    if not normalized:
        raise ValueError("coding executor is required: no default executor configured")
    if normalized not in VALID_EXECUTORS:
        raise ValueError(f"unsupported coding executor: {executor!r}")
    if normalized not in settings.executors:
        raise ValueError(
            f"coding executor {normalized!r} is not enabled for this agent (coding.executors)"
        )
    return normalized


async def _ensure_executor_available(db, runtime: ToolRuntime, executor: str) -> None:
    """选中执行器必须已配置且引用可用，否则返回结构化不可用原因。"""
    await CodingCredentialService(db).ensure_executor_available(
        uid=str(runtime.context.uid), executor=executor
    )


async def _queue_turn(
    db,
    runtime: ToolRuntime,
    *,
    config: dict | None,
    executor: str,
    task: str,
    plan_only: bool,
    session_id: str | None = None,
    budget: dict | None = None,
) -> str:
    """异步模式：准备环境、入队 pending turn 并投递 worker，立即返回。"""
    from yuxi.repositories.coding_session_repository import CodingSessionRepository
    from yuxi.services.coding_execution_service import enqueue_coding_turn
    from yuxi.services.sandbox_lifecycle_service import resolve_agent_sandbox_policy

    service = await _build_service(db, runtime)
    policy = await resolve_agent_sandbox_policy(
        db=db,
        agent_config=config,
        agent_slug=service.scope.agent_slug or "",
        project_id=service.scope.project_id or "",
    )
    if not policy.is_dedicated or policy.lifecycle not in {"persistent", "resident"}:
        raise ValueError(
            "async coding turns require a persistent or resident dedicated sandbox policy"
        )
    await service.prepare(config)
    repo = CodingSessionRepository(db)
    if session_id:
        session = await repo.get_for_update(session_id)
        if session is None or session.uid != service.uid:
            raise ValueError("coding session not found")
        if session.status != "idle":
            raise CodingSessionStateError(f"coding session is not idle: {session.status}")
    else:
        session = await service.sessions.create_session(
            uid=service.uid,
            project_id=service.scope.project_id or "",
            runtime_scope_id=service.scope.cache_key,
            executor=executor,
            workdir_path=service.workdir_relative_path,
            title=task.strip()[:120] or None,
            policy={"executor": executor},
            budget=budget,
        )
    session.executor = executor
    turn = await service.sessions.queue_turn(session, request_text=task)
    await db.commit()
    await enqueue_coding_turn(session_id=session.id, turn_id=turn.id, plan_only=plan_only)
    return json.dumps(
        {
            "session_id": session.id,
            "turn_seq": turn.seq,
            "executor": executor,
            "status": "running",
            "queued": True,
        },
        ensure_ascii=False,
    )


def _error_payload(exc: Exception) -> str:
    code = getattr(exc, "error_code", None) or type(exc).__name__
    return json.dumps({"error_code": code, "message": str(exc)}, ensure_ascii=False)


def _emit_session_event(outcome) -> None:
    """把会话 turn 摘要投影到 Run SSE（custom: yuxi.coding_session_event）。"""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(
        {
            "status": "coding_session_event",
            "session_id": outcome.session_id,
            "turn_seq": outcome.turn_seq,
            "executor": outcome.executor,
            "state": outcome.status,
            "resume_degraded": outcome.resume_degraded,
            "output_preview": outcome.output_text[:400],
            "usage": outcome.usage or {},
            "error_code": outcome.error_code,
        }
    )


def _ensure_declared_executor(config: dict | None, executor: str) -> str:
    """兼容入口：仅按 Agent 配置校验执行器白名单。"""
    normalized = str(executor or "").strip().lower()
    if normalized not in VALID_EXECUTORS:
        raise ValueError(f"unsupported coding executor: {executor!r}")
    declared = CodingCredentialService.declared_executors(config)
    if normalized not in declared:
        raise ValueError(
            f"coding executor {normalized!r} is not enabled for this agent (coding.executors)"
        )
    return normalized


async def _build_service(db, runtime: ToolRuntime) -> CodingExecutionService:
    return CodingExecutionService(db, **_scope_inputs(runtime))


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="启动编码会话",
    icon="SquareTerminal",
    args_schema=CodingStartInput,
)
async def coding_session_start(
    task: str,
    executor: str | None = None,
    plan_first: bool = True,
    max_turns: int | None = None,
    wait: bool = True,
    runtime: ToolRuntime = None,
) -> str:
    """启动编码执行器会话并运行第一轮（默认只读计划轮）。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            config, settings = await _load_coding_context(db, runtime)
            normalized = _select_executor(settings, executor)
            await _ensure_executor_available(db, runtime, normalized)
            budget = {"max_turns": int(max_turns)} if max_turns else None
            if not wait:
                return await _queue_turn(
                    db,
                    runtime,
                    config=config,
                    executor=normalized,
                    task=task,
                    plan_only=bool(plan_first),
                    budget=budget,
                )
            service = await _build_service(db, runtime)
            outcome = await service.run_turn(
                executor=normalized,
                task=task,
                plan_only=bool(plan_first),
                agent_config=config,
                budget=budget,
            )
            _emit_session_event(outcome)
            return CodingExecutionService.summarize_for_tool(outcome)
    except (ValueError, CodingSessionStateError, CodingScopeUnsupportedError, RuntimeError) as exc:
        return _error_payload(exc)


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="编码会话下一轮",
    icon="SquareTerminal",
    args_schema=CodingSendInput,
)
async def coding_session_send(
    session_id: str,
    message: str,
    wait: bool = True,
    runtime: ToolRuntime = None,
) -> str:
    """在既有编码会话中追加一轮执行（执行轮）。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            config, settings = await _load_coding_context(db, runtime)
            service = await _build_service(db, runtime)
            status = await service.status(session_id)
            normalized = _select_executor(settings, status["session"]["executor"])
            await _ensure_executor_available(db, runtime, normalized)
            if not wait:
                return await _queue_turn(
                    db,
                    runtime,
                    config=config,
                    executor=normalized,
                    task=message,
                    plan_only=False,
                    session_id=session_id,
                )
            outcome = await service.run_turn(
                executor=normalized,
                task=message,
                plan_only=False,
                session_id=session_id,
                agent_config=config,
            )
            _emit_session_event(outcome)
            return CodingExecutionService.summarize_for_tool(outcome)
    except (ValueError, CodingSessionStateError, CodingScopeUnsupportedError, RuntimeError) as exc:
        return _error_payload(exc)


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="编码会话状态",
    icon="SquareTerminal",
    args_schema=CodingStatusInput,
)
async def coding_session_status(session_id: str, runtime: ToolRuntime = None) -> str:
    """查询编码会话的状态、turn 时间线与最近事件。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            service = await _build_service(db, runtime)
            return json.dumps(await service.status(session_id), ensure_ascii=False)
    except (ValueError, CodingScopeUnsupportedError, RuntimeError) as exc:
        return _error_payload(exc)


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="等待编码会话",
    icon="SquareTerminal",
    args_schema=CodingAwaitInput,
)
async def coding_session_await(
    session_id: str,
    timeout_seconds: int = 300,
    runtime: ToolRuntime = None,
) -> str:
    """等待最新 turn 进入终态或超时；用于异步 turn 的收割。"""
    from yuxi.services.coding_execution_service import wait_for_latest_turn

    try:
        result = await wait_for_latest_turn(
            uid=str(runtime.context.uid),
            session_id=session_id,
            timeout_seconds=float(timeout_seconds),
        )
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, RuntimeError) as exc:
        return _error_payload(exc)


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="控制编码会话",
    icon="SquareTerminal",
    args_schema=CodingControlInput,
)
async def coding_session_control(
    session_id: str,
    action: str,
    runtime: ToolRuntime = None,
) -> str:
    """控制编码会话；当前支持 cancel（取消未终结的会话）。"""
    if str(action or "").strip().lower() != "cancel":
        return _error_payload(ValueError(f"unsupported coding session action: {action!r}"))
    try:
        async with pg_manager.get_async_session_context() as db:
            service = await _build_service(db, runtime)
            status = await service.status(session_id)
            if status["session"]["status"] == "running":
                await publish_coding_cancel_signal(session_id)
                await service.terminate_cli_processes()
                return json.dumps(
                    {"session_id": session_id, "status": "cancel_requested"}, ensure_ascii=False
                )
            return json.dumps(await service.cancel(session_id), ensure_ascii=False)
    except (ValueError, CodingSessionStateError, CodingScopeUnsupportedError, RuntimeError) as exc:
        return _error_payload(exc)


@tool(
    category="coding",
    tags=["编码", "执行器"],
    display_name="编码会话列表",
    icon="SquareTerminal",
    args_schema=CodingListInput,
)
async def coding_session_list(
    conversation_id: int | None = None,
    runtime: ToolRuntime = None,
) -> str:
    """列出当前用户的编码会话，供选择继续或管理。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            service = await _build_service(db, runtime)
            return json.dumps(
                await service.list_sessions(conversation_id=conversation_id), ensure_ascii=False
            )
    except (ValueError, CodingScopeUnsupportedError, RuntimeError) as exc:
        return _error_payload(exc)


CODING_TOOLS = (
    coding_session_start,
    coding_session_send,
    coding_session_status,
    coding_session_await,
    coding_session_control,
    coding_session_list,
)