"""补充翻页运行和新增结果类型的数据库注释。"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0005"
down_revision = "20260914_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """允许系统翻页运行不绑定用户消息，并同步枚举说明。"""

    op.alter_column(
        "agent_runs",
        "trigger_message_sequence",
        existing_type=sa.BigInteger(),
        nullable=True,
        comment="触发本次运行的消息序号；直接翻页等系统动作为空",
    )
    op.alter_column(
        "agent_runs",
        "result_status",
        existing_type=sa.String(40),
        existing_nullable=True,
        comment=(
            "结果状态：OK=有结果，EMPTY=无结果，UNSUPPORTED=条件不支持，"
            "NEEDS_CLARIFICATION=待澄清，DENIED=无权限，MODEL_ERROR=模型错误，"
            "DEPENDENCY_ERROR=依赖错误，INTERNAL_ERROR=内部错误，CANCELLED=已取消，"
            "SUPERSEDED=已被替代"
        ),
    )
    op.alter_column(
        "agent_pending_clarifications",
        "card_json",
        existing_type=sa.JSON(),
        existing_nullable=False,
        comment=(
            "澄清卡快照；kind 可为 LOCATION_SCOPE、POSITION_SCOPE、COMPANY_SCOPE、"
            "ENTITY_AMBIGUITY、ENTITY_NOT_FOUND、UNSUPPORTED_CONDITION、MESSAGE_INTENT"
        ),
    )


def downgrade() -> None:
    """恢复 V1 初始字段约束和枚举说明。"""

    op.alter_column(
        "agent_runs",
        "trigger_message_sequence",
        existing_type=sa.BigInteger(),
        nullable=False,
        comment="触发本次运行的消息序号",
    )
    op.alter_column(
        "agent_runs",
        "result_status",
        existing_type=sa.String(40),
        existing_nullable=True,
        comment=(
            "结果状态：OK=有结果，EMPTY=无结果，UNSUPPORTED=条件不支持，"
            "NEEDS_CLARIFICATION=待澄清，DENIED=无权限，MODEL_ERROR=模型错误，"
            "DEPENDENCY_ERROR=依赖错误，CANCELLED=已取消，SUPERSEDED=已被替代"
        ),
    )
