from __future__ import annotations

import pytest

from yuxi.coding.terminal_ticket import (
    TerminalTicketError,
    TerminalTicketNotConfiguredError,
    decode_terminal_ticket,
    issue_terminal_ticket,
    verify_terminal_ticket,
)

SECRET = "unit-test-jwt-secret-for-terminal-tickets"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)


def test_terminal_ticket_roundtrip_and_binding():
    ticket = issue_terminal_ticket(uid="user-1", session_id="session-1", ttl_seconds=60, now=1000)

    payload = decode_terminal_ticket(ticket, now=1010)
    verify_terminal_ticket(ticket, uid="user-1", session_id="session-1", now=1010)

    assert payload["uid"] == "user-1"
    assert payload["sid"] == "session-1"


@pytest.mark.parametrize(
    ("uid", "session_id"),
    [("user-2", "session-1"), ("user-1", "session-2")],
)
def test_terminal_ticket_rejects_identity_mismatch(uid: str, session_id: str):
    ticket = issue_terminal_ticket(uid="user-1", session_id="session-1", now=1000)

    with pytest.raises(TerminalTicketError, match="does not match"):
        verify_terminal_ticket(ticket, uid=uid, session_id=session_id, now=1010)


def test_terminal_ticket_rejects_expiry_and_tampering():
    ticket = issue_terminal_ticket(uid="user-1", session_id="session-1", ttl_seconds=5, now=1000)

    with pytest.raises(TerminalTicketError, match="expired"):
        decode_terminal_ticket(ticket, now=1006)

    body, _, signature = ticket.partition(".")
    tampered = f"{body}.{signature[:-2]}xx"
    with pytest.raises(TerminalTicketError, match="invalid"):
        decode_terminal_ticket(tampered, now=1001)


def test_terminal_ticket_requires_signature_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(TerminalTicketNotConfiguredError):
        issue_terminal_ticket(uid="user-1", session_id="session-1")
