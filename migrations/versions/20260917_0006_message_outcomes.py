"""保存对话回复以支持刷新恢复。"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0006"
down_revision = "20260914_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_messages", sa.Column(
        "outcome_json", sa.JSON(), nullable=True, comment="消息对应的安全回复快照"
    ))


def downgrade() -> None:
    op.drop_column("agent_messages", "outcome_json")
