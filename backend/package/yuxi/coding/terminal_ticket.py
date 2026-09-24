"""编码会话终端的单次短 TTL 门票（HMAC 签名，不暴露 provisioner token）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

DEFAULT_TICKET_TTL_SECONDS = 60


class TerminalTicketError(RuntimeError):
    """门票无效、过期或与请求身份不匹配。"""


class TerminalTicketNotConfiguredError(TerminalTicketError):
    """签名密钥缺失。"""


def _secret() -> bytes:
    raw = os.getenv("JWT_SECRET_KEY", "").strip()
    if not raw:
        raise TerminalTicketNotConfiguredError("JWT_SECRET_KEY is required for terminal tickets")
    return raw.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_terminal_ticket(
    *,
    uid: str,
    session_id: str,
    ttl_seconds: int = DEFAULT_TICKET_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """签发单次门票；TTL 默认 60 秒。"""
    issued_at = time.time() if now is None else float(now)
    payload = {
        "uid": str(uid),
        "sid": str(session_id),
        "exp": int(issued_at + max(1, int(ttl_seconds))),
    }
    body = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64encode(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def decode_terminal_ticket(ticket: str, *, now: float | None = None) -> dict:
    """校验签名与有效期并返回载荷；失败抛 TerminalTicketError。"""
    raw = str(ticket or "").strip()
    if "." not in raw:
        raise TerminalTicketError("invalid terminal ticket")
    body, _, signature = raw.partition(".")
    expected = _b64encode(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise TerminalTicketError("invalid terminal ticket")
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TerminalTicketError("invalid terminal ticket") from exc
    if not isinstance(payload, dict):
        raise TerminalTicketError("invalid terminal ticket")
    current = time.time() if now is None else float(now)
    if int(payload.get("exp") or 0) < int(current):
        raise TerminalTicketError("terminal ticket expired")
    return payload


def verify_terminal_ticket(
    ticket: str,
    *,
    uid: str,
    session_id: str,
    now: float | None = None,
) -> None:
    """校验门票签名、有效期与身份绑定；失败抛 TerminalTicketError。"""
    payload = decode_terminal_ticket(ticket, now=now)
    if str(payload.get("uid") or "") != str(uid) or str(payload.get("sid") or "") != str(
        session_id
    ):
        raise TerminalTicketError("terminal ticket does not match session")
