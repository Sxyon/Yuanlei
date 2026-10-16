"""选择校验只触达主题实际声明的文件边界。"""
from types import SimpleNamespace

import pytest

from yuxi.services.project_theme_service import ProjectThemeService, Workdir
from yuxi.themes.packages import ThemeError


def test_file_free_theme_does_not_require_workdir_but_rejects_extra_alias(monkeypatch):
    """无文件主题可用于未建目录项目，额外alias仍必须被拒绝。"""
    def unexpected_open(*args):
        """若无文件主题触达目录则立即暴露回归。"""
        raise AssertionError("不应读取Workdir")

    monkeypatch.setattr(Workdir, "open_existing", unexpected_open)
    parsed = SimpleNamespace(definition=SimpleNamespace(manifest=SimpleNamespace(files={})))
    project = SimpleNamespace(uid="synthetic", workdir_path="missing")
    ProjectThemeService.validate_files(project, parsed, {})
    with pytest.raises(ThemeError, match="alias"):
        ProjectThemeService.validate_files(project, parsed, {"unknown": "/missing.json"})
