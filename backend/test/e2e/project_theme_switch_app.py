"""S04-R隔离合成环境：真实认证、路由、数据库和独立文件根。"""

import asyncio
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# 仅由具名证据容器启动，不改变日常库或文件根。
sys.path.insert(0, "/app")
url = urlsplit(os.environ["POSTGRES_URL"])
os.environ["POSTGRES_URL"] = urlunsplit(url._replace(path="/yuanlei_s04_repair_evidence"))
os.environ["YUXI_USER_DATA_DIR"] = "/tmp/s04-repair/user-data"
os.environ["YUXI_THEME_SOURCES_DIR"] = "/tmp/s04-repair/theme-sources"


async def seed():
    """在独立库生成三项目共用Workdir的合成账号，登录信息只留私有文件。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yuxi.storage.postgres.manager import pg_manager
    from yuxi.storage.postgres.models_business import Department, User, Project, ProjectSettings
    from yuxi.services.project_theme_service import install_builtin_themes, ProjectThemeService
    from yuxi.utils.auth_utils import AuthUtils
    from yuxi.workspace.paths import user_workspace_dir

    pg_manager.initialize()
    await pg_manager.create_business_tables()
    await pg_manager.create_knowledge_tables()
    await pg_manager.upgrade_yuanlei_schema_v38_to_v39()
    await pg_manager.upgrade_yuanlei_schema_v39_to_v40()
    factory = async_sessionmaker(pg_manager.async_engine, expire_on_commit=False)
    async with factory() as db:
        department = Department(name="S04-R合成部门-" + uuid.uuid4().hex[:8])
        db.add(department)
        await db.flush()
        password = secrets.token_urlsafe(18)
        user = User(
            uid="s04r-" + uuid.uuid4().hex,
            username="s04r-" + uuid.uuid4().hex[:10],
            password_hash=AuthUtils.hash_password(password),
            role="user",
            is_deleted=0,
            department_id=department.id,
        )
        db.add(user)
        await db.flush()
        projects = [
            Project(
                id=str(uuid.uuid4()),
                uid=user.uid,
                name=f"S04-R验证项目{c}",
                selection_status="selectable",
                directory_mode="linked",
                workdir_path="projects/shared",
            )
            for c in ["A", "B", "C"]
        ]
        db.add_all(projects)
        await db.flush()
        db.add_all([ProjectSettings(project_id=p.id, owner_id=p.uid, description="隔离合成切换验证") for p in projects])
        await db.commit()
        await install_builtin_themes(db)
        svc = ProjectThemeService(db, user.uid)
        catalog = await svc.catalog(projects[0].id)
        default = next(v for s in catalog["sources"] for v in s["versions"] if s["name"] == "默认 · 项目管理")
        root = user_workspace_dir(user.uid) / "projects/shared"
        root.mkdir(parents=True, exist_ok=True)
        (root / "survey.json").write_text('{"samples":12}')
        await svc.select(projects[0].id, default["id"], {}, 0)
        private = Path("/tmp/s04-repair/session.json")
        private.write_text(
            json.dumps(
                {
                    "username": user.username,
                    "password": password,
                    "uid": user.uid,
                    "token": AuthUtils.create_access_token({"sub": str(user.id)}),
                    "projects": [{"id": p.id, "name": p.name} for p in projects],
                }
            )
        )
        private.chmod(0o600)
    await pg_manager.close()


if __name__ == "__main__":
    if not Path("/tmp/s04-repair/session.json").exists():
        asyncio.run(seed())
    import uvicorn

    uvicorn.run(
        "project_theme_app:app",
        host="0.0.0.0",
        port=5060,
        log_level="warning",
        reload=True,
        reload_dirs=["/app/package", "/app/server"],
    )
