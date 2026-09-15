from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from yuxi.workspace import paths


@pytest.mark.parametrize(
    "value",
    [
        "projects/11111111-1111-4111-8111-111111111111",
        "projects/2026-09-02_14-35-08_a1b2c3d4",
        "projects/2026-09-02_14-35-08_a1b2c3d4-2",
    ],
)
def test_normalize_managed_workdir_path_accepts_legacy_and_timestamped_names(value: str):
    assert paths.normalize_managed_workdir_path(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "projects/2026-02-30_14-35-08_a1b2c3d4",
        "projects/2026-09-02_24-00-00_a1b2c3d4",
        "projects/2026-09-02_14-35-08_A1B2C3D4",
        "projects/2026-09-02_14-35-08_a1b2c3d4-0",
        "projects/2026-09-02_14-35-08_a1b2c3d",
    ],
)
def test_normalize_managed_workdir_path_rejects_noncanonical_timestamped_names(value: str):
    with pytest.raises(ValueError, match="supported projects/<managed-id>"):
        paths.normalize_managed_workdir_path(value)


def test_allocate_default_user_workdir_path_uses_shanghai_time_and_project_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)

    result = paths.allocate_default_user_workdir_path(
        "user-1",
        "a1b2c3d4-e5f6-4789-8123-456789abcdef",
        allocated_at=datetime.fromisoformat("2026-09-02T06:35:08+00:00"),
    )

    assert result == "projects/2026-09-02_14-35-08_a1b2c3d4"


def test_allocate_default_user_workdir_path_appends_first_available_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(paths, "get_user_data_dir", lambda: tmp_path)
    paths.ensure_user_workspace("user-1")
    projects = paths.user_workspace_dir("user-1") / "projects"
    projects.mkdir()
    stem = "2026-09-02_14-35-08_a1b2c3d4"
    (projects / stem).mkdir()
    (projects / f"{stem}-1").mkdir()
    (projects / f"{stem}-2").write_text("occupied", encoding="utf-8")

    result = paths.allocate_default_user_workdir_path(
        "user-1",
        UUID("a1b2c3d4-e5f6-4789-8123-456789abcdef"),
        allocated_at=datetime.fromisoformat("2026-09-02T14:35:08+08:00"),
    )

    assert result == "projects/2026-09-02_14-35-08_a1b2c3d4-3"
