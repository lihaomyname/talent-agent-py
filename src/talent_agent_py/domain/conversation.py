"""会话、运行、澄清和搜索结果模型。"""

from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.enums import ClarificationKind, MessageType, ResultStatus, RunStatus
from talent_agent_py.domain.plan import SearchConditions, SearchPlan


class UserContext(StrictModel):
    """请求级可信身份和临时凭据，禁止来自模型输出或持久化。"""

    # 可信请求身份中的用户标识，用于会话归属检查。
    user_id: str = Field(min_length=1, max_length=128)
    # 租户标识；未提供时为空。
    tenant_id: str | None = Field(default=None, max_length=128)
    # 请求链路标识；未提供时为空。
    trace_id: str | None = Field(default=None, max_length=128)
    # 仅本次调用透传的招聘登录凭据，序列化和对象展示时排除。
    auth_open_id_token: SecretStr | None = Field(
        default=None,
        exclude=True,
        repr=False,
        description="仅用于当前请求透传的招聘系统登录令牌",
    )


class MessageRoute(StrictModel):
    """启动或打断运行之前产生的消息决策。"""

    # 消息意图分类，决定应用服务执行哪个分支。
    message_type: MessageType
    # 路由对是否影响活动运行的判断；具体操作由应用服务分支决定。
    affects_active_run: bool
    # 意图分类置信度，取值 0～1。
    confidence: float = Field(ge=0, le=1)
    # 规则或模型给出的分类原因标识，便于排查路由。
    reason_code: str = Field(min_length=1, max_length=100)
    # 翻页方向：1 为下一页，-1 为上一页；非翻页消息可为空。
    page_delta: int | None = Field(default=None, ge=-1, le=1)


class ClarificationOption(StrictModel):
    """澄清卡中展示的一个安全选项。"""

    # 提交给服务端的选项值，必须与当前卡片的选项匹配。
    value: str = Field(min_length=1, max_length=128)
    # 供用户阅读的实体或选项名称。
    label: str = Field(min_length=1, max_length=200)


class ClarificationCard(StrictModel):
    """跨请求保存的固定模板澄清问题。"""

    # 澄清问题唯一标识，防止旧卡片答案应用到新问题。
    question_id: str = Field(min_length=1, max_length=64)
    # 澄清类型，决定如何解释选项并恢复草稿。
    kind: ClarificationKind
    # 待处理字段路径，例如 current_city 或 company:0。
    field: str = Field(min_length=1, max_length=100)
    # 前端展示的问题文案。
    title: str = Field(min_length=1, max_length=300)
    # 允许用户选择的封闭选项列表。
    options: list[ClarificationOption] = Field(min_length=1, max_length=20)
    # 恢复草稿所需的少量上下文，例如待确定范围的城市名。
    context: dict[str, str] = Field(default_factory=dict)


class ClarificationAnswer(StrictModel):
    """澄清卡提交的结构化答案。"""

    # 用户回答的卡片标识，需与当前待澄清问题一致。
    question_id: str = Field(min_length=1, max_length=64)
    # 选中的选项值，而不是界面显示名称。
    value: str = Field(min_length=1, max_length=128)


class SessionView(StrictModel):
    """对外安全返回的会话视图。"""

    # 所属会话的唯一标识，用于隔离不同搜索对话。
    session_id: str
    # 会话关联的活动运行标识；尚未启动运行时为空。
    active_run_id: str | None = None
    # 关联的计划版本；尚未生成计划时为 0。
    plan_version: int = 0
    # 当前保存的搜索计划；首次搜索之前为空。
    current_plan: SearchPlan | None = None
    # 待回答的澄清卡；没有阻塞问题时为空。
    pending_clarification: ClarificationCard | None = None
    # 记录创建时间。
    created_at: datetime
    # 记录最近更新时间。
    updated_at: datetime


class SessionSummaryView(StrictModel):
    """历史会话列表使用的轻量视图。"""

    # 所属会话的唯一标识，用于隔离不同搜索对话。
    session_id: str
    # 由首条消息生成的历史会话标题。
    title: str
    # 历史列表展示状态，优先使用结果状态，其次运行状态，初始为 READY。
    status: str
    # 关联的计划版本；尚未生成计划时为 0。
    plan_version: int = 0
    # 记录最近更新时间。
    updated_at: datetime


