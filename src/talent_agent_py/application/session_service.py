"""会话查询服务。"""

from talent_agent_py.application.exceptions import SessionNotFoundError
from talent_agent_py.domain.conversation import SessionView, UserContext
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork


class SessionService:
    """创建和读取当前用户拥有的搜索会话。"""

    def __init__(self, uow_factory) -> None:
        self._uow_factory = uow_factory

    async def create(self, user: UserContext) -> SessionView:
        async with self._uow_factory() as uow:
            record = await uow.sessions.create(user.user_id)
            return SessionView(
                session_id=record.id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    async def get(self, session_id: str, user: UserContext) -> SessionView:
        async with self._uow_factory() as uow:
            record = await uow.sessions.get_owned(session_id, user.user_id)
            if record is None:
                raise SessionNotFoundError("会话不存在")
            plan = await uow.plans.get_current(session_id)
            clarification = await uow.clarifications.get(session_id)
            return SessionView(
                session_id=record.id,
                active_run_id=record.active_run_id,
                plan_version=record.current_plan_version,
                current_plan=plan,
                pending_clarification=clarification,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
