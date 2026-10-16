"""在S04具名隔离环境准备三主题内容并回验HTTP、PG及包字节。"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

# 复用已授权隔离应用的环境选择，不访问日常库或账号。
import project_theme_switch_app
from yuxi.storage.postgres.manager import pg_manager


async def main(mode):
    """只为合成项目准备内容，读取时不修改主题选择。"""
    if urlsplit(project_theme_switch_app.os.environ["POSTGRES_URL"]).path != "/yuanlei_s04_repair_evidence":
        raise RuntimeError("只允许具名主题隔离库")
    session = json.loads(Path("/tmp/s04-repair/session.json").read_text())
    pg_manager.initialize()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:5060/api", headers={"Authorization": "Bearer " + session["token"]}
    ) as client:
        if mode == "prepare":
            project = session["projects"][0]["id"]
            blueprints = (await client.get(f"/projects/{project}/blueprint")).json()
            if not blueprints["documents"]:
                result = await client.post(
                    f"/projects/{project}/blueprint",
                    json={
                        "name": "阅读空间试点.md",
                        "content": (
                            "# 社区阅读空间试点\n\n## 两周试运营\n"
                            "先开放20个座位，完成首场共读与反馈复盘。\n\n## 边界\n"
                            "先验证时段、座位和志愿排班，不承诺长期投入。"
                        ),
                    },
                )
                result.raise_for_status()
            existing = (await client.get(f"/projects/{project}/governance/topics")).json()
            for title, summary, expected in [
                ("周末开放时段如何安排", "核对访客反馈与志愿排班，保留不同意见。", "形成可复核的两周开放安排。"),
                ("儿童活动是否单独设时段", "核对家长参与、噪声与场地安排。", "用参与人数与反馈核对儿童专属时段。"),
            ]:
                if not any(item["title"] == title for item in existing):
                    result = await client.post(
                        f"/projects/{project}/governance/topics",
                        json={"title": title, "summary": summary, "source_channel": "project"},
                    )
                    result.raise_for_status()
                    topic = result.json()
                    updated = await client.put(
                        f"/projects/{project}/governance/topics/{topic['id']}",
                        json={
                            "title": title,
                            "summary": summary,
                            "expected_outcome": expected,
                            "expected_revision": topic["revision_number"],
                            "reason": "隔离样例内容准备",
                        },
                    )
                    updated.raise_for_status()
            print("合成蓝图与两个研究问题已准备；未修改绑定")
        elif mode in ("corrupt", "restore"):
            project = session["projects"][0]["id"]
            binding = (await client.get(f"/projects/{project}/theme")).json()["binding"]
            async with async_sessionmaker(pg_manager.async_engine)() as db:
                row = (
                    (
                        await db.execute(
                            text("SELECT source_id,digest FROM project_theme_versions WHERE id=:v"),
                            {"v": binding["version_id"]},
                        )
                    )
                    .mappings()
                    .one()
                )
            file = Path("/tmp/s04-repair/theme-sources") / row["source_id"] / (row["digest"] + ".zip")
            backup = file.with_suffix(".samples-backup")
            file.chmod(0o600)
            if mode == "corrupt":
                if not backup.exists():
                    backup.write_bytes(file.read_bytes())
                file.write_bytes(b"isolated-current-sample-corrupt")
            else:
                file.write_bytes(backup.read_bytes())
            file.chmod(0o400)
            print("仅当前合成项目的主题包字节故障已" + ("注入" if mode == "corrupt" else "恢复"))
        elif mode == "read":
            evidence = {"kind": "真实HTTP、PG与包字节回读；项目为隔离合成项目", "projects": []}
            async with async_sessionmaker(pg_manager.async_engine)() as db:
                for project in session["projects"]:
                    result = await client.get(f"/projects/{project['id']}/theme")
                    result.raise_for_status()
                    value = result.json()
                    row = (
                        (
                            await db.execute(
                                text("SELECT version_id,generation FROM project_theme_bindings WHERE project_id=:p"),
                                {"p": project["id"]},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    assert (dict(row) if row else None) == (
                        {"version_id": value["binding"]["version_id"], "generation": value["generation"]}
                        if value["binding"]
                        else None
                    )
                    if value["state"] == "ready":
                        from yuxi.themes.store import ThemeStore

                        raw = ThemeStore().read(value["source"]["id"], value["version"]["digest"])
                        assert hashlib.sha256(raw).hexdigest() == value["package"]["digest"]
                    evidence["projects"].append(
                        {
                            "project": project["name"],
                            "id": project["id"],
                            "state": value["state"],
                            "version_id": value["binding"]["version_id"] if value["binding"] else None,
                            "generation": value["generation"],
                            "source": value.get("source", {}).get("name"),
                            "digest": value.get("version", {}).get("digest"),
                            "presentation": (value.get("package") or {})
                            .get("theme", {})
                            .get("presentation", "baseline"),
                        }
                    )
                sources = (
                    (
                        await db.execute(
                            text(
                                "SELECT name,status FROM project_theme_sources "
                                "WHERE kind='builtin' ORDER BY name,status"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                evidence["catalog"] = [dict(row) for row in sources]
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
    await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
