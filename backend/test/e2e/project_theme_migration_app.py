"""S06隔离实例B：真实认证、路由、独立数据库与文件根。"""

import asyncio
import io
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# 仅由具名证据容器启动，不改变日常库或文件根。
sys.path.insert(0, "/app")

# 只由具名证据容器启动，不读写日常数据库、主题文件根或用户目录。
DB_NAME = os.environ.get("THEME_EVIDENCE_DB", "yuanlei_s06_evidence_b")
EVIDENCE_ROOT = Path(os.environ.get("THEME_EVIDENCE_DIR", "/tmp/s06-b"))
url = urlsplit(os.environ["POSTGRES_URL"])
os.environ["POSTGRES_URL"] = urlunsplit(url._replace(path=f"/{DB_NAME}"))
os.environ["YUXI_USER_DATA_DIR"] = str(EVIDENCE_ROOT / "user-data")
os.environ["YUXI_THEME_SOURCES_DIR"] = str(EVIDENCE_ROOT / "theme-sources")


async def seed():
    """生成B自己的账号、项目、主题选择与可区分资料。"""
    from PIL import Image
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from yuxi.config.options import system_options
    from yuxi.services.project_theme_service import ProjectThemeService, install_builtin_themes
    from yuxi.storage.postgres.manager import pg_manager
    from yuxi.storage.postgres.models_business import ConfigOption, Department, Project, ProjectSettings, User
    from yuxi.utils.auth_utils import AuthUtils
    from yuxi.workspace.paths import user_workspace_dir

    pg_manager.initialize()
    await pg_manager.create_business_tables()
    await pg_manager.create_knowledge_tables()
    await pg_manager.upgrade_yuanlei_schema_v38_to_v39()
    await pg_manager.upgrade_yuanlei_schema_v39_to_v40()
    await pg_manager.upgrade_yuanlei_schema_v40_to_v41()
    factory = async_sessionmaker(pg_manager.async_engine, expire_on_commit=False)
    async with factory() as db:
        department = Department(name="S06迁移合成部门-" + uuid.uuid4().hex[:8])
        db.add(department)
        await db.flush()
        password = secrets.token_urlsafe(18)
        user = User(
            uid="s06b-" + uuid.uuid4().hex,
            username="s06b-" + uuid.uuid4().hex[:10],
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
                name=name,
                selection_status="selectable",
                directory_mode="linked",
                workdir_path=workdir,
            )
            for name, workdir in [
                ("S06迁移目标B1", "projects/s06-b-target"),
                ("S06迁移对照B2", "projects/s06-b-control"),
            ]
        ]
        db.add_all(projects)
        await db.flush()
        db.add_all(
            [ProjectSettings(project_id=project.id, owner_id=project.uid, description="S06跨实例迁移隔离项目") for project in projects]
        )
        db.add(
            ConfigOption(
                key=system_options.key,
                name=system_options.name,
                description=system_options.description,
                params=system_options.params,
                value={},
                created_by="system",
                updated_by="system",
            )
        )
        await db.commit()
        await install_builtin_themes(db)
        service = ProjectThemeService(db, user.uid)
        catalog = await service.catalog(projects[0].id)
        versions = {source["name"]: source["versions"][0] for source in catalog["sources"] if source["versions"]}
        default = versions["默认 · 项目管理"]
        focus = versions["精简 · 专注推进"]
        await service.select(projects[0].id, default["id"], {}, 0)
        await service.select(projects[1].id, focus["id"], {}, 0)

        target_root = user_workspace_dir(user.uid) / "projects/s06-b-target"
        control_root = user_workspace_dir(user.uid) / "projects/s06-b-control"
        target_root.mkdir(parents=True, exist_ok=True)
        control_root.mkdir(parents=True, exist_ok=True)
        (target_root / "facts.json").write_text(
            json.dumps({"origin": "B", "samples": 99, "note": "B项目真实资料"}, ensure_ascii=False), encoding="utf-8"
        )
        (control_root / "facts.json").write_text(json.dumps({"origin": "B2", "samples": 7}), encoding="utf-8")
        chart = io.BytesIO()
        Image.new("RGB", (24, 12), (20, 90, 200)).save(chart, format="PNG")
        (target_root / "chart.png").write_bytes(chart.getvalue())

        private = EVIDENCE_ROOT / "session.json"
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(
            json.dumps(
                {
                    "username": user.username,
                    "password": password,
                    "uid": user.uid,
                    "token": AuthUtils.create_access_token({"sub": str(user.id)}),
                    "projects": [
                        {"id": project.id, "name": project.name, "workdir": project.workdir_path} for project in projects
                    ],
                    "default_version_id": default["id"],
                    "focus_version_id": focus["id"],
                }
            )
        )
        private.chmod(0o600)
    await pg_manager.close()


if __name__ == "__main__":
    if not (EVIDENCE_ROOT / "session.json").exists():
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
