"""Run 执行 scope 解析：专属沙盒 scope key 存 yuanlei 映射。

上游 ck_agent_runs_nonterminal_shape 要求根 chat/resume run 的
runtime_scope_id 必须等于会话线程 id，因此专属沙盒的 agent-project
scope key 不能写回 agent_runs；统一通过本模块读写映射并回退。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.agent_run_scope_repository import AgentRunScopeRepository


async def resolve_run_scope_key(db: AsyncSession, run) -> str:
    """返回 Run 的执行 scope key；无映射时回退 runtime_scope_id / 会话线程。"""
    if run is None:
        return ""
    run_id = str(getattr(run, "id", "") or "")
    if run_id:
        mapped = await AgentRunScopeRepository(db).get(run_id)
        if mapped is not None and mapped.scope_key:
            return str(mapped.scope_key)
    return str(
        getattr(run, "runtime_scope_id", None)
        or getattr(run, "conversation_thread_id", "")
        or ""
    )


async def bind_run_scope(
    db: AsyncSession,
    *,
    run_id: str,
    scope_key: str,
    conversation_thread_id: str,
) -> None:
    """专属 scope 与线程 id 不同时才落映射；共享路径零写入。"""
    key = str(scope_key or "").strip()
    thread = str(conversation_thread_id or "").strip()
    if not key or key == thread:
        return
    await AgentRunScopeRepository(db).upsert(run_id=str(run_id), scope_key=key)


async def inherit_run_scope(
    db: AsyncSession,
    *,
    parent_run,
    child_run_id: str,
    child_conversation_thread_id: str,
) -> None:
    """Resume / SubAgent 继承父 Run 的执行 scope。"""
    key = await resolve_run_scope_key(db, parent_run)
    await bind_run_scope(
        db,
        run_id=child_run_id,
        scope_key=key,
        conversation_thread_id=child_conversation_thread_id,
    )


async def list_scope_run_ids(db: AsyncSession, *, scope_key: str) -> list[str]:
    """同一执行 scope 内已映射的 Run id，用于清理时的兄弟 Run 查询。"""
    return await AgentRunScopeRepository(db).list_run_ids(scope_key=str(scope_key))
