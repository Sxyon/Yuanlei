"""部署维护者按需核对PG引用与主题文件；无删除、导入或选择副作用。"""

import asyncio
import json

from sqlalchemy import text

from yuxi.services.project_theme_service import ProjectThemeService
from yuxi.storage.postgres.manager import pg_manager


async def main():
    """同来源锁下检查候选、版本及项目引用，故障使命令非零退出。"""
    pg_manager.initialize()
    try:
        await pg_manager.require_current_schema()
        results = []
        async with pg_manager.get_async_session_context() as db:
            service = ProjectThemeService(db, "")
            sources = (await db.execute(text("SELECT id FROM project_theme_sources ORDER BY id FOR UPDATE"))).scalars()
            for source_id in sources:
                references = await service.repo.references(source_id)
                files = await asyncio.to_thread(service.audit_files, source_id, references, False)
                results.append({"source_id": source_id, "files": files})
            invalid = await db.scalar(
                text("""
                SELECT count(*) FROM project_theme_bindings b
                JOIN projects p ON p.id=b.project_id
                JOIN project_theme_versions v ON v.id=b.version_id
                JOIN project_theme_sources s ON s.id=v.source_id
                WHERE NOT (s.kind='builtin' OR (s.owner_uid=p.uid AND
                    (s.kind='personal' OR s.project_id=p.id)))
            """)
            )
        faults = [
            item
            for source in results
            for item in source["files"]
            if item["state"] not in {"referenced", "orphan", "temporary"}
        ]
        print(
            json.dumps(
                {"sources": results, "invalid_bindings": invalid, "fault_count": len(faults)}, ensure_ascii=False
            )
        )
        if faults or invalid:
            raise SystemExit(1)
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
