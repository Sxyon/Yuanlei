"""通过 Agent 回调记录首次模型请求时间。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from yuxi.repositories.agent_run_repository import AgentRunRepository
from yuxi.storage.postgres.manager import pg_manager
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger


class FirstModelRequestRecorder(BaseCallbackHandler):
    """在首次 ChatModel callback 中捕获时间，并由 Run owner 持久化。"""

    run_inline = True

    def __init__(self) -> None:
        self.first_model_request_at: datetime | None = None
        self._persisted = False

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs: Any,
    ) -> None:
        """在 LangChain 发起供应商调用前记录首次时间。"""
        del serialized, messages, run_id, parent_run_id, tags, metadata, kwargs
        if self.first_model_request_at is None:
            self.first_model_request_at = utc_now_naive()

    async def persist(self, *, run_id: str, worker_id: str) -> None:
        """在当前 Run 仍由 worker 持有时写入一次性时间事实。"""
        if self.first_model_request_at is None or self._persisted:
            return

        try:
            async with pg_manager.get_async_session_context() as db:
                await AgentRunRepository(db).record_first_model_request(
                    run_id,
                    worker_id=worker_id,
                    observed_at=self.first_model_request_at,
                )
            self._persisted = True
        except Exception:
            logger.warning(f"Failed to persist first model request timing: run={run_id}", exc_info=True)
