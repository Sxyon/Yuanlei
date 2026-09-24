from __future__ import annotations

import pytest

from yuxi.agents.backends.sandbox.policy import (
    merge_sandbox_config,
    parse_sandbox_policy,
    resolve_sandbox_policy,
)

pytestmark = [pytest.mark.unit]


def test_default_policy_matches_current_thread_behavior():
    policy = parse_sandbox_policy(None)

    assert policy.mode == "shared"
    assert policy.lifecycle == "ephemeral"
    assert policy.resume_policy == "auto"
    assert policy.idle_suspend_seconds is None
    assert policy.is_dedicated is False


def test_dedicated_policy_parses_lifecycle_and_idle():
    policy = parse_sandbox_policy(
        {"mode": "dedicated", "lifecycle": "persistent", "idle_suspend_seconds": 1800}
    )

    assert policy.is_dedicated is True
    assert policy.lifecycle == "persistent"
    assert policy.idle_suspend_seconds == 1800
    assert policy.provisioner_idle_timeout == 1800


def test_resident_policy_never_reaps_container():
    policy = parse_sandbox_policy({"mode": "dedicated", "lifecycle": "resident"})

    assert policy.lifecycle == "resident"
    assert policy.provisioner_idle_timeout == 0


def test_shared_policy_forces_ephemeral_lifecycle():
    policy = parse_sandbox_policy({"mode": "shared", "lifecycle": "resident"})

    assert policy.lifecycle == "ephemeral"


def test_policy_rejects_invalid_values():
    with pytest.raises(ValueError, match="sandbox.mode"):
        parse_sandbox_policy({"mode": "pool"})
    with pytest.raises(ValueError, match="sandbox.lifecycle"):
        parse_sandbox_policy({"mode": "dedicated", "lifecycle": "forever"})
    with pytest.raises(ValueError, match="sandbox.resume_policy"):
        parse_sandbox_policy({"mode": "dedicated", "resume_policy": "later"})
    with pytest.raises(ValueError, match="idle_suspend_seconds"):
        parse_sandbox_policy({"mode": "dedicated", "idle_suspend_seconds": -1})
    with pytest.raises(ValueError, match="idle_suspend_seconds"):
        parse_sandbox_policy({"mode": "dedicated", "idle_suspend_seconds": True})


def test_project_override_wins_over_agent_default():
    merged = merge_sandbox_config(
        {"mode": "dedicated", "lifecycle": "persistent", "idle_suspend_seconds": 1800},
        {"lifecycle": "resident", "idle_suspend_seconds": 600},
    )
    policy = parse_sandbox_policy(merged)

    assert policy.mode == "dedicated"
    assert policy.lifecycle == "resident"
    assert policy.idle_suspend_seconds == 600


def test_resolve_sandbox_policy_merges_blocks():
    policy = resolve_sandbox_policy(
        agent_block={"mode": "dedicated", "lifecycle": "persistent", "resume_policy": "auto"},
        project_block={"resume_policy": "confirm"},
    )

    assert policy.mode == "dedicated"
    assert policy.lifecycle == "persistent"
    assert policy.resume_policy == "confirm"
