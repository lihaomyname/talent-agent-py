"""为 Alembic 自身的迁移版本表补充中文注释。"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0004"
down_revision = "20260914_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """保证 talent_agent 数据库中的框架表也具备完整说明。"""

    op.execute(
        "ALTER TABLE `alembic_version` COMMENT = 'Alembic 数据库结构迁移版本记录'"
    )
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(32),
        existing_nullable=False,
        comment="当前已执行到的 Alembic 迁移版本号",
    )


def downgrade() -> None:
    """移除 Alembic 版本表的中文注释。"""

    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(32),
        existing_nullable=False,
        comment=None,
    )
    op.execute("ALTER TABLE `alembic_version` COMMENT = ''")
