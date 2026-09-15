import pytest

from yuxi.services.task_registry import get_failure_task_definition


def test_failure_hook_fallback_is_limited_to_migrated_legacy_version() -> None:
    assert get_failure_task_definition("knowledge_parse", 0).version == 1

    with pytest.raises(ValueError, match="Unsupported handler version"):
        get_failure_task_definition("knowledge_parse", 2)