class RunView(StrictModel):
    """对外安全返回的运行进度视图。"""

    # 本轮运行唯一标识，用于查询状态和绑定结果。
    run_id: str
    # 所属会话的唯一标识，用于隔离不同搜索对话。
    session_id: str
    # 运行生命周期状态，如 RUNNING、SUCCEEDED。
    status: RunStatus
    # 数据库记录的执行或终止阶段；不代表实时节点事件流。
    stage: str
    # 面向用户的结果分类；尚无结果时为空。
    result_status: ResultStatus | None = None
    # 失败时的稳定业务错误码；正常运行可为空。
    error_code: str | None = None
    # 记录创建时间。
    created_at: datetime
    # 记录最近更新时间。
    updated_at: datetime


class PageReference(StrictModel):
    """服务端签发并绑定计划版本的分页引用。"""

    # 所属会话的唯一标识，用于隔离不同搜索对话。
    session_id: str
    # 分页绑定的计划版本；条件改变后旧引用失效。
    plan_version: int = Field(ge=1)
    # 目标页码，从 1 开始。
    page: int = Field(ge=1, le=1000)


class PreferenceEvidenceView(StrictModel):
    """页面展示的一条偏好证据。"""

    preference_id: str
    preference: str
    status: Literal["SUPPORTED", "PARTIAL"]
    explanation: str
    quote: str | None = None


class ExperienceView(StrictModel):
    """候选人的一条教育或工作经历展示数据。"""

    category: Literal["EDUCATION", "WORK"]
    path: str
    text: str


class CandidateCard(StrictModel):
    """Java 返回的安全候选人卡片。"""

    # 招聘系统候选人标识。
    candidate_id: str
    # 允许展示的候选人姓名；接口未提供时为空。
    display_name: str | None = None
    # 候选人职位或摘要；接口未提供时为空。
    headline: str | None = None
    # 当前公司展示名称；接口未提供时为空。
    current_company: str | None = None
    # 当前居住地展示名称；接口未提供时为空。
    current_city: str | None = None
    # 招聘接口返回的候选人摘要亮点，不由模型补造。
    highlights: list[str] = Field(default_factory=list, max_length=20)
    # 普通搜索为空；偏好搜索时用于同一卡片增加标签和推荐依据。
    preference_evidence: list[PreferenceEvidenceView] = Field(default_factory=list)
    # 偏好搜索读取的白名单教育/工作经历，默认折叠展示。
    experiences: list[ExperienceView] = Field(default_factory=list)


class SearchResult(StrictModel):
    """绑定具体 Run 和 SearchPlan 的搜索结果。"""

    # 业务结果分类，例如有结果、无结果、待澄清或失败。
    status: ResultStatus
    # 本轮运行唯一标识，用于查询状态和绑定结果。
    run_id: str
    # 关联的计划版本；尚未生成计划时为 0。
    plan_version: int = Field(ge=0)
    # 本结果对应的页码，从 1 开始。
    page: int = Field(default=1, ge=1, le=1000)
    # 当前页的候选人卡片，保持招聘接口原始顺序。
    candidates: list[CandidateCard] = Field(default_factory=list)
    # 接口报告的总命中数；未执行搜索时可为空。
    total: int | None = Field(default=None, ge=0)
    # 下一页引用；没有下一页时为空。
    next_page: PageReference | None = None
    # 结果附带的计划条件；未有可用计划时为空。
    executed_conditions: SearchConditions | None = None
    # 本轮需要回答的澄清卡；无澄清时为空。
    clarification: ClarificationCard | None = None
    # 停止、替代或失败等情况下的用户提示。
    message: str | None = None


class MessageOutcome(StrictModel):
    """消息接口的统一返回，前端按 kind 渲染。"""

    # 响应分支：RESULT 为搜索结果，CHAT 为文本回复，STATUS 为运行状态。
    kind: Literal["RESULT", "CHAT", "STATUS"]
    # RESULT 分支的结构化结果；其他分支通常为空。
    result: SearchResult | None = None
    # STATUS 分支的运行信息；其他分支通常为空。
    run: RunView | None = None
    # CHAT 分支的文本回复；其他分支通常为空。
    reply: str | None = None
    is_page: bool = False


class MessageHistoryView(StrictModel):
    """按用户消息顺序恢复对话及对应回复。"""

    content: str
    outcome: MessageOutcome | None = None
