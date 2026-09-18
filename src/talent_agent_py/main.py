"""FastAPI 应用工厂和进程生命周期。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from talent_agent_py.api.errors import register_error_handlers
from talent_agent_py.api.v1.matching_router import router as matching_router
from talent_agent_py.api.v1.router import router as v1_router
from talent_agent_py.application.agent_service import AgentService
from talent_agent_py.application.matching_service import MatchingService
from talent_agent_py.application.message_router import MessageRouter
from talent_agent_py.application.ports.llm import LLMClient
from talent_agent_py.application.ports.talent_search import TalentSearchPort
from talent_agent_py.application.session_service import SessionService
from talent_agent_py.infrastructure.clients.internal_llm import (
    InternalLLMClient,
    UnavailableLLMClient,
)
from talent_agent_py.infrastructure.clients.java_talent import JavaTalentClient
from talent_agent_py.infrastructure.clients.matching_llm import MatchingLLMClient
from talent_agent_py.infrastructure.persistence.database import Database
from talent_agent_py.infrastructure.persistence.models import Base
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork
from talent_agent_py.infrastructure.runtime.task_registry import TaskRegistry
from talent_agent_py.orchestration.graph import build_graph
from talent_agent_py.orchestration.nodes import GraphDependencies
from talent_agent_py.settings import Settings, get_settings
from talent_agent_py.telemetry import RequestResponseLogMiddleware, configure_telemetry

STATIC_DIR = Path(__file__).with_name("static")


def create_app(
    settings: Settings | None = None,
    *,
    llm_client: LLMClient | None = None,
    talent_search_client: TalentSearchPort | None = None,
    matching_llm_client=None,
) -> FastAPI:
    """创建应用；显式参数便于测试注入独立配置。"""

    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """启动时组装数据库、客户端和 Graph，退出时关闭客户端与连接池。"""

        database = Database(settings.database_url, echo=settings.database_echo)
        if settings.auto_create_schema:
            # 仅供测试和本地开发；正式环境必须通过 Alembic 迁移建表。
            async with database.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        http_client = httpx.AsyncClient(
            base_url=settings.java_base_url,
            timeout=httpx.Timeout(settings.java_timeout_seconds),
        )
        llm = llm_client or (
            InternalLLMClient(settings)
            if settings.llm_api_key is not None
            else UnavailableLLMClient()
        )
        talent_search = talent_search_client or JavaTalentClient(http_client, settings)
        def uow_factory() -> UnitOfWork:
            """为一次业务操作创建独立事务单元。"""

            return UnitOfWork(database.session_factory)
        graph = build_graph(GraphDependencies(
            uow_factory=uow_factory,
            llm=llm,
            talent_search=talent_search,
            settings=settings,
        ))
        task_registry = TaskRegistry()

        app.state.settings = settings
        app.state.database = database
        app.state.session_service = SessionService(uow_factory)
        app.state.agent_service = AgentService(
            uow_factory=uow_factory,
            router=MessageRouter(llm),
            graph=graph,
            talent_search=talent_search,
            task_registry=task_registry,
            settings=settings,
        )
        app.state.matching_service = MatchingService(
            uow_factory=uow_factory,
            llm=matching_llm_client or MatchingLLMClient(settings, http_client),
            talent_search=talent_search, tasks=task_registry, settings=settings,
            message_lock=app.state.agent_service._message_write_lock,
        )
        await app.state.matching_service.recover()
        app.state.agent_service.matching_service = app.state.matching_service
        try:
            yield
        finally:
            await task_registry.shutdown()
            await http_client.aclose()
            await database.dispose()

    app = FastAPI(
        title="Talent Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    configure_telemetry(app)
    app.add_middleware(RequestResponseLogMiddleware)
    app.include_router(v1_router, prefix=settings.api_prefix)
    app.include_router(matching_router, prefix=settings.api_prefix)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def conversation_page() -> FileResponse:
        """返回无需单独构建的 Agent 会话页面。"""

        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        """只反映进程存活，不泄露配置或密钥。"""

        return {"status": "ok"}

    @app.get("/ready")
    async def readiness() -> dict[str, str]:
        """验证数据库可连接；外部业务服务在实际调用时独立降级。"""

        async with app.state.database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


def run() -> None:
    """控制台脚本入口。"""

    uvicorn.run("talent_agent_py.main:create_app", factory=True, host="0.0.0.0", port=8000)
