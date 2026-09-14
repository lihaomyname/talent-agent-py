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
    """一次搜索 Run 在节点间传递的最小状态。"""

    session_id: str
    run_id: str
    trigger_message_sequence: int
    user: UserContext
    route: MessageRoute
    messages: list[str]
    current_plan: SearchPlan | None
    entities_resolved: bool
    draft: SearchPlanDraft
    patch: PlanPatch
    validation: ValidationOutcome
    clarification: ClarificationCard
    search_request: TalentSearchRequest
    search_response: TalentSearchResponse
    result: SearchResult
