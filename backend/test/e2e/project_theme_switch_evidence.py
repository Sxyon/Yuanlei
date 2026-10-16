"""S04-R隔离环境的真实HTTP、PG与包字节回验和可恢复故障注入。"""

import asyncio
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

PRIVATE = Path("/tmp/s04-repair/session.json")


async def main(mode):
    """只处理具名隔离库与私有合成身份，不访问日常项目。"""
    session = json.loads(PRIVATE.read_text())
    url = urlsplit(os.environ["POSTGRES_URL"])
    database = urlunsplit(url._replace(path="/yuanlei_s04_repair_evidence"))
    engine = create_async_engine(database)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:5060", headers={"Authorization": "Bearer " + session["token"]}, timeout=30
    ) as client:

        async def request(method, path, **kwargs):
            """调用隔离服务并拒绝非成功状态。"""
            response = await client.request(method, "/api" + path, **kwargs)
            response.raise_for_status()
            return response.json()

        if mode == "prepare":
            from yuxi.config.options import ensure_options_in_db

            async with async_sessionmaker(engine)() as db:
                await ensure_options_in_db(db)
                await db.commit()
            directory = await request("GET", "/theme-sources")
            source = next((s for s in directory["sources"] if s["name"] == "S04-R无设置声明"), None)
            if source is None:
                source = await request("POST", "/theme-sources", json={"name": "S04-R无设置声明", "kind": "personal"})
                with zipfile.ZipFile("/app/package/yuxi/themes/builtin/workspace-research.theme.zip") as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    theme = json.loads(archive.read("theme.json"))
                theme.update(id="independent-s04", name="S04-R独立课题", version="3.0.0")
                theme["pages"] = [page for page in theme["pages"] if page["capability"] == "topics"]
                theme["pages"][0]["id"] = "independent-topic-directory"
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr("manifest.json", json.dumps(manifest))
                    archive.writestr("theme.json", json.dumps(theme))
                await request(
                    "PUT",
                    f"/theme-sources/{source['id']}/candidate?expected_revision=0",
                    content=output.getvalue(),
                    headers={"Content-Type": "application/zip"},
                )
                version = await request("POST", f"/theme-sources/{source['id']}/publish", json={"expected_revision": 1})
            else:
                version = source["versions"][0]
            session["noSettings"] = {"source": source["id"], "version": version["id"]}
            base = f"/projects/{session['projects'][0]['id']}/governance"
            existing = await request("GET", base + "/topics-page?limit=100")
            topic = next((t for t in existing["items"] if t["title"] == "S04-R准确对象"), None)
            if topic is None:
                topic = await request(
                    "POST",
                    base + "/topics",
                    json={"title": "S04-R准确对象", "summary": "两主题共享原业务ID", "source_channel": "project"},
                )
            session["topic"] = topic["id"]
            PRIVATE.write_text(json.dumps(session))
            PRIVATE.chmod(0o600)
            print("无settings声明的真实不可变包及准确业务对象已准备")
        elif mode in ("corrupt", "restore"):
            version = session["noSettings"]["version"]
            async with engine.connect() as conn:
                row = (
                    (
                        await conn.execute(
                            text("SELECT source_id,digest FROM project_theme_versions WHERE id=:id"), {"id": version}
                        )
                    )
                    .mappings()
                    .one()
                )
            file = Path("/tmp/s04-repair/theme-sources") / row["source_id"] / (row["digest"] + ".zip")
            backup = file.with_suffix(".s04-backup")
            file.chmod(0o600)
            if mode == "corrupt":
                if not backup.exists():
                    backup.write_bytes(file.read_bytes())
                file.write_bytes(b"isolated-corrupt-package")
            else:
                file.write_bytes(backup.read_bytes())
            file.chmod(0o400)
            print("仅隔离包的字节故障已" + ("注入" if mode == "corrupt" else "恢复"))
        elif mode in ("deny", "allow"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE projects SET status=:status WHERE id=:id"),
                    {"status": "deleted" if mode == "deny" else "active", "id": session["projects"][0]["id"]},
                )
            print("仅隔离项目可见性已" + ("撤销" if mode == "deny" else "恢复"))
        else:
            report = []
            for project in session["projects"]:
                result = await request("GET", f"/projects/{project['id']}/theme")
                async with engine.connect() as conn:
                    row = (
                        (
                            await conn.execute(
                                text(
                                    "SELECT b.version_id,b.generation,b.files,v.digest,v.source_id "
                                    "FROM project_theme_bindings b JOIN project_theme_versions v ON v.id=b.version_id "
                                    "WHERE project_id=:id"
                                ),
                                {"id": project["id"]},
                            )
                        )
                        .mappings()
                        .first()
                    )
                assert result["generation"] == (row["generation"] if row else 0)
                if row:
                    assert result["binding"]["version_id"] == row["version_id"]
                    assert result["binding"]["files"] == row["files"]
                    raw = (
                        Path("/tmp/s04-repair/theme-sources") / row["source_id"] / (row["digest"] + ".zip")
                    ).read_bytes()
                    actual = hashlib.sha256(raw).hexdigest()
                    if result["state"] == "ready":
                        assert actual == row["digest"] == result["package"]["digest"]
                    report.append(
                        {
                            "project": project["name"],
                            "version": row["version_id"],
                            "generation": row["generation"],
                            "digest": row["digest"],
                            "actualDigest": actual,
                            "state": result["state"],
                        }
                    )
                else:
                    report.append({"project": project["name"], "state": result["state"], "generation": 0})
            print(json.dumps(report, ensure_ascii=False))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "read"))
