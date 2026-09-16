"""LangGraph 可序列化状态定义。"""

from typing import TypedDict

from talent_agent_py.application.plan_validation import ValidationOutcome
from talent_agent_py.application.ports.talent_search import (
    TalentSearchRequest,
    TalentSearchResponse,
)
from talent_agent_py.domain.conversation import (
    ClarificationCard,
    MessageRoute,
    SearchResult,
    UserContext,
)
from talent_agent_py.domain.plan import PlanPatch, SearchPlan, SearchPlanDraft


class AgentState(TypedDict, total=False):
    """一次搜索 Run 在节点间传递的状态字典。

    total=False 表示字段可以尚未产生，并不表示字段值都可以为 None。
    每个节点只返回本次更新的字段，LangGraph 将其合并到现有状态中。
    """

    # 所属会话的唯一标识，用于隔离不同搜索对话。
    session_id: str
    # 本轮运行唯一标识，用于查询状态和绑定结果。
    run_id: str
    # 触发本轮的消息序号；load_context 只读取此序号及之前的未吸收消息。
    trigger_message_sequence: int
    # 请求入口注入的用户身份和临时凭据；不得作为长期记忆保存。
    user: UserContext
    # Graph 外部 MessageRouter 产生的意图分类，用于选择首次解析或增量修改。
    route: MessageRoute
    # load_context 加载的待处理用户文本，只包含影响搜索计划的消息。
    messages: list[str]
    # load_context 加载的已保存计划；首次为空，save_plan 完成后更新为新版本。
    current_plan: SearchPlan | None
    # 入口判断是否可跳过实体解析；结构化实体选择后可能为 True。
    entities_resolved: bool
    # parse_plan 生成或入口恢复的草稿；校验和实体解析节点继续处理它。
    draft: SearchPlanDraft
    # 增量解析时生成的修改指令；首次搜索或直接恢复草稿时不存在。
    patch: PlanPatch
    # validate 或 resolve_entities 写入的校验结果，用于决定是否澄清。
    validation: ValidationOutcome
    # clarify 生成的澄清卡，供本轮结果展示；普通搜索路径不产生。
    clarification: ClarificationCard
    # compile_search 生成的受控招聘接口参数。
    search_request: TalentSearchRequest
    # search_candidates 返回的候选人及分页信息。
    search_response: TalentSearchResponse
    # clarify 或 finalize 产生的最终业务结果，由应用服务返回给前端。
    result: SearchResult


class LoadContextOutput(TypedDict):
    """加载上下文的返回值；两个字段都会写回 Graph 状态。"""

    # 数据库最新计划；首次搜索为空。
    current_plan: SearchPlan | None
    # 尚未被计划吸收、且不晚于本轮触发序号的搜索消息。
    messages: list[str]


class ParsePlanOutput(TypedDict, total=False):
    """解析节点的状态更新；已有恢复草稿时返回空字典。"""

    # 本轮生成或修改后的搜索草稿。
    draft: SearchPlanDraft
    # 仅增量修改路径返回本轮补丁。
    patch: PlanPatch


class ValidationOutput(TypedDict):
    """确定性校验的返回值。"""

    # 后续分支使用的可执行性和歧义信息。
    validation: ValidationOutcome


class EntityResolutionOutput(TypedDict):
    """业务实体解析后的状态更新。"""

    # 已填入权威编码或追加实体歧义的草稿。
    draft: SearchPlanDraft
    # 根据解析后的草稿重新计算的校验结果。
    validation: ValidationOutcome


class ClarifyOutput(TypedDict, total=False):
    """澄清节点结果；旧运行已被替代时只返回 result。"""

    # 正常澄清路径生成的卡片。
    clarification: ClarificationCard
    # 待澄清、不支持条件或已被替代的本轮结果。
    result: SearchResult


class SavePlanOutput(TypedDict):
    """保存计划后的状态更新。"""

    # 已经完成事务保存的新版本计划。
    current_plan: SearchPlan


class CompileSearchOutput(TypedDict):
    """搜索参数编译后的状态更新。"""

    # 仅包含白名单字段和服务端搜索策略的请求。
    search_request: TalentSearchRequest


class SearchCandidatesOutput(TypedDict):
    """招聘接口调用后的状态更新。"""

    # 候选人当前页、总数和是否有下一页。
    search_response: TalentSearchResponse


class FinalizeOutput(TypedDict):
    """搜索收尾节点的返回值。"""

    # 成功、无结果或被新运行替代的业务结果。
    result: SearchResult
