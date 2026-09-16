"""应用服务使用的事务边界。"""

from __future__ import annotations

from types import TracebackType

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

    # 进入 async with 后创建，以下仓储共享同一个会话和事务。
    session: AsyncSession
    # 会话创建及归属查询仓储。
    sessions: SessionRepository
    # 用户消息的幂等保存和增量读取仓储。
    messages: MessageRepository
    # 搜索计划版本仓储。
    plans: PlanRepository
    # 运行状态及结果快照仓储。
    runs: RunRepository
    # 当前待澄清卡和草稿仓储。
    clarifications: ClarificationRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """保存异步数据库会话工厂，进入上下文后才创建会话。"""

        # 进入事务上下文时创建 AsyncSession 的工厂。
        self._session_factory = session_factory

    async def __aenter__(self) -> UnitOfWork:
        """创建数据库会话及共享该会话的仓储，返回事务单元自身。"""

        self.session = self._session_factory()
        self.sessions = SessionRepository(self.session)
        self.messages = MessageRepository(self.session)
        self.plans = PlanRepository(self.session)
        self.runs = RunRepository(self.session)
        self.clarifications = ClarificationRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """正常退出时提交，异常退出时回滚；最后始终释放连接。"""
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
