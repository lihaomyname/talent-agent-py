"""接口身份和服务依赖。"""

from typing import Annotated

from fastapi import Cookie, Header, Request
from pydantic import SecretStr

from talent_agent_py.application.agent_service import AgentService
from talent_agent_py.application.session_service import SessionService
from talent_agent_py.domain.conversation import UserContext


async def get_user_context(
    x_user_id: Annotated[str, Header(min_length=1, max_length=128)],
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_trace_id: Annotated[str | None, Header()] = None,
    auth_open_id_token: Annotated[
        str | None,
        Cookie(alias="authOpenIdToken"),
    ] = None,
) -> UserContext:
    """构造请求身份；招聘 Cookie 只保留在本次调用的内存中。"""

    return UserContext(
        user_id=x_user_id,
        tenant_id=x_tenant_id,
        trace_id=x_trace_id,
        auth_open_id_token=(
            SecretStr(auth_open_id_token) if auth_open_id_token else None
        ),
    )


def get_session_service(request: Request) -> SessionService:
    """读取 lifespan 初始化的会话服务。"""

    return request.app.state.session_service


def get_agent_service(request: Request) -> AgentService:
    """读取 lifespan 初始化的 Agent 服务。"""

    return request.app.state.agent_service
