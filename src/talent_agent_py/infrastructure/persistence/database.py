"""SQLAlchemy 异步引擎和会话生命周期。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """管理共享数据库资源并创建请求级会话。"""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        """创建共享连接池与会话工厂；提交后保留已加载属性以供返回 DTO。"""

        # 共享数据库连接池，应用退出时释放。
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        # 生成独立异步会话；提交后不使已加载属性过期。
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        """生成一个可开启事务的 SQLAlchemy 会话。"""

        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """应用关闭时释放连接池。"""

        await self.engine.dispose()
