"""外部执行器委派事实与入向同步游标的数据访问层（yuanlei 域）。

投递/回收本地状态、远端只读投影与同步游标都由本仓储读写；事务提交由调用方决定。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ChannelDelegation, ChannelSyncCursor, CodingSessionTurn
from yuxi.utils.datetime_utils import utc_now_naive


class ChannelDelegationRepository:
    """读写委派事实与同步游标；不拥有远端执行状态。"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def add_delegation(
        self,
        *,
        operation_id: str,
        project_id: str,
        executor_key: str,
        task: str,
        request_json: dict,
        initiator_run_id: str | None,
        created_by: str | None,
        now: datetime | None = None,
    ) -> ChannelDelegation:
        """先写入投递意图行（pending）并 flush，调用方随后提交。"""
        timestamp = now or utc_now_naive()
        row = ChannelDelegation(
            id=str(uuid.uuid4()),
            operation_id=str(operation_id),
            project_id=str(project_id),
            executor_key=str(executor_key),
            task=str(task),
            request_json=request_json,
            initiator_run_id=str(initiator_run_id) if initiator_run_id else None,
            work_task_id=(request_json.get("metadata") or {}).get("work_task_id"),
            source_topic_id=(request_json.get("metadata") or {}).get("source_topic_id"),
            source_decision_id=(request_json.get("metadata") or {}).get("source_decision_id"),
            source_decision_revision=(request_json.get("metadata") or {}).get("source_decision_revision"),
            dispatch_state="pending",
            attempts=0,
            result_json={},
            created_by=str(created_by) if created_by else None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def lock_task_delegations(self, task_id: str) -> None:
        """完成持有既有委派锁，避免终态投影在检查后进入回收。"""
        await self.db.scalars(
            select(ChannelDelegation.id)
            .where(ChannelDelegation.work_task_id == task_id)
            .order_by(ChannelDelegation.id)
            .with_for_update()
        )

    async def has_active_task_work(self, task_id: str) -> bool:
        """投递和回收中始终活跃，已投递按执行器真实终态判断。"""
        coding_terminal = ("completed", "failed", "cancelled")
        external_terminal = ("done", "cancelled")
        active = await self.db.scalar(
            select(ChannelDelegation.id)
            .outerjoin(CodingSessionTurn, CodingSessionTurn.id == ChannelDelegation.turn_id)
            .where(
                ChannelDelegation.work_task_id == task_id,
                or_(
                    CodingSessionTurn.status.notin_(coding_terminal),
                    ChannelDelegation.dispatch_state.in_(("pending", "collecting")),
                    (ChannelDelegation.dispatch_state.in_(("dispatched", "reclaimed")))
                    & or_(
                        (ChannelDelegation.executor_key == "multica")
                        & or_(
                            ChannelDelegation.remote_status.is_(None),
                            ChannelDelegation.remote_status.notin_(external_terminal),
                        ),
                        (ChannelDelegation.executor_key != "multica")
                        & or_(
                            CodingSessionTurn.status.notin_(coding_terminal),
                            CodingSessionTurn.id.is_(None)
                            & or_(
                                ChannelDelegation.remote_status.is_(None),
                                ChannelDelegation.remote_status.notin_(coding_terminal),
                            ),
                        ),
                    ),
                ),
            )
            .limit(1)
        )
        return active is not None

    async def get_by_operation_id(
        self,
        *,
        operation_id: str,
        for_update: bool = False,
    ) -> ChannelDelegation | None:
        """按稳定 operation_id 读取委派，可选行锁。"""
        statement = select(ChannelDelegation).where(ChannelDelegation.operation_id == str(operation_id))
        if for_update:
            statement = statement.with_for_update()
        return await self.db.scalar(statement)

    async def list_for_project(self, *, project_id: str) -> list[ChannelDelegation]:
        """按创建时间读取项目内委派事实。"""
        result = await self.db.scalars(
            select(ChannelDelegation)
            .where(ChannelDelegation.project_id == str(project_id))
            .order_by(ChannelDelegation.created_at, ChannelDelegation.id)
        )
        return list(result)

    async def list_unsettled_leased(
        self,
        *,
        now: datetime,
        limit: int = 50,
    ) -> list[ChannelDelegation]:
        """读取需要收敛的非终态委派：无租约或租约已过期。"""
        result = await self.db.scalars(
            select(ChannelDelegation)
            .where(
                ChannelDelegation.dispatch_state.in_(("pending", "dispatched", "collecting")),
                (ChannelDelegation.lease_expires_at.is_(None)) | (ChannelDelegation.lease_expires_at < now),
            )
            .order_by(ChannelDelegation.updated_at, ChannelDelegation.id)
            .limit(int(limit))
        )
        return list(result)

    async def get_cursor_for_update(self, *, channel: str, project_id: str) -> ChannelSyncCursor | None:
        """锁定读取渠道游标，供一次同步读改写使用。"""
        return await self.db.scalar(
            select(ChannelSyncCursor)
            .where(
                ChannelSyncCursor.channel == str(channel),
                ChannelSyncCursor.project_id == str(project_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def add_cursor(
        self,
        *,
        channel: str,
        project_id: str,
        now: datetime | None = None,
    ) -> ChannelSyncCursor:
        """为渠道（Project, channel）创建初始游标行并 flush。"""
        timestamp = now or utc_now_naive()
        row = ChannelSyncCursor(
            id=str(uuid.uuid4()),
            channel=str(channel),
            project_id=str(project_id),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_cursors_for_channel(self, *, channel: str) -> list[ChannelSyncCursor]:
        """列出渠道下所有 Project 的同步游标。"""
        result = await self.db.scalars(
            select(ChannelSyncCursor)
            .where(ChannelSyncCursor.channel == str(channel))
            .order_by(ChannelSyncCursor.created_at, ChannelSyncCursor.id)
        )
        return list(result)
