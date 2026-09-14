"""创建 Agent 会话、消息、运行、计划和澄清表。"""

from alembic import op
import sqlalchemy as sa

revision = "20260906_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 V1 所需的最小持久化结构。"""

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_user_id", sa.String(128), nullable=False),
        sa.Column("active_run_id", sa.String(64), nullable=True),
        sa.Column("current_plan_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_sessions_owner_user_id", "agent_sessions", ["owner_user_id"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_message_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("route_type", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "client_message_id", name="uq_message_client_id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_message_sequence"),
    )
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_message_sequence", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("result_status", sa.String(40), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("superseded_by_run_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_table(
        "agent_search_plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("applied_through_message_seq", sa.BigInteger(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "version", name="uq_plan_session_version"),
    )
    op.create_index("ix_agent_search_plans_session_id", "agent_search_plans", ["session_id"])
    op.create_table(
        "agent_pending_clarifications",
        sa.Column("question_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("source_message_sequence", sa.BigInteger(), nullable=False),
        sa.Column("card_json", sa.JSON(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_pending_clarifications_session_id", "agent_pending_clarifications", ["session_id"])


def downgrade() -> None:
    """按依赖顺序删除 V1 表。"""

    op.drop_table("agent_pending_clarifications")
    op.drop_table("agent_search_plans")
    op.drop_table("agent_runs")
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
