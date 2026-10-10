"""个人协作者连接、目标与准确尝试的可见性查询。"""

from sqlalchemy import select

from yuxi.storage.postgres.models_business import (
    CollaboratorConnection,
    CollaboratorConnectionProject,
    CollaboratorTarget,
    DelegationAttempt,
    ChannelDelegation,
)


class CollaboratorRepository:
    """持有本人项目的连接与目标范围，历史尝试不猜最新运行。"""

    def __init__(self, db):
        self.db = db

    async def connection(self, identifier, uid, *, lock=False):
        """读取本人连接，修改时锁行。"""
        query = select(CollaboratorConnection).where(
            CollaboratorConnection.id == identifier, CollaboratorConnection.uid == uid
        )
        return await self.db.scalar(
            (query.with_for_update() if lock else query).execution_options(populate_existing=True)
        )

    async def connections(self, uid):
        """列出本人连接，不读取其他人的秘密。"""
        return list(
            (await self.db.scalars(select(CollaboratorConnection).where(CollaboratorConnection.uid == uid))).all()
        )

    async def permissions(self, connection_id):
        """保留撤销许可行供历史外键引用。"""
        return list(
            (
                await self.db.scalars(
                    select(CollaboratorConnectionProject).where(
                        CollaboratorConnectionProject.connection_id == connection_id
                    )
                )
            ).all()
        )

    async def target(self, identifier, uid, *, lock=False):
        """读取本人目标与持久核验。"""
        query = select(CollaboratorTarget).where(CollaboratorTarget.id == identifier, CollaboratorTarget.uid == uid)
        return await self.db.scalar(
            (query.with_for_update() if lock else query).execution_options(populate_existing=True)
        )

    async def targets(self, connection_id, uid):
        """列出指定本人连接的目标。"""
        return list(
            (
                await self.db.scalars(
                    select(CollaboratorTarget).where(
                        CollaboratorTarget.connection_id == connection_id, CollaboratorTarget.uid == uid
                    )
                )
            ).all()
        )

    async def attempt(self, *, identifier=None, delegation_id=None, lock=False):
        """按准确主键或唯一委派来源读取，不推断相邻尝试。"""
        query = select(DelegationAttempt)
        query = (
            query.where(DelegationAttempt.id == identifier)
            if identifier
            else query.where(DelegationAttempt.delegation_id == delegation_id)
        )
        return await self.db.scalar(
            (query.with_for_update() if lock else query).execution_options(populate_existing=True)
        )

    async def delegation_owner(self, identifier):
        """派发副作用前锁定真实委派owner。"""
        return await self.db.scalar(
            select(ChannelDelegation)
            .where(ChannelDelegation.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def delegation(self, identifier):
        """读取准确委派来源，读投影不取得执行租约。"""
        return await self.db.scalar(select(ChannelDelegation).where(ChannelDelegation.id == identifier))
