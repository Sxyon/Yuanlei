"""合成账号、真实TCP HTTP、独立PG与文件字节的主题持久化证据。"""

import asyncio
import hashlib
import io
import json
import os
import socket
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.project_theme_router import project_themes
from server.routers.governance_router import governance
from server.routers.project_work_router import project_work
from server.routers.project_files_router import project_files
from server.utils.auth_middleware import get_db
from yuxi.services.project_theme_service import install_builtin_themes
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import Department, Project, User
from yuxi.themes.packages import ThemeError
from yuxi.themes.store import ThemeStore
from yuxi.utils.auth_utils import AuthUtils
from yuxi.workspace.paths import user_workspace_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
BUILTIN = Path(__file__).parents[3] / "package/yuxi/themes/builtin"


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件只迁移独立schema，不迁移日常运行库。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """独立schema统一收回本测试的数据库资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """主题测试不创建沙盒。"""
    yield


@pytest_asyncio.fixture
async def live_theme(tmp_path, monkeypatch):
    """仅切换真实数据库连接，认证走原JWT、用户行及依赖。"""
    schema = f"theme_{uuid.uuid4().hex[:16]}"
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("YUXI_THEME_SOURCES_DIR", str(tmp_path / "theme-sources"))
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path / "user-data"))
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    app = FastAPI()
    app.include_router(project_themes, prefix="/api")
    app.include_router(governance, prefix="/api")
    app.include_router(project_work, prefix="/api")
    app.include_router(project_files, prefix="/api")

    async def sessions():
        """请求各自使用真实事务，错误回滚、成功提交。"""
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = sessions
    servers = []

    async def start(port=0):
        """启动真实TCP服务，可替换进程内服务器实例验证重启读取。"""
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started
        servers.append((server, task))
        return sock.getsockname()[1]

    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await manager.create_business_tables()
        users = [
            User(
                uid=f"test-{uuid.uuid4().hex}",
                username=f"theme-{uuid.uuid4().hex}",
                password_hash="synthetic",
                role="user",
                is_deleted=0,
            )
            for _ in range(2)
        ]
        projects = []
        async with factory() as db:
            department = Department(name="合成主题测试部门")
            db.add(department)
            await db.flush()
            for user in users:
                user.department_id = department.id
            db.add_all(users)
            await db.flush()
            for index in range(3):
                user = users[0 if index < 2 else 1]
                project = Project(
                    id=str(uuid.uuid4()),
                    uid=user.uid,
                    name=f"合成主题项目{index}",
                    selection_status="selectable",
                    directory_mode="linked",
                    workdir_path="projects/shared",
                )
                projects.append(project)
                db.add(project)
            await db.commit()
        # 先有旧Project行，增量迁移两次验证幂等与原数据保留。
        await manager.upgrade_yuanlei_schema_v38_to_v39()
        await manager.upgrade_yuanlei_schema_v38_to_v39()
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE project_theme_versions DROP CONSTRAINT project_theme_versions_check"))
            await conn.execute(text("ALTER TABLE project_theme_versions ADD CONSTRAINT project_theme_versions_check CHECK (format_version=1 AND component_abi=1)"))
        await manager.upgrade_yuanlei_schema_v39_to_v40()
        await manager.upgrade_yuanlei_schema_v39_to_v40()
        await manager.upgrade_yuanlei_schema_v40_to_v41()
        await manager.upgrade_yuanlei_schema_v40_to_v41()
        async with factory() as db:
            assert (await db.get(Project, projects[0].id)).name == "合成主题项目0"
            await install_builtin_themes(db)
        root = user_workspace_dir(users[0].uid) / "projects/shared"
        root.mkdir(parents=True)
        (root / "data.json").write_bytes(b'{"samples":12}')
        (root / "bad.json").write_bytes(b"not-json")
        (root / "link.json").symlink_to(root / "data.json")
        port = await start()
        headers = [{"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(u.id)})} for u in users]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers[0]) as client:
            yield SimpleNamespace(
                client=client,
                headers=headers,
                db=factory,
                projects=projects,
                users=users,
                root=root,
                store=ThemeStore(tmp_path / "theme-sources"),
                start=start,
                servers=servers,
                port=port,
                manager=manager,
            )
    finally:
        for server, task in servers:
            server.should_exit = True
            await task
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def create_publish(env, *, kind="personal", name="真实候选", archive="default"):
    """HTTP上传与发布，并供独立数据库查询核对。"""
    project = env.projects[0].id if kind == "project" else None
    r = await env.client.post("/api/theme-sources", json={"name": name, "kind": kind, "project_id": project})
    assert r.status_code == 200, r.text
    source = r.json()
    query = {"expected_revision": 0}
    if project:
        query["project_id"] = project
    raw = (BUILTIN / f"{archive}.theme.zip").read_bytes()
    r = await env.client.put(f"/api/theme-sources/{source['id']}/candidate", params=query, content=raw)
    assert r.status_code == 200, r.text
    r = await env.client.post(
        f"/api/theme-sources/{source['id']}/publish",
        params={"project_id": project} if project else {},
        json={"expected_revision": 1},
    )
    assert r.status_code == 200, r.text
    return source, r.json(), raw


async def test_real_identity_binding_conflicts_same_workdir_and_restart(live_theme):
    env = live_theme
    source, version, raw = await create_publish(env)
    a, b = env.projects[:2]
    r = await env.client.put(
        f"/api/projects/{a.id}/theme", json={"version_id": version["id"], "files": {}, "expected_generation": 0}
    )
    assert r.status_code == 200, r.text
    directory = (await env.client.get("/api/theme-sources")).json()
    builtin = next(s for s in directory["sources"] if s["kind"] == "builtin" and s["status"] == "active" and s["versions"][0]["size"] < 2000)
    r = await env.client.put(
        f"/api/projects/{b.id}/theme",
        json={"version_id": builtin["versions"][0]["id"], "files": {}, "expected_generation": 0},
    )
    assert r.status_code == 200, r.text
    async with env.db() as db:
        rows = (
            (
                await db.execute(
                    text("SELECT project_id,version_id,generation FROM project_theme_bindings ORDER BY project_id")
                )
            )
            .mappings()
            .all()
        )
        bindings = {row["project_id"]: row for row in rows}
        assert bindings[a.id]["version_id"] == version["id"] and bindings[b.id]["version_id"] != version["id"]
        assert (await db.get(Project, a.id)).workdir_path == (await db.get(Project, b.id)).workdir_path
    assert env.store.read(source["id"], version["digest"]) == raw
    requests = [
        env.client.put(
            f"/api/projects/{a.id}/theme", json={"version_id": version["id"], "files": {}, "expected_generation": 1}
        )
        for _ in range(2)
    ]
    responses = await asyncio.gather(*requests)
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["detail"]["code"] == "binding_conflict"
    r = await env.client.get(f"/api/projects/{a.id}/theme", headers=env.headers[1])
    assert r.status_code == 404
    r = await env.client.get(f"/api/theme-versions/{version['id']}", headers=env.headers[1])
    assert r.status_code == 404
    server, task = env.servers[-1]
    server.should_exit = True
    await task
    await env.start(env.port)
    r = await env.client.get(f"/api/projects/{a.id}/theme")
    assert r.json()["package"]["digest"] == hashlib.sha256(raw).hexdigest() and r.json()["generation"] == 2


async def test_candidate_edit_immutable_version_and_same_version_conflict(live_theme):
    env = live_theme
    source, version, raw = await create_publish(env)
    current = (await env.client.get(f"/api/theme-sources/{source['id']}/candidate")).json()
    body = {"manifest": current["package"]["manifest"], "theme": current["package"]["theme"], "expected_revision": 1}
    body["theme"]["name"] = "仅候选改变"
    r = await env.client.put(f"/api/theme-sources/{source['id']}/definition", json=body)
    assert r.status_code == 200, r.text
    r = await env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 2})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"
    old = (await env.client.get(f"/api/theme-versions/{version['id']}")).json()
    assert old["digest"] == hashlib.sha256(raw).hexdigest() and old["theme"]["name"] != "仅候选改变"
    assert env.store.read(source["id"], version["digest"]) == raw
    async with env.db() as db:
        assert (
            await db.scalar(
                text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": source["id"]}
            )
            == 1
        )
        with pytest.raises(Exception, match="immutable"):
            await db.execute(
                text("UPDATE project_theme_versions SET digest=:digest WHERE id=:id"),
                {"digest": "0" * 64, "id": version["id"]},
            )
        await db.rollback()
    r = await env.client.put(
        f"/api/theme-sources/{source['id']}/candidate", params={"expected_revision": 1}, content=raw
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "candidate_conflict"


async def test_project_source_alias_boundary_and_actual_asset_bytes(live_theme):
    env = live_theme
    source, version, raw = await create_publish(env, kind="project", archive="research")
    a, b = env.projects[:2]
    query = {"version_id": version["id"], "files": {"survey": "/data.json"}, "expected_generation": 0}
    r = await env.client.put(f"/api/projects/{b.id}/theme", json=query)
    assert r.status_code == 404
    for path in ["/../data.json", "/link.json", "/bad.json", "/missing.json"]:
        r = await env.client.put(f"/api/projects/{a.id}/theme", json={**query, "files": {"survey": path}})
        assert r.status_code == 422, r.text
        async with env.db() as db:
            assert await db.scalar(text("SELECT count(*) FROM project_theme_bindings")) == 0
    r = await env.client.put(f"/api/projects/{a.id}/theme", json=query)
    assert r.status_code == 200, r.text
    r = await env.client.get(
        f"/api/projects/{a.id}/theme/assets", params={"expected_generation": 1, "alias": "distribution"}
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert r.content == archive.read("assets/survey.png")
    assert r.headers["cache-control"] == "no-store, private" and r.headers["x-content-type-options"] == "nosniff"
    r = await env.client.get(
        f"/api/projects/{a.id}/theme/assets", params={"expected_generation": 2, "alias": "distribution"}
    )
    assert r.status_code == 409
    r = await env.client.get(
        f"/api/theme-versions/{version['id']}/assets", params={"project_id": b.id, "alias": "distribution"}
    )
    assert r.status_code == 404


async def test_stop_withdraw_corrupt_missing_and_original_binding(live_theme):
    env = live_theme
    source, version, raw = await create_publish(env)
    project = env.projects[0]
    body = {"version_id": version["id"], "files": {}, "expected_generation": 0}
    assert (await env.client.put(f"/api/projects/{project.id}/theme", json=body)).status_code == 200
    path = f"/api/theme-sources/{source['id']}/status"
    assert (await env.client.put(path, json={"status": "disabled", "reason": "停用"})).status_code == 200
    assert (await env.client.get(f"/api/projects/{project.id}/theme")).json()["state"] == "ready"
    r = await env.client.put(f"/api/projects/{project.id}/theme", json={**body, "expected_generation": 1})
    assert r.status_code == 409
    assert (await env.client.put(path, json={"status": "withdrawn", "reason": ""})).status_code == 422
    assert (await env.client.put(path, json={"status": "withdrawn", "reason": "合成安全复核"})).status_code == 200
    result = (await env.client.get(f"/api/projects/{project.id}/theme")).json()
    assert result["error"]["code"] == "source_withdrawn" and result["binding"]["version_id"] == version["id"]
    assert (await env.client.put(path, json={"status": "active", "reason": "复核完成"})).status_code == 200
    target = env.store.root / source["id"] / f"{version['digest']}.zip"
    os.chmod(target, 0o600)
    target.write_bytes(b"tampered")
    result = (await env.client.get(f"/api/projects/{project.id}/theme")).json()
    assert result["error"]["code"] == "package_corrupt" and result["generation"] == 1
    target.unlink()
    result = (await env.client.get(f"/api/projects/{project.id}/theme")).json()
    assert result["error"]["code"] == "package_missing"
    env.store.put(source["id"], raw, version["digest"])
    assert (await env.client.get(f"/api/projects/{project.id}/theme")).json()["state"] == "ready"
    async with env.db() as db:
        assert (
            await db.scalar(
                text("SELECT generation FROM project_theme_bindings WHERE project_id=:id"), {"id": project.id}
            )
            == 1
        )
        assert (
            await db.scalar(text("SELECT count(*) FROM project_theme_events WHERE source_id=:id"), {"id": source["id"]})
            == 3
        )


async def test_concurrent_candidate_publish_and_builtin_readonly(live_theme):
    """重复投递、并发候选和发布由PG锁及唯一性收敛。"""
    env = live_theme
    directory = (await env.client.get("/api/theme-sources")).json()["sources"]
    builtin = next(source for source in directory if source["kind"] == "builtin")
    r = await env.client.put(
        f"/api/theme-sources/{builtin['id']}/status", json={"status": "withdrawn", "reason": "无权"}
    )
    assert r.status_code == 403 and r.json()["detail"]["code"] == "builtin_readonly"
    r = await env.client.post("/api/theme-sources", json={"kind": "builtin", "name": "伪造"})
    assert r.status_code == 422
    r = await env.client.post("/api/theme-sources", json={"kind": "personal", "name": "并发"})
    source = r.json()
    raw = (BUILTIN / "default.theme.zip").read_bytes()
    responses = await asyncio.gather(
        *[
            env.client.put(f"/api/theme-sources/{source['id']}/candidate", params={"expected_revision": 0}, content=raw)
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    responses = await asyncio.gather(
        *[
            env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 1})
            for _ in range(2)
        ]
    )
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    async with env.db() as db:
        assert (
            await db.scalar(
                text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": source["id"]}
            )
            == 1
        )
    r = await env.client.post(f"/api/theme-sources/{source['id']}/cleanup")
    assert all(item["state"] == "referenced" for item in r.json()["files"])
    assert env.store.read(source["id"], hashlib.sha256(raw).hexdigest()) == raw


async def test_actual_database_failure_leaves_complete_orphan_and_preserves_reference(live_theme):
    """用真实PG拒绝更新制造失败，再回读原引用及完整孤儿。"""
    env = live_theme
    source, version, raw = await create_publish(env)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = {info.filename: archive.read(info) for info in archive.infolist()}
    theme = json.loads(items["theme.json"])
    theme["version"] = "1.1.0"
    items["theme.json"] = json.dumps(theme).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in items.items():
            archive.writestr(name, content)
    new_raw = output.getvalue()
    digest = hashlib.sha256(new_raw).hexdigest()
    async with env.db() as db:
        await db.execute(
            text("""CREATE FUNCTION reject_theme_candidate() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'synthetic database rejection'; END; $$ LANGUAGE plpgsql""")
        )
        await db.execute(
            text("""CREATE TRIGGER reject_theme_candidate BEFORE UPDATE ON project_theme_sources
            FOR EACH ROW EXECUTE FUNCTION reject_theme_candidate()""")
        )
        await db.commit()
    r = await env.client.put(
        f"/api/theme-sources/{source['id']}/candidate", params={"expected_revision": 1}, content=new_raw
    )
    assert r.status_code == 500
    async with env.db() as db:
        row = (
            await db.execute(
                text("SELECT candidate_digest,candidate_revision FROM project_theme_sources WHERE id=:id"),
                {"id": source["id"]},
            )
        ).first()
        assert row.candidate_digest == version["digest"] and row.candidate_revision == 1
        await db.execute(text("DROP TRIGGER reject_theme_candidate ON project_theme_sources"))
        await db.commit()
    assert env.store.read(source["id"], digest) == new_raw
    r = await env.client.get(f"/api/theme-sources/{source['id']}/audit")
    assert {item["digest"]: item["state"] for item in r.json()["files"]}[digest] == "orphan"
    r = await env.client.post(f"/api/theme-sources/{source['id']}/cleanup")
    assert {item["digest"]: item["state"] for item in r.json()["files"]}[digest] == "removed_orphan"
    assert env.store.read(source["id"], version["digest"]) == raw
    assert not (env.store.root / source["id"] / f"{digest}.zip").exists()


async def test_actual_process_interruption_before_atomic_link(live_theme):
    """真实子进程在发布link前停止并被杀，临时包不成为新可加载版本。"""
    import inspect
    import signal
    import sys

    env = live_theme
    source, version, raw = await create_publish(env)
    source_lines, start = inspect.getsourcelines(ThemeStore.put)
    line = start + next(i for i, item in enumerate(source_lines) if "os.link(" in item)
    script = """
