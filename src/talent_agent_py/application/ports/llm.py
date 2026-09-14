"""大模型能力端口。"""

from typing import Protocol

from talent_agent_py.domain.conversation import MessageRoute
from talent_agent_py.domain.plan import PlanPatch, SearchPlan, SearchPlanDraft


class LLMClient(Protocol):
    """屏蔽具体模型厂商，只暴露 V1 所需的三个结构化能力。"""

    async def classify_message(
        self,
        *,
        message: str,
        current_plan: SearchPlan | None,
        has_pending_clarification: bool,
    ) -> MessageRoute:
        """判断消息类型以及是否影响正在执行的搜索。"""

    async def parse_search_draft(self, *, messages: list[str]) -> SearchPlanDraft:
        """把首次搜索消息解析成语义草稿。"""

    async def parse_plan_patch(
        self,
        *,
        messages: list[str],
        current_plan: SearchPlan,
    ) -> PlanPatch:
        """把后续对话解析成针对当前计划的增量修改。"""
