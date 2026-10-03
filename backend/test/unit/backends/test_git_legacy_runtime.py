"""历史全目录 RW 沙盒必须在保护扫描前撤销。"""

from types import SimpleNamespace

import pytest

from yuxi.agents.backends.sandbox.provider import ProvisionerSandboxProvider
from yuxi.workspace.paths import workspace_uid_dirname


@pytest.mark.parametrize("active", [True, False])
def test_legacy_runtime_is_retained_for_active_run_and_revoked_before_protection(active):
    legacy = SimpleNamespace(
        uid=workspace_uid_dirname("owner"),
        sandbox_id="old",
        generation="old-generation",
        git_mount_fingerprint=None,
    )
    protected = SimpleNamespace(
        uid=workspace_uid_dirname("owner"),
        sandbox_id="protected",
        generation="new-generation",
        git_mount_fingerprint="protected-profile",
    )
    records = {record.sandbox_id: record for record in (legacy, protected)}

    def delete(sandbox_id, *, expected_generation):
        assert records[sandbox_id].generation == expected_generation
        del records[sandbox_id]

    class Connection:
        def execute(self, query, parameters):
            assert "agent_runs" in query
            assert parameters == ("owner",)
            return SimpleNamespace(fetchone=lambda: (active,))

    provider = ProvisionerSandboxProvider.__new__(ProvisionerSandboxProvider)
    provider._client = SimpleNamespace(
        list=lambda: list(records.values()),
        delete=delete,
        discover=lambda sandbox_id: records.get(sandbox_id),
    )
    provider._connections = {}
    if active:
        with pytest.raises(RuntimeError, match="结束运行"):
            provider.revoke_legacy_git_runtimes(uid="owner", connection=Connection())
        assert set(records) == {"old", "protected"}
    else:
        provider.revoke_legacy_git_runtimes(uid="owner", connection=Connection())
        assert set(records) == {"protected"}


def test_legacy_runtime_still_discovered_blocks_protection():
    legacy = SimpleNamespace(
        uid=workspace_uid_dirname("owner"),
        sandbox_id="old",
        generation="old-generation",
        git_mount_fingerprint=None,
    )
    provider = ProvisionerSandboxProvider.__new__(ProvisionerSandboxProvider)
    provider._client = SimpleNamespace(
        list=lambda: [legacy],
        delete=lambda *_args, **_kwargs: None,
        discover=lambda _id: legacy,
    )
    provider._connections = {}
    connection = SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchone=lambda: (False,)))
    with pytest.raises(RuntimeError, match="撤销未完成"):
        provider.revoke_legacy_git_runtimes(uid="owner", connection=connection)
