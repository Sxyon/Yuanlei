"""仅在具名隔离数据库建立S05合成身份及Workdir，不启动模型或Worker。"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import async_sessionmaker

from yuxi.config.options import ensure_options_in_db
from yuxi.services.project_theme_service import install_builtin_themes
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import Department, Project, ProjectSettings, User
from yuxi.utils.auth_utils import AuthUtils
from yuxi.workspace.paths import user_workspace_dir


async def main():
    """独立数据库与文件根是执行前提，凭据仅写私有session。"""
    if urlsplit(os.environ["POSTGRES_URL"]).path != "/yuanlei_s05_evidence":
        raise RuntimeError("S05证据只允许具名独立数据库")
    pg_manager.initialize()
    await pg_manager.create_business_tables()
    await pg_manager.create_knowledge_tables()
    await pg_manager.upgrade_yuanlei_schema_v38_to_v39()
    factory = async_sessionmaker(pg_manager.async_engine, expire_on_commit=False)
    async with factory() as db:
        await ensure_options_in_db(db)
        department = Department(name="S05合成部门")
        db.add(department)
        await db.flush()
        users = [
            User(
                uid=f"s05-{uuid.uuid4().hex}",
                username=f"s05-{uuid.uuid4().hex}",
                password_hash="synthetic-no-login",
                role="user",
                is_deleted=0,
                department_id=department.id,
            )
            for _ in range(2)
        ]
        db.add_all(users)
        await db.flush()
        projects = [
            Project(
                id=str(uuid.uuid4()),
                uid=users[0 if i < 2 else 1].uid,
                name=f"S05合成项目{i + 1}",
                selection_status="selectable",
                directory_mode="linked",
                workdir_path=f"projects/s05-{i}",
            )
            for i in range(3)
        ]
        db.add_all(projects)
        await db.flush()
        db.add_all(
            [ProjectSettings(project_id=p.id, owner_id=p.uid, description="S05隔离真实接通验证") for p in projects]
        )
        await db.commit()
        await install_builtin_themes(db)
        for project in projects:
            root = user_workspace_dir(project.uid) / project.workdir_path
            root.mkdir(parents=True, exist_ok=True)
            (root / "survey.json").write_bytes(
                json.dumps({"project": project.name, "samples": 12}, ensure_ascii=False).encode()
            )
        private = Path(os.environ["YUXI_USER_DATA_DIR"]) / ".s05-session.json"
        private.write_text(
            json.dumps(
                {
                    "users": [
                        {"uid": u.uid, "token": AuthUtils.create_access_token({"sub": str(u.id)})} for u in users
                    ],
                    "projects": [
                        {"id": p.id, "name": p.name, "uid": p.uid, "workdir_path": p.workdir_path} for p in projects
                    ],
                },
                ensure_ascii=False,
            )
        )
        private.chmod(0o600)
    await pg_manager.close()
    print("S05独立数据库、两账号三项目及指定JSON已建立；身份仅保留私有session")


if __name__ == "__main__":
    asyncio.run(main())
