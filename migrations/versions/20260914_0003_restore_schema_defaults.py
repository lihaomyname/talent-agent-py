"""恢复添加字段注释时需要显式保留的数据库默认值。"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """确保新会话的当前计划版本由数据库默认初始化为零。"""

    op.alter_column(
        "agent_sessions",
        "current_plan_version",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("0"),
        existing_comment="当前搜索计划版本号；0 表示尚无计划",
    )


def downgrade() -> None:
    """移除数据库默认值，字段中文注释保持不变。"""

    op.alter_column(
        "agent_sessions",
        "current_plan_version",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=None,
        existing_comment="当前搜索计划版本号；0 表示尚无计划",
    )
