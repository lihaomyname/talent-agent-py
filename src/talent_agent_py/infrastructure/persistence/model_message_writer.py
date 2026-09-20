"""保存模型请求和原始回复。"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from talent_agent_py.infrastructure.clients.model_session import current_model_session_id
from talent_agent_py.infrastructure.persistence.models import ModelMessageRecord

logger = structlog.get_logger(__name__)


class ModelMessageWriter:
    """一次调用写两行：请求前写 user，响应后写 assistant。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def write_user(
        self, operation: str, attempt: int, model: str,
        system_prompt: str, content: str,
    ) -> int | None:
        """写入请求，并用自增主键作为本次模型调用顺序号。"""

        record = ModelMessageRecord(
            invocation_id=None,
            session_id=current_model_session_id(),
            role="user",
            operation=operation,
            attempt=attempt,
            model=model,
            system_prompt=system_prompt,
            content=content,
            created_at=datetime.now(UTC),
        )
        try:
            async with self._session_factory() as session:
                session.add(record)
                await session.flush()
                record.invocation_id = record.id
                await session.commit()
                return record.id
        except Exception:
            logger.exception("模型请求消息保存失败")
            return None

    async def write_assistant(
        self, invocation_id: int | None, operation: str, attempt: int, model: str,
        content: str | None, status: str, latency_ms: int,
        prompt_tokens: int | None = None, completion_tokens: int | None = None,
        total_tokens: int | None = None, error_message: str | None = None,
    ) -> None:
        if invocation_id is None:
            return
        await self._write(ModelMessageRecord(
            invocation_id=invocation_id,
            session_id=current_model_session_id(),
            role="assistant",
            operation=operation,
            attempt=attempt,
            model=model,
            content=content,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            error_message=error_message,
            created_at=datetime.now(UTC),
        ))

    async def _write(self, record: ModelMessageRecord) -> None:
        """记录失败只写日志，不改变找人主流程。"""

        try:
            async with self._session_factory() as session:
                session.add(record)
                await session.commit()
        except Exception:
            logger.exception("模型消息保存失败", invocation_id=record.invocation_id)