import sys,os,signal,hashlib
from pathlib import Path
from yuxi.themes.packages import ThemeError
from yuxi.themes.store import ThemeStore
raw=sys.stdin.buffer.read()
def trace(frame,event,arg):
 if frame.f_code.co_filename.endswith('/themes/store.py') and event=='line' and frame.f_lineno==int(sys.argv[3]):
  print('fsynced-before-link',flush=True)
  os.kill(os.getpid(),signal.SIGSTOP)
 return trace
sys.settrace(trace)
ThemeStore(Path(sys.argv[1])).put(sys.argv[2],raw,hashlib.sha256(raw).hexdigest())
"""
    # 同摘要重放也走完整临时写；停止点位于原子link前，不替换生产文件原语。
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        str(env.store.root),
        source["id"],
        str(line),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        process.stdin.write(raw)
        await process.stdin.drain()
        process.stdin.close()
        assert (await asyncio.wait_for(process.stdout.readline(), 10)).strip() == b"fsynced-before-link"
        os.kill(process.pid, signal.SIGKILL)
        assert await process.wait() == -signal.SIGKILL
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    temporary = list((env.store.root / source["id"]).glob(".pending-*"))
    assert len(temporary) == 1 and temporary[0].read_bytes() == raw
    r = await env.client.get(f"/api/theme-sources/{source['id']}/audit")
    assert any(item["state"] == "temporary" for item in r.json()["files"])
    r = await env.client.post(f"/api/theme-sources/{source['id']}/cleanup")
    assert any(item["state"] == "removed_temporary" for item in r.json()["files"])
    assert env.store.read(source["id"], version["digest"]) == raw
    async with env.db() as db:
        assert (
            await db.scalar(
                text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": source["id"]}
            )
            == 1
        )


async def test_json_body_limit_and_native_project_owner_constraint(live_theme):
    """真实HTTP实际字节限额及替代数据库写入的归属拒绝。"""
    from sqlalchemy.exc import IntegrityError
    from yuxi.themes.packages import MAX_ARCHIVE_BYTES

    env = live_theme
    r = await env.client.post(
        "/api/theme-sources", content=b'{"name":"' + b"x" * MAX_ARCHIVE_BYTES + b'","kind":"personal"}'
    )
    assert r.status_code == 413 and r.json()["detail"]["code"] == "archive_limit"
    async with env.db() as db:
        with pytest.raises(IntegrityError, match="project_id_owner_uid_fkey"):
            await db.execute(
                text("""INSERT INTO project_theme_sources(id,kind,owner_uid,project_id,name)
                VALUES(:id,'project',:uid,:project,'wrong owner')"""),
                {"id": str(uuid.uuid4()), "uid": env.users[1].uid, "project": env.projects[0].id},
            )
        await db.rollback()


async def test_logical_alias_query_and_file_total_budget(live_theme):
    """alias不是路径段，保留S03允许的斜杠与原型字段名。"""
    from yuxi.themes.packages import MAX_MEMBER_BYTES

    env = live_theme
    source, _, raw = await create_publish(env, archive="research")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = {i.filename: archive.read(i) for i in archive.infolist()}
    manifest = json.loads(items["manifest.json"])
    theme = json.loads(items["theme.json"])
    asset = manifest["assets"].pop("distribution")
    manifest["assets"]["证据/图一"] = asset
    manifest["files"] = {"__proto__": "application/json"}
    theme["version"] = "alias-test"
    for page in theme["pages"]:
        for block in page["blocks"]:
            if block.get("binding", {}).get("alias") == "distribution":
                block["binding"]["alias"] = "证据/图一"
            if block.get("binding", {}).get("alias") == "survey":
                block["binding"]["alias"] = "__proto__"
    r = await env.client.put(
        f"/api/theme-sources/{source['id']}/definition",
        json={"manifest": manifest, "theme": theme, "expected_revision": 1},
    )
    assert r.status_code == 200, r.text
    r = await env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 2})
    version = r.json()
    r = await env.client.put(
        f"/api/projects/{env.projects[0].id}/theme",
        json={"version_id": version["id"], "files": {"__proto__": "/data.json"}, "expected_generation": 0},
    )
    assert r.status_code == 200, r.text
    r = await env.client.get(
        f"/api/projects/{env.projects[0].id}/theme/assets", params={"alias": "证据/图一", "expected_generation": 1}
    )
    assert r.status_code == 200 and r.content == items["assets/survey.png"]
    # 大文件校验不得把正确归属但超限描述成路径错误。
    (env.root / "large.json").write_bytes(b"x" * (MAX_MEMBER_BYTES + 1))
    r = await env.client.put(
        f"/api/projects/{env.projects[0].id}/theme",
        json={"version_id": version["id"], "files": {"__proto__": "/large.json"}, "expected_generation": 1},
    )
    assert r.status_code == 413 and r.json()["detail"]["code"] == "file_limit"


async def test_source_text_nul_rejection_and_normal_hex_names(live_theme):
    """拒绝PG不接受的NUL，同时保留普通x0名称及原因。"""
    env = live_theme
    r = await env.client.post("/api/theme-sources", json={"name": "x0 source", "kind": "personal"})
    assert r.status_code == 200, r.text
    source = r.json()
    r = await env.client.put(
        f"/api/theme-sources/{source['id']}/status", json={"status": "disabled", "reason": "x0 review"}
    )
    assert r.status_code == 200, r.text
    r = await env.client.post("/api/theme-sources", json={"name": "bad\x00name", "kind": "personal"})
    assert r.status_code == 422


async def test_copy_database_failure_retains_owned_recoverable_source(live_theme):
    """复制候选失败留下可授权来源，残留完整包可查可清。"""
    env = live_theme
    _, version, _ = await create_publish(env)
    async with env.db() as db:
        await db.execute(
            text("""CREATE FUNCTION reject_copy_candidate() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'synthetic copy failure'; END; $$ LANGUAGE plpgsql""")
        )
        await db.execute(
            text("""CREATE TRIGGER reject_copy_candidate BEFORE UPDATE ON project_theme_sources
            FOR EACH ROW EXECUTE FUNCTION reject_copy_candidate()""")
        )
        await db.commit()
    result = await env.client.post(
        "/api/theme-sources", json={"name": "复制失败可恢复", "kind": "personal", "copy_version_id": version["id"]}
    )
    assert result.status_code == 500 and result.json()["detail"]["code"] == "copy_incomplete"
    async with env.db() as db:
        source = (
            await db.execute(
                text(
                    "SELECT id,candidate_digest,candidate_revision FROM project_theme_sources "
                    "WHERE name='复制失败可恢复'"
                )
            )
        ).first()
        assert source and source.candidate_digest is None and source.candidate_revision == 0
        await db.execute(text("DROP TRIGGER reject_copy_candidate ON project_theme_sources"))
        await db.commit()
    assert source.id in result.json()["detail"]["message"]
    denied = await env.client.get(f"/api/theme-sources/{source.id}/audit", headers=env.headers[1])
    assert denied.status_code == 404
    audit = (await env.client.get(f"/api/theme-sources/{source.id}/audit")).json()
    assert len(audit["files"]) == 1 and audit["files"][0]["state"] == "orphan"
    cleanup = (await env.client.post(f"/api/theme-sources/{source.id}/cleanup")).json()
    assert cleanup["files"][0]["state"] == "removed_orphan"
    assert not list((env.store.root / source.id).iterdir())


async def test_compressed_candidate_edit_and_total_file_budget(live_theme):
    """接近单成员限额的压缩资源可编辑，总文件预算失败不改选择。"""
    from yuxi.themes.packages import MAX_MEMBER_BYTES

    env = live_theme
    source, _, raw = await create_publish(env)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = {item.filename: archive.read(item) for item in archive.infolist()}
    manifest = json.loads(items["manifest.json"])
    content = b'"' + b"x" * (MAX_MEMBER_BYTES - 3) + b'"'
    manifest["assets"] = {
        "large": {
            "path": "assets/large.json",
            "mediaType": "application/json",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    }
    manifest["files"] = {f"f{i}": "application/json" for i in range(5)}
    items["manifest.json"] = json.dumps(manifest).encode()
    items["assets/large.json"] = content
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in items.items():
            archive.writestr(name, data)
    response = await env.client.put(
        f"/api/theme-sources/{source['id']}/candidate", params={"expected_revision": 1}, content=output.getvalue()
    )
    assert response.status_code == 200, response.text
    theme = response.json()["package"]["theme"]
    theme["version"] = "compressed-edit"
    response = await env.client.put(
        f"/api/theme-sources/{source['id']}/definition",
        json={"manifest": manifest, "theme": theme, "expected_revision": 2},
    )
    assert response.status_code == 200, response.text
    response = await env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 3})
    assert response.status_code == 200, response.text
    version = response.json()
    assert version["size"] < MAX_MEMBER_BYTES
    (env.root / "large-valid.json").write_bytes(content)
    response = await env.client.put(
        f"/api/projects/{env.projects[0].id}/theme",
        json={
            "version_id": version["id"],
            "files": {f"f{i}": "/large-valid.json" for i in range(5)},
            "expected_generation": 0,
        },
    )
    assert response.status_code == 413 and response.json()["detail"]["code"] == "file_binding_limit"
    async with env.db() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_theme_bindings")) == 0


async def test_resource_waiting_for_source_lock_rechecks_project_generation(live_theme):
    """旧资源请求等待来源锁时改选另一来源，恢复后明确409。"""
    env = live_theme
    source, version, _ = await create_publish(env, archive="research")
    project = env.projects[0].id
    selected = await env.client.put(
        f"/api/projects/{project}/theme",
        json={"version_id": version["id"], "files": {"survey": "/data.json"}, "expected_generation": 0},
    )
    assert selected.status_code == 200
    catalog = (await env.client.get("/api/theme-sources")).json()
    default = next(
        s["versions"][0] for s in catalog["sources"] if s["kind"] == "builtin" and s["status"] == "active" and s["versions"][0]["size"] < 2000
    )
    async with env.db() as locker:
        owner = await locker.scalar(text("SELECT pg_backend_pid()"))
        await locker.execute(text("SELECT id FROM project_theme_sources WHERE id=:id FOR UPDATE"), {"id": source["id"]})
        pending = asyncio.create_task(
            env.client.get(
                f"/api/projects/{project}/theme/assets", params={"alias": "distribution", "expected_generation": 1}
            )
        )
        try:
            blocked = False
            async with env.db() as observer:
                for _ in range(100):
                    blocked = bool(
                        await observer.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE :owner=ANY(pg_blocking_pids(pid)))"
                            ),
                            {"owner": owner},
                        )
                    )
                    if blocked:
                        break
                    await asyncio.sleep(0.05)
            assert blocked, "真实HTTP必须已等待原来源锁"
            changed = await env.client.put(
                f"/api/projects/{project}/theme",
                json={"version_id": default["id"], "files": {}, "expected_generation": 1},
            )
            assert changed.status_code == 200 and changed.json()["generation"] == 2
        finally:
            await locker.rollback()
        response = await asyncio.wait_for(pending, 10)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "binding_conflict"
    async with env.db() as db:
        bound = (
            await db.execute(
                text("SELECT version_id,generation FROM project_theme_bindings WHERE project_id=:id"), {"id": project}
            )
        ).first()
        assert bound.version_id == default["id"] and bound.generation == 2


async def test_project_file_bytes_errors_and_binding_scope(live_theme):
    """读取只认当前alias，独立字节与协议metadata一致。"""
    env = live_theme
    _, version, _ = await create_publish(env, archive="research")
    a, b = env.projects[:2]
    body = {"version_id": version["id"], "files": {"survey": "/data.json"}, "expected_generation": 0}
    assert (await env.client.put(f"/api/projects/{a.id}/theme", json=body)).status_code == 200
    path = f"/api/projects/{a.id}/theme/files"
    query = {"expected_generation": 1, "alias": "survey"}
    r = await env.client.get(path, params=query)
    assert r.content == env.root.joinpath("data.json").read_bytes()
    assert r.headers["x-theme-sha256"] == hashlib.sha256(r.content).hexdigest()
    assert r.headers["x-theme-size"] == str(len(r.content))
    assert r.headers["content-type"] == "application/json"
    assert r.headers["cache-control"] == "no-store, private"
    assert r.headers["x-content-type-options"] == "nosniff"
    env.root.joinpath("data.json").write_bytes(b'{"samples":25}')
    refreshed = await env.client.get(path, params=query)
    assert refreshed.content == b'{"samples":25}'
    assert refreshed.headers["x-theme-sha256"] != r.headers["x-theme-sha256"]
    for params, headers, code in (
        ({**query, "path": "/data.json"}, None, "file_query"),
        ({**query, "alias": "../../data.json"}, None, "file_alias"),
        ({**query, "expected_generation": 2}, None, "binding_conflict"),
        (query, env.headers[1], "project_denied"),
    ):
        failure = await env.client.get(path, params=params, headers=headers)
        assert failure.json()["detail"]["code"] == code
        assert b"samples" not in failure.content
    missing_binding = await env.client.get(f"/api/projects/{b.id}/theme/files", params=query)
    assert missing_binding.json()["detail"]["code"] == "binding_unbound"
    env.root.joinpath("data.json").unlink()
    failure = await env.client.get(path, params=query)
    assert failure.json()["detail"]["code"] == "file_missing"
    env.root.joinpath("data.json").symlink_to(env.root / "bad.json")
    failure = await env.client.get(path, params=query)
    assert failure.json()["detail"]["code"] in {"file_denied", "file_boundary"}
    env.root.joinpath("data.json").unlink()
    env.root.joinpath("data.json").write_bytes(b"not-json")
    failure = await env.client.get(path, params=query)
    assert failure.json()["detail"]["code"] == "invalid_json"
    env.root.joinpath("data.json").write_bytes(b'{"samples":12}')
    async with env.db() as db:
        await db.execute(text("UPDATE project_theme_bindings SET files='{}'::jsonb WHERE project_id=:id"), {"id": a.id})
        await db.commit()
    failure = await env.client.get(path, params=query)
    assert failure.json()["detail"]["code"] == "file_unbound"
    async with env.db() as db:
        await db.execute(
            text("UPDATE project_theme_bindings SET files=CAST(:files AS jsonb) WHERE project_id=:id"),
            {"id": a.id, "files": json.dumps({"survey": "/../bad.json"})},
        )
        await db.commit()
    failure = await env.client.get(path, params=query)
    assert failure.json()["detail"]["code"] == "file_boundary"


async def test_live_business_pages_scope_filter_comments_and_formal_tasks(live_theme):
    """真实HTTP创建原业务，SQL独立核对分页与准确对象。"""
    env = live_theme
    a, b = env.projects[:2]
    base = f"/api/projects/{a.id}"
    topics = []
    for index in range(24):
        r = await env.client.post(
            base + "/governance/topics",
            json={"title": f"分页议题 {index:02d}", "summary": "合成业务", "source_channel": "project"},
        )
        assert r.status_code == 200, r.text
        topics.append(r.json())
    other = await env.client.post(
        f"/api/projects/{b.id}/governance/topics", json={"title": "另一项目", "source_channel": "project"}
    )
    assert other.status_code == 200, other.text
    other_id = other.json()["id"]
    first_id = topics[0]["id"]
    for title in ["准确讨论一", "准确讨论二"]:
        r = await env.client.post(base + f"/governance/topics/{first_id}/comments", json={"content": title})
        assert r.status_code == 200, r.text
    decision = await env.client.post(
        base + "/governance/decisions", json={"title": "真实草案", "conclusion": "待办理", "topic_id": first_id}
    )
    assert decision.status_code == 200, decision.text
    assert (await env.client.put(base + "/work/code", json={"code": "S05"})).status_code == 200
    assert (await env.client.put(base + f"/work/topics/{first_id}/code", json={"code": "CHK"})).status_code == 200
    work = await env.client.post(base + "/work/tasks", json={"title": "正式工作", "topic_id": first_id})
    assert work.status_code == 200, work.text
    suggestion = await env.client.post(base + "/governance/tasks", json={"title": "工作建议", "topic_id": first_id})
    assert suggestion.status_code == 200, suggestion.text
    r = await env.client.get(base + "/governance/topics-page", params={"offset": 20, "limit": 20})
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 4 and r.json()["pagination"]["total"] == 24
    assert all(item["project_id"] == a.id for item in r.json()["items"])
    r = await env.client.get(base + "/governance/topics-page", params={"search": "23", "limit": 1})
    assert [item["id"] for item in r.json()["items"]] == [topics[23]["id"]]
    assert r.json()["pagination"]["total"] == 1
    r = await env.client.get(base + "/governance/summary")
    assert r.json()["counts"] == {"topics": 24, "approvedDecisions": 0, "workTasks": 1, "blockedTasks": 0}
    async with env.db() as db:
        assert (
            await db.scalar(text("SELECT count(*) FROM governance_topics WHERE project_id=:id"), {"id": a.id})
            == r.json()["counts"]["topics"]
        )
    r = await env.client.get(base + "/work/tasks-page")
    assert [item["id"] for item in r.json()["items"]] == [work.json()["id"]]
    assert suggestion.json()["id"] not in str(r.json())
    r = await env.client.get(base + f"/governance/topics/{first_id}/comments-page", params={"limit": 1})
    assert r.json()["contextTopic"]["id"] == first_id
    assert r.json()["pagination"]["total"] == 2 and len(r.json()["items"]) == 1
    assert r.json()["items"][0]["topic_id"] == first_id
    for endpoint, status in (("/governance/topics-page", "closed"), ("/work/tasks-page", "done")):
        filtered = await env.client.get(base + endpoint, params={"statuses": status})
        assert filtered.json()["items"] == [] and filtered.json()["pagination"]["total"] == 0
    filtered = await env.client.get(base + "/work/tasks-page", params=[("statuses", "todo"), ("statuses", "blocked")])
    assert filtered.json()["items"][0]["id"] == work.json()["id"]
    assert filtered.json()["pagination"]["total"] == 1
    wrong_topic = await env.client.get(base + f"/governance/topics/{topics[1]['id']}/comments-page")
    assert wrong_topic.json()["items"] == []
    assert wrong_topic.json()["contextTopic"]["id"] == topics[1]["id"]
    for path in (
        f"/governance/topics/{other_id}/comments-page",
        f"/governance/topics/{other_id}",
        f"/work/tasks-page?topic_id={other_id}",
        f"/governance/decisions-page?topic_id={other_id}",
    ):
        r = await env.client.get(base + path)
        assert r.status_code == 404, r.text
    for path in ("/governance/summary", "/governance/topics-page", "/governance/decisions-page", "/work/tasks-page"):
        assert (await env.client.get(base + path, headers=env.headers[1])).status_code == 404
    for params in ({"limit": 101}, {"offset": -1}, {"progress": "approved"}):
        assert (await env.client.get(base + "/governance/topics-page", params=params)).status_code == 422
    r = await env.client.get(base + "/governance/decisions-page", params={"statuses": "approved"})
    assert r.json()["items"] == [] and r.json()["pagination"]["total"] == 0


async def test_bound_png_actual_bytes_and_type_no_conversation(live_theme):
    """第三份合法定义读取指定PNG，类型按实际解码且不创建会话。"""
    env = live_theme
    source, _, raw = await create_publish(env, archive="research")
    pack = (await env.client.get(f"/api/theme-sources/{source['id']}/candidate")).json()["package"]
    pack["theme"]["version"] = "s05-file-png"
    pack["manifest"]["files"] = {"chart": "image/png"}
    pack["theme"]["pages"][1]["blocks"][1] = {
        "id": "chart",
        "type": "image",
        "title": "实际指定PNG",
        "region": "main",
        "binding": {"kind": "file", "alias": "chart"},
        "alt": "当前项目文件",
    }
    r = await env.client.put(
        f"/api/theme-sources/{source['id']}/definition",
        json={"expected_revision": 1, "manifest": pack["manifest"], "theme": pack["theme"]},
    )
    assert r.status_code == 200, r.text
    version = await env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 2})
    assert version.status_code == 200, version.text
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        png = archive.read(pack["manifest"]["assets"]["distribution"]["path"])
    env.root.joinpath("chart.png").write_bytes(png)
    base = f"/api/projects/{env.projects[0].id}/theme"
    r = await env.client.put(
        base, json={"version_id": version.json()["id"], "expected_generation": 0, "files": {"chart": "/chart.png"}}
    )
    assert r.status_code == 200, r.text
    query = {"alias": "chart", "expected_generation": 1}
    r = await env.client.get(base + "/files", params=query)
    assert r.content == png == env.root.joinpath("chart.png").read_bytes()
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-theme-size"] == str(len(png))
    assert r.headers["x-theme-sha256"] == hashlib.sha256(png).hexdigest()
    env.root.joinpath("chart.png").write_bytes(b"{}")
    r = await env.client.get(base + "/files", params=query)
    assert r.json()["detail"]["code"] == "invalid_png"
    env.root.joinpath("chart.png").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    r = await env.client.get(base + "/files", params=query)
    assert r.json()["detail"]["code"] == "file_limit" and r.status_code == 413
    async with env.db() as db:
        assert await db.scalar(text("SELECT count(*) FROM conversations")) == 0


async def test_complete_workspace_theme_abi2_preserves_binding_and_immutable_versions(live_theme):
    """ABI增量迁移幂等；旧绑定、字节与新发布版本均可回读。"""
    env = live_theme
    source, version, raw = await create_publish(env)
    project = env.projects[0].id
    response = await env.client.put(f"/api/projects/{project}/theme", json={"version_id": version["id"], "files": {}, "expected_generation": 0})
    assert response.status_code == 200, response.text
    before = response.json()
    await env.manager.upgrade_yuanlei_schema_v40_to_v41()
    await env.manager.upgrade_yuanlei_schema_v40_to_v41()
    after = (await env.client.get(f"/api/projects/{project}/theme")).json()
    assert after["binding"] == before["binding"]
    assert after["generation"] == before["generation"]
    assert after["package"]["digest"] == hashlib.sha256(raw).hexdigest()
    catalog = (await env.client.get(f"/api/theme-sources?project_id={project}")).json()
    complete = next(s for s in catalog["sources"] if s["name"] == "默认 · 项目管理" and s["status"] == "disabled")
    loaded = (await env.client.get(f"/api/theme-versions/{complete['versions'][0]['id']}?project_id={project}")).json()
    assert loaded["manifest"]["componentAbi"] == 2
    assert loaded["theme"]["baseVersion"] == 1
    assert {page["capability"] for page in loaded["theme"]["pages"]} == {"overview", "blueprints", "topics", "plans", "work", "inspection", "files", "agents", "settings"}


async def test_project_files_http_scope_roundtrip_and_negative_boundaries(live_theme):
    """真实HTTP/PG/文件验证项目范围，越界与失权不会落盘。"""
    env = live_theme
    base = f"/api/projects/{env.projects[0].id}/files"
    result = await env.client.get(base)
    assert result.status_code == 200, result.text
    assert any(row["path"] == "/data.json" for row in result.json()["entries"])
    result = await env.client.post(base + "/directory", json={"parent_path": "/", "name": "story"})
    assert result.status_code == 200, result.text
    result = await env.client.post(base + "/upload", data={"parent_path": "/story"}, files=[("files", ("story.md", "# 故事初稿\n".encode(), "text/markdown"))])
    assert result.status_code == 200, result.text
    assert (env.root / "story/story.md").read_text() == "# 故事初稿\n"
    result = await env.client.put(base + "/content", json={"path": "/story/story.md", "content": "# 真实回读\n"})
    assert result.status_code == 200, result.text
    assert (env.root / "story/story.md").read_text() == "# 真实回读\n"
    result = await env.client.get(base + "/content", params={"path": "/story/story.md"})
    assert result.status_code == 200 and "真实回读" in result.text
    for path in ("/../outside.md", "/story/../../outside.md", "\\outside.md"):
        denied = await env.client.put(base + "/content", json={"path": path, "content": "bad"})
        assert denied.status_code == 400, denied.text
    for path in ("//", "/"):
        denied = await env.client.delete(base, params={"path": path})
        assert denied.status_code in (400, 422), denied.text
        assert env.root.is_dir()
    denied = await env.client.get(base + "/content", params={"path": "/link.json"})
    assert denied.status_code == 403
    denied = await env.client.get(base, headers=env.headers[1])
    assert denied.status_code == 404
    denied = await env.client.put(base + "/content", headers=env.headers[1], json={"path": "/story/story.md", "content": "foreign"})
    assert denied.status_code == 404
    assert (env.root / "story/story.md").read_text() == "# 真实回读\n"
    assert not (env.root.parent / "outside.md").exists()


async def test_project_activity_uses_real_event_identity_and_authorization(live_theme):
    """最近动态混合原历史事实，评论和决定均返回准确来源。"""
    env = live_theme
    base = f"/api/projects/{env.projects[0].id}/governance"
    topic = (await env.client.post(base + "/topics", json={"title": "开放方案", "summary": "正文常驻", "source_channel": "project"})).json()
    comment = await env.client.post(base + f"/topics/{topic['id']}/comments", json={"content": "先试运营两周", "discussion_type": "discussion"})
    assert comment.status_code == 200, comment.text
    comment_id = comment.json()["id"]
    decision = await env.client.post(base + "/decisions", json={"title": "试运营方案", "conclusion": "采用两周试点", "topic_id": topic["id"]})
    assert decision.status_code == 200, decision.text
    activity = await env.client.get(base + "/activity")
    assert activity.status_code == 200, activity.text
    items = activity.json()["items"]
    assert any(item["kind"] == "comment" and item["id"] == comment_id and item["comment_id"] == comment_id and item["topic_id"] == topic["id"] for item in items)
    assert any(item["kind"] == "decision" and item["id"] == decision.json()["id"] for item in items)
    assert len({item["event_key"] for item in items}) == len(items)
    denied = await env.client.get(base + "/activity", headers=env.headers[1])
    assert denied.status_code == 404
    async with env.db() as db:
        assert await db.scalar(text("SELECT content FROM governance_topic_comments WHERE id=:id"), {"id": comment_id}) == "先试运营两周"


@pytest.mark.asyncio
async def test_activity_excludes_deleted_independent_decision(live_theme):
    """软删除草案不得在当前动态中复活。"""
    env = live_theme
    base = f"/api/projects/{env.projects[0].id}/governance"
    created = await env.client.post(base + "/decisions", json={"title":"无来源测试草案", "conclusion":"可撤回合成内容"})
    assert created.status_code == 200, created.text
    row = created.json()
    before = (await env.client.get(base + "/activity")).json()["items"]
    assert any(item["id"] == row["id"] and item["topic_id"] is None and item["author_name"] == env.users[0].username for item in before)
    deleted = await env.client.post(base + f"/decisions/{row['id']}/operations", json={"action":"delete","reason":"隔离测试删除草案", "expected_revision":row["revision_number"]})
    assert deleted.status_code == 200, deleted.text
    after = (await env.client.get(base + "/activity")).json()["items"]
    assert not any(item["id"] == row["id"] for item in after)
    async with env.db() as db:
        assert await db.scalar(text("SELECT deleted_at IS NOT NULL FROM governance_decisions WHERE id=:id"), {"id":row["id"]})


async def test_selection_preflight_is_read_only_and_shares_final_guards(live_theme):
    """只读预检解释条件，不推进绑定；实际应用仍拒绝过期及非法文件。"""
    env = live_theme
    project = env.projects[0].id
    _, research, _ = await create_publish(env, archive='research')
    path = f'/api/projects/{project}/theme'
    body = {'version_id': research['id'], 'expected_generation': 0, 'files': {'survey': '/data.json'}}
    preview = await env.client.post(path + '/check', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['selectable'] is True
    async with env.db() as db:
        count = await db.scalar(text('SELECT count(*) FROM project_theme_bindings WHERE project_id=:id'), {'id': project})
        assert count == 0
    invalid = {**body, 'files': {'survey': '/bad.json'}}
    refused = await env.client.post(path + '/check', json=invalid)
    assert refused.status_code == 200 and not refused.json()['selectable']
    assert refused.json()['error']['alias'] == 'survey'
    saved = await env.client.put(path, json=body)
    assert saved.status_code == 200
    stale = await env.client.post(path + '/check', json=body)
    assert stale.status_code == 200 and stale.json()['error']['code'] == 'binding_conflict'
    denied = await env.client.post(path + '/check', json={**body, 'expected_generation': 1}, headers=env.headers[1])
    assert denied.status_code == 404
    unchanged = (await env.client.get(path)).json()
    assert unchanged['generation'] == 1 and unchanged['binding']['files'] == body['files']


async def test_current_samples_retire_history_without_replacing_project_bindings(live_theme):
    """当前目录三主题、旧选择保留与真实ABI3包由HTTP及PG共同证明。"""
    env = live_theme
    project, other = [item.id for item in env.projects[:2]]
    catalog = (await env.client.get('/api/theme-sources')).json()['sources']
    current = [source for source in catalog if source['kind'] == 'builtin' and source['status'] == 'active']
    assert {source['name'] for source in current} == {'默认 · 项目管理', '精简 · 专注推进', '调研 · 阅读工作室'}
    legacy = next(source for source in catalog if source['name'] == '默认 · 日常管理')
    old = legacy['versions'][0]
    async with env.db() as db:
        # 模拟部署前已经持久选择早期主题的项目，随后由正式登记重跑证明不迁移。
        await db.execute(text('INSERT INTO project_theme_bindings(project_id,version_id,files,generation,updated_by) VALUES (:p,:v,CAST(:files AS JSONB),7,:uid)'), {'p':project,'v':old['id'],'files':'{}','uid':env.users[0].uid})
        await db.commit()
        await install_builtin_themes(db)
        await install_builtin_themes(db)
    retained = (await env.client.get(f'/api/projects/{project}/theme')).json()
    assert retained['generation'] == 7 and retained['binding']['version_id'] == old['id']
    assert retained['state'] == 'ready' and retained['package']['digest'] == old['digest']
    refused = await env.client.put(f'/api/projects/{other}/theme', json={'version_id':old['id'],'files':{},'expected_generation':0})
    assert refused.status_code == 409 and refused.json()['detail']['code'] == 'source_disabled'
    for index, name in enumerate(['精简 · 专注推进','调研 · 阅读工作室','默认 · 项目管理'],8):
        source = next(source for source in current if source['name'] == name)
        version = source['versions'][0]
        saved = await env.client.put(f'/api/projects/{project}/theme',json={'version_id':version['id'],'files':{},'expected_generation':index-1})
        assert saved.status_code == 200, saved.text
        read = (await env.client.get(f'/api/projects/{project}/theme')).json()
        assert read['generation'] == index and read['binding']['version_id'] == version['id']
        raw = (BUILTIN / ({'默认 · 项目管理':'current-default','精简 · 专注推进':'current-focus','调研 · 阅读工作室':'current-research'}[name]+'.theme.zip')).read_bytes()
        assert read['package']['digest'] == hashlib.sha256(raw).hexdigest()
        assert read['package']['manifest']['componentAbi'] == 3
        async with env.db() as db:
            row = (await db.execute(text('SELECT version_id,generation FROM project_theme_bindings WHERE project_id=:p'), {'p':project})).mappings().one()
            assert row['version_id'] == version['id'] and row['generation'] == index
        assert (await env.client.get(f'/api/projects/{other}/theme')).json()['generation'] == 0


async def test_authoring_private_source_denies_foreign_copy_edit_and_publish(live_theme):
    """他人主题制作与复制均拒绝，不创建身份或改候选、发布历史。"""
    env = live_theme
    source, version, raw = await create_publish(env)
    candidate = (await env.client.get(f"/api/theme-sources/{source['id']}/candidate")).json()
    async with env.db() as db:
        before = await db.scalar(text("SELECT count(*) FROM project_theme_sources"))
    denied = env.headers[1]
    response = await env.client.get(f"/api/theme-sources/{source['id']}/candidate", headers=denied)
    assert response.status_code == 404
    response = await env.client.put(
        f"/api/theme-sources/{source['id']}/definition",
        headers=denied,
        json={
            "expected_revision": 1,
            "manifest": candidate["package"]["manifest"],
            "theme": candidate["package"]["theme"],
        },
    )
    assert response.status_code == 404
    response = await env.client.post(
        f"/api/theme-sources/{source['id']}/publish",
        json={"expected_revision": 1},
        headers=denied,
    )
    assert response.status_code == 404
    response = await env.client.post(
        "/api/theme-sources",
        headers=denied,
        json={"name": "无权副本", "kind": "personal", "copy_version_id": version["id"]},
    )
    assert response.status_code == 404
    async with env.db() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_theme_sources")) == before
        row = (
            await db.execute(
                text("SELECT candidate_digest,candidate_revision FROM project_theme_sources WHERE id=:id"),
                {"id": source["id"]},
            )
        ).one()
        assert row.candidate_revision == 1 and row.candidate_digest == version["digest"]
    assert env.store.read(source["id"], version["digest"]) == raw


async def test_mixed_preview_files_exact_revision_and_workdir(live_theme):
    """混合定义在不应用时读取真实文件，引用、越界及失权均拒绝。"""
    env = live_theme
    source, _, _ = await create_publish(env, archive="current-research")
    path = f"/api/theme-sources/{source['id']}"
    candidate = (await env.client.get(path + "/candidate")).json()["package"]
    candidate["theme"]["version"] = "3.1-evidence"
    candidate["manifest"]["files"] = {"facts": "application/json", "chart": "image/png"}
    candidate["theme"]["pages"].append(
        {
            "id": "project-evidence",
            "title": "项目证据",
            "description": "Project级资料",
            "layout": "reading",
            "blocks": [
                {
                    "id": "facts",
                    "type": "json",
                    "title": "资料",
                    "region": "main",
                    "binding": {"kind": "file", "alias": "facts"},
                },
                {
                    "id": "chart",
                    "type": "image",
                    "title": "图示",
                    "region": "aside",
                    "binding": {"kind": "file", "alias": "chart"},
                    "alt": "项目图示",
                },
            ],
        }
    )
    saved = await env.client.put(
        path + "/definition",
        json={
            "expected_revision": 1,
            "manifest": candidate["manifest"],
            "theme": candidate["theme"],
        },
    )
    assert saved.status_code == 200, saved.text
    base = f"/api/projects/{env.projects[0].id}/theme"
    body = {
        "source_id": source["id"],
        "revision": 2,
        "expected_generation": 0,
        "files": {"facts": "/data.json"},
        "alias": "facts",
    }
    before = (await env.client.get(base)).json()
    for raw in (b'{"samples":12}', b'{"samples":34}'):
        env.root.joinpath("data.json").write_bytes(raw)
        result = await env.client.post(base + "/preview-file", json=body)
        assert result.status_code == 200, result.text
        assert result.content == env.root.joinpath("data.json").read_bytes() == raw
        assert result.headers["x-theme-sha256"] == hashlib.sha256(raw).hexdigest()
    for extra, code in [
        ({"revision": 1}, "candidate_conflict"),
        ({"expected_generation": 1}, "binding_conflict"),
        ({"alias": "unknown"}, "file_alias"),
        ({"files": {}}, "file_unbound"),
        ({"files": {"unknown": "/data.json"}}, "file_mapping"),
        ({"files": {"facts": "/missing.json"}}, "file_missing"),
        ({"files": {"facts": "/bad.json"}}, "invalid_json"),
        ({"files": {"facts": "/link.json"}}, "file_denied"),
        ({"files": {"facts": "/../data.json"}}, "file_boundary"),
    ]:
        result = await env.client.post(base + "/preview-file", json={**body, **extra})
        assert result.json()["detail"]["code"] == code, result.text
    env.root.joinpath("large.json").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    result = await env.client.post(base + "/preview-file", json={**body, "files": {"facts": "/large.json"}})
    assert result.status_code == 413 and result.json()["detail"]["code"] == "file_limit"
    foreign = await env.client.post(base + "/preview-file", json=body, headers=env.headers[1])
    assert foreign.status_code == 404 and foreign.json()["detail"]["code"] == "project_denied"
    foreign_source = await env.client.post(
        f"/api/projects/{env.projects[2].id}/theme/preview-file", json=body, headers=env.headers[1]
    )
    assert foreign_source.status_code == 404 and foreign_source.json()["detail"]["code"] == "source_denied"
    malformed = await env.client.post(base + "/preview-file", json={**body, "version_id": "v"})
    assert malformed.status_code == 422
    from PIL import Image

    for color in ["red", "blue"]:
        png = io.BytesIO()
        Image.new("RGB", (20, 10), color).save(png, format="PNG")
        env.root.joinpath("chart.png").write_bytes(png.getvalue())
        result = await env.client.post(
            base + "/preview-file",
            json={
                **body,
                "alias": "chart",
                "files": {"chart": "/chart.png"},
            },
        )
        assert result.status_code == 200 and result.content == png.getvalue()
        assert result.headers["x-theme-sha256"] == hashlib.sha256(png.getvalue()).hexdigest()
    env.root.joinpath("chart.png").write_bytes(b"{}")
    result = await env.client.post(
        base + "/preview-file",
        json={
            **body,
            "alias": "chart",
            "files": {"chart": "/chart.png"},
        },
    )
    assert result.json()["detail"]["code"] == "invalid_png"
    version = (await env.client.post(path + "/publish", json={"expected_revision": 2})).json()
    published = {k: v for k, v in body.items() if k not in {"source_id", "revision"}}
    published["version_id"] = version["id"]
    assert (await env.client.post(base + "/preview-file", json=published)).content == b'{"samples":34}'
    assert (await env.client.get(base)).json() == before
    async with env.db() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_theme_bindings")) == 0


def variant_package(raw, *, name):
    """构造同版本异字节的合法包，供版本冲突负例使用。"""
    return changed_theme(raw, name=name)


def changed_theme(raw, **changes):
    """只改theme.json的合法变体，供长度与冲突负例使用。"""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for member in archive.infolist():
            data = archive.read(member)
            if member.filename == "theme.json":
                definition = json.loads(data)
                definition.update(changes)
                data = json.dumps(definition, ensure_ascii=False).encode()
            target.writestr(member, data)
    return output.getvalue()


async def test_version_package_export_original_bytes_and_authorization(live_theme):
    """已发布版本按原ZIP下载；越权、撤回、缺包拒绝且不改绑定。"""
    env = live_theme
    source, version, raw = await create_publish(env)
    project = env.projects[0]
    assert (await env.client.put(
        f"/api/projects/{project.id}/theme",
        json={"version_id": version["id"], "files": {}, "expected_generation": 0},
    )).status_code == 200
    response = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert response.status_code == 200, response.text
    assert response.content == raw
    assert response.headers["x-theme-sha256"] == version["digest"]
    assert response.headers["x-theme-size"] == str(len(raw))
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert ".theme.zip" in response.headers["content-disposition"]
    denied = await env.client.get(f"/api/theme-versions/{version['id']}/package", headers=env.headers[1])
    assert denied.status_code == 404 and denied.json()["detail"]["code"] == "source_denied"
    path = f"/api/theme-sources/{source['id']}/status"
    assert (await env.client.put(path, json={"status": "withdrawn", "reason": "导出负例"})).status_code == 200
    withdrawn = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert withdrawn.status_code == 409 and withdrawn.json()["detail"]["code"] == "source_withdrawn"
    assert (await env.client.put(path, json={"status": "active", "reason": "恢复导出"})).status_code == 200
    assert (await env.client.put(path, json={"status": "disabled", "reason": "停用仍可读"})).status_code == 200
    disabled = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert disabled.status_code == 200 and disabled.content == raw
    assert (await env.client.put(path, json={"status": "active", "reason": "恢复导出"})).status_code == 200
    target = env.store.root / source["id"] / f"{version['digest']}.zip"
    target.unlink()
    missing = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "package_missing"
    env.store.put(source["id"], raw, version["digest"])
    os.chmod(target, 0o600)
    target.write_bytes(b"tampered")
    corrupt = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert corrupt.status_code == 409 and corrupt.json()["detail"]["code"] == "package_corrupt"
    target.unlink()
    env.store.put(source["id"], raw, version["digest"])
    project_source, project_version, project_raw = await create_publish(env, kind="project", name="项目导出")
    own = await env.client.get(
        f"/api/theme-versions/{project_version['id']}/package", params={"project_id": project.id}
    )
    assert own.status_code == 200 and own.content == project_raw
    foreign = await env.client.get(
        f"/api/theme-versions/{project_version['id']}/package", params={"project_id": env.projects[1].id}
    )
    assert foreign.status_code == 404 and foreign.json()["detail"]["code"] == "source_denied"
    unscoped = await env.client.get(f"/api/theme-versions/{project_version['id']}/package")
    assert unscoped.status_code == 404 and unscoped.json()["detail"]["code"] == "source_denied"
    binding = (await env.client.get(f"/api/projects/{project.id}/theme")).json()
    assert binding["binding"]["version_id"] == version["id"] and binding["generation"] == 1


async def test_import_preflight_then_target_draft_preview_publish_and_assign(live_theme):
    """A原包导出后只读预检，B保存草稿再显式发布／分配；A绑定不变。"""
    env = live_theme
    source, _, _ = await create_publish(env, archive="current-research")
    path = f"/api/theme-sources/{source['id']}"
    candidate = (await env.client.get(path + "/candidate")).json()["package"]
    declared_source = candidate["manifest"]["source"]
    candidate["theme"]["version"] = "3.1-portable"
    candidate["theme"]["name"] = "迁移混合证据"
    candidate["manifest"]["files"] = {"facts": "application/json"}
    candidate["theme"]["pages"].append(
        {
            "id": "portable-evidence",
            "title": "迁移证据",
            "description": "目标项目资料",
            "layout": "reading",
            "blocks": [
                {
                    "id": "facts",
                    "type": "json",
                    "title": "资料",
                    "region": "main",
                    "binding": {"kind": "file", "alias": "facts"},
                }
            ],
        }
    )
    saved = await env.client.put(
        path + "/definition",
        json={"expected_revision": 1, "manifest": candidate["manifest"], "theme": candidate["theme"]},
    )
    assert saved.status_code == 200, saved.text
    published = (await env.client.post(path + "/publish", json={"expected_revision": 2})).json()
    exported = await env.client.get(f"/api/theme-versions/{published['id']}/package")
    assert exported.status_code == 200
    raw = exported.content
    assert hashlib.sha256(raw).hexdigest() == published["digest"]

    async with env.db() as db:
        before = {
            "sources": await db.scalar(text("SELECT count(*) FROM project_theme_sources")),
            "versions": await db.scalar(text("SELECT count(*) FROM project_theme_versions")),
            "bindings": await db.scalar(text("SELECT count(*) FROM project_theme_bindings")),
        }
    preflight = await env.client.post("/api/theme-imports/preflight", content=raw)
    assert preflight.status_code == 200, preflight.text
    summary = preflight.json()
    assert summary["compatible"] is True
    assert summary["digest"] == published["digest"] and summary["size"] == len(raw)
    assert summary["manifest"] == {"formatVersion": 1, "componentAbi": 3, "source": declared_source}
    assert summary["theme"]["version"] == "3.1-portable"
    assert summary["files"] == [{"alias": "facts", "mediaType": "application/json"}]
    assert any(page["id"] == "portable-evidence" for page in summary["pages"])
    async with env.db() as db:
        after_preflight = {
            "sources": await db.scalar(text("SELECT count(*) FROM project_theme_sources")),
            "versions": await db.scalar(text("SELECT count(*) FROM project_theme_versions")),
            "bindings": await db.scalar(text("SELECT count(*) FROM project_theme_bindings")),
        }
    assert after_preflight == before

    imported = await env.client.post(
        "/api/theme-imports",
        params={"digest": summary["digest"], "name": "B迁移草稿"},
        content=raw,
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["created"] is True and result["version_state"] == "new_source"
    assert result["source"]["kind"] == "personal" and result["source"]["candidate_revision"] == 1
    assert result["source"]["candidate_digest"] == summary["digest"]
    assert result["package"]["digest"] == summary["digest"]
    assert env.store.read(result["source"]["id"], summary["digest"]) == raw
    async with env.db() as db:
        assert await db.scalar(
            text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": result["source"]["id"]}
        ) == 0
        assert await db.scalar(text("SELECT count(*) FROM project_theme_bindings")) == before["bindings"]

    target = env.projects[1]
    preview = await env.client.post(
        f"/api/projects/{target.id}/theme/preview-file",
        json={
            "source_id": result["source"]["id"],
            "revision": result["source"]["candidate_revision"],
            "expected_generation": 0,
            "files": {"facts": "/data.json"},
            "alias": "facts",
        },
    )
    assert preview.status_code == 200 and preview.content == b'{"samples":12}'
    publish = await env.client.post(
        f"/api/theme-sources/{result['source']['id']}/publish", json={"expected_revision": 1}
    )
    assert publish.status_code == 200, publish.text
    target_version = publish.json()
    assert target_version["digest"] == summary["digest"]
    selected = await env.client.put(
        f"/api/projects/{target.id}/theme",
        json={"version_id": target_version["id"], "files": {"facts": "/data.json"}, "expected_generation": 0},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["generation"] == 1
    assert (await env.client.get(f"/api/projects/{env.projects[0].id}/theme")).json()["generation"] == 0
    rebound = await env.client.get(
        f"/api/theme-versions/{target_version['id']}/package", params={"project_id": target.id}
    )
    assert rebound.content == raw and rebound.headers["x-theme-sha256"] == summary["digest"]


async def test_import_rejections_conflicts_and_recovery_facts(live_theme):
    """非法包、摘要变化、内置、越权、旧修订及版本冲突分别失败。"""
    env = live_theme
    source, version, raw = await create_publish(env, archive="research")
    digest = hashlib.sha256(raw).hexdigest()
    directory = (await env.client.get("/api/theme-sources")).json()["sources"]
    builtin = next(item for item in directory if item["kind"] == "builtin" and item["status"] == "active")
    async with env.db() as db:
        before = await db.scalar(text("SELECT count(*) FROM project_theme_sources"))
    long_version = changed_theme(raw, version="v" * 161)
    length = await env.client.post("/api/theme-imports/preflight", content=long_version)
    assert length.status_code == 422 and length.json()["detail"]["code"] == "version_length"
    length_import = await env.client.post(
        "/api/theme-imports",
        params={"digest": hashlib.sha256(long_version).hexdigest(), "name": "超长版本"},
        content=long_version,
    )
    assert length_import.status_code == 422 and length_import.json()["detail"]["code"] == "version_length"
    summary = await env.client.post("/api/theme-imports/preflight", content=raw)
    assert summary.status_code == 200, summary.text
    assert summary.json()["files"] == [{"alias": "survey", "mediaType": "application/json"}]
    assert [asset["alias"] for asset in summary.json()["assets"]] == ["distribution"]
    assert summary.json()["assets"][0]["size"] > 0
    long_name = changed_theme(raw, name="名" * 161)
    name_summary = await env.client.post("/api/theme-imports/preflight", content=long_name)
    assert name_summary.status_code == 200, name_summary.text
    assert name_summary.json()["warnings"] == [
        {"code": "name_length", "message": "主题显示名超过160字符；请填写更短的目标主题名称。"}
    ]
    name_import = await env.client.post(
        "/api/theme-imports", params={"digest": hashlib.sha256(long_name).hexdigest()}, content=long_name
    )
    assert name_import.status_code == 422 and name_import.json()["detail"]["code"] == "source_name"
    invalid = await env.client.post("/api/theme-imports/preflight", content=b"not-a-zip")
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "invalid_zip"
    changed = await env.client.post(
        "/api/theme-imports", params={"digest": digest, "name": "摘要不符"}, content=variant_package(raw, name="摘要不符")
    )
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "preflight_changed"
    readonly = await env.client.post(
        "/api/theme-imports",
        params={"digest": digest, "source_id": builtin["id"], "expected_revision": 0},
        content=raw,
    )
    assert readonly.status_code == 403 and readonly.json()["detail"]["code"] == "builtin_readonly"
    foreign = await env.client.post(
        "/api/theme-imports",
        params={"digest": digest, "source_id": source["id"], "expected_revision": 1},
        headers=env.headers[1],
        content=raw,
    )
    assert foreign.status_code == 404 and foreign.json()["detail"]["code"] == "source_denied"
    async with env.db() as db:
        assert await db.scalar(text("SELECT count(*) FROM project_theme_sources")) == before

    same = await env.client.post(
        "/api/theme-imports",
        params={"digest": digest, "source_id": source["id"], "expected_revision": 1},
        content=raw,
    )
    assert same.status_code == 200, same.text
    assert same.json()["version_state"] == "published_same_bytes"
    assert same.json()["reusable_version_id"] == version["id"]
    assert same.json()["source"]["candidate_revision"] == 2
    stale = await env.client.post(
        "/api/theme-imports",
        params={"digest": digest, "source_id": source["id"], "expected_revision": 1},
        content=raw,
    )
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "candidate_conflict"
    different = variant_package(raw, name="同版本异字节")
    different_digest = hashlib.sha256(different).hexdigest()
    conflict = await env.client.post(
        "/api/theme-imports",
        params={"digest": different_digest, "source_id": source["id"], "expected_revision": 2},
        content=different,
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["version_state"] == "same_version_different_bytes"
    assert conflict.json()["source"]["candidate_digest"] == different_digest
    refused = await env.client.post(f"/api/theme-sources/{source['id']}/publish", json={"expected_revision": 3})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "version_conflict"
    async with env.db() as db:
        assert await db.scalar(
            text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": source["id"]}
        ) == 1
        candidate = (
            await db.execute(
                text("SELECT candidate_digest,candidate_revision FROM project_theme_sources WHERE id=:id"),
                {"id": source["id"]},
            )
        ).one()
        assert candidate.candidate_digest == different_digest and candidate.candidate_revision == 3
    exported = await env.client.get(f"/api/theme-versions/{version['id']}/package")
    assert exported.content == raw


async def test_import_existing_project_source_and_incomplete_identity(live_theme):
    """项目专属来源导入复用原授权；新建身份写入失败留下可核实身份。"""
    env = live_theme
    project, other = env.projects[:2]
    source, version, raw = await create_publish(env, kind="project", name="项目导入目标")
    digest = hashlib.sha256(raw).hexdigest()
    same = await env.client.post(
        "/api/theme-imports",
        params={"digest": digest, "source_id": source["id"], "expected_revision": 1, "project_id": project.id},
        content=raw,
    )
    assert same.status_code == 200, same.text
    assert same.json()["source"]["kind"] == "project"
    assert same.json()["version_state"] == "published_same_bytes"
    assert same.json()["reusable_version_id"] == version["id"]
    for project_id in (None, other.id):
        params = {"digest": digest, "source_id": source["id"], "expected_revision": 2}
        if project_id:
            params["project_id"] = project_id
        denied = await env.client.post("/api/theme-imports", params=params, content=raw)
        assert denied.status_code == 404 and denied.json()["detail"]["code"] == "source_denied"

    async with env.db() as db:
        before = await db.scalar(text("SELECT count(*) FROM project_theme_sources"))
        await db.execute(
            text("""CREATE FUNCTION reject_import_candidate() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'synthetic import failure'; END; $$ LANGUAGE plpgsql""")
        )
        await db.execute(
            text("""CREATE TRIGGER reject_import_candidate BEFORE UPDATE ON project_theme_sources
            FOR EACH ROW EXECUTE FUNCTION reject_import_candidate()""")
        )
        await db.commit()
    result = await env.client.post(
        "/api/theme-imports", params={"digest": digest, "name": "导入中断身份"}, content=raw
    )
    assert result.status_code == 500 and result.json()["detail"]["code"] == "import_incomplete"
    assert "导入中断身份" in result.json()["detail"]["message"]
    async with env.db() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id,candidate_digest,candidate_revision FROM project_theme_sources "
                    "WHERE name='导入中断身份'"
                )
            )
        ).one()
        assert row.candidate_digest is None and row.candidate_revision == 0
        assert await db.scalar(text("SELECT count(*) FROM project_theme_sources")) == before + 1
        assert await db.scalar(
            text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": row.id}
        ) == 0
        await db.execute(text("DROP TRIGGER reject_import_candidate ON project_theme_sources"))
        await db.execute(text("DROP FUNCTION reject_import_candidate()"))
        await db.commit()
    audit = (await env.client.get(f"/api/theme-sources/{row.id}/audit")).json()
    assert len(audit["files"]) == 1 and audit["files"][0]["state"] == "orphan"
    cleanup = (await env.client.post(f"/api/theme-sources/{row.id}/cleanup")).json()
    assert cleanup["files"][0]["state"] == "removed_orphan"


async def test_import_saved_unverified_branch(live_theme):
    """候选已提交但回读失败时明确已保存待核实，修复后可发布。"""
    env = live_theme
    raw = (BUILTIN / "research.theme.zip").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with mock.patch.object(
        ThemeStore, "read", side_effect=ThemeError("package_missing", "synthetic read failure", 409)
    ):
        result = await env.client.post(
            "/api/theme-imports", params={"digest": digest, "name": "已保存回读失败"}, content=raw
        )
    assert result.status_code == 500 and result.json()["detail"]["code"] == "import_saved_unverified"
    async with env.db() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id,candidate_digest,candidate_revision FROM project_theme_sources "
                    "WHERE name='已保存回读失败'"
                )
            )
        ).one()
        assert row.candidate_digest == digest and row.candidate_revision == 1
        assert await db.scalar(
            text("SELECT count(*) FROM project_theme_versions WHERE source_id=:id"), {"id": row.id}
        ) == 0
        assert await db.scalar(
            text("SELECT count(*) FROM project_theme_sources WHERE name='已保存回读失败'")
        ) == 1
    assert (env.store.root / row.id / f"{digest}.zip").is_file()
    published = await env.client.post(f"/api/theme-sources/{row.id}/publish", json={"expected_revision": 1})
    assert published.status_code == 200 and published.json()["digest"] == digest
    exported = await env.client.get(f"/api/theme-versions/{published.json()['id']}/package")
    assert exported.status_code == 200 and exported.content == raw
