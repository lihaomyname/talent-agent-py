"""应用服务使用的事务边界。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from talent_agent_py.infrastructure.persistence.repositories import (
    ClarificationRepository,
    MessageRepository,
    PlanRepository,
    RunRepository,
    SessionRepository,
)


class UnitOfWork:
    """向应用服务暴露共享同一数据库事务的仓储。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> UnitOfWork:
        self.session = self._session_factory()
        self.sessions = SessionRepository(self.session)
        self.messages = MessageRepository(self.session)
        self.plans = PlanRepository(self.session)
        self.runs = RunRepository(self.session)
        self.clarifications = ClarificationRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
