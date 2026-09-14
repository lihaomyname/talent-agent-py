"""会话、运行、澄清和搜索结果模型。"""

from datetime import datetime

from typing import Literal

from pydantic import Field, SecretStr

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.enums import ClarificationKind, MessageType, ResultStatus, RunStatus
from talent_agent_py.domain.plan import SearchConditions, SearchPlan


class UserContext(StrictModel):
    """请求级可信身份和临时凭据，禁止来自模型输出或持久化。"""

    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    auth_open_id_token: SecretStr | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="仅用于当前请求透传的招聘系统登录令牌",
    )


class MessageRoute(StrictModel):
    """启动或打断运行之前产生的消息决策。"""

    message_type: MessageType
    affects_active_run: bool
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(min_length=1, max_length=100)


class ClarificationOption(StrictModel):
    """澄清卡中展示的一个安全选项。"""

    value: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)


class ClarificationCard(StrictModel):
    """跨请求保存的固定模板澄清问题。"""

    question_id: str = Field(min_length=1, max_length=64)
    kind: ClarificationKind
    field: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    options: list[ClarificationOption] = Field(min_length=1, max_length=20)
    context: dict[str, str] = Field(default_factory=dict)


class ClarificationAnswer(StrictModel):
    """澄清卡提交的结构化答案。"""

    question_id: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=128)


class SessionView(StrictModel):
    """对外安全返回的会话视图。"""

    session_id: str
    active_run_id: str | None = None
    plan_version: int = 0
    current_plan: SearchPlan | None = None
    pending_clarification: ClarificationCard | None = None
    created_at: datetime
    updated_at: datetime


class RunView(StrictModel):
    """对外安全返回的运行进度视图。"""

    run_id: str
    session_id: str
    status: RunStatus
    stage: str
    result_status: ResultStatus | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class PageReference(StrictModel):
    """服务端签发并绑定计划版本的分页引用。"""

    session_id: str
    plan_version: int = Field(ge=1)
    page: int = Field(ge=1)


class CandidateCard(StrictModel):
    """Java 返回的安全候选人卡片。"""

    candidate_id: str
    display_name: str | None = None
    headline: str | None = None
    current_company: str | None = None
    current_city: str | None = None
    highlights: list[str] = Field(default_factory=list, max_length=20)


class SearchResult(StrictModel):
    """绑定具体 Run 和 SearchPlan 的搜索结果。"""

    status: ResultStatus
    run_id: str
    plan_version: int = Field(ge=0)
    candidates: list[CandidateCard] = Field(default_factory=list)
    total: int | None = Field(default=None, ge=0)
    next_page: PageReference | None = None
    executed_conditions: SearchConditions | None = None
    clarification: ClarificationCard | None = None
    message: str | None = None


class MessageOutcome(StrictModel):
    """消息接口的统一返回，前端按 kind 渲染。"""

    kind: Literal["RESULT", "CHAT", "STATUS"]
    result: SearchResult | None = None
    run: RunView | None = None
    reply: str | None = None
