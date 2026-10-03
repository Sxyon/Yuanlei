"""历史文件别名在启用资源保护时必须显式拒绝。"""

import os

import pytest

import yuxi.agents.backends.sandbox.git_mounts as mounts


def test_legacy_hardlink_is_rejected_without_deleting_user_content(monkeypatch, tmp_path):
    """普通工作区中的旧别名不能保留对只读资源 inode 的写能力。"""
    resource = tmp_path / "projects/first/resource"
    resource.mkdir(parents=True)
    original = resource / "result.txt"
    original.write_text("keep user data\n")
    alias = tmp_path / "outside-alias.txt"
    os.link(original, alias)
    monkeypatch.setattr(mounts, "user_workspace_dir", lambda _uid: tmp_path)
    profile = [{"path": "projects/first/resource", "read_only": True}]
    with pytest.raises(RuntimeError, match="历史硬链接"):
        mounts.verify_git_mount_aliases(uid="user", mounts=profile)
    assert original.read_text() == alias.read_text() == "keep user data\n"
    alias.unlink()
    mounts.verify_git_mount_aliases(uid="user", mounts=profile)


def test_symlink_scan_does_not_follow_external_directory(monkeypatch, tmp_path):
    """只检查资源 inode，不访问链接指向的外部文件。"""
    workspace = tmp_path / "workspace"
    resource = workspace / "resource"
    resource.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "private"
    original.write_text("external\n")
    os.link(original, outside / "alias")
    (resource / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(mounts, "user_workspace_dir", lambda _uid: workspace)
    mounts.verify_git_mount_aliases(uid="user", mounts=[{"path": "resource", "read_only": True}])
    assert original.read_text() == "external\n"
