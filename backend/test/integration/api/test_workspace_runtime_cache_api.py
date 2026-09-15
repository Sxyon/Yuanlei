from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from yuxi.config import get_legacy_storage_dir, get_runtime_dir
from yuxi.workspace.paths import user_workspace_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_workspace_owner_safe_cleanup_unlinks_symlink_without_following_target(test_client, admin_headers):
    """真实个人空间 API 必须先冲突，再仅删除链接目录项并保留外部目标。"""

    profile = await test_client.get("/api/auth/me", headers=admin_headers)
    assert profile.status_code == 200, profile.text
    workspace_root = user_workspace_dir(profile.json()["uid"])
    suffix = uuid4().hex
    directory = workspace_root / f"pytest-symlink-cleanup-{suffix}"
    outside = workspace_root.parent / f"pytest-symlink-target-{suffix}"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    directory.mkdir(parents=True)
    (directory / "tracked.txt").write_text("tracked", encoding="utf-8")
    (directory / "linked").symlink_to(outside, target_is_directory=True)
    workspace_path = f"/{directory.name}"

    try:
        rejected = await test_client.delete(
            "/api/workspace/file",
            params={"path": workspace_path},
            headers=admin_headers,
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "workspace_contains_symlinks"
        assert directory.exists()

        cleaned = await test_client.delete(
            "/api/workspace/file",
            params={"path": workspace_path, "safe_unlink_symlinks": True},
            headers=admin_headers,
        )
        assert cleaned.status_code == 200, cleaned.text
        assert not directory.exists()
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def _file_snapshot(roots: list[Path]) -> dict[Path, tuple[int, int]]:
    """记录真实文件的大小与修改时间，用于证明请求写入边界。"""
    snapshot: dict[Path, tuple[int, int]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[path] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


async def test_office_preview_cache_is_written_only_to_api_runtime(test_client, admin_headers):
    """真实上传和两次预览应只在 API 运行目录生成可重建缓存。"""
    fixture = Path(__file__).resolve().parents[2] / "data" / "测试文档.docx"
    filename = f"pytest-runtime-cache-{uuid4().hex}.docx"
    workspace_path = f"/{filename}"
    runtime_cache = get_runtime_dir() / "cache" / "office-previews"
    legacy_cache_dirs = set(get_legacy_storage_dir().rglob(".office_preview_cache"))
    runtime_before = _file_snapshot([runtime_cache])
    legacy_before = _file_snapshot(list(legacy_cache_dirs))

    try:
        with fixture.open("rb") as source:
            upload = await test_client.post(
                "/api/workspace/upload",
                data={"parent_path": "/"},
                files={
                    "files": (
                        filename,
                        source,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                headers=admin_headers,
            )
        assert upload.status_code == 200, upload.text

        first = await test_client.get("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)
        second = await test_client.get("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.headers["content-type"].startswith("application/pdf")
        assert first.content.startswith(b"%PDF-")
        assert second.content == first.content

        runtime_after = _file_snapshot([runtime_cache])
        legacy_cache_dirs_after = set(get_legacy_storage_dir().rglob(".office_preview_cache"))
        assert set(runtime_after) - set(runtime_before)
        assert legacy_cache_dirs_after == legacy_cache_dirs
        assert _file_snapshot(list(legacy_cache_dirs_after)) == legacy_before
    finally:
        await test_client.delete("/api/workspace/file", params={"path": workspace_path}, headers=admin_headers)
        for cache_path in set(_file_snapshot([runtime_cache])) - set(runtime_before):
            cache_path.unlink(missing_ok=True)
        for legacy_cache_dir in set(get_legacy_storage_dir().rglob(".office_preview_cache")) - legacy_cache_dirs:
            shutil.rmtree(legacy_cache_dir, ignore_errors=True)
