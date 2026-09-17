"""Agent 自有状态的数据库记录。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """统一生成带时区的时间。"""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """迁移和测试共用的声明式基类。"""


class AgentSessionRecord(Base):
    """会话归属和当前状态指针。"""

    __tablename__ = "agent_sessions"
    __table_args__ = {"comment": "自然语言找人会话，保存归属用户和当前计划、运行指针"}

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="会话唯一标识")
    owner_user_id: Mapped[str] = mapped_column(
        String(128), index=True, comment="会话所属用户标识，由可信网关注入"
    )
    active_run_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="当前生效的搜索运行标识；空表示尚未运行"
    )
    current_plan_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        comment="当前搜索计划版本号；0 表示尚无计划",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, comment="会话创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, comment="会话最后更新时间"
    )


class MessageRecord(Base):
    """有序且支持幂等接收的用户或助手消息。"""

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "client_message_id", name="uq_message_client_id"),
        UniqueConstraint("session_id", "sequence", name="uq_message_sequence"),
        {"comment": "会话内按顺序保存的用户消息，用于幂等接收和多轮计划记忆"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="消息唯一标识")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True, comment="所属会话标识"
    )
    client_message_id: Mapped[str] = mapped_column(
        String(128), comment="客户端生成的消息幂等标识"
    )
    sequence: Mapped[int] = mapped_column(BigInteger, comment="消息在会话内的严格递增序号")
    role: Mapped[str] = mapped_column(
        String(20), comment="消息角色：user=用户，assistant=助手"
    )
    content: Mapped[str] = mapped_column(Text, comment="消息原始文本内容")
    outcome_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="消息对应的安全回复快照"
    )
    route_type: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment=(
            "消息路由：CASUAL_CHAT=闲聊，STATUS_QUERY=进度，CONTROL_STOP=停止，"
            "PAGE_ACTION=翻页，CLARIFICATION_ANSWER=澄清回答，SEARCH_NEW=新搜索，"
            "SEARCH_PATCH=修改搜索，UNKNOWN=意图不明"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, comment="消息接收时间"
    )


class RunRecord(Base):
    """由一条完成路由的消息触发的运行记录。"""

    __tablename__ = "agent_runs"
    __table_args__ = {"comment": "每次搜索或澄清执行的运行记录，承载阶段、状态和最终结果"}

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="运行唯一标识")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True, comment="所属会话标识"
    )
    trigger_message_sequence: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="触发本次运行的消息序号；直接翻页等系统动作为空",
    )
    status: Mapped[str] = mapped_column(
        String(40),
        comment=(
            "运行状态：QUEUED=排队，RUNNING=执行中，NEEDS_CLARIFICATION=待澄清，"
            "SUCCEEDED=成功，FAILED=失败，CANCELLED=已取消，SUPERSEDED=已被替代"
        ),
    )
    stage: Mapped[str] = mapped_column(
        String(100), default="queued", comment="当前执行节点或终止阶段名称"
    )
    result_status: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment=(
            "结果状态：OK=有结果，EMPTY=无结果，UNSUPPORTED=条件不支持，"
            "NEEDS_CLARIFICATION=待澄清，DENIED=无权限，MODEL_ERROR=模型错误，"
            "DEPENDENCY_ERROR=依赖错误，INTERNAL_ERROR=内部错误，CANCELLED=已取消，"
            "SUPERSEDED=已被替代"
        ),
    )
    error_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="稳定业务错误码；成功时为空"
    )
    result_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="与运行和计划版本绑定的结构化搜索结果快照"
    )
    superseded_by_run_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="替代本运行的新运行标识；未被替代时为空"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, comment="运行创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, comment="运行最后更新时间"
    )


class SearchPlanRecord(Base):
    """不可变的 SearchPlan 快照。"""

    __tablename__ = "agent_search_plans"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_plan_session_version"),
        {"comment": "不可变的搜索计划版本，作为多轮会话记忆和搜索审计依据"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="搜索计划记录唯一标识")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True, comment="所属会话标识"
    )
    version: Mapped[int] = mapped_column(Integer, comment="会话内从 1 开始递增的计划版本号")
    applied_through_message_seq: Mapped[int] = mapped_column(
        BigInteger, comment="该计划已吸收的最后一条消息序号"
    )
    plan_json: Mapped[dict] = mapped_column(
        JSON, comment="SearchPlan 完整快照，包含九类白名单搜索条件及解析后的业务编码"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, comment="计划版本创建时间"
    )


class PendingClarificationRecord(Base):
    """V1 每个会话最多保留一个未回答的澄清问题。"""

    __tablename__ = "agent_pending_clarifications"
    __table_args__ = {"comment": "会话当前等待用户回答的澄清卡及暂停时搜索草稿"}

    question_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="澄清问题唯一标识，用于校验结构化答案"
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        comment="所属会话标识；每个会话最多一条待澄清记录",
    )
    source_message_sequence: Mapped[int] = mapped_column(
        BigInteger, comment="产生该澄清问题的用户消息序号"
    )
    card_json: Mapped[dict] = mapped_column(
        JSON,
        comment=(
            "澄清卡快照；kind 可为 LOCATION_SCOPE、POSITION_SCOPE、COMPANY_SCOPE、"
            "ENTITY_AMBIGUITY、ENTITY_NOT_FOUND、UNSUPPORTED_CONDITION、MESSAGE_INTENT"
        ),
    )
    draft_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="暂停执行时的 SearchPlanDraft；无可继续草稿时为空"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, comment="澄清问题创建时间"
    )
