from __future__ import annotations

import json

import pytest

from yuxi.coding.adapters import (
    CodexAdapter,
    CodingTurnRequest,
    OpenCodeAdapter,
    extract_turn_result,
    get_coding_adapter,
)

pytestmark = [pytest.mark.unit]

OPENCODE_OUTPUT = "\n".join(
    [
        json.dumps(
            {
                "type": "step_start",
                "sessionID": "ses_abc",
                "part": {"type": "step-start", "sessionID": "ses_abc"},
            }
        ),
        json.dumps(
            {
                "type": "text",
                "sessionID": "ses_abc",
                "part": {"type": "text", "text": "PONG"},
            }
        ),
        json.dumps(
            {
                "type": "step_finish",
                "sessionID": "ses_abc",
                "part": {
                    "type": "step-finish",
                    "reason": "stop",
                    "tokens": {"total": 12, "input": 10, "output": 2},
                    "cost": 0,
                },
            }
        ),
    ]
)

CODEX_OUTPUT = "\n".join(
    [
        json.dumps({"type": "thread.started", "thread_id": "01a0-thread"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": "PONG"},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        ),
    ]
)


def test_opencode_command_builds_plan_and_session_variants():
    adapter = OpenCodeAdapter()

    fresh = adapter.build_command(CodingTurnRequest(prompt="do it"))
    planned = adapter.build_command(
        CodingTurnRequest(
            prompt="plan it",
            plan_only=True,
            model="sf/deepseek",
            session_ref="ses_abc",
            workdir="/home/gem/user-data/projects/demo",
        )
    )

    assert fresh == "opencode run --format json 'do it'"
    assert planned.startswith("cd /home/gem/user-data/projects/demo && ")
    assert "--agent plan" in planned
    assert "-m sf/deepseek" in planned
    assert "-s ses_abc" in planned


def test_opencode_parse_and_extract_result():
    events = OpenCodeAdapter().parse_events(OPENCODE_OUTPUT)
    result = extract_turn_result(events)

    assert [event.kind for event in events] == ["session_ref", "output_delta", "usage"]
    assert result.output_text == "PONG"
    assert result.session_ref == "ses_abc"
    assert result.usage["tokens"]["total"] == 12
    assert result.error is None


def test_opencode_unknown_event_becomes_warning():
    events = OpenCodeAdapter().parse_events('{"type":"mystery","sessionID":"ses_x"}')

    assert events == [
        type(events[0])("warning", {"message": "unknown opencode event type: mystery"})
    ]


def test_codex_command_builds_read_only_plan_and_resume():
    adapter = CodexAdapter()

    plan = adapter.build_command(CodingTurnRequest(prompt="plan", plan_only=True))
    resume = adapter.build_command(
        CodingTurnRequest(prompt="continue", session_ref="01a0-thread", model="deepseek-flash")
    )

    assert plan == "codex exec --json --skip-git-repo-check -s read-only plan"
    assert resume == "codex exec resume 01a0-thread --json --skip-git-repo-check continue"


def test_codex_parse_and_extract_result():
    events = CodexAdapter().parse_events(CODEX_OUTPUT)
    result = extract_turn_result(events)

    assert [event.kind for event in events] == ["session_ref", "output_delta", "usage"]
    assert result.output_text == "PONG"
    assert result.session_ref == "01a0-thread"
    assert result.usage["usage"]["input_tokens"] == 10


def test_codex_failure_events_surface_error():
    output = "\n".join(
        [
            '{"type":"thread.started","thread_id":"t1"}',
            '{"type":"turn.failed","error":{"message":"stream disconnected"}}',
        ]
    )
    result = extract_turn_result(CodexAdapter().parse_events(output))

    assert result.error == "stream disconnected"


def test_get_coding_adapter_rejects_unknown_executor():
    assert get_coding_adapter("OpenCode").executor == "opencode"

    with pytest.raises(ValueError, match="unsupported coding executor"):
        get_coding_adapter("aider")
