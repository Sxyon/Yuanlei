"""真实 Docker、proxy generation 与文件回读证明 Git 写权限边界。"""

import os
import shutil
import uuid

import httpx
import pytest

from yuxi.agents.backends.sandbox.git_mounts import git_mount_fingerprint
from yuxi.agents.backends.sandbox.provisioner_client import ProvisionerClient
from yuxi.agents.backends.sandbox.provider import sandbox_provisioner_token
from yuxi.config import get_skill_projection_dir
from yuxi.workspace.paths import ensure_user_workspace, user_workspace_dir, workspace_uid_dirname

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_readonly_resource_cross_mount_link_and_revoked_generation():
    """未选择目录及另一项目只读，授权目录可写，旧请求不能进入新容器。"""
    from agent_sandbox import Sandbox

    uid = f"git-mount-e2e-{uuid.uuid4().hex[:12]}"
    sandbox_id = uuid.uuid4().hex[:12]
    token = sandbox_provisioner_token()
    provisioner = ProvisionerClient(os.environ["SANDBOX_PROVISIONER_URL"], token=token)
    ensure_user_workspace(uid)
    workspace = user_workspace_dir(uid)
    projection = get_skill_projection_dir() / workspace_uid_dirname(uid)
    projection.mkdir(parents=True)
    selected = workspace / "projects/first/selected"
    unselected = workspace / "projects/first/unselected"
    other_project = workspace / "projects/second/resource"
    for path in (selected, unselected, other_project):
        path.mkdir(parents=True)
        (path / "result.txt").write_text("initial\n")
    mounts = [
        {"path": "projects/first/selected", "read_only": False},
        {"path": "projects/first/unselected", "read_only": True},
        {"path": "projects/second/resource", "read_only": True},
    ]
    record = None
    try:
        record = provisioner.create(
            sandbox_id, "git-evidence-thread", workspace_uid_dirname(uid),
            workdir_path="projects/first", git_mounts=mounts,
        )
        assert record.git_mount_fingerprint == git_mount_fingerprint(mounts)
        headers = {"Authorization": f"Bearer {token}", "X-Yuanlei-Sandbox-Generation": record.generation}
        client = Sandbox(base_url=record.sandbox_url, headers=headers, timeout=30)
        prefix = "/home/gem/user-data"
        write = client.shell.exec_command(command=f"printf 'approved\\n' > {prefix}/projects/first/selected/result.txt")
        assert write.data.exit_code == 0, write.data.output
        assert (selected / "result.txt").read_text() == "approved\n"
        for path in ("projects/first/unselected", "projects/second/resource"):
            refused = client.shell.exec_command(command=f"printf 'bypass\\n' > {prefix}/{path}/result.txt")
            assert refused.data.exit_code != 0, refused.data.output
        assert (unselected / "result.txt").read_text() == "initial\n"
        assert (other_project / "result.txt").read_text() == "initial\n"
        hardlink = client.shell.exec_command(
            command=f"ln {prefix}/projects/first/selected/result.txt {prefix}/escaped-result.txt"
        )
        assert hardlink.data.exit_code != 0, hardlink.data.output
        assert not (workspace / "escaped-result.txt").exists()
        missing_generation = httpx.get(record.sandbox_url + "/v1/sandbox", headers={"Authorization": f"Bearer {token}"})
        assert missing_generation.status_code == 409
        old_generation = record.generation
        provisioner.delete(sandbox_id, expected_generation=old_generation)
        assert provisioner.discover(sandbox_id) is None
        readonly_mounts = [{**mount, "read_only": True} for mount in mounts]
        record = provisioner.create(
            sandbox_id, "git-evidence-thread", workspace_uid_dirname(uid),
            workdir_path="projects/first", git_mounts=readonly_mounts,
        )
        assert record.generation != old_generation
        stale = httpx.get(record.sandbox_url + "/v1/sandbox", headers=headers)
        assert stale.status_code == 409
        new_client = Sandbox(
            base_url=record.sandbox_url,
            headers={**headers, "X-Yuanlei-Sandbox-Generation": record.generation}, timeout=30,
        )
        refused = new_client.shell.exec_command(command=f"printf 'late\\n' > {prefix}/projects/first/selected/result.txt")
        assert refused.data.exit_code != 0
        assert (selected / "result.txt").read_text() == "approved\n"
    finally:
        if record is not None:
            provisioner.delete(sandbox_id, expected_generation=record.generation)
        shutil.rmtree(workspace.parent)
        shutil.rmtree(projection)
