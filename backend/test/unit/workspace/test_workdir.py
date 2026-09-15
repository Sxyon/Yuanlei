from pathlib import Path

import pytest

from yuxi.workspace import filesystem as workspace_filesystem_module
from yuxi.workspace.workdir import Workdir


def test_open_existing_returns_workdir_capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workdir_path = "projects/11111111-1111-4111-8111-111111111111"
    workspace_root = tmp_path / "workspace"
    (workspace_root / workdir_path).mkdir(parents=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    workdir = Workdir.open_existing("user-1", workdir_path)

    assert workdir.relative_path == workdir_path
    assert workdir.root_path == f"/{workdir_path}"


def test_open_existing_rejects_missing_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    with pytest.raises(FileNotFoundError):
        Workdir.open_existing("user-1", "projects/11111111-1111-4111-8111-111111111111")


def test_open_existing_rejects_regular_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workdir_path = "projects/11111111-1111-4111-8111-111111111111"
    workspace_root = tmp_path / "workspace"
    (workspace_root / "projects").mkdir(parents=True)
    (workspace_root / workdir_path).write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    with pytest.raises(ValueError, match="existing directory"):
        Workdir.open_existing("user-1", workdir_path)


def test_open_existing_rejects_symlinked_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workdir_path = "projects/11111111-1111-4111-8111-111111111111"
    workspace_root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace_root / "projects").mkdir(parents=True)
    (workspace_root / workdir_path).symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    with pytest.raises(PermissionError, match="symlink"):
        Workdir.open_existing("user-1", workdir_path)


def test_project_workdir_delete_keeps_default_symlink_rejection(tmp_path: Path, monkeypatch) -> None:
    workdir_path = "projects/11111111-1111-4111-8111-111111111111"
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / workdir_path
    target = tmp_path / "outside"
    project_root.mkdir(parents=True)
    target.mkdir()
    (project_root / "repository").mkdir()
    (project_root / "repository" / "linked").symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(workspace_filesystem_module, "user_workspace_dir", lambda _uid: workspace_root)

    workdir = Workdir.open_existing("user-1", workdir_path)

    with pytest.raises(PermissionError, match="symlink"):
        workdir.delete("/repository")

    assert (project_root / "repository").exists()
    assert target.exists()
