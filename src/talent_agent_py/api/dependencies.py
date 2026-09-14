"""接口身份和服务依赖。"""

from typing import Annotated

from fastapi import Header, Request

from talent_agent_py.application.agent_service import AgentService
from talent_agent_py.application.session_service import SessionService
from talent_agent_py.domain.conversation import UserContext


async def get_user_context(
    x_user_id: Annotated[str, Header(min_length=1, max_length=128)],
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_trace_id: Annotated[str | None, Header()] = None,
) -> UserContext:
    """从受信网关注入的 Header 构造身份，不接收请求体 operatorId。"""

    return UserContext(user_id=x_user_id, tenant_id=x_tenant_id, trace_id=x_trace_id)


def get_session_service(request: Request) -> SessionService:
    """读取 lifespan 初始化的会话服务。"""

    return request.app.state.session_service


def get_agent_service(request: Request) -> AgentService:
    """读取 lifespan 初始化的 Agent 服务。"""

    return request.app.state.agent_service
