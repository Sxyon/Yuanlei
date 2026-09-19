from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yuxi.agents.toolkits.buildin.coding_tools import _ensure_declared_executor
from yuxi.services.coding_credential_service import (
    CodingCredentialService,
    CodingCredentialWrite,
)
from yuxi.services.coding_execution_service import (
    CodingBudgetExceededError,
    CodingExecutionService,
    CodingScopeUnsupportedError,
)
from yuxi.services.coding_session_service import CodingSessionStateError
from yuxi.storage.postgres.models_business import Base

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]

SCOPE_KEY = "agent-project:user-1:coder:project-1"
WORKDIR = "projects/11111111-1111-4111-8111-111111111111"
MASTER_KEY = base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("=")

OPENCODE_OUTPUT = "\n".join(
    [
        json.dumps({"type": "step_start", "sessionID": "ses_1", "part": {"sessionID": "ses_1"}}),
        json.dumps({"type": "text", "sessionID": "ses_1", "part": {"text": "PONG"}}),
        json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_1",
                "part": {"tokens": {"total": 5}, "reason": "stop"},
            }
        ),
    ]
)

FAILED_OUTPUT = json.dumps({"type": "error", "error": {"data": {"message": "Invalid API key."}}})


class _FakeProvider:
    def __init__(self):
        self.connections: dict[str, object] = {}
        self.create_calls: list[dict] = []
        self.release_calls: list[str] = []
        self.records: list[object] = []

    def get_scope(
        self,
        scope,
        *,
        create_if_missing=False,
        inherit_env=True,
        workdir_path=None,
        lifecycle=None,
        idle_timeout_seconds=None,
        env_overrides=None,
    ):
        if scope.cache_key in self.connections:
            return self.connections[scope.cache_key]
        if not create_if_missing:
            return None
        self.create_calls.append(
            {"workdir_path": workdir_path, "env_overrides": env_overrides, "lifecycle": lifecycle}
        )
        connection = SimpleNamespace(
            cache_key=scope.cache_key,
            sandbox_id=scope.sandbox_id,
            generation=f"gen-{len(self.create_calls)}",
            workdir_path=workdir_path,
        )
        self.connections[scope.cache_key] = connection
        self.records.append(connection)
        return connection

    def release_scope(self, scope, **_kwargs):
        self.release_calls.append(scope.cache_key)
        self.connections.pop(scope.cache_key, None)

    def touch(self, _sandbox_id):
        return True

    def list_sandboxes(self):
        return self.records


class _FakeBackend:
    def __init__(self, output: str, *, state_present: bool = True):
        self.output = output
        self.state_present = state_present
        self.commands: list[str] = []

    def execute(self, command: str, timeout: int | None = None):
        self.commands.append(command)
        if command.startswith("test -d"):
            output = "__PRESENT__" if self.state_present else ""
            return SimpleNamespace(output=output, exit_code=0, truncated=False)
        return SimpleNamespace(output=self.output, exit_code=0, truncated=False)


@pytest_asyncio.fixture()
async def session(monkeypatch):
    monkeypatch.setenv("YUXI_CODING_CREDENTIAL_KEY", MASTER_KEY)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed_credential(session):
    await CodingCredentialService(session).upsert(
        scope="user",
        uid="user-1",
        payload=CodingCredentialWrite(
            executor="opencode", provider="sf", api_key="sk-secret"
        ),
        actor="user-1",
    )


AGENT_CONFIG = {"sandbox": {"mode": "dedicated"}, "coding": {"executors": ["opencode"]}}


def _service(session, backend, provider):
    return CodingExecutionService(
        session,
        uid="user-1",
        thread_id="thread-1",
        runtime_scope_id=SCOPE_KEY,
        workdir_relative_path=WORKDIR,
        backend=backend,
        provider=provider,
    )


async def test_start_plan_turn_persists_session_turn_and_events(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT)
    service = _service(session, backend, provider)

    outcome = await service.run_turn(
        executor="opencode",
        task="实现登录接口",
        plan_only=True,
        agent_config=AGENT_CONFIG,
    )

    assert outcome.status == "idle"
    assert outcome.output_text == "PONG"
    assert outcome.cli_session_ref == "ses_1"
    assert "--agent plan" in backend.commands[0]
    assert provider.create_calls[0]["env_overrides"]["OPENCODE_API_KEY"] == "sk-secret"
    status = await service.status(outcome.session_id)
    assert status["session"]["status"] == "idle"
    assert [turn["seq"] for turn in status["turns"]] == [1]
    kinds = [event["kind"] for event in status["events"]]
    assert "turn_started" in kinds
    assert "output_delta" in kinds
    assert "turn_finished" in kinds


