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

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.project_theme_router import project_themes
from server.utils.auth_middleware import get_db
from yuxi.services.project_theme_service import install_builtin_themes
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import Department, Project, User
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
    builtin = next(s for s in directory["sources"] if s["kind"] == "builtin" and s["versions"][0]["size"] < 2000)
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
        s["versions"][0] for s in catalog["sources"] if s["kind"] == "builtin" and s["versions"][0]["size"] < 2000
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
