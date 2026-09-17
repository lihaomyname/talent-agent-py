"""会话查询服务。"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from talent_agent_py.application.exceptions import SessionNotFoundError
from talent_agent_py.domain.conversation import (
    MessageHistoryView,
    MessageOutcome,
    SearchResult,
    SessionSummaryView,
    SessionView,
    UserContext,
)
from talent_agent_py.infrastructure.persistence.models import MessageRecord, RunRecord
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork


class SessionService:
    """创建和读取当前用户拥有的搜索会话。"""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """保存事务工厂，每次操作创建独立的数据库事务。"""

        # 创建会话查询和写入所需的独立事务。
        self._uow_factory = uow_factory

    async def create(self, user: UserContext) -> SessionView:
        """创建归属于当前用户的空会话，并返回会话视图。"""

        async with self._uow_factory() as uow:
            record = await uow.sessions.create(user.user_id)
            return SessionView(
                session_id=record.id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    async def list(self, user: UserContext) -> list[SessionSummaryView]:
        """从数据库恢复当前用户最近的会话，而不是依赖浏览器缓存。"""

        async with self._uow_factory() as uow:
            rows = await uow.sessions.list_owned(user.user_id)
            return [
                SessionSummaryView(
                    session_id=record.id,
                    title=(first_message or "新的人才搜索")[:24],
                    status=result_status or run_status or "READY",
                    plan_version=record.current_plan_version,
                    updated_at=record.updated_at,
                )
                for record, first_message, run_status, result_status in rows
            ]

    async def get(self, session_id: str, user: UserContext) -> SessionView:
        """查询会话、计划和待澄清卡；会话不存在或不归当前用户时抛出异常。"""

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

    async def history(self, session_id: str, user: UserContext) -> list[MessageHistoryView]:
        """恢复用户消息和回复；旧数据从关联 Run 尽量补回搜索结果。"""

        async with self._uow_factory() as uow:
            if await uow.sessions.get_owned(session_id, user.user_id) is None:
                raise SessionNotFoundError("会话不存在")
            messages = (await uow.session.scalars(
                select(MessageRecord).where(MessageRecord.session_id == session_id)
                .order_by(MessageRecord.sequence)
            )).all()
            runs = (await uow.session.scalars(
                select(RunRecord).where(RunRecord.session_id == session_id)
                .order_by(RunRecord.created_at)
            )).all()
            by_sequence = {
                run.trigger_message_sequence: run for run in runs
                if run.trigger_message_sequence is not None and run.result_json
            }
            history = []
            for message in messages:
                outcome = None
                if message.outcome_json:
                    outcome = MessageOutcome.model_validate(message.outcome_json, strict=False)
                elif run := by_sequence.get(message.sequence):
                    outcome = MessageOutcome(
                        kind="RESULT",
                        result=SearchResult.model_validate(run.result_json, strict=False),
                        is_page=message.route_type == "PAGE_ACTION",
                    )
                history.append(MessageHistoryView(content=message.content, outcome=outcome))
            return history