async def test_send_continues_native_session(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT)
    service = _service(session, backend, provider)
    first = await service.run_turn(
        executor="opencode", task="计划", plan_only=True, agent_config=AGENT_CONFIG
    )

    second = await service.run_turn(
        executor="opencode",
        task="开始实现",
        plan_only=False,
        session_id=first.session_id,
        agent_config=AGENT_CONFIG,
    )

    assert second.turn_seq == 2
    assert any("-s ses_1" in command for command in backend.commands)
    assert "--agent plan" not in backend.commands[-1]
    status = await service.status(first.session_id)
    assert [turn["seq"] for turn in status["turns"]] == [1, 2]


async def test_executor_error_fails_session_explicitly(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(FAILED_OUTPUT)
    service = _service(session, backend, provider)

    outcome = await service.run_turn(
        executor="opencode", task="会失败", plan_only=False, agent_config=AGENT_CONFIG
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "executor_error"
    status = await service.status(outcome.session_id)
    assert status["session"]["status"] == "failed"


async def test_shared_scope_is_rejected(session):
    provider = _FakeProvider()
    with pytest.raises(CodingScopeUnsupportedError, match="dedicated"):
        CodingExecutionService(
            session,
            uid="user-1",
            thread_id="thread-1",
            runtime_scope_id="thread-1",
            workdir_relative_path=WORKDIR,
            provider=provider,
        )


async def test_cancel_session_is_idempotent_guarded(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    service = _service(session, _FakeBackend(OPENCODE_OUTPUT), provider)
    created = await service.run_turn(
        executor="opencode", task="取消我", plan_only=True, agent_config=AGENT_CONFIG
    )

    cancelled = await service.cancel(created.session_id)

    assert cancelled["status"] == "cancelled"
    with pytest.raises(CodingSessionStateError, match="terminal"):
        await service.cancel(created.session_id)


async def test_turn_command_persists_cli_state_under_workdir(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT)
    service = _service(session, backend, provider)

    await service.run_turn(
        executor="opencode", task="持久化状态", plan_only=True, agent_config=AGENT_CONFIG
    )

    command = backend.commands[0]
    assert "XDG_DATA_HOME=" in command
    assert "/home/gem/user-data/agents/coding/" in command
    assert "mkdir -p" in command


async def test_resume_degraded_when_cli_state_missing(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT, state_present=False)
    service = _service(session, backend, provider)
    first = await service.run_turn(
        executor="opencode", task="第一轮", plan_only=True, agent_config=AGENT_CONFIG
    )
    assert first.cli_session_ref == "ses_1"

    second = await service.run_turn(
        executor="opencode",
        task="续跑",
        plan_only=False,
        session_id=first.session_id,
        agent_config=AGENT_CONFIG,
    )

    assert second.resume_degraded is True
    assert "-s " not in backend.commands[-1]
    status = await service.status(first.session_id)
    kinds = [event["kind"] for event in status["events"]]
    assert "resume_degraded" in kinds


async def test_budget_exceeded_fails_session(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT)
    service = _service(session, backend, provider)
    first = await service.run_turn(
        executor="opencode",
        task="预算一轮",
        plan_only=True,
        agent_config=AGENT_CONFIG,
        budget={"max_turns": 1},
    )

    with pytest.raises(CodingBudgetExceededError, match="budget"):
        await service.run_turn(
            executor="opencode",
            task="第二轮",
            plan_only=False,
            session_id=first.session_id,
            agent_config=AGENT_CONFIG,
        )

    status = await service.status(first.session_id)
    assert status["session"]["status"] == "failed"
    assert status["session"]["error_code"] == "budget_exceeded"


async def test_terminate_cli_processes_issues_pkill(session):
    await _seed_credential(session)
    provider = _FakeProvider()
    backend = _FakeBackend(OPENCODE_OUTPUT)
    service = _service(session, backend, provider)

    await service.terminate_cli_processes()

    assert any("pkill -f 'opencode run'" in command for command in backend.commands)
    assert any("pkill -f 'codex exec'" in command for command in backend.commands)


async def test_ensure_declared_executor_requires_whitelist():
    assert _ensure_declared_executor(AGENT_CONFIG, "opencode") == "opencode"

    with pytest.raises(ValueError, match="not enabled"):
        _ensure_declared_executor(AGENT_CONFIG, "codex")
    with pytest.raises(ValueError, match="unsupported coding executor"):
        _ensure_declared_executor({"coding": {"executors": ["aider"]}}, "aider")
