"""入向渠道同步：Multica → 元垒 proposed 治理行的确定性收敛（yuanlei 域）。

游标、去重与失败重试由本服务与 `channel_sync_cursors` 行持有，不依赖 Agent
自行决定同步。导入入口只调用治理用例的创建路径，只产生 `proposed`，不暴露
审核或状态写入参数，也不开放公网 webhook。游标是稳定组合键 `(updated_at, id)`，
请求固定按 `updated_at` 倒序，客户端按组合键做增量过滤；`updated_after` 被服务端
忽略，不作为增量依据。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.delegation.contracts import DelegationLeaseLostError
from yuxi.delegation.multica import MULTICA_EXECUTOR_KEY, MulticaClient, MulticaIssue, build_multica_client_from_env
from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository
from yuxi.repositories.user_repository import UserRepository
from yuxi.services.governance_service import create_governance_topic
from yuxi.utils import logger
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive

MULTICA_SYNC_CHANNEL = MULTICA_EXECUTOR_KEY
DEFAULT_CURSOR_LEASE_SECONDS = 120
MULTICA_SYNC_MAX_PAGES = 10


def _normalize_timestamp(value: str) -> str:
    """把远端时间戳归一为固定 UTC 微秒格式，使字符串比较与时间先后一致。"""
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _cursor_key(issue: MulticaIssue) -> tuple[str, str]:
    """计算议题的稳定排序键 (归一 updated_at, id)；缺字段时显式失败而非静默丢项。"""
    if not issue.updated_at or not issue.id:
        raise ValueError(f"multica issue missing updated_at/id: {issue.identifier or issue.id or '<unknown>'}")
    return (_normalize_timestamp(issue.updated_at), str(issue.id))


def _encode_cursor(key: tuple[str, str]) -> str:
    """把组合游标编码为可持久化的稳定字符串。"""
    return json.dumps({"updated_at": key[0], "id": key[1]}, separators=(",", ":"), sort_keys=True)


def _decode_cursor(value: str | None) -> tuple[str, str] | None:
    """解析组合游标；历史裸 updated_at 值按 (updated_at, "") 兼容读取，无法解析即 fail-closed。"""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
            updated_at = str(payload["updated_at"]).strip()
            issue_id = str(payload["id"]).strip()
            if not updated_at or not issue_id:
                raise KeyError("empty cursor field")
            return (_normalize_timestamp(updated_at), issue_id)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed multica sync cursor: {text!r}") from exc
    try:
        return (_normalize_timestamp(text), "")
    except ValueError as exc:
        raise ValueError(f"malformed legacy multica sync cursor: {text!r}") from exc


class ChannelSyncService:
    """Multica 入向同步的确定性 Owner；一次同步一个 Project 的游标。"""

    def __init__(self, db: AsyncSession, *, client: MulticaClient, lease_seconds: int = DEFAULT_CURSOR_LEASE_SECONDS):
        self.db = db
        self.client = client
        self.repo = ChannelDelegationRepository(db)
        self.lease_seconds = int(lease_seconds)

    async def pull_multica(self, *, project_id: str, actor_uid: str, limit: int = 50) -> dict:
        """在游标租约内按 updated_at 倒序有界拉取 Multica 议题并归一为 proposed；整批取回后推进组合游标。"""
        actor = await UserRepository().get_by_uid_with_db(self.db, str(actor_uid))
        if actor is None:
            raise DelegationLeaseLostError("同步发起用户不存在")
        page_size = max(1, int(limit))
        cursor = await self._claim_cursor(project_id=project_id)
        owner_token = cursor.owner_token
        initial_value = cursor.cursor_value
        try:
            initial_key = _decode_cursor(initial_value)
        except ValueError as exc:
            logger.warning("Multica inbound sync rejected cursor: project={} cursor={}", project_id, initial_value)
            await self._finish_cursor(
                project_id=project_id, owner_token=owner_token, cursor_value=None, last_error=str(exc)
            )
            return {
                "channel": MULTICA_SYNC_CHANNEL,
                "project_id": project_id,
                "imported": 0,
                "skipped": 0,
                "cursor": initial_value,
                "error": str(exc),
            }
        imported = skipped = 0
        latest_key = initial_key
        consumed = False
        try:
            offset = 0
            for _ in range(MULTICA_SYNC_MAX_PAGES):
                issues = await self.client.list_issues(limit=page_size, offset=offset)
                if not issues:
                    consumed = True
                    break
                reached_cursor = False
                for issue in issues:
                    key = _cursor_key(issue)
                    if initial_key is not None and key[0] < initial_key[0]:
                        reached_cursor = True
                        break
                    # 边界秒内的项每轮纳入并靠 source_external_id 去重：服务端并列次序不可依赖，
                    # 若按 id 严格过滤会漏掉同一 updated_at 下更小的 id。
                    if latest_key is None or key > latest_key:
                        latest_key = key
                    try:
                        await create_governance_topic(
                            project_id=project_id,
                            title=issue.title,
                            summary=issue.description,
                            source_channel=MULTICA_SYNC_CHANNEL,
                            source_external_id=issue.identifier,
                            source_url=issue.url,
                            db=self.db,
                            user=actor,
                        )
                        imported += 1
                    except HTTPException as exc:
                        if exc.status_code == 409:
                            skipped += 1
                            continue
                        raise
                if reached_cursor or len(issues) < page_size:
                    consumed = True
                    break
                offset += len(issues)
        except Exception as exc:
            logger.warning("Multica inbound sync failed: project={} error={}", project_id, exc)
            await self._finish_cursor(
                project_id=project_id, owner_token=owner_token, cursor_value=None, last_error=str(exc)
            )
            return {
                "channel": MULTICA_SYNC_CHANNEL,
                "project_id": project_id,
                "imported": imported,
                "skipped": skipped,
                "cursor": initial_value,
                "error": str(exc),
            }
        # 只有确认整个结果集取回后才推进游标；触顶分页上限时保持原游标并显式告警，避免满页时静默跳过未取回项。
        error = None
        if not consumed:
            error = f"Multica 同步达到 {MULTICA_SYNC_MAX_PAGES} 页上限，游标未推进"
            logger.warning(
                "Multica inbound sync hit page cap without consuming all items: project={} pages={}",
                project_id,
                MULTICA_SYNC_MAX_PAGES,
            )
        cursor_value = _encode_cursor(latest_key) if consumed and latest_key is not None else initial_value
        await self._finish_cursor(
            project_id=project_id, owner_token=owner_token, cursor_value=cursor_value, last_error=error
        )
        result = {
            "channel": MULTICA_SYNC_CHANNEL,
            "project_id": project_id,
            "imported": imported,
            "skipped": skipped,
            "cursor": cursor_value,
        }
        if error:
            result["error"] = error
        return result

    async def converge(self, *, limit_per_project: int = 50, max_projects: int = 20) -> dict[str, int]:
        """确定性收敛：对已有游标的 Project 继续拉取，并释放超租约的陈旧游标。"""
        project_ids = [
            cursor.project_id
            for cursor in (await self.repo.list_cursors_for_channel(channel=MULTICA_SYNC_CHANNEL))[: int(max_projects)]
        ]
        now = utc_now_naive()
        counts = {"projects": 0, "imported": 0, "skipped": 0, "released": 0, "failed": 0}
        for project_id in project_ids:
            locked = await self.repo.get_cursor_for_update(channel=MULTICA_SYNC_CHANNEL, project_id=project_id)
            if locked is not None and locked.lease_expires_at is not None and locked.lease_expires_at <= now:
                locked.owner_token = None
                locked.lease_expires_at = None
                counts["released"] += 1
        await self.db.commit()
        for project_id in project_ids:
            actor_uid = await self._project_owner_uid(project_id=project_id)
            if actor_uid is None:
                continue
            try:
                result = await self.pull_multica(
                    project_id=project_id, actor_uid=actor_uid, limit=int(limit_per_project)
                )
            except DelegationLeaseLostError:
                # 单个 Project 游标被其他 owner 持有不阻断其余 Project。
                logger.warning("Multica sync skipped a project: project={}", project_id)
                counts["failed"] += 1
                continue
            counts["projects"] += 1
            counts["imported"] += int(result.get("imported", 0))
            counts["skipped"] += int(result.get("skipped", 0))
            if result.get("error"):
                counts["failed"] += 1
        return counts

    async def _project_owner_uid(self, *, project_id: str) -> str | None:
        from sqlalchemy import select

        from yuxi.storage.postgres.models_business import Project

        return await self.db.scalar(select(Project.uid).where(Project.id == str(project_id)))

    async def _claim_cursor(self, *, project_id: str):
        cursor = await self.repo.get_cursor_for_update(channel=MULTICA_SYNC_CHANNEL, project_id=project_id)
        if cursor is None:
            cursor = await self.repo.add_cursor(channel=MULTICA_SYNC_CHANNEL, project_id=project_id)
        now = utc_now_naive()
        if cursor.lease_expires_at is not None and cursor.lease_expires_at > now:
            await self.db.rollback()
            raise DelegationLeaseLostError("渠道同步游标已被其他 owner 持有")
        cursor.owner_token = uuid.uuid4().hex
        cursor.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        await self.db.commit()
        await self.db.refresh(cursor)
        return cursor

    async def _finish_cursor(
        self, *, project_id: str, owner_token: str, cursor_value: str | None, last_error: str | None
    ) -> None:
        cursor = await self.repo.get_cursor_for_update(channel=MULTICA_SYNC_CHANNEL, project_id=project_id)
        if (
            cursor is None
            or cursor.owner_token != owner_token
            or cursor.lease_expires_at is None
            or cursor.lease_expires_at <= utc_now_naive()
        ):
            await self.db.rollback()
            raise DelegationLeaseLostError("渠道同步游标租约已失效")
        if cursor_value is not None:
            cursor.cursor_value = cursor_value
        cursor.last_synced_at = utc_now_naive() if last_error is None else cursor.last_synced_at
        cursor.last_error = last_error
        cursor.owner_token = None
        cursor.lease_expires_at = None
        await self.db.commit()

    async def get_cursor(self, *, project_id: str) -> dict | None:
        """读取 Project 的 Multica 同步游标状态。"""
        cursors = await self.repo.list_cursors_for_channel(channel=MULTICA_SYNC_CHANNEL)
        for cursor in cursors:
            if cursor.project_id == str(project_id):
                return {
                    "channel": cursor.channel,
                    "project_id": cursor.project_id,
                    "cursor": cursor.cursor_value,
                    "last_synced_at": format_utc_datetime(cursor.last_synced_at),
                    "last_error": cursor.last_error,
                }
        return None


async def reconcile_channel_sync() -> dict[str, int]:
    """确定性收敛 Multica 入向游标；无凭据时不发任何外部请求。"""
    from yuxi.storage.postgres.manager import pg_manager

    client = build_multica_client_from_env()
    if client is None:
        return {"projects": 0, "imported": 0, "skipped": 0, "released": 0, "failed": 0}
    async with pg_manager.get_async_session_context() as db:
        return await ChannelSyncService(db, client=client).converge()
