"""为 Agent 表和字段补充中文注释及枚举说明。"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_0002"
down_revision = "20260906_0001"
branch_labels = None
depends_on = None


TABLE_COMMENTS = {
    "agent_sessions": "自然语言找人会话，保存归属用户和当前计划、运行指针",
    "agent_messages": "会话内按顺序保存的用户消息，用于幂等接收和多轮计划记忆",
    "agent_runs": "每次搜索或澄清执行的运行记录，承载阶段、状态和最终结果",
    "agent_search_plans": "不可变的搜索计划版本，作为多轮会话记忆和搜索审计依据",
    "agent_pending_clarifications": "会话当前等待用户回答的澄清卡及暂停时搜索草稿",
}


COLUMN_COMMENTS = {
    "agent_sessions": {
        "id": (sa.String(64), False, "会话唯一标识"),
        "owner_user_id": (sa.String(128), False, "会话所属用户标识，由可信网关注入"),
        "active_run_id": (sa.String(64), True, "当前生效的搜索运行标识；空表示尚未运行"),
        "current_plan_version": (sa.Integer(), False, "当前搜索计划版本号；0 表示尚无计划"),
        "created_at": (sa.DateTime(timezone=True), False, "会话创建时间"),
        "updated_at": (sa.DateTime(timezone=True), False, "会话最后更新时间"),
    },
    "agent_messages": {
        "id": (sa.String(64), False, "消息唯一标识"),
        "session_id": (sa.String(64), False, "所属会话标识"),
        "client_message_id": (sa.String(128), False, "客户端生成的消息幂等标识"),
        "sequence": (sa.BigInteger(), False, "消息在会话内的严格递增序号"),
        "role": (sa.String(20), False, "消息角色：user=用户，assistant=助手"),
        "content": (sa.Text(), False, "消息原始文本内容"),
        "route_type": (
            sa.String(40),
            True,
            "消息路由：CASUAL_CHAT=闲聊，STATUS_QUERY=进度，CONTROL_STOP=停止，"
            "PAGE_ACTION=翻页，CLARIFICATION_ANSWER=澄清回答，SEARCH_NEW=新搜索，"
            "SEARCH_PATCH=修改搜索，UNKNOWN=意图不明",
        ),
        "created_at": (sa.DateTime(timezone=True), False, "消息接收时间"),
    },
    "agent_runs": {
        "id": (sa.String(64), False, "运行唯一标识"),
        "session_id": (sa.String(64), False, "所属会话标识"),
        "trigger_message_sequence": (sa.BigInteger(), False, "触发本次运行的消息序号"),
        "status": (
            sa.String(40),
            False,
            "运行状态：QUEUED=排队，RUNNING=执行中，NEEDS_CLARIFICATION=待澄清，"
            "SUCCEEDED=成功，FAILED=失败，CANCELLED=已取消，SUPERSEDED=已被替代",
        ),
        "stage": (sa.String(100), False, "当前执行节点或终止阶段名称"),
        "result_status": (
            sa.String(40),
            True,
            "结果状态：OK=有结果，EMPTY=无结果，UNSUPPORTED=条件不支持，"
            "NEEDS_CLARIFICATION=待澄清，DENIED=无权限，MODEL_ERROR=模型错误，"
            "DEPENDENCY_ERROR=依赖错误，CANCELLED=已取消，SUPERSEDED=已被替代",
        ),
        "error_code": (sa.String(100), True, "稳定业务错误码；成功时为空"),
        "result_json": (sa.JSON(), True, "与运行和计划版本绑定的结构化搜索结果快照"),
        "superseded_by_run_id": (sa.String(64), True, "替代本运行的新运行标识；未被替代时为空"),
        "created_at": (sa.DateTime(timezone=True), False, "运行创建时间"),
        "updated_at": (sa.DateTime(timezone=True), False, "运行最后更新时间"),
    },
    "agent_search_plans": {
        "id": (sa.String(64), False, "搜索计划记录唯一标识"),
        "session_id": (sa.String(64), False, "所属会话标识"),
        "version": (sa.Integer(), False, "会话内从 1 开始递增的计划版本号"),
        "applied_through_message_seq": (sa.BigInteger(), False, "该计划已吸收的最后一条消息序号"),
        "plan_json": (sa.JSON(), False, "SearchPlan 完整快照，包含九类白名单搜索条件及解析后的业务编码"),
        "created_at": (sa.DateTime(timezone=True), False, "计划版本创建时间"),
    },
    "agent_pending_clarifications": {
        "question_id": (sa.String(64), False, "澄清问题唯一标识，用于校验结构化答案"),
        "session_id": (sa.String(64), False, "所属会话标识；每个会话最多一条待澄清记录"),
        "source_message_sequence": (sa.BigInteger(), False, "产生该澄清问题的用户消息序号"),
        "card_json": (
            sa.JSON(),
            False,
            "澄清卡快照；kind 可为 LOCATION_SCOPE、POSITION_SCOPE、COMPANY_SCOPE、"
            "ENTITY_AMBIGUITY、UNSUPPORTED_CONDITION、MESSAGE_INTENT",
        ),
        "draft_json": (sa.JSON(), True, "暂停执行时的 SearchPlanDraft；无可继续草稿时为空"),
        "created_at": (sa.DateTime(timezone=True), False, "澄清问题创建时间"),
    },
}


def upgrade() -> None:
    """为已存在的表和字段写入 MySQL 可查询的中文 COMMENT。"""

    for table_name, comment in TABLE_COMMENTS.items():
        op.execute(
            f"ALTER TABLE `{table_name}` COMMENT = '{comment}'"
        )
    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, (column_type, nullable, comment) in columns.items():
            op.alter_column(
                table_name,
                column_name,
                existing_type=column_type,
                existing_nullable=nullable,
                comment=comment,
            )


def downgrade() -> None:
    """删除本次迁移增加的注释，不改变任何业务数据。"""

    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, (column_type, nullable, _) in columns.items():
            op.alter_column(
                table_name,
                column_name,
                existing_type=column_type,
                existing_nullable=nullable,
                comment=None,
            )
    for table_name in TABLE_COMMENTS:
        op.execute(f"ALTER TABLE `{table_name}` COMMENT = ''")
