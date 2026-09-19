"""编码执行器凭据的数据访问层。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import CodingCredential
from yuxi.utils.datetime_utils import utc_now_naive


class CodingCredentialRepository:
    """读写用户级与全局编码执行器凭据。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
    ) -> CodingCredential | None:
        return await self.db.scalar(
            select(CodingCredential).where(
                CodingCredential.scope == str(scope),
                CodingCredential.uid == (str(uid) if uid is not None else None),
                CodingCredential.executor == str(executor),
                CodingCredential.provider == str(provider),
            )
        )

    async def list_active(self, *, scope: str, uid: str | None = None) -> list[CodingCredential]:
        query = select(CodingCredential).where(
            CodingCredential.scope == str(scope),
            CodingCredential.status == "active",
        )
        if uid is not None:
            query = query.where(CodingCredential.uid == str(uid))
        result = await self.db.execute(
            query.order_by(
                CodingCredential.executor.asc(),
                CodingCredential.updated_at.desc(),
                CodingCredential.created_at.desc(),
                CodingCredential.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        credential_id: str,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
        source: str = "manual",
        model_provider_id: str | None = None,
        key_mode: str | None = None,
        base_url: str | None,
        model: str | None,
        ciphertext: bytes | None,
        nonce: bytes | None,
        key_version: int | None,
        extra: dict | None,
        actor: str | None,
        now: datetime | None = None,
    ) -> CodingCredential:
        """写入或轮换凭据；密文版本自增，状态恢复为 active。"""
        timestamp = now or utc_now_naive()
        row = await self.get(scope=scope, uid=uid, executor=executor, provider=provider)
        if row is None:
            row = CodingCredential(
                id=str(credential_id),
                scope=str(scope),
                uid=str(uid) if uid is not None else None,
                executor=str(executor),
                provider=str(provider),
                status="active",
                version=1,
                created_by=actor,
                created_at=timestamp,
            )
            self.db.add(row)
        else:
            row.version = int(row.version or 0) + 1
            row.status = "active"
        row.source = source
        row.model_provider_id = model_provider_id
        row.key_mode = key_mode
        row.base_url = base_url
        row.model = model
        row.api_key_cipher = ciphertext
        row.nonce = nonce
        row.key_version = key_version
        row.extra_json = extra or {}
        row.updated_by = actor
        row.updated_at = timestamp
        await self.db.flush()
        return row

    async def deactivate_other_executor_rows(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        keep_id: str,
        actor: str | None,
        now: datetime | None = None,
    ) -> int:
        """同一 scope 同一执行器只保留一条 active：其余软删并清理密文。"""
        timestamp = now or utc_now_naive()
        query = select(CodingCredential).where(
            CodingCredential.scope == str(scope),
            CodingCredential.uid == (str(uid) if uid is not None else None),
            CodingCredential.executor == str(executor),
            CodingCredential.status == "active",
            CodingCredential.id != str(keep_id),
        )
        rows = list((await self.db.execute(query)).scalars().all())
        for row in rows:
            row.status = "deleted"
            row.api_key_cipher = None
            row.nonce = None
            row.key_version = None
            row.version = int(row.version or 0) + 1
            row.updated_by = actor
            row.updated_at = timestamp
        if rows:
            await self.db.flush()
        return len(rows)

    async def delete(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str | None = None,
        actor: str | None,
        now: datetime | None = None,
    ) -> bool:
        """销毁密文并标记 deleted；未指定 provider 时删除该执行器最新一条。"""
        if provider is None:
            rows = await self.list_active(scope=scope, uid=uid)
            candidates = [row for row in rows if row.executor == str(executor)]
            if not candidates:
                return False
            row = max(
                candidates,
                key=lambda item: (
                    item.updated_at or datetime.min,
                    item.created_at or datetime.min,
                    item.id or "",
                ),
            )
        else:
            row = await self.get(scope=scope, uid=uid, executor=executor, provider=provider)
        if row is None or row.status != "active":
            return False
        row.status = "deleted"
        row.api_key_cipher = None
        row.nonce = None
        row.key_version = None
        row.version = int(row.version or 0) + 1
        row.updated_by = actor
        row.updated_at = now or utc_now_naive()
        await self.db.flush()
        return True
