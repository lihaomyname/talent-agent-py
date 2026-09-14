"""自然语言找人 V1 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from talent_agent_py.api.dependencies import (
    get_agent_service,
    get_session_service,
    get_user_context,
)
from talent_agent_py.api.schemas import PageRequest, SendMessageRequest
from talent_agent_py.application.agent_service import AgentService
from talent_agent_py.application.session_service import SessionService
from talent_agent_py.domain.conversation import (
    MessageOutcome,
    RunView,
    SearchResult,
    SessionSummaryView,
    SessionView,
    UserContext,
)

router = APIRouter()

UserDep = Annotated[UserContext, Depends(get_user_context)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def create_session(user: UserDep, service: SessionServiceDep) -> SessionView:
    """创建当前用户拥有的空搜索会话。"""

    return await service.create(user)


@router.get("/sessions", response_model=list[SessionSummaryView])
async def list_sessions(user: UserDep, service: SessionServiceDep) -> list[SessionSummaryView]:
    """读取当前用户最近的历史会话。"""

    return await service.list(user)


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: str, user: UserDep, service: SessionServiceDep
) -> SessionView:
    """读取当前计划和待澄清状态。"""

    return await service.get(session_id, user)


@router.post("/sessions/{session_id}/messages", response_model=MessageOutcome)
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    user: UserDep,
    service: AgentServiceDep,
) -> MessageOutcome:
    """保存并执行一条消息；client_message_id 保证幂等。"""

    return await service.handle_message(
        session_id=session_id,
        client_message_id=payload.client_message_id,
        content=payload.content,
        clarification_answer=payload.clarification_answer,
        user=user,
    )


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str, user: UserDep, service: AgentServiceDep) -> RunView:
    """轮询 Run 当前阶段；V1 暂不启用 SSE。"""

    return await service.get_run(run_id, user)


@router.post("/sessions/{session_id}/cancel", response_model=MessageOutcome)
async def cancel_session_run(
    session_id: str, user: UserDep, service: AgentServiceDep
) -> MessageOutcome:
    """显式取消当前会话的运行。"""

    return await service.cancel_current(session_id, user)


@router.get("/sessions/{session_id}/result", response_model=SearchResult | None)
async def get_result(
    session_id: str, user: UserDep, service: AgentServiceDep
) -> SearchResult | None:
    """读取当前 activeRunId 的最终结果。"""

    return await service.get_result(session_id, user)


@router.post("/sessions/{session_id}/pages", response_model=MessageOutcome)
async def get_page(
    session_id: str,
    payload: PageRequest,
    user: UserDep,
    service: AgentServiceDep,
) -> MessageOutcome:
    """校验分页引用属于路径会话后，直接调用 Java。"""

    if payload.reference.session_id != session_id:
        from talent_agent_py.application.exceptions import StalePageReferenceError

        raise StalePageReferenceError("分页引用与会话不一致")
    return await service.get_page(payload.reference, user)
