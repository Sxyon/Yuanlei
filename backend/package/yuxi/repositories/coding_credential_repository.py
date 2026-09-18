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
        result = await self.db.execute(query.order_by(CodingCredential.executor.asc(), CodingCredential.provider.asc()))
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        credential_id: str,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
        base_url: str | None,
        model: str | None,
        ciphertext: bytes,
        nonce: bytes,
        key_version: int,
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
        row.base_url = base_url
        row.model = model
        row.api_key_cipher = ciphertext
        row.nonce = nonce
        row.key_version = int(key_version)
        row.extra_json = extra or {}
        row.updated_by = actor
        row.updated_at = timestamp
        await self.db.flush()
        return row

    async def delete(
        self,
        *,
        scope: str,
        uid: str | None,
        executor: str,
        provider: str,
        actor: str | None,
        now: datetime | None = None,
    ) -> bool:
        """销毁密文并标记 deleted；重复删除返回 False。"""
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
