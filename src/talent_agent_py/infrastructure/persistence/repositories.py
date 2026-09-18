"""Agent 自有状态的专用仓储。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from talent_agent_py.application.matching_snapshots import read_search_plan, snapshot_kind
from talent_agent_py.domain.conversation import ClarificationCard
from talent_agent_py.domain.enums import RunStatus
from talent_agent_py.domain.plan import SearchPlan, SearchPlanDraft
from talent_agent_py.infrastructure.persistence.models import (
    AgentSessionRecord,
    MessageRecord,
    PendingClarificationRecord,
    RunRecord,
    SearchPlanRecord,
)


def new_id(prefix: str) -> str:
    """生成便于日志和 API 识别类型的紧凑 ID。"""

    return f"{prefix}_{uuid4().hex}"


class SessionRepository:
    """创建和读取用户拥有的会话。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定事务单元提供的数据库会话，写操作只 flush，不自行提交事务。"""

        # 外部事务单元提供的会话；仓储不负责 commit 或 close。
        self.session = session

    async def create(self, owner_user_id: str) -> AgentSessionRecord:
        """创建记录并 flush，使调用方立即取得标识；最终提交由事务单元负责。"""

        record = AgentSessionRecord(id=new_id("ses"), owner_user_id=owner_user_id)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_owned(self, session_id: str, owner_user_id: str) -> AgentSessionRecord | None:
        """按会话 ID 和用户归属查找记录；未找到返回 None。"""

        query = select(AgentSessionRecord).where(
            AgentSessionRecord.id == session_id,
            AgentSessionRecord.owner_user_id == owner_user_id,
        )
        return await self.session.scalar(query)

    async def list_owned(self, owner_user_id: str, *, limit: int = 20) -> list[tuple[AgentSessionRecord, str | None, str | None, str | None]]:
        """按最近更新时间返回会话列表。

        每项依次为（会话记录、首条消息、运行状态、结果状态）；后三项可为空。
        """

        first_message = (
            select(MessageRecord.content)
            .where(MessageRecord.session_id == AgentSessionRecord.id)
            .order_by(MessageRecord.sequence)
            .limit(1)
            .scalar_subquery()
        )
        query = (
            select(
                AgentSessionRecord,
                first_message.label("first_message"),
                RunRecord.status.label("run_status"),
                RunRecord.result_status.label("result_status"),
            )
            .outerjoin(RunRecord, RunRecord.id == AgentSessionRecord.active_run_id)
            .where(AgentSessionRecord.owner_user_id == owner_user_id)
            .order_by(AgentSessionRecord.updated_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).all()
        return [tuple(row) for row in rows]


class MessageRepository:
    """保存有序消息并处理幂等重试。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定事务单元提供的数据库会话，写操作只 flush，不自行提交事务。"""

        # 外部事务单元提供的会话；仓储不负责 commit 或 close。
        self.session = session

    async def get_by_client_id(
        self, session_id: str, client_message_id: str
    ) -> MessageRecord | None:
        """按会话及客户端消息标识查询，用于识别重复提交；未找到返回 None。"""

        query = select(MessageRecord).where(
            MessageRecord.session_id == session_id,
            MessageRecord.client_message_id == client_message_id,
        )
        return await self.session.scalar(query)

    async def append_user(
        self, session_id: str, client_message_id: str, content: str
    ) -> tuple[MessageRecord, bool]:
        """返回（消息记录、是否新建）；重复提交返回原记录和 False。"""

        existing = await self.get_by_client_id(session_id, client_message_id)
        if existing:
            return existing, False

        # V1 在应用层对同一会话的消息处理做串行化。
        next_sequence = (
            await self.session.scalar(
                select(func.coalesce(func.max(MessageRecord.sequence), 0) + 1).where(
                    MessageRecord.session_id == session_id
                )
            )
        )
        record = MessageRecord(
            id=new_id("msg"),
            session_id=session_id,
            client_message_id=client_message_id,
            sequence=int(next_sequence or 1),
            role="user",
            content=content,
        )
        self.session.add(record)
        await self.session.flush()
        return record, True

    async def list_after(
        self, session_id: str, sequence: int, *, through: int | None = None
    ) -> list[MessageRecord]:
        """返回指定序号之后的搜索相关消息；through 限定本轮可读取的末尾序号。"""

        query = select(MessageRecord).where(
            MessageRecord.session_id == session_id,
            MessageRecord.sequence > sequence,
        )
        if through is not None:
            query = query.where(MessageRecord.sequence <= through)
        # 只把会影响计划的消息交给解析器，避免“你好”等闲聊污染搜索语义。
        query = query.where(MessageRecord.route_type.in_([
            "SEARCH_NEW", "SEARCH_PATCH", "CLARIFICATION_ANSWER"
        ]))
        query = query.order_by(MessageRecord.sequence)
        return list((await self.session.scalars(query)).all())


class PlanRepository:
    """保存不可变计划版本并更新当前版本指针。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定事务单元提供的数据库会话，写操作只 flush，不自行提交事务。"""

        # 外部事务单元提供的会话；仓储不负责 commit 或 close。
        self.session = session

    async def get_current(self, session_id: str) -> SearchPlan | None:
        """读取最新计划快照并还原领域对象；尚无计划时返回 None。"""

        query = (
            select(SearchPlanRecord)
            .where(SearchPlanRecord.session_id == session_id)
            .order_by(SearchPlanRecord.version.desc())
            .limit(1)
        )
        record = await self.session.scalar(query)
        return read_search_plan(record.plan_json) if record else None

    async def save(self, session_record: AgentSessionRecord, plan: SearchPlan) -> SearchPlan:
        """新增不可变计划快照、更新会话版本指针并返回原计划；事务退出时提交。"""

        record = SearchPlanRecord(
            id=new_id("plan"),
            session_id=session_record.id,
            version=plan.version,
            applied_through_message_seq=plan.applied_through_message_seq,
            plan_json=plan.model_dump(mode="json"),
        )
        self.session.add(record)
        session_record.current_plan_version = plan.version
        await self.session.flush()
        return plan


class ClarificationRepository:
    """保存和消费 V1 唯一的待处理澄清问题。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定事务单元提供的数据库会话，写操作只 flush，不自行提交事务。"""

        # 外部事务单元提供的会话；仓储不负责 commit 或 close。
        self.session = session

    async def get(self, session_id: str) -> ClarificationCard | None:
        """读取会话的待澄清卡；不存在时返回 None。"""

        query = select(PendingClarificationRecord).where(
            PendingClarificationRecord.session_id == session_id
        )
        record = await self.session.scalar(query)
        if record and snapshot_kind(record.card_json) == "matching_draft":
            return None
        return ClarificationCard.model_validate(record.card_json, strict=False) if record else None

    async def get_with_draft(
        self, session_id: str
    ) -> tuple[ClarificationCard, SearchPlanDraft | None] | None:
        """读取卡片及暂停时的草稿，供结构化答案继续执行。"""

        record = await self.session.scalar(select(PendingClarificationRecord).where(
            PendingClarificationRecord.session_id == session_id
        ))
        if not record:
            return None
        if snapshot_kind(record.card_json) == "matching_draft":
            return None
        draft = (
            SearchPlanDraft.model_validate(record.draft_json, strict=False)
            if record.draft_json else None
        )
        return ClarificationCard.model_validate(record.card_json, strict=False), draft

    async def save(
        self,
        session_id: str,
        source_message_sequence: int,
        card: ClarificationCard,
        draft: SearchPlanDraft | None = None,
    ) -> None:
        """保存或替换本会话唯一的澄清卡及草稿；仅 flush，事务退出时提交。"""

        existing = await self.session.scalar(
            select(PendingClarificationRecord).where(
                PendingClarificationRecord.session_id == session_id
            )
        )
        if existing:
            existing.question_id = card.question_id
            existing.source_message_sequence = source_message_sequence
            existing.card_json = card.model_dump(mode="json")
            existing.draft_json = draft.model_dump(mode="json") if draft else None
        else:
            self.session.add(
                PendingClarificationRecord(
                    question_id=card.question_id,
                    session_id=session_id,
                    source_message_sequence=source_message_sequence,
                    card_json=card.model_dump(mode="json"),
                    draft_json=draft.model_dump(mode="json") if draft else None,
                )
            )
        await self.session.flush()

    async def clear(self, session_id: str) -> None:
        """删除当前会话的待澄清记录；记录不存在时无需处理。"""

        record = await self.session.scalar(
            select(PendingClarificationRecord).where(
                PendingClarificationRecord.session_id == session_id
            )
        )
        if record:
            await self.session.delete(record)


class RunRepository:
    """管理活动 Run，且不回滚已经完成的计划写入。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定事务单元提供的数据库会话，写操作只 flush，不自行提交事务。"""

        # 外部事务单元提供的会话；仓储不负责 commit 或 close。
        self.session = session

    async def create(
        self,
        session_record: AgentSessionRecord,
        trigger_message_sequence: int | None,
        *,
        activate: bool = True,
    ) -> RunRecord:
        """创建运行；翻页和旁路澄清可选择不替换当前活动运行。"""

        run = RunRecord(
            id=new_id("run"),
            session_id=session_record.id,
            trigger_message_sequence=trigger_message_sequence,
            status=RunStatus.QUEUED.value,
            stage="queued",
        )
        self.session.add(run)
        if activate:
            session_record.active_run_id = run.id
        await self.session.flush()
        return run

    async def get(self, run_id: str) -> RunRecord | None:
        """按运行 ID 查询数据库记录；不存在时返回 None。"""

        return await self.session.get(RunRecord, run_id)

    async def get_by_trigger(
        self, session_id: str, trigger_message_sequence: int
    ) -> RunRecord | None:
        """幂等重试时查找已经由该消息创建的 Run。"""

        return await self.session.scalar(select(RunRecord).where(
            RunRecord.session_id == session_id,
            RunRecord.trigger_message_sequence == trigger_message_sequence,
        ))

    async def mark_superseded(self, run_id: str, replacement_id: str) -> None:
        """记录旧运行被哪个新运行替代；已成功或失败的记录保持原状。"""

        run = await self.get(run_id)
        if run and run.status not in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value}:
            run.status = RunStatus.SUPERSEDED.value
            run.superseded_by_run_id = replacement_id

    async def update(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: str | None = None,
        result_status: str | None = None,
        error_code: str | None = None,
        result_json: dict[str, Any] | None = None,
    ) -> RunRecord:
        """更新非空参数指定的运行字段并返回记录；运行不存在时抛出 LookupError。"""

        run = await self.get(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        if status is not None:
            run.status = status.value
        if stage is not None:
            run.stage = stage
        if result_status is not None:
            run.result_status = result_status
        if error_code is not None:
            run.error_code = error_code
        if result_json is not None:
            run.result_json = result_json
        await self.session.flush()
        return run
