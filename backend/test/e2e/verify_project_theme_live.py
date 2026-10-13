"""只读回验S05浏览器对象、真实HTTP、独立SQL和文件字节。"""

import asyncio
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from yuxi.storage.postgres.manager import pg_manager
from yuxi.workspace.paths import user_workspace_dir


async def main():
    """隔离库及私有合成session是前提；公开回执只保存事实与摘要。"""
    if urlsplit(os.environ["POSTGRES_URL"]).path != "/yuanlei_s05_evidence":
        raise RuntimeError("证据只读回验仅允许S05隔离数据库")
    browser = json.load(sys.stdin)
    session = json.loads((Path(os.environ["YUXI_USER_DATA_DIR"]) / ".s05-session.json").read_text())
    pg_manager.initialize()
    factory = async_sessionmaker(pg_manager.async_engine)
    report = {"browserChecks": len(browser["checks"]), "projects": [], "negativeChecks": []}
    async with factory() as db, httpx.AsyncClient(base_url="http://127.0.0.1:5060", timeout=30) as client:
        own = {"Authorization": "Bearer " + session["users"][0]["token"]}
        other = {"Authorization": "Bearer " + session["users"][1]["token"]}
        for project in session["projects"][:2]:
            project_id = project["id"]
            base = f"/api/projects/{project_id}"
            response = await client.get(base + "/theme", headers=own)
            response.raise_for_status()
            binding = response.json()
            row = (
                (
                    await db.execute(
                        text("SELECT version_id,generation,files FROM project_theme_bindings WHERE project_id=:id"),
                        {"id": project_id},
                    )
                )
                .mappings()
                .one()
            )
            assert binding["state"] == "ready"
            assert binding["binding"]["version_id"] == row["version_id"]
            assert binding["generation"] == row["generation"]
            assert binding["binding"]["files"] == row["files"]
            version = (
                (
                    await db.execute(
                        text("SELECT source_id,digest,size FROM project_theme_versions WHERE id=:id"),
                        {"id": row["version_id"]},
                    )
                )
                .mappings()
                .one()
            )
            raw = (
                Path(os.environ["YUXI_THEME_SOURCES_DIR"]) / version["source_id"] / f"{version['digest']}.zip"
            ).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == version["digest"] == binding["package"]["digest"]
            assert len(raw) == version["size"]
            resources = []
            for alias, bound_path in row["files"].items():
                file_response = await client.get(
                    base + "/theme/files",
                    headers=own,
                    params={"alias": alias, "expected_generation": row["generation"]},
                )
                file_response.raise_for_status()
                independent = (
                    user_workspace_dir(project["uid"]) / project["workdir_path"] / bound_path.lstrip("/")
                ).read_bytes()
                assert independent == file_response.content
                digest = hashlib.sha256(independent).hexdigest()
                assert file_response.headers["x-theme-sha256"] == digest
                assert int(file_response.headers["x-theme-size"]) == len(independent)
                assert file_response.headers["content-type"] == binding["package"]["manifest"]["files"][alias]
                if project_id == browser["fileEvidence"]["projectId"]:
                    assert digest == browser["fileEvidence"]["sha256"]
                resources.append({"kind": "file", "alias": alias, "sha256": digest, "size": len(independent)})
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                for alias, asset in manifest["assets"].items():
                    independent = archive.read(asset["path"])
                    resource = await client.get(
                        base + "/theme/assets",
                        headers=own,
                        params={"alias": alias, "expected_generation": row["generation"]},
                    )
                    resource.raise_for_status()
                    assert resource.content == independent
                    assert (
                        hashlib.sha256(independent).hexdigest() == asset["sha256"] == resource.headers["x-theme-sha256"]
                    )
                    resources.append(
                        {"kind": "asset", "alias": alias, "sha256": asset["sha256"], "size": len(independent)}
                    )
            report["projects"].append(
                {
                    "id": project_id,
                    "versionId": row["version_id"],
                    "generation": row["generation"],
                    "packageSha256": version["digest"],
                    "resources": resources,
                }
            )
            for endpoint in (
                "/theme",
                "/governance/summary",
                "/governance/topics-page",
                "/governance/decisions-page",
                "/work/tasks-page",
            ):
                denied = await client.get(base + endpoint, headers=other)
                assert denied.status_code == 404 and b"S05" not in denied.content
                report["negativeChecks"].append(
                    {"projectId": project_id, "endpoint": endpoint, "status": denied.status_code}
                )
        objects = browser["objects"]
        task = (
            (
                await db.execute(
                    text(
                        "SELECT project_id,status,source_decision_id,source_decision_revision "
                        "FROM project_work_tasks WHERE id=:id"
                    ),
                    {"id": objects["workTaskId"]},
                )
            )
            .mappings()
            .one()
        )
        assert task["project_id"] == objects["projectId"] and task["status"] == "in_progress"
        assert task["source_decision_id"] == objects["decisionId"]
        detail = await client.get(
            f"/api/projects/{objects['projectId']}/work/tasks/{objects['workTaskId']}", headers=own
        )
        detail.raise_for_status()
        assert detail.json()["status"] == task["status"]
        revision = (
            await db.execute(
                text("SELECT snapshot FROM governance_decision_revisions WHERE decision_id=:id AND number=:number"),
                {"id": task["source_decision_id"], "number": task["source_decision_revision"]},
            )
        ).scalar_one()
        assert detail.json()["source"]["decision"]["snapshot"] == revision
        report["task"] = dict(task)
        report["counts"] = {
            table: await db.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("governance_topics", "project_work_tasks", "governance_tasks", "conversations")
        }
        assert report["counts"] == {
            "governance_topics": 25,
            "project_work_tasks": 1,
            "governance_tasks": 1,
            "conversations": 0,
        }
    await pg_manager.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
