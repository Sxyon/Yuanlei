"""编码会话 HTTP 表面：列表、详情（事件回放）与事件尾随流。"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress

import websockets
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.agents.backends.sandbox import SandboxScope
from yuxi.coding.terminal_ticket import (
    DEFAULT_TICKET_TTL_SECONDS,
    TerminalTicketError,
    TerminalTicketNotConfiguredError,
    decode_terminal_ticket,
    issue_terminal_ticket,
)
from yuxi.services.coding_session_service import (
    SESSION_TERMINAL_STATUSES,
    CodingSessionService,
)
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import User

coding_sessions = APIRouter(prefix="/coding", tags=["coding-sessions"])

STREAM_POLL_SECONDS = 0.5


@coding_sessions.get("/sessions")
async def list_coding_sessions(
    conversation_id: int | None = None,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的编码会话摘要。"""
    return await CodingSessionService(db).list_sessions_for_uid(
        uid=str(current_user.uid), conversation_id=conversation_id
    )


@coding_sessions.get("/sessions/{session_id}")
async def get_coding_session(
    session_id: str,
    after_seq: int = Query(default=0, ge=0),
    event_limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取会话详情；after_seq 用于断线后的增量事件回放。"""
    detail = await CodingSessionService(db).session_detail(
        uid=str(current_user.uid),
        session_id=session_id,
        after_seq=after_seq,
        event_limit=event_limit,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="编码会话不存在")
    return detail


async def iter_coding_session_events(
    *,
    uid: str,
    session_id: str,
    after_seq: int = 0,
    session_factory=None,
    poll_seconds: float = STREAM_POLL_SECONDS,
):
    """尾随会话事件：轮询持久事件并在会话终态且追平后结束。"""
    factory = session_factory or pg_manager.get_async_session_context
    cursor = int(after_seq)
    while True:
        async with factory() as db:
            detail = await CodingSessionService(db).session_detail(
                uid=uid, session_id=session_id, after_seq=cursor, event_limit=200
            )
        if detail is None:
            yield f"event: coding_error\ndata: {json.dumps({'error_code': 'coding_session_not_found'})}\n\n"
            return
        for event in detail["events"]:
            cursor = max(cursor, int(event["seq"]))
            yield f"event: coding_event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        status = str(detail.get("status") or "")
        if status in SESSION_TERMINAL_STATUSES and not detail["events"]:
            yield f"event: coding_end\ndata: {json.dumps({'status': status})}\n\n"
            return
        if not detail["events"]:
            yield ": keep-alive\n\n"
        await asyncio.sleep(poll_seconds)


@coding_sessions.post("/sessions/{session_id}/terminal-ticket")
async def create_terminal_ticket(
    session_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """签发单次短 TTL 终端门票；浏览器凭票连接 WebSocket。"""
    detail = await CodingSessionService(db).session_detail(
        uid=str(current_user.uid), session_id=session_id, event_limit=1
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="编码会话不存在")
    try:
        ticket = issue_terminal_ticket(uid=str(current_user.uid), session_id=session_id)
    except TerminalTicketNotConfiguredError:
        raise HTTPException(status_code=503, detail="终端门票签名未配置") from None
    return {
        "ticket": ticket,
        "ws_path": f"/api/coding/sessions/{session_id}/terminal?ticket={ticket}",
        "expires_in": DEFAULT_TICKET_TTL_SECONDS,
    }


async def _set_terminal_attached(uid: str, session_id: str, attached: bool) -> None:
    """记录终端接管状态与事件；失败只告警不阻断终端。"""
    from yuxi.repositories.coding_session_repository import CodingSessionRepository

    async with pg_manager.get_async_session_context() as db:
        repo = CodingSessionRepository(db)
        session = await repo.get_for_update(session_id)
        if session is None or session.uid != str(uid):
            return
        policy = dict(session.policy_json or {})
        policy["terminal_attached"] = bool(attached)
        session.policy_json = policy
        await repo.append_event(
            session,
            kind="terminal_attached" if attached else "terminal_detached",
            payload={},
        )
        await db.commit()


def _provisioner_ws_url(sandbox_id: str, query: str) -> str:
    base = (os.getenv("SANDBOX_PROVISIONER_URL") or "http://sandbox-provisioner:8002").strip().rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://") :]
    else:
        ws_base = "ws://" + base[len("http://") :]
    url = f"{ws_base}/api/sandboxes/{sandbox_id}/proxy/ws"
    return f"{url}?{query}" if query else url


def _connect_provisioner_ws(ws_url: str):
    token = os.getenv("SANDBOX_PROVISIONER_TOKEN") or ""
    headers = {"authorization": f"Bearer {token}"}
    try:
        return websockets.connect(
            ws_url, additional_headers=headers, open_timeout=10, max_size=8 * 1024 * 1024
        )
    except TypeError:
        return websockets.connect(
            ws_url, extra_headers=headers, open_timeout=10, max_size=8 * 1024 * 1024
        )


@coding_sessions.websocket("/sessions/{session_id}/terminal")
async def coding_session_terminal(websocket: WebSocket, session_id: str):
    """终端 WebSocket 中继：门票鉴权后转发到 provisioner WS 代理。"""
    ticket = websocket.query_params.get("ticket")
    try:
        payload = decode_terminal_ticket(ticket or "")
    except TerminalTicketError:
        await websocket.close(code=4401)
        return
    uid = str(payload.get("uid") or "")
    if str(payload.get("sid") or "") != session_id:
        await websocket.close(code=4401)
        return

    async with pg_manager.get_async_session_context() as db:
        detail = await CodingSessionService(db).session_detail(
            uid=uid, session_id=session_id, event_limit=1
        )
    if detail is None:
        await websocket.close(code=4404)
        return
    try:
        scope = SandboxScope.from_cache_key(str(detail.get("runtime_scope_id") or ""))
    except ValueError:
        await websocket.close(code=4409)
        return
    if scope.kind != "agent_project":
        await websocket.close(code=4409)
        return

    await websocket.accept()
    await _set_terminal_attached(uid, session_id, True)
    forwarded_query = "&".join(
        f"{key}={value}"
        for key, value in websocket.query_params.multi_items()
        if key != "ticket"
    )

    async def client_to_upstream(upstream) -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def upstream_to_client(upstream) -> None:
        async for incoming in upstream:
            if isinstance(incoming, (bytes, bytearray)):
                await websocket.send_bytes(bytes(incoming))
            else:
                await websocket.send_text(str(incoming))

    try:
        async with _connect_provisioner_ws(
            _provisioner_ws_url(scope.sandbox_id, forwarded_query)
        ) as upstream:
            tasks = {
                asyncio.create_task(client_to_upstream(upstream)),
                asyncio.create_task(upstream_to_client(upstream)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                with suppress(Exception):
                    task.result()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await _set_terminal_attached(uid, session_id, False)
        with suppress(Exception):
            await websocket.close()


@coding_sessions.get("/sessions/{session_id}/events/stream")
async def stream_coding_session_events(
    session_id: str,
    after_seq: int = Query(default=0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 尾随会话事件；断线用 after_seq 续读，终态后自动结束。"""
    exists = await CodingSessionService(db).session_detail(
        uid=str(current_user.uid), session_id=session_id, after_seq=0, event_limit=1
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="编码会话不存在")
    return StreamingResponse(
        iter_coding_session_events(
            uid=str(current_user.uid), session_id=session_id, after_seq=after_seq
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
