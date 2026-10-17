"""S05-R2具名隔离库准备与HTTP/PG/包字节回读，不访问日常数据。"""

import asyncio
import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import project_theme_switch_app
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import Project, ProjectSettings
from yuxi.themes.store import ThemeStore
from yuxi.workspace.paths import user_workspace_dir


async def main():
    """有权复制、编辑、校验、预览与发布两种组织的证据派生版。"""
    if urlsplit(project_theme_switch_app.os.environ["POSTGRES_URL"]).path != "/yuanlei_s04_repair_evidence":
        raise RuntimeError("只允许具名隔离库")
    session = json.loads(Path("/tmp/s04-repair/session.json").read_text())
    pg_manager.initialize()
    context_file = Path("/tmp/s04-repair/s05-r2.json")
    if context_file.exists():
        print(context_file.read_text())
        return
    factory = async_sessionmaker(pg_manager.async_engine, expire_on_commit=False)
    async with factory() as db:
        projects = [
            Project(
                id=str(uuid.uuid4()),
                uid=session["uid"],
                name=f"S05-R2验例{c}",
                selection_status="selectable",
                directory_mode="linked",
                workdir_path=f"projects/s05-r2-{uuid.uuid4().hex[:8]}",
            )
            for c in "AB"
        ]
        db.add_all(projects)
        await db.flush()
        db.add_all([ProjectSettings(project_id=p.id, owner_id=p.uid, description="隔离合成主题验例") for p in projects])
        await db.commit()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:5060/api", headers={"Authorization": "Bearer " + session["token"]}
    ) as client:

        async def call(method, path, body=None):
            """检查真实接口结果，失败保留具体协议错误。"""
            r = await client.request(method, path, json=body)
            assert r.status_code == 200, (path, r.status_code, r.text)
            return r.json()

        catalog = await call("GET", "/theme-sources")
        builtin = {s["name"]: s for s in catalog["sources"] if s["kind"] == "builtin" and s["status"] == "active"}
        default = builtin["默认 · 项目管理"]["versions"][0]
        focus = builtin["精简 · 专注推进"]["versions"][0]
        derived = []
        # 从旧协议资源取得合成PNG；不修改任何已发布包。
        with zipfile.ZipFile(Path("/app/package/yuxi/themes/builtin/research.theme.zip")) as archive:
            png = archive.read("assets/survey.png")
        for p, count in zip(projects, [12, 99], strict=True):
            root = user_workspace_dir(p.uid) / p.workdir_path
            root.mkdir(parents=True, exist_ok=True)
            (root / "facts.json").write_text(json.dumps({"项目": p.name, "样本": count}, ensure_ascii=False))
            (root / "chart.png").write_bytes(png)
            await call(
                "PUT", f"/projects/{p.id}/theme", {"version_id": default["id"], "files": {}, "expected_generation": 0}
            )
        for name in ["调研 · 阅读工作室", "默认 · 项目管理"]:
            original = builtin[name]["versions"][0]
            source = await call(
                "POST",
                "/theme-sources",
                {"name": f"S05-R2证据 · {name}", "kind": "personal", "copy_version_id": original["id"]},
            )
            candidate = await call("GET", f"/theme-sources/{source['id']}/candidate")
            pack = candidate["package"]
            pack["manifest"]["files"] = {"facts": "application/json", "chart": "image/png"}
            pack["theme"]["version"] = "3.1.0-r2"
            pack["theme"]["name"] = f"S05-R2证据 · {name}"
            pack["theme"]["pages"].append(
                {
                    "id": "project-evidence",
                    "title": "项目证据",
                    "description": "当前Project指定资料；不随课题选择改变。",
                    "layout": "reading",
                    "blocks": [
                        {
                            "id": "facts",
                            "type": "json",
                            "title": "项目调查资料",
                            "region": "main",
                            "binding": {"kind": "file", "alias": "facts"},
                        },
                        {
                            "id": "chart",
                            "type": "image",
                            "title": "项目证据图",
                            "region": "aside",
                            "binding": {"kind": "file", "alias": "chart"},
                            "alt": "项目调查图示",
                        },
                    ],
                }
            )
            candidate = await call(
                "PUT",
                f"/theme-sources/{source['id']}/definition",
                {"expected_revision": 1, "manifest": pack["manifest"], "theme": pack["theme"]},
            )
            revision = candidate["source"]["candidate_revision"]
            assert revision == 2
            mapping = {"facts": "/facts.json", "chart": "/chart.png"}
            resources = {}
            for alias, filename in [("facts", "facts.json"), ("chart", "chart.png")]:
                r = await client.post(
                    f"/projects/{projects[0].id}/theme/preview-file",
                    json={
                        "source_id": source["id"],
                        "revision": revision,
                        "files": mapping,
                        "expected_generation": 1,
                        "alias": alias,
                    },
                )
                assert r.status_code == 200, r.text
                raw = (user_workspace_dir(projects[0].uid) / projects[0].workdir_path / filename).read_bytes()
                assert r.content == raw and r.headers["x-theme-sha256"] == hashlib.sha256(raw).hexdigest()
                resources[alias] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
            version = await call("POST", f"/theme-sources/{source['id']}/publish", {"expected_revision": revision})
            raw = ThemeStore().read(source["id"], version["digest"])
            assert hashlib.sha256(raw).hexdigest() == version["digest"]
            derived.append(
                {"source_id": source["id"], "revision": revision, "version": version, "resources": resources}
            )
        topic = await call(
            "POST",
            f"/projects/{projects[0].id}/governance/topics",
            {"title": "同一议题跨主题验证", "summary": "用户原文保留：议题与课题。", "source_channel": "project"},
        )
        topic = await call(
            "POST", f"/projects/{projects[0].id}/governance/topics/{topic['id']}/review", {"approve": True}
        )
        context = {
            "projects": [{"id": p.id, "name": p.name, "workdir_path": p.workdir_path} for p in projects],
            "default": default["id"],
            "focus": focus["id"],
            "derived": derived,
            "topic_id": topic["id"],
        }
        async with factory() as db:
            for p in projects:
                row = (
                    (
                        await db.execute(
                            text("SELECT version_id,generation,files FROM project_theme_bindings WHERE project_id=:id"),
                            {"id": p.id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert row["version_id"] == default["id"] and row["generation"] == 1 and row["files"] == {}
        context_file.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n")
        print(context_file.read_text())
    await pg_manager.close()


async def verify():
    """独立回读HTTP、PG、Workdir字节及不可变ZIP，不修改业务。"""
    if urlsplit(project_theme_switch_app.os.environ["POSTGRES_URL"]).path != "/yuanlei_s04_repair_evidence":
        raise RuntimeError("只允许具名隔离库")
    session = json.loads(Path("/tmp/s04-repair/session.json").read_text())
    context = json.loads(Path("/tmp/s04-repair/s05-r2.json").read_text())
    pg_manager.initialize()
    result = {"projects": [], "packages": []}
    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:5060/api", headers={"Authorization": "Bearer " + session["token"]}
        ) as client,
        async_sessionmaker(pg_manager.async_engine)() as db,
    ):
        for index, project in enumerate(context["projects"]):
            project_id = project["id"]
            response = await client.get(f"/projects/{project_id}/theme")
            response.raise_for_status()
            selection = response.json()
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
            assert dict(row) == {
                "version_id": selection["binding"]["version_id"],
                "generation": selection["generation"],
                "files": selection["binding"]["files"],
            }
            expected = context["default"] if index == 0 else context["derived"][1]["version"]["id"]
            assert row["version_id"] == expected
            resources = {}
            for alias, filename in [("facts", "facts.json"), ("chart", "chart.png")]:
                raw = (user_workspace_dir(session["uid"]) / project["workdir_path"] / filename).read_bytes()
                response = await client.post(
                    f"/projects/{project_id}/theme/preview-file",
                    json={
                        "version_id": context["derived"][index]["version"]["id"],
                        "expected_generation": row["generation"],
                        "files": {"facts": "/facts.json", "chart": "/chart.png"},
                        "alias": alias,
                    },
                )
                assert response.status_code == 200, response.text
                assert response.content == raw and response.headers["x-theme-sha256"] == hashlib.sha256(raw).hexdigest()
                resources[alias] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
            topic_count = await db.scalar(
                text("SELECT count(*) FROM governance_topics WHERE project_id=:id"), {"id": project_id}
            )
            result["projects"].append(
                {**project, "binding": dict(row), "resources": resources, "topic_count": topic_count}
            )
        topic_id = context["topic_id"]
        topic = (
            (
                await db.execute(
                    text("SELECT id,project_id,title,summary,revision_number FROM governance_topics WHERE id=:id"),
                    {"id": topic_id},
                )
            )
            .mappings()
            .one()
        )
        assert topic["revision_number"] == 3 and "默认主题补充事实" in topic["summary"]
        assert "调研主题继续维护" in topic["summary"] and "议题与课题" in topic["summary"]
        comments = (
            (
                await db.execute(
                    text("SELECT topic_id,content FROM governance_topic_comments WHERE topic_id=:id"), {"id": topic_id}
                )
            )
            .mappings()
            .all()
        )
        assert any("调研主题记录证据讨论" in c["content"] for c in comments)
        works = (
            (
                await db.execute(
                    text(
                        "SELECT id,topic_id,source_decision_id,source_decision_revision,title "
                        "FROM project_work_tasks WHERE topic_id=:id"
                    ),
                    {"id": topic_id},
                )
            )
            .mappings()
            .all()
        )
        assert len(works) == 1 and works[0]["source_decision_revision"] == 2
        decision = (
            (
                await db.execute(
                    text(
                        "SELECT id,status,topic_id,revision_number,topic_revision_number "
                        "FROM governance_decisions WHERE id=:id"
                    ),
                    {"id": works[0]["source_decision_id"]},
                )
            )
            .mappings()
            .one()
        )
        assert decision["status"] == "approved" and decision["topic_id"] == topic_id
        assert decision["revision_number"] == 2 and decision["topic_revision_number"] == 3
        result["business"] = {
            "topic": dict(topic),
            "comments": [dict(c) for c in comments],
            "works": [dict(w) for w in works],
            "decision": dict(decision),
        }
        for derived in context["derived"]:
            version = derived["version"]
            raw = ThemeStore().read(derived["source_id"], version["digest"])
            assert hashlib.sha256(raw).hexdigest() == version["digest"]
            result["packages"].append(
                {
                    "source_id": derived["source_id"],
                    "revision": derived["revision"],
                    "version_id": version["id"],
                    "digest": version["digest"],
                }
            )
        for project in context["projects"]:
            current = (await client.get(f"/projects/{project['id']}/theme")).json()
            saved = next(p["binding"] for p in result["projects"] if p["id"] == project["id"])
            assert (
                current["generation"] == saved["generation"] and current["binding"]["version_id"] == saved["version_id"]
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    await pg_manager.close()


if __name__ == "__main__":
    import sys

    asyncio.run(verify() if "--verify" in sys.argv else main())
