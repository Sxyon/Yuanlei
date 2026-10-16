"""只读回验具名隔离库的M1草稿、发布包与项目选择。"""

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import project_theme_switch_app
from yuxi.storage.postgres.manager import pg_manager
from yuxi.themes.packages import parse_package
from yuxi.themes.store import ThemeStore


async def main():
    """HTTP、PG引用及磁盘ZIP各自回读，拒绝日常库。"""
    if urlsplit(project_theme_switch_app.os.environ["POSTGRES_URL"]).path != "/yuanlei_s04_repair_evidence":
        raise RuntimeError("只允许具名隔离库")
    session = json.loads(Path("/tmp/s04-repair/session.json").read_text())
    pg_manager.initialize()
    evidence = {"sources": [], "bindings": []}
    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:5060/api", headers={"Authorization": "Bearer " + session["token"]}
        ) as client,
        async_sessionmaker(pg_manager.async_engine)() as db,
    ):
        catalog = (await client.get("/theme-sources")).json()
        for source in catalog["sources"]:
            if not source["name"].startswith("M1-"):
                continue
            candidate = (await client.get(f"/theme-sources/{source['id']}/candidate")).json()
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT candidate_digest,candidate_revision,copied_from_version_id "
                            "FROM project_theme_sources WHERE id=:id"
                        ),
                        {"id": source["id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert row["candidate_digest"] == source["candidate_digest"]
            assert row["candidate_revision"] == candidate["source"]["candidate_revision"]
            versions = []
            for version in source["versions"]:
                package = (await client.get(f"/theme-versions/{version['id']}")).json()
                raw = ThemeStore().read(source["id"], version["digest"])
                assert hashlib.sha256(raw).hexdigest() == package["digest"] == version["digest"]
                versions.append(
                    {
                        "id": version["id"],
                        "version": version["version"],
                        "digest": version["digest"],
                        "theme": parse_package(raw).definition.theme.model_dump(),
                    }
                )
            if source["candidate_digest"]:
                raw = ThemeStore().read(source["id"], source["candidate_digest"])
                assert hashlib.sha256(raw).hexdigest() == candidate["package"]["digest"]
            evidence["sources"].append(
                {
                    "id": source["id"],
                    "name": source["name"],
                    **dict(row),
                    "candidate": candidate["package"],
                    "versions": versions,
                }
            )
        for project in session["projects"]:
            value = (await client.get(f"/projects/{project['id']}/theme")).json()
            row = (
                (
                    await db.execute(
                        text("SELECT version_id,generation FROM project_theme_bindings WHERE project_id=:id"),
                        {"id": project["id"]},
                    )
                )
                .mappings()
                .first()
            )
            expected = (
                {"version_id": value["binding"]["version_id"], "generation": value["generation"]}
                if value["binding"]
                else None
            )
            assert (dict(row) if row else None) == expected
            evidence["bindings"].append({"project": project["name"], "binding": expected})
    await pg_manager.close()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
